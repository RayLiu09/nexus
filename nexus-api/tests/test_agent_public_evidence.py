from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from nexus_app import models
from nexus_app.enums import AssetVersionStatus, ChunkType, ChunkingStrategy
from test_agent_public_business import seed_document


def seed_chunk(session, ref, id="chunk", text="证据正文", outline_node_id=None):
    chunk = models.KnowledgeChunk(id=id, normalized_ref_id=ref.id, knowledge_type_code="course_textbook",
        chunk_type=ChunkType.SEMANTIC_BLOCK, chunking_strategy=ChunkingStrategy.SEMANTIC_REPACK, chunk_index=0, content=text, source_block_ids=["block-1"],
        locator={"page_start": 1}, chunk_metadata={}, knowledge_outline_node_id=outline_node_id)
    session.add(chunk)
    session.commit()
    return chunk


def test_sections_are_bounded_continuable_and_hidden_refs_never_loaded(app, session, monkeypatch):
    seed_document(session, "book")
    seed_document(session, "hidden", status=AssetVersionStatus.REVIEW_REQUIRED)
    from nexus_api.api import open_evidence
    loaded = []
    def load(ref):
        loaded.append(ref.id)
        return {"body_markdown": "甲" * 150 + "乙" * 50, "blocks": [
            {"block_id": "b1", "md_char_range": [0, 150], "page_start": 3},
            {"block_id": "b2", "md_char_range": [150, 200], "page_start": 4}]}
    monkeypatch.setattr(open_evidence, "load_payload", load)
    client = TestClient(app)
    first = client.get("/open/v1/normalized-refs/ref-book/sections/b1?max_chars=100").json()["data"]
    assert first["content"] == "甲" * 100
    assert first["next_offset"] == 100 and first["locator"]["page_start"] == 3
    second = client.get("/open/v1/normalized-refs/ref-book/sections/b1?offset=100&max_chars=100").json()["data"]
    assert second["content"] == "甲" * 50 and second["next_offset"] is None
    assert client.get("/open/v1/normalized-refs/ref-book/sections?limit=1").json()["data"]["next_offset"] == 1
    assert client.get("/open/v1/normalized-refs/ref-hidden/sections").status_code == 404
    assert "ref-hidden" not in loaded


def test_read_outlines_never_build_and_context_continues_inside_chunk(app, session):
    ref = seed_document(session, "book")
    client = TestClient(app)
    empty = client.get(f"/open/v1/normalized-refs/{ref.id}/knowledge-outline").json()["data"]
    assert empty["available"] is False and empty["nodes"] == []
    assert session.scalar(select(func.count()).select_from(models.KnowledgeOutlineNode)) == 0
    node = models.KnowledgeOutlineNode(id="node", normalized_ref_id=ref.id, title="章节", level=1, order_index=1, build_run_id="existing")
    session.add(node)
    session.commit()
    seed_chunk(session, ref, text="甲" * 150, outline_node_id=node.id)
    outline = client.get(f"/open/v1/normalized-refs/{ref.id}/knowledge-outline?parent_node_id=node").json()["data"]
    assert outline["available"] is True and outline["total"] == 1
    path = f"/open/v1/normalized-refs/{ref.id}/outlines/knowledge/nodes/node/context"
    first = client.get(path + "?max_chars=100").json()["data"]
    assert first["chunks"][0]["content"] == "甲" * 100
    assert first["next_offset"] == 0 and first["next_char_offset"] == 100
    second = client.get(path + "?offset=0&char_offset=100&max_chars=100").json()["data"]
    assert second["chunks"][0]["content"] == "甲" * 50 and second["next_offset"] is None
    assert client.get(f"/open/v1/normalized-refs/{ref.id}/task-outline").json()["data"]["available"] is False


def test_batch_resolves_each_item_without_visibility_leak(app, session):
    public = seed_document(session, "public")
    hidden = seed_document(session, "hidden", status=AssetVersionStatus.REVIEW_REQUIRED)
    seed_chunk(session, public, "public-chunk", "甲" * 200)
    seed_chunk(session, hidden, "hidden-chunk", "不应返回的内容")
    client = TestClient(app)
    references = [{"kind": "chunk", "id": id} for id in ("public-chunk", "hidden-chunk", "missing")]
    result = client.post("/open/v1/evidence-resolutions", json={"references": references, "max_chars": 100})
    assert result.status_code == 200, result.text
    data = result.json()["data"]
    assert data[0]["status"] == "available" and data[0]["truncated"]
    assert data[0]["source_block_ids"] == ["block-1"]
    assert data[1] == {**data[2], "id": "hidden-chunk"}
    assert "不应返回" not in result.text
    assert client.post("/open/v1/evidence-resolutions", json={"references": references * 11}).status_code == 422


def test_current_ref_and_latest_official_classification_gate(app, session):
    ref = seed_document(session, "book")
    newer = models.NormalizedAssetRef(**{column.key: getattr(ref, column.key) for column in models.NormalizedAssetRef.__table__.columns if column.key not in ("id", "created_at", "updated_at")})
    newer.id = "newer-ref"
    newer.created_at = ref.created_at + timedelta(seconds=1)
    session.add(newer)
    session.commit()
    client = TestClient(app)
    assert client.get(f"/open/v1/normalized-refs/{ref.id}/knowledge-outline").status_code == 404
    assert client.get("/open/v1/course-textbooks").json()["data"] == []


def test_graph_exact_ref_subgraph_and_no_build(app, session):
    ref = seed_document(session, "graph", "competency_analysis")
    client = TestClient(app)
    path = f"/open/v1/normalized-refs/{ref.id}/knowledge-graph?graph_type=ability_analysis"
    assert client.get(path).json()["data"]["reason"] == "not_generated"
    assert session.scalar(select(func.count()).select_from(models.CapabilityGraphStagingBuild)) == 0
    build = models.CapabilityGraphStagingBuild(id="build", normalized_ref_id=ref.id, domain="occupation", build_type="ability_analysis", status="generated", schema_version="1")
    session.add(build)
    session.flush()
    session.add_all([models.CapabilityGraphStagingNode(id=id, build_id=build.id, node_type="skill", node_key=id, display_name=id, properties={}) for id in ("n1", "n2", "n3")])
    session.flush()
    session.add_all([models.CapabilityGraphStagingEdge(id=f"edge-{i}", build_id=build.id, source_node_id="n1", target_node_id=f"n{i}", edge_type="requires", evidence={"source_block_ids": ["block-1"]}) for i in (2, 3)])
    session.commit()
    result = client.get(path + "&node_id=n1&depth=1&max_nodes=2")
    assert result.status_code == 200, result.text
    data = result.json()["data"]
    assert data["build_id"] == "build" and data["truncated"]
    assert len(data["nodes"]) == 2 and len(data["edges"]) == 1
    assert data["edges"][0]["evidence"]
    zero = client.get(path + "&node_id=n1&depth=0").json()["data"]
    assert len(zero["nodes"]) == 1 and zero["edges"] == []
    semantic = seed_document(session, "semantic", "talent_demand_report")
    assert client.get(f"/open/v1/normalized-refs/{semantic.id}/knowledge-graph").json()["data"]["reason"] == "semantic_only_resource"


def test_standard_graph_read_allows_review_library_without_activating(app, session):
    from test_teaching_standard_library_api import _seed_library
    ref = seed_document(session, "review", "teaching_standard")
    library, _ = _seed_library(session)
    session.add(models.CapabilityGraphStagingBuild(id="standard-build", normalized_ref_id=ref.id,
        domain="standard", build_type="teaching_standard", status="generated", schema_version="1"))
    session.commit()
    result = TestClient(app).get(f"/open/v1/normalized-refs/{ref.id}/knowledge-graph?graph_type=teaching_standard")
    assert result.status_code == 200, result.text
    assert result.json()["data"]["available"] is True
    session.refresh(library)
    assert library.status == "review"


def test_search_scope_is_intersected_before_retrieval_and_multikb(app, session, stub_api_caller, monkeypatch):
    session.add(stub_api_caller)
    selected = seed_document(session, "selected", "industry_policy")
    seed_document(session, "other", "industry_policy")
    seed_document(session, "hidden", "industry_policy", status=AssetVersionStatus.REVIEW_REQUIRED)
    calls = []
    class Adapter:
        def search(self, session, **kwargs):
            calls.append(kwargs)
            return []
    from nexus_api.api import open as open_api
    monkeypatch.setattr(open_api, "get_pgvector_search_adapter", lambda: Adapter())
    client = TestClient(app)
    result = client.get("/open/v1/search", params=[("q", "政策"), ("asset_ids", "asset-selected"), ("knowledge_types", "industry_policy"), ("knowledge_types", "industry_report")])
    assert result.status_code == 200, result.text
    assert len(calls) == 2
    assert all(call["normalized_ref_ids"] == [selected.id] for call in calls)
    calls.clear()
    result = client.get("/open/v1/search?q=政策&asset_ids=asset-selected&normalized_ref_ids=ref-other")
    assert result.status_code == 200 and calls == []


def test_evidence_graph_exposes_stored_facts_and_same_ref_anchors(app, session):
    ref = seed_document(session, "kg")
    chunk = seed_chunk(session, ref)
    build = models.KnowledgeGraphBuild(id="kg", normalized_ref_id=ref.id, graph_profile="course_textbook", strategy_version="1", status="succeeded")
    session.add(build)
    session.flush()
    session.add_all([models.KnowledgeGraphNode(id=id, graph_build_id=build.id, normalized_ref_id=ref.id, node_key=id, node_type="concept", name=id) for id in ("entity1", "entity2")])
    session.flush()
    fact = models.KnowledgeGraphFact(id="fact", graph_build_id=build.id, normalized_ref_id=ref.id, fact_type="relation", subject_node_id="entity1", predicate="requires", object_node_id="entity2", qualifiers={"source": "document"})
    edge = models.KnowledgeGraphEdge(id="edge", graph_build_id=build.id, normalized_ref_id=ref.id, source_node_id="entity1", target_node_id="entity2", relation_type="requires")
    session.add_all([fact, edge])
    session.flush()
    session.add(models.KnowledgeGraphEvidence(graph_build_id=build.id, normalized_ref_id=ref.id, fact_id=fact.id, edge_id=edge.id, chunk_id=chunk.id, source_block_ids=["block-1"], evidence_text="原文依据", extraction_method="llm"))
    session.commit()
    result = TestClient(app).get(f"/open/v1/normalized-refs/{ref.id}/knowledge-graph")
    assert result.status_code == 200, result.text
    data = result.json()["data"]
    assert data["facts"][0]["id"] == fact.id
    assert data["edges"][0]["evidence"][0]["chunk_id"] == chunk.id
    assert data["edges"][0]["evidence"][0]["source_block_ids"] == ["block-1"]


def test_task_outline_context_search_and_same_ref_cycle_safe_subtree(app, session, stub_api_caller, monkeypatch):
    session.add(stub_api_caller)
    ref = seed_document(session, "task")
    profile = models.CourseTextbook(id="profile", normalized_ref_id=ref.id, asset_version_id=ref.version_id,
        asset_profile="course_textbook", title="实训", textbook_subtype="training_operation", processing_profile="task_outline", evidence_graph_admission="recommended")
    session.add(profile)
    session.flush()
    root = models.TaskOutlineNode(id="task-root", normalized_ref_id=ref.id, profile_id=profile.id, title="实训", node_type="project", depth=0, order_no=0, content="任务说明")
    child = models.TaskOutlineNode(id="task-child", normalized_ref_id=ref.id, profile_id=profile.id, title="任务", node_type="task", parent_id=root.id, depth=1, order_no=1)
    session.add_all([root, child])
    session.commit()
    chunk = seed_chunk(session, ref, "task-chunk")
    chunk.chunk_metadata = {"outline_node_id": child.id}
    session.commit()
    client = TestClient(app)
    result = client.get(f"/open/v1/normalized-refs/{ref.id}/task-outline?parent_node_id=task-root")
    assert result.status_code == 200 and result.json()["data"]["total"] == 2
    context = client.get(f"/open/v1/normalized-refs/{ref.id}/outlines/task/nodes/task-root/context").json()["data"]
    assert context["chunks"][0]["id"] == chunk.id
    calls = []
    class Adapter:
        def search(self, session, **kwargs):
            calls.append(kwargs)
            return []
    from nexus_api.api import open as open_api
    monkeypatch.setattr(open_api, "get_pgvector_search_adapter", lambda: Adapter())
    result = client.get("/open/v1/search?q=任务&task_outline_node=task-root")
    assert result.status_code == 200, result.text
    assert calls[0]["chunk_ids"] == [chunk.id]
    # Bad historical cycles cannot make a read recurse forever.
    root.parent_id = child.id
    session.commit()
    assert client.get(f"/open/v1/normalized-refs/{ref.id}/task-outline?parent_node_id=task-root").json()["data"]["total"] == 2


def test_revocation_during_payload_load_fails_before_data_and_audit(app, session, stub_api_caller, monkeypatch):
    from datetime import datetime, timezone
    session.add(stub_api_caller)
    seed_document(session, "revoke")
    session.commit()
    before = session.scalar(select(func.count()).select_from(models.AuditLog))
    from nexus_api.api import open_evidence
    def load(ref):
        stub_api_caller.revoked_at = datetime.now(timezone.utc)
        session.commit()
        return {"body_markdown": "应被拒绝的原文"}
    monkeypatch.setattr(open_evidence, "load_payload", load)
    result = TestClient(app).get("/open/v1/normalized-refs/ref-revoke/sections")
    assert result.status_code == 403 and "应被拒绝" not in result.text
    assert session.scalar(select(func.count()).select_from(models.AuditLog)) == before


def test_batch_missing_payload_does_not_abort_other_items(app, session, monkeypatch):
    from fastapi import HTTPException
    from nexus_api.api import open_evidence
    ref = seed_document(session, "missing-payload")
    session.add(models.RawJob(id="job", title_raw="运营"))
    session.commit()
    def load(ref):
        raise HTTPException(404, "normalized_payload_missing")
    monkeypatch.setattr(open_evidence, "load_payload", load)
    result = TestClient(app).post("/open/v1/evidence-resolutions", json={"references": [
        {"kind": "normalized_ref", "id": ref.id}, {"kind": "market_job", "id": "job"}]})
    assert result.status_code == 200, result.text
    data = result.json()["data"]
    assert data[0]["status"] == "not_found" and data[0]["normalized_ref_id"] is None
    assert data[1]["status"] == "available"
