"""Bounded read adapters: no knowledge production, rebuilding or promotion."""
from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from nexus_api import public_schemas as dto, schemas
from nexus_api.auth import require_api_caller
from nexus_api.public_access import audit_read, classification_for, require_ref
from nexus_api.responses import response
from nexus_app import models
from nexus_app.database import get_db

router = APIRouter(prefix="/open/v1", tags=["public-evidence"], dependencies=[Depends(require_api_caller)])


def bounded_object(value, max_chars=4000):
    encoded = json.dumps(value, ensure_ascii=False, default=str)
    return value if len(encoded) <= max_chars else {"truncated": True, "preview": encoded[:max_chars]}


def load_payload(ref):
    from nexus_api.api.internal.normalized_refs import _load_normalized_payload
    return _load_normalized_payload(ref)


def sections(payload):
    """Block IDs are persisted source anchors. 'body' is the full-text fallback."""
    blocks = [block for block in payload.get("blocks", []) if isinstance(block, dict)]
    body = payload.get("body_markdown") or ""
    result = []
    for block in blocks:
        block_id = block.get("block_id") or block.get("id")
        if not block_id:
            continue
        span = block.get("md_char_range")
        text = block.get("text") or block.get("content") or ""
        if isinstance(span, list) and len(span) == 2 and all(isinstance(x, int) for x in span):
            text = body[max(0, span[0]):max(0, span[1])]
        if not isinstance(text, str):
            text = json.dumps(text, ensure_ascii=False)
        locator = dict(block.get("locator") or {})
        for key in ("page_start", "page_end", "page_index", "md_char_range"):
            if key in block:
                locator[key] = block[key]
        result.append({"id": str(block_id), "title": block.get("title"), "content": text,
                       "source_block_ids": [str(block_id)], "locator": locator})
    if not result:
        result.append({"id": "body", "title": payload.get("title"), "content": body,
                       "source_block_ids": [], "locator": {}})
    return result


def section_slice(item, ref_id, offset, max_chars):
    text = item["content"]
    end = min(len(text), offset + max_chars)
    return {**item, "normalized_ref_id": ref_id, "content": text[offset:end],
            "offset": offset, "total_chars": len(text), "truncated": end < len(text),
            "next_offset": end if end < len(text) else None}


@router.get("/normalized-refs/{ref_id}/sections", operation_id="list_document_sections", response_model=schemas.ApiResponse[dto.SectionPage])
def list_sections(ref_id: str, request: Request, offset: int = Query(0, ge=0),
                  limit: int = Query(20, ge=1, le=100), max_chars: int = Query(200, ge=0, le=1000),
                  caller=Depends(require_api_caller), session: Session = Depends(get_db)):
    """List persisted block anchors, with bounded previews and an explicit continuation offset."""
    ref = require_ref(session, ref_id)
    items = sections(load_payload(ref))
    selected = items[offset:offset + limit]
    audit_read(session, request, caller, "document_sections", len(selected), normalized_ref_id=ref_id)
    return response({"items": [section_slice(item, ref_id, 0, max_chars) for item in selected],
                     "total": len(items), "next_offset": offset + len(selected) if offset + len(selected) < len(items) else None}, request)


@router.get("/normalized-refs/{ref_id}/sections/{section_id}", operation_id="read_document_section", response_model=schemas.ApiResponse[dto.SectionRead])
def read_section(ref_id: str, section_id: str, request: Request, offset: int = Query(0, ge=0),
                 max_chars: int = Query(4000, ge=100, le=20000), adjacent_blocks: int = Query(0, ge=0, le=3),
                 caller=Depends(require_api_caller), session: Session = Depends(get_db)):
    """Read an anchored block and optional neighbors. Offsets count Unicode characters in the joined source text."""
    ref = require_ref(session, ref_id)
    items = sections(load_payload(ref))
    index = next((i for i, item in enumerate(items) if item["id"] == section_id), None)
    if index is None:
        raise HTTPException(404, "section_not_found")
    selected = items[max(0, index - adjacent_blocks):index + adjacent_blocks + 1]
    item = {**items[index], "content": "\n\n".join(part["content"] for part in selected),
            "source_block_ids": [bid for part in selected for bid in part["source_block_ids"]],
            "locator": {**items[index]["locator"], "context_blocks": [{"id": part["id"], "locator": part["locator"]} for part in selected]}}
    result = section_slice(item, ref_id, offset, max_chars)
    audit_read(session, request, caller, "document_section", 1, normalized_ref_id=ref_id, section_id=section_id)
    return response(result, request)


def outline_model(kind):
    return models.KnowledgeOutlineNode if kind == "knowledge" else models.TaskOutlineNode


def outline_payload(node, kind):
    if kind == "knowledge":
        anchor = node.anchor_range or {}
        return {"id": node.id, "parent_id": node.parent_id, "title": node.title,
                "depth": node.level, "order": node.order_index, "node_type": "heading",
                "source_block_ids": anchor.get("source_block_ids") or anchor.get("block_ids") or [], "locator": anchor}
    return {"id": node.id, "parent_id": node.parent_id, "title": node.title, "depth": node.depth,
            "order": node.order_no, "node_type": node.node_type, "content": (node.content or node.summary or "")[:4000],
            "content_truncated": len(node.content or node.summary or "") > 4000,
            "source_block_ids": node.source_block_ids or [], "locator": node.locator}


def descendant_ids(session, model, ref_id, node_id):
    tree = select(model.id).where(model.id == node_id, model.normalized_ref_id == ref_id).cte("public_outline_tree", recursive=True)
    # UNION (distinct IDs) terminates even if stored parent links contain a cycle.
    tree = tree.union(select(model.id).join(tree, model.parent_id == tree.c.id).where(model.normalized_ref_id == ref_id))
    return select(tree.c.id)


def read_outline(kind, ref_id, request, offset, limit, parent_node_id, caller, session):
    require_ref(session, ref_id, ("course_textbook",))
    model = outline_model(kind)
    base = select(model).where(model.normalized_ref_id == ref_id)
    available = session.scalar(select(model.id).where(model.normalized_ref_id == ref_id).limit(1)) is not None
    if parent_node_id:
        if not session.scalar(select(model.id).where(model.id == parent_node_id, model.normalized_ref_id == ref_id)):
            raise HTTPException(404, "outline_node_not_found")
        base = base.where(model.id.in_(descendant_ids(session, model, ref_id, parent_node_id)))
    total = session.scalar(select(func.count()).select_from(base.subquery())) or 0
    order = model.order_index if kind == "knowledge" else model.order_no
    rows = session.scalars(base.order_by(order, model.id).offset(offset).limit(limit)).all()
    audit_read(session, request, caller, f"{kind}_outline", len(rows), normalized_ref_id=ref_id)
    return response({"normalized_ref_id": ref_id, "outline_type": kind, "available": available,
                     "nodes": [outline_payload(node, kind) for node in rows], "total": total,
                     "has_more": offset + len(rows) < total,
                     "next_offset": offset + len(rows) if offset + len(rows) < total else None}, request)


@router.get("/normalized-refs/{ref_id}/knowledge-outline", operation_id="get_knowledge_outline", response_model=schemas.ApiResponse[dto.OutlineRead])
def knowledge_outline(ref_id: str, request: Request, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500),
                      parent_node_id: str | None = Query(None, max_length=36),
                      caller=Depends(require_api_caller), session: Session = Depends(get_db)):
    """Read only the existing knowledge outline; a missing outline never triggers a build."""
    return read_outline("knowledge", ref_id, request, offset, limit, parent_node_id, caller, session)


@router.get("/normalized-refs/{ref_id}/task-outline", operation_id="get_task_outline", response_model=schemas.ApiResponse[dto.OutlineRead])
def task_outline(ref_id: str, request: Request, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500),
                 parent_node_id: str | None = Query(None, max_length=36),
                 caller=Depends(require_api_caller), session: Session = Depends(get_db)):
    """Read only the existing task outline, separately from the knowledge hierarchy."""
    return read_outline("task", ref_id, request, offset, limit, parent_node_id, caller, session)


@router.get("/normalized-refs/{ref_id}/outlines/{outline_type}/nodes/{node_id}/context", operation_id="get_outline_node_context", response_model=schemas.ApiResponse[dto.NodeContextRead])
def node_context(ref_id: str, outline_type: Literal["knowledge", "task"], node_id: str, request: Request,
                 offset: int = Query(0, ge=0), char_offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100), max_chars: int = Query(8000, ge=100, le=20000),
                 caller=Depends(require_api_caller), session: Session = Depends(get_db)):
    """Read linked chunks in a node subtree, bounded by both chunk count and total text characters."""
    ref = require_ref(session, ref_id, ("course_textbook",))
    model = outline_model(outline_type)
    node = session.scalar(select(model).where(model.id == node_id, model.normalized_ref_id == ref_id))
    if node is None:
        raise HTTPException(404, "outline_node_not_found")
    ids = descendant_ids(session, model, ref_id, node_id)
    chunk = models.KnowledgeChunk
    link = chunk.knowledge_outline_node_id if outline_type == "knowledge" else chunk.chunk_metadata["outline_node_id"].as_string()
    base = select(chunk).where(chunk.normalized_ref_id == ref_id, link.in_(ids))
    total = session.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = session.scalars(base.order_by(chunk.chunk_index, chunk.id).offset(offset).limit(limit)).all()
    from nexus_api.api.open import _serialize_chunk
    version = session.get(models.AssetVersion, ref.version_id)
    result, remaining, next_char_offset = [], max_chars, 0
    for row in rows:
        if remaining <= 0:
            break
        item = _serialize_chunk(row, ref, version)
        start = char_offset if not result else 0
        item["content_offset"] = start
        item["content_total_chars"] = len(row.content)
        item["content"] = row.content[start:start + remaining]
        item["truncated"] = len(row.content) > start + remaining
        if item["truncated"]:
            next_char_offset = start + len(item["content"])
        remaining -= len(item["content"])
        result.append(item)
    next_offset = offset + len(result) - 1 if next_char_offset else (offset + len(result) if offset + len(result) < total else None)
    audit_read(session, request, caller, "outline_node_context", len(result), normalized_ref_id=ref_id, node_id=node_id)
    return response({"normalized_ref_id": ref_id, "node": outline_payload(node, outline_type), "chunks": result,
                     "total": total, "next_offset": next_offset, "next_char_offset": next_char_offset,
                     "truncated": next_offset is not None or any(item["truncated"] for item in result)}, request)


@router.get("/normalized-refs/{ref_id}/knowledge-graph", operation_id="read_existing_graph", response_model=schemas.ApiResponse[dto.GraphRead])
def graph(ref_id: str, request: Request,
          graph_type: Literal["evidence_grounded_kg", "teaching_standard", "ability_analysis", "job_demand", "combined"] = Query("evidence_grounded_kg"),
          node_id: str | None = Query(None, max_length=36), node_types: list[str] | None = Query(None, max_length=10),
          relation_types: list[str] | None = Query(None, max_length=10), depth: int = Query(1, ge=0, le=5),
          max_nodes: int = Query(100, ge=1, le=500), max_edges: int = Query(200, ge=1, le=1000),
          caller=Depends(require_api_caller), session: Session = Depends(get_db)):
    """Read an existing exact-ref graph or bounded neighborhood. Generated relations remain derived assertions with evidence."""
    require_ref(session, ref_id)
    classification = session.scalar(select(classification_for(ref_id)))
    result = {"normalized_ref_id": ref_id, "graph_type": graph_type, "available": False,
              "nodes": [], "edges": [], "facts": [], "truncated": False, "reason": "not_generated"}
    active_standard = graph_type != "teaching_standard" or (classification == "teaching_standard" and session.scalar(select(models.TeachingStandardLibrary.id).where(
        models.TeachingStandardLibrary.normalized_ref_id == ref_id, models.TeachingStandardLibrary.status == "active").limit(1)))
    if not active_standard:
        result["reason"] = "standard_library_not_active"
    elif classification in ("talent_demand_report", "teaching_case"):
        result["reason"] = "semantic_only_resource"
    else:
        evidence_graph = graph_type == "evidence_grounded_kg"
        build_model = models.KnowledgeGraphBuild if evidence_graph else models.CapabilityGraphStagingBuild
        type_col = build_model.graph_type if evidence_graph else build_model.build_type
        build = session.scalar(select(build_model).where(build_model.normalized_ref_id == ref_id,
            type_col == graph_type, build_model.status == ("succeeded" if evidence_graph else "generated"))
            .order_by(build_model.created_at.desc(), build_model.id.desc()).limit(1))
        if build:
            result.update(available=True, build_id=build.id, reason=None)
            node_model = models.KnowledgeGraphNode if evidence_graph else models.CapabilityGraphStagingNode
            edge_model = models.KnowledgeGraphEdge if evidence_graph else models.CapabilityGraphStagingEdge
            nbuild = node_model.graph_build_id if evidence_graph else node_model.build_id
            ebuild = edge_model.graph_build_id if evidence_graph else edge_model.build_id
            relation = edge_model.relation_type if evidence_graph else edge_model.edge_type
            ns = select(node_model).where(nbuild == build.id)
            if node_types:
                ns = ns.where(node_model.node_type.in_(node_types))
            es = select(edge_model).where(ebuild == build.id)
            if relation_types:
                es = es.where(relation.in_(relation_types))
            if node_id:
                if not session.scalar(ns.where(node_model.id == node_id)):
                    raise HTTPException(404, "graph_node_not_found")
                selected, frontier = {node_id}, {node_id}
                for _ in range(depth):
                    touching = es.where(or_(edge_model.source_node_id.in_(frontier), edge_model.target_node_id.in_(frontier)))
                    edges = session.scalars(touching.order_by(edge_model.id).limit(max_edges + 1)).all()
                    candidates = {id_ for edge in edges for id_ in (edge.source_node_id, edge.target_node_id)}
                    allowed = set(session.scalars(ns.with_only_columns(node_model.id).where(node_model.id.in_(candidates)).order_by(node_model.id).limit(max_nodes + 1)))
                    new = sorted(allowed - selected)
                    remaining = max_nodes - len(selected)
                    result["truncated"] |= len(edges) > max_edges or len(new) > remaining
                    frontier = set(new[:remaining])
                    selected.update(frontier)
                    if not frontier:
                        break
                ns = ns.where(node_model.id.in_(selected))
            nodes = session.scalars(ns.order_by(node_model.node_type, node_model.id).limit(max_nodes + 1)).all()
            result["truncated"] |= len(nodes) > max_nodes
            nodes = nodes[:max_nodes]
            ids = [node.id for node in nodes]
            edges = session.scalars(es.where(edge_model.source_node_id.in_(ids), edge_model.target_node_id.in_(ids)).order_by(edge_model.id).limit(max_edges + 1)).all()
            result["truncated"] |= len(edges) > max_edges
            edges = edges[:max_edges]
            node_evidence, edge_evidence = {}, {}
            if evidence_graph and (ids or edges):
                ev = models.KnowledgeGraphEvidence
                # Per target caps prevent one fact's evidence from exhausting the response.
                for target, mapping, keys in ((ev.entity_id, node_evidence, ids), (ev.edge_id, edge_evidence, [e.id for e in edges])):
                    ranked = select(ev.id, func.row_number().over(partition_by=target, order_by=ev.id).label("rn")).where(
                        ev.graph_build_id == build.id, ev.normalized_ref_id == ref_id, target.in_(keys),
                        ev.chunk_id.in_(select(models.KnowledgeChunk.id).where(models.KnowledgeChunk.normalized_ref_id == ref_id)),
                    ).subquery()
                    for item in session.scalars(select(ev).join(ranked, ranked.c.id == ev.id).where(ranked.c.rn <= 3).order_by(ev.id)):
                        key = item.entity_id if mapping is node_evidence else item.edge_id
                        mapping.setdefault(key, []).append({"fact_id": item.fact_id, "chunk_id": item.chunk_id,
                            "source_block_ids": item.source_block_ids or [], "locator": item.locator,
                            "evidence_text": item.evidence_text[:1000], "truncated": len(item.evidence_text) > 1000})
            if evidence_graph:
                fact_ids = {ev.get("fact_id") for mapping in (node_evidence, edge_evidence) for values in mapping.values() for ev in values if ev.get("fact_id")}
                fact = models.KnowledgeGraphFact
                facts = session.scalars(select(fact).where(fact.graph_build_id == build.id,
                    fact.normalized_ref_id == ref_id, fact.id.in_(fact_ids), fact.subject_node_id.in_(ids),
                    or_(fact.object_node_id.is_(None), fact.object_node_id.in_(ids))).order_by(fact.id).limit(1001)).all()
                result["truncated"] |= len(facts) > 1000
                result["facts"] = [{"id": f.id, "fact_type": f.fact_type, "subject_node_id": f.subject_node_id,
                    "predicate": f.predicate, "object_node_id": f.object_node_id, "object_literal": (f.object_literal or "")[:2000] if f.object_literal is not None else None,
                    "qualifiers": bounded_object(f.qualifiers or {}), "confidence": f.confidence,
                    "truncated": len(f.object_literal or "") > 2000} for f in facts[:1000]]
            result["nodes"] = [{"id": n.id, "node_type": n.node_type, "name": n.name if evidence_graph else n.display_name,
                "properties": bounded_object(n.properties or {}), "confidence": n.confidence, "evidence": node_evidence.get(n.id, [])} for n in nodes]
            result["edges"] = [{"id": e.id, "source_node_id": e.source_node_id, "target_node_id": e.target_node_id,
                "relation_type": e.relation_type if evidence_graph else e.edge_type, "confidence": e.confidence,
                "evidence": edge_evidence.get(e.id, []) if evidence_graph else [bounded_object(e.evidence or {})]} for e in edges]
    audit_read(session, request, caller, "existing_graph", len(result["nodes"]), normalized_ref_id=ref_id)
    return response(result, request)


@router.post("/evidence-resolutions", operation_id="get_evidence_bundle", response_model=schemas.ApiResponse[list[dto.EvidenceResolution]])
def evidence_bundle(body: dto.EvidenceRequest, request: Request, caller=Depends(require_api_caller), session: Session = Depends(get_db)):
    """Batch read-only resolution. Every item is independently checked; hidden and unknown IDs both return not_found."""
    from nexus_api.api.open_business import job_payload
    from nexus_api.api.open_record_assets import _serialize_ability_item
    from nexus_app.major_offerings import serialize as serialize_offering
    result = []
    for reference in body.references:
        item = {"kind": reference.kind, "id": reference.id, "status": "not_found"}
        model = {"chunk": models.KnowledgeChunk, "normalized_ref": models.NormalizedAssetRef,
            "market_job": models.RawJob, "enterprise": models.Enterprise, "industrial_park": models.IndustrialPark,
            "major_distribution": models.MajorOfferingRecord, "ability_item": models.OccupationalAbilityItem}[reference.kind]
        row = session.get(model, reference.id)
        if row is not None:
            if reference.kind in ("chunk", "normalized_ref"):
                try:
                    ref = require_ref(session, row.normalized_ref_id if reference.kind == "chunk" else row.id)
                except HTTPException as exc:
                    if exc.status_code != 404:
                        raise
                    result.append(item)
                    continue
                version = session.get(models.AssetVersion, ref.version_id)
                try:
                    payload = None if reference.kind == "chunk" else load_payload(ref)
                except HTTPException as exc:
                    if exc.status_code != 404:
                        raise
                    result.append(item)
                    continue
                text = row.content if reference.kind == "chunk" else (payload.get("body_markdown") or (
                    json.dumps(payload["record_body"], ensure_ascii=False) if "record_body" in payload else ""))
                item.update(normalized_ref_id=ref.id, asset_id=version.asset_id, version_id=version.id,
                            source_block_ids=(row.source_block_ids or []) if reference.kind == "chunk" else [],
                            locator=row.locator if reference.kind == "chunk" else None)
            elif reference.kind == "market_job":
                provenance = session.get(models.RawJobProvenance, row.id)
                text = json.dumps(job_payload(row, provenance), ensure_ascii=False, default=str)
                item.update(source_url=provenance.source_url if provenance else None,
                            collected_at=provenance.collected_at if provenance else None)
            elif reference.kind in ("enterprise", "industrial_park"):
                text = json.dumps({key: getattr(row, key) for key in
                    (("enterprise_name", "business_scope", "industrial_park_id") if reference.kind == "enterprise" else ("park_name", "industry_tags", "introduction"))}, ensure_ascii=False)
                item["source_url"] = row.source_url
            else:
                data = serialize_offering(row) if reference.kind == "major_distribution" else _serialize_ability_item(row)
                text = json.dumps(data, ensure_ascii=False, default=str)
                # These are independent domain records, not document-read permission bypasses.
            item.update(status="available", content=text[:body.max_chars], truncated=len(text) > body.max_chars)
        result.append(item)
    audit_read(session, request, caller, "evidence_resolutions", sum(item["status"] == "available" for item in result), requested_count=len(result))
    return response(result, request)
