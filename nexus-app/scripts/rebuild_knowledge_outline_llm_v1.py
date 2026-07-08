"""v1 LLM-classifier prototype for knowledge outline construction.

Extracts every MinerU heading, batches to LiteLLM for semantic label
classification, then builds a strict root → chapter → knowledge_point tree
from `chapter` + `knowledge_point` labels only. Everything else (tasks,
steps, training, list items, front/back matter, structural template nodes)
is dropped from the tree but its blocks still attach to the enclosing kept
heading's chunk span.

Usage::

    python scripts/rebuild_knowledge_outline_llm_v1.py --ref-id <uuid> [--apply]

Without ``--apply``, prints the LLM classifications and the built tree
without touching the DB. With ``--apply``, replaces the existing outline for
the ref via ``build_and_persist_outline_llm``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

_REPO_LOCAL = Path(__file__).resolve().parent.parent
if str(_REPO_LOCAL) not in sys.path:
    sys.path.insert(0, str(_REPO_LOCAL))

from nexus_app import models  # noqa: E402
from nexus_app.ai_governance.services import (  # noqa: E402
    _create_default_litellm_client,
)
from nexus_app.config import get_settings  # noqa: E402
from nexus_app.database import get_session_local  # noqa: E402
from nexus_app.knowledge_outline.llm_classifier import (  # noqa: E402
    LLMOutlineOutcome,
    build_and_persist_outline_llm,
    build_outline_from_classifications,
    classify_headings,
    extract_heading_candidates,
)
from nexus_app.storage import get_object_storage  # noqa: E402


def _object_key(uri: str) -> str:
    return uri.split("/", 3)[-1] if uri.startswith("s3://") else uri


def _load_payload(ref: models.NormalizedAssetRef) -> dict[str, Any]:
    raw = get_object_storage().get_bytes(_object_key(ref.object_uri))
    return json.loads(raw.decode("utf-8"))


def _print_summary(outcome: LLMOutlineOutcome) -> None:
    tree = outcome.tree
    print("\n=== 结果摘要 ===")
    print(f"  Root:           {tree.root_id[:8]}…  '{next((n.title for n in tree.nodes if n.id == tree.root_id), '')}'")
    print(f"  total_nodes:    {tree.total_nodes}")
    print(f"  max_depth:      {tree.max_depth}")
    print(f"  fallback_used:  {tree.fallback_used}")
    print(f"  headings 总数:  {outcome.total_headings}")
    print(f"  headings 保留:  {outcome.kept_headings}")
    print(f"  build_run_id:   {tree.build_run_id}")
    print(f"  label 分布:")
    for lbl, cnt in sorted(outcome.label_distribution.items(), key=lambda x: -x[1]):
        print(f"    {lbl:16s}  {cnt}")

    print("\n=== LLM 调用统计 ===")
    print(f"  batches: {len(outcome.llm_stats)}")
    total_latency = sum(s.latency_ms for s in outcome.llm_stats)
    ok = sum(1 for s in outcome.llm_stats if s.status == "success")
    print(f"  成功批次: {ok} / {len(outcome.llm_stats)}")
    print(f"  总耗时:   {total_latency/1000:.1f}s  (平均 {total_latency/max(1,len(outcome.llm_stats)):.0f}ms/批)")
    for s in outcome.llm_stats:
        marker = "✓" if s.status == "success" else "✗"
        err = f"  err={s.error_message[:60]}" if s.error_message else ""
        print(f"    {marker} batch#{s.batch_no:2d} headings={s.heading_count:2d} parsed={s.parsed_count:2d} {s.latency_ms:.0f}ms{err}")


def _print_tree_topology(outcome: LLMOutlineOutcome, *, max_l2_per_chapter: int = 3) -> None:
    tree = outcome.tree
    nodes_by_parent: dict[str | None, list] = {}
    for n in tree.nodes:
        nodes_by_parent.setdefault(n.parent_id, []).append(n)
    for lst in nodes_by_parent.values():
        lst.sort(key=lambda n: n.order_index)

    root_id = tree.root_id
    print("\n=== 树结构（前几条示例） ===")
    root = next(n for n in tree.nodes if n.id == root_id)
    print(f"  🌳 {root.title}")
    for chap in nodes_by_parent.get(root_id, [])[:8]:
        print(f"    ├─ [{chap.numbering or '?'}] {chap.title[:60]}")
        kps = nodes_by_parent.get(chap.id, [])
        for kp in kps[:max_l2_per_chapter]:
            print(f"    │    ├─ {kp.title[:70]}")
        if len(kps) > max_l2_per_chapter:
            print(f"    │    └─ … 共 {len(kps)} 个知识点")


def _print_dry_run_report(
    candidates, classifications, tree_result, ref_id: str,
) -> None:
    labels_by_idx = {c.idx: c for c in classifications}
    label_dist: Counter = Counter(c.label for c in classifications)
    kept = [c for c in classifications if c.label in ("chapter", "knowledge_point")]

    print(f"\n=== DRY-RUN 结果 for ref {ref_id} ===")
    print(f"  headings 总数: {len(candidates)}")
    print(f"  headings 保留: {len(kept)}")
    print(f"  label 分布:")
    for lbl, cnt in sorted(label_dist.items(), key=lambda x: -x[1]):
        print(f"    {lbl:16s}  {cnt}")

    print(f"\n  预计将建 {tree_result.total_nodes} 节点，max_depth={tree_result.max_depth}，fallback={tree_result.fallback_used}")

    # Sample some misc classifications
    print("\n  示例分类（前 15 条）:")
    for c in candidates[:15]:
        cls = labels_by_idx.get(c.idx)
        if cls:
            print(f"    [{c.block_index:4d}] {cls.label:16s} conf={cls.confidence:.2f}  {c.text[:55]}")

    # Sample kept
    print("\n  保留的 chapter (前 5):")
    for cand in candidates:
        cls = labels_by_idx.get(cand.idx)
        if cls and cls.label == "chapter":
            print(f"    [{cand.block_index:4d}] {cand.text[:70]}")
            if sum(1 for c in candidates[:cand.idx+1] if (labels_by_idx.get(c.idx) or None) and labels_by_idx[c.idx].label == "chapter") >= 5:
                break

    print("\n  保留的 knowledge_point (前 10):")
    kp_count = 0
    for cand in candidates:
        cls = labels_by_idx.get(cand.idx)
        if cls and cls.label == "knowledge_point":
            print(f"    [{cand.block_index:4d}] {cand.text[:70]}")
            kp_count += 1
            if kp_count >= 10:
                break


def rebuild(ref_id: str, *, apply: bool, batch_size: int) -> int:
    settings = get_settings()
    if not settings.litellm_endpoint or not settings.litellm_api_key:
        print("ERROR: LITELLM_ENDPOINT / LITELLM_API_KEY not configured")
        return 1

    SessionLocal = get_session_local()
    with SessionLocal() as session:
        ref = session.get(models.NormalizedAssetRef, ref_id)
        if ref is None:
            print(f"ERROR: normalized_ref '{ref_id}' not found")
            return 1

        payload = _load_payload(ref)
        client = _create_default_litellm_client(settings)
        model_alias = settings.default_governance_model
        print(f"→ ref '{ref.id}'  blocks={ref.block_count}  model={model_alias}")

        if not apply:
            candidates = extract_heading_candidates(payload.get("blocks") or [])
            print(f"→ 抽取 headings: {len(candidates)} 条，开始批分类 (batch={batch_size})…")
            classifications, stats = classify_headings(
                candidates, client=client, model_alias=model_alias,
                batch_size=batch_size,
            )
            from nexus_app.models import new_uuid
            result = build_outline_from_classifications(
                candidates, classifications, payload.get("blocks") or [],
                root_title=payload.get("title") or "全文",
                build_run_id=new_uuid(),
            )
            _print_dry_run_report(candidates, classifications, result, ref_id)
            print("\n(dry-run: 未落库。加 --apply 提交。)")
            return 0

        outcome = build_and_persist_outline_llm(
            session,
            ref=ref,
            payload=payload,
            client=client,
            model_alias=model_alias,
            rules_etag=None,
            actor_type="script",
            actor_id="rebuild_knowledge_outline_llm_v1",
            is_rebuild=True,
            batch_size=batch_size,
        )
        session.commit()

        _print_summary(outcome)
        _print_tree_topology(outcome)
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ref-id", required=True)
    parser.add_argument("--apply", action="store_true",
                        help="persist to DB; without this flag runs dry-run")
    parser.add_argument("--batch-size", type=int, default=40)
    args = parser.parse_args()
    return rebuild(args.ref_id, apply=args.apply, batch_size=args.batch_size)


if __name__ == "__main__":
    raise SystemExit(main())
