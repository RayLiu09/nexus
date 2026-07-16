"""A4 (§10 阶段 A + §1.15 §7.3) — Graph API → chart:echarts fence adapter.

Two adapter surfaces:

* `capability_graph_to_chart` / `knowledge_graph_to_chart` — serialise the
  domain graph node/edge shape into the `chart:echarts` JSON contract
  declared in the retrieval router design (§7.1). No LLM involvement; the
  data must be assembled server-side (§7.2 硬约束).

* `ChartRegistry` — a per-request in-memory map that stages chart JSON
  and hands back a `chart_id`. Composer streams `[[CHART:{chart_id}]]`
  as a placeholder; after Composer finishes, the backend calls
  `replace_chart_placeholders()` to swap each placeholder for the actual
  fenced code block (§7.3 streaming timing decision — swap after stream
  end, not incrementally).

Design red lines carried into this module:

* chart_id format is exactly ``{tool_call_id}:{chart_index}`` (§7.3).
* When Composer references a chart_id that was never registered
  (LLM hallucination), the placeholder is left verbatim in the final
  Markdown AND the id is recorded in
  `audit.summary.chart_hallucination_ids` (see `RetrievalV2SummaryFields`).
* When registered charts are never referenced by Composer they are
  recorded in `audit.summary.chart_unused_ids`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal

# ---------------------------------------------------------------------------
# chart:echarts JSON shape (§7.1)
# ---------------------------------------------------------------------------

ChartType = Literal["graph"]


@dataclass(frozen=True)
class ChartNode:
    id: str
    name: str
    category: str


@dataclass(frozen=True)
class ChartEdge:
    source: str
    target: str
    relation: str


@dataclass(frozen=True)
class ChartMeta:
    title: str
    source_ref: str | None = None  # normalized_ref_id / build_id


@dataclass(frozen=True)
class ChartPayload:
    nodes: list[ChartNode]
    edges: list[ChartEdge]
    meta: ChartMeta

    def to_json(self) -> dict[str, Any]:
        return {
            "type": "graph",
            "nodes": [
                {"id": n.id, "name": n.name, "category": n.category}
                for n in self.nodes
            ],
            "edges": [
                {"source": e.source, "target": e.target, "relation": e.relation}
                for e in self.edges
            ],
            "meta": {
                "title": self.meta.title,
                **({"source_ref": self.meta.source_ref}
                   if self.meta.source_ref is not None else {}),
            },
        }


# ---------------------------------------------------------------------------
# Capability graph staging adapter — used by scenario_2/3 tools that go
# through `capability_graph_staging_node/edge`.
# ---------------------------------------------------------------------------


def _normalise_category(node_type: str | None) -> str:
    """Fold graph builder node_type into a display category.

    ECharts categories are surface-level buckets for hover / colour; we
    keep them equal to the domain node_type verbatim (already lowercase
    snake_case in the whitelist).
    """
    return (node_type or "unknown").lower()


def capability_graph_to_chart(
    *,
    nodes: Iterable[Any],
    edges: Iterable[Any],
    title: str,
    source_ref: str | None = None,
) -> ChartPayload:
    """Convert `CapabilityGraphStagingNode/Edge` rows to a ChartPayload.

    Accepts SQLAlchemy row objects (or any duck-typed equivalent) with
    attributes `id / node_type / display_name` for nodes and
    `source_node_id / target_node_id / edge_type` for edges.

    Edge endpoints that reference a node id not present in the node list
    are silently dropped — the caller (Composer) never wants a chart with
    dangling arrows. In practice this shouldn't fire because
    `capability_graph/service.py` already prunes dangling edges; the
    defensive filter guards against upstream regressions.
    """
    node_specs: list[ChartNode] = []
    known_ids: set[str] = set()
    for n in nodes:
        node_id = str(getattr(n, "id"))
        node_specs.append(ChartNode(
            id=node_id,
            name=str(getattr(n, "display_name", "") or node_id),
            category=_normalise_category(getattr(n, "node_type", None)),
        ))
        known_ids.add(node_id)

    edge_specs: list[ChartEdge] = []
    for e in edges:
        src = str(getattr(e, "source_node_id"))
        tgt = str(getattr(e, "target_node_id"))
        if src not in known_ids or tgt not in known_ids:
            continue
        edge_specs.append(ChartEdge(
            source=src,
            target=tgt,
            relation=str(getattr(e, "edge_type", "") or "related"),
        ))

    return ChartPayload(
        nodes=node_specs,
        edges=edge_specs,
        meta=ChartMeta(title=title, source_ref=source_ref),
    )


# ---------------------------------------------------------------------------
# Knowledge graph (evidence-grounded) adapter — used by scenario_4 教材
# 章节知识图谱 (KnowledgeGraphNode/Edge).
# ---------------------------------------------------------------------------


def knowledge_graph_to_chart(
    *,
    nodes: Iterable[Any],
    edges: Iterable[Any],
    title: str,
    source_ref: str | None = None,
) -> ChartPayload:
    """Convert `KnowledgeGraphNode/Edge` rows to a ChartPayload.

    Node attributes: `id / name / node_type` (see `models.py:2226`).
    Edge attributes: `source_node_id / target_node_id / relation_type`
    (see `models.py:2296+`).
    """
    node_specs: list[ChartNode] = []
    known_ids: set[str] = set()
    for n in nodes:
        node_id = str(getattr(n, "id"))
        node_specs.append(ChartNode(
            id=node_id,
            name=str(getattr(n, "name", "") or node_id),
            category=_normalise_category(getattr(n, "node_type", None)),
        ))
        known_ids.add(node_id)

    edge_specs: list[ChartEdge] = []
    for e in edges:
        src = str(getattr(e, "source_node_id"))
        tgt = str(getattr(e, "target_node_id"))
        if src not in known_ids or tgt not in known_ids:
            continue
        edge_specs.append(ChartEdge(
            source=src,
            target=tgt,
            relation=str(getattr(e, "relation_type", "") or "related"),
        ))

    return ChartPayload(
        nodes=node_specs,
        edges=edge_specs,
        meta=ChartMeta(title=title, source_ref=source_ref),
    )


# ---------------------------------------------------------------------------
# chart_id generation + registry (§7.3)
# ---------------------------------------------------------------------------


def make_chart_id(tool_call_id: str, chart_index: int = 0) -> str:
    """Deterministic chart_id.

    Format is fixed at ``{tool_call_id}:{chart_index}`` so the same
    (tool_call_id, chart_index) always produces the same id — Composer
    prompts that reuse the same tool_calls list won't stage two different
    chart entries for what's semantically one artefact.
    """
    if not tool_call_id:
        raise ValueError("tool_call_id required to produce chart_id")
    if chart_index < 0:
        raise ValueError("chart_index must be >= 0")
    return f"{tool_call_id}:{chart_index}"


@dataclass
class ChartRegistry:
    """Per-request map of chart_id → ChartPayload.

    Lifetime is one Layer 2 / Layer 3 round-trip — instantiated by the
    dispatcher, populated as tools run, consumed by
    `replace_chart_placeholders()` after Composer finishes streaming.
    Not thread-safe (a request lives on a single async task) and not
    persisted (would defeat the "Composer output never touches
    governance" contract).
    """

    _charts: dict[str, ChartPayload] = field(default_factory=dict)

    def register(
        self,
        *,
        tool_call_id: str,
        payload: ChartPayload,
        chart_index: int = 0,
    ) -> str:
        chart_id = make_chart_id(tool_call_id, chart_index)
        # Repeated registration of the same key is legal (Composer might
        # replay a tool_call) but the last-write wins so downstream sees
        # the freshest payload.
        self._charts[chart_id] = payload
        return chart_id

    def get(self, chart_id: str) -> ChartPayload | None:
        return self._charts.get(chart_id)

    def registered_ids(self) -> set[str]:
        return set(self._charts.keys())

    def __len__(self) -> int:  # pragma: no cover - trivial
        return len(self._charts)


# ---------------------------------------------------------------------------
# Placeholder replacement (§7.3 — swap after stream end, not incrementally)
# ---------------------------------------------------------------------------

# Placeholder token that Composer prompt is instructed to emit whenever it
# would reference a chart. `chart_id` follows `[[CHART:` and matches the
# `{tool_call_id}:{chart_index}` format produced by `make_chart_id`. The
# regex is deliberately loose about the tail so a copy-paste typo in the
# Composer output still parses (we treat malformed placeholders as
# hallucinations rather than silently keeping them).
_PLACEHOLDER_RE = re.compile(r"\[\[CHART:([^\[\]\s]+)\]\]")


@dataclass(frozen=True)
class ChartReplacementResult:
    """Outcome of `replace_chart_placeholders` — carries the rewritten
    Markdown plus audit-ready lists for the two failure modes (§7.3).
    """

    text: str
    hallucination_ids: list[str]      # ids referenced by Composer but not registered
    unused_ids: list[str]             # ids registered but never referenced


def _fence_for(chart_id: str, payload: ChartPayload) -> str:
    """Render one chart:echarts fenced code block.

    Kept as its own helper so tests can call it directly and so callers
    can render a single chart without going through the whole replacer.
    """
    import json as _json
    body = _json.dumps(payload.to_json(), ensure_ascii=False, indent=2)
    # The fence language `chart:echarts` is the P0 canonical value (§7.1);
    # front-end matches on this exact string.
    return f"```chart:echarts\n{body}\n```"


def replace_chart_placeholders(
    text: str,
    registry: ChartRegistry,
) -> ChartReplacementResult:
    """Swap `[[CHART:xxx]]` placeholders for fenced blocks after stream end.

    Behaviour matches §7.3:

    * Every `[[CHART:xxx]]` whose xxx is registered is replaced by the
      corresponding fenced code block.
    * Placeholders whose xxx is NOT registered are left verbatim in the
      output AND the id is recorded in `hallucination_ids`.
    * Registered ids that never appear in `text` are recorded in
      `unused_ids`.

    Rationale for keeping hallucinated placeholders visible: makes
    review-time diagnosis possible; front-end can style the leftover
    tokens or hide them entirely. Silent removal would obscure the
    issue.
    """
    seen: set[str] = set()
    hallucination: list[str] = []

    def _sub(match: re.Match[str]) -> str:
        chart_id = match.group(1)
        payload = registry.get(chart_id)
        if payload is None:
            # Track uniquely — repeated hallucinations of the same id
            # only surface once in the audit summary.
            if chart_id not in hallucination:
                hallucination.append(chart_id)
            return match.group(0)
        seen.add(chart_id)
        return _fence_for(chart_id, payload)

    replaced = _PLACEHOLDER_RE.sub(_sub, text)
    unused = sorted(registry.registered_ids() - seen)
    return ChartReplacementResult(
        text=replaced,
        hallucination_ids=hallucination,
        unused_ids=unused,
    )


__all__ = [
    "ChartEdge",
    "ChartMeta",
    "ChartNode",
    "ChartPayload",
    "ChartRegistry",
    "ChartReplacementResult",
    "capability_graph_to_chart",
    "knowledge_graph_to_chart",
    "make_chart_id",
    "replace_chart_placeholders",
]
