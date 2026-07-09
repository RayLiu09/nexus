"""Review queue lifecycle: upsert during rebuild + SME actions + rebuild
consumption of prior SME decisions."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from nexus_app import models
from nexus_app.enums import (
    AssetKind,
    AssetVersionStatus,
    AuditEventType,
    DataSourceType,
    IngestBatchStatus,
    NormalizedAssetRefStatus,
    NormalizedType,
    RawObjectStatus,
)
from nexus_app.knowledge_outline.review_service import (
    STATUS_APPROVED,
    STATUS_DISMISSED,
    STATUS_OVERRIDDEN,
    STATUS_PENDING,
    ClassifiedHeadingInput,
    approve_review_item,
    dismiss_review_item,
    get_sme_decisions,
    list_review_items,
    override_review_item,
    upsert_review_items,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _seed_ref(session, ref_id: str = "ref-rev"):
    ds = models.DataSource(id=f"ds-{ref_id}", code=f"ds-{ref_id}", name="src",
                           source_type=DataSourceType.FILE_UPLOAD)
    batch = models.IngestBatch(id=f"b-{ref_id}", data_source_id=ds.id,
                               idempotency_key=f"idem-{ref_id}",
                               source_type=DataSourceType.FILE_UPLOAD,
                               status=IngestBatchStatus.COMPLETED)
    raw = models.RawObject(id=f"r-{ref_id}", batch_id=batch.id, data_source_id=ds.id,
                           source_type=DataSourceType.FILE_UPLOAD,
                           object_uri="s3://x/y.pdf", checksum=f"cs-{ref_id}",
                           mime_type="application/pdf",
                           status=RawObjectStatus.RAW_PERSISTED)
    asset = models.Asset(id=f"a-{ref_id}", data_source_id=ds.id,
                         source_object_key=f"{ref_id}.pdf", title="T",
                         asset_kind=AssetKind.DOCUMENT,
                         status=AssetVersionStatus.PROCESSING)
    version = models.AssetVersion(id=f"v-{ref_id}", asset_id=asset.id,
                                  raw_object_id=raw.id, version_no=1,
                                  source_checksum=raw.checksum,
                                  version_status=AssetVersionStatus.PROCESSING)
    ref = models.NormalizedAssetRef(
        id=ref_id, version_id=version.id,
        normalized_type=NormalizedType.DOCUMENT,
        object_uri=f"s3://x/{ref_id}.json",
        schema_version="normalized-document-v1", checksum=f"nc-{ref_id}",
        status=NormalizedAssetRefStatus.GENERATED,
        block_count=5, record_count=0,
    )
    session.add_all([ds, batch, raw, asset, version, ref])
    session.flush()
    return ref


def _seed_ai_run(session, ref, run_id: str = "run-1"):
    from nexus_app.enums import (
        AIGovernanceRunAdoptionStatus, AIGovernanceRunValidationStatus,
    )
    run = models.AIGovernanceRun(
        id=run_id, normalized_ref_id=ref.id,
        model_alias="fake", prompt_version="v1",
        input_hash="0" * 64, input_summary={}, ai_output={},
        validation_status=AIGovernanceRunValidationStatus.SCHEMA_VALID,
        adoption_status=AIGovernanceRunAdoptionStatus.REVIEW_REQUIRED,
    )
    session.add(run)
    session.flush()
    return run


def _mk_heading(
    block_id: str, label: str = "knowledge_point",
    conf: float = 0.6, bucket: str = "mid",
) -> ClassifiedHeadingInput:
    return ClassifiedHeadingInput(
        block_id=block_id, heading_text=f"标题-{block_id}",
        llm_label=label, llm_confidence=conf,
        llm_reason=f"reason-{block_id}", bucket=bucket,
    )


# ---------------------------------------------------------------------------
# upsert_review_items
# ---------------------------------------------------------------------------


def test_upsert_skips_high_confidence_and_creates_mid_low(session):
    ref = _seed_ref(session, "ref-upsert-1")
    run = _seed_ai_run(session, ref)
    created, updated = upsert_review_items(
        session, ref=ref, ai_run=run,
        headings=[
            _mk_heading("b1", conf=0.95, bucket="high"),
            _mk_heading("b2", conf=0.6, bucket="mid"),
            _mk_heading("b3", conf=0.2, bucket="low"),
        ],
    )
    session.commit()
    rows = list(session.scalars(
        select(models.KnowledgeOutlineReviewItem)
        .where(models.KnowledgeOutlineReviewItem.normalized_ref_id == ref.id)
    ))
    assert created == 2 and updated == 0
    block_ids = {r.heading_block_id for r in rows}
    assert block_ids == {"b2", "b3"}


def test_upsert_refreshes_pending_row_on_rebuild(session):
    ref = _seed_ref(session, "ref-upsert-2")
    run1 = _seed_ai_run(session, ref, "run-a")
    upsert_review_items(
        session, ref=ref, ai_run=run1,
        headings=[_mk_heading("b1", label="knowledge_point", conf=0.6)],
    )
    session.commit()

    run2 = _seed_ai_run(session, ref, "run-b")
    upsert_review_items(
        session, ref=ref, ai_run=run2,
        headings=[_mk_heading("b1", label="chapter", conf=0.55)],
    )
    session.commit()

    row = session.scalars(
        select(models.KnowledgeOutlineReviewItem)
        .where(models.KnowledgeOutlineReviewItem.heading_block_id == "b1")
    ).one()
    assert row.ai_run_id == "run-b"
    assert row.llm_label == "chapter"
    assert row.llm_confidence == Decimal("0.550")


def test_upsert_does_not_clobber_sme_decision(session):
    ref = _seed_ref(session, "ref-upsert-3")
    run1 = _seed_ai_run(session, ref, "run-1")
    upsert_review_items(
        session, ref=ref, ai_run=run1,
        headings=[_mk_heading("b1", label="task", conf=0.5)],
    )
    session.commit()
    item = session.scalars(
        select(models.KnowledgeOutlineReviewItem)
    ).one()
    override_review_item(
        session, item_id=item.id,
        label="knowledge_point", reason="真实为知识点",
        sme_id="sme-alice",
    )
    session.commit()

    # Second rebuild refreshes LLM data but keeps SME status
    run2 = _seed_ai_run(session, ref, "run-2")
    upsert_review_items(
        session, ref=ref, ai_run=run2,
        headings=[_mk_heading("b1", label="task_step", conf=0.4)],
    )
    session.commit()

    refreshed = session.scalars(select(models.KnowledgeOutlineReviewItem)).one()
    assert refreshed.status == STATUS_OVERRIDDEN
    assert refreshed.sme_override_label == "knowledge_point"
    assert refreshed.llm_label == "task_step"
    assert refreshed.ai_run_id == "run-2"


# ---------------------------------------------------------------------------
# SME actions
# ---------------------------------------------------------------------------


def test_approve_sets_status_approved_and_audits(session):
    ref = _seed_ref(session, "ref-approve")
    run = _seed_ai_run(session, ref)
    upsert_review_items(session, ref=ref, ai_run=run,
                         headings=[_mk_heading("b1", conf=0.6)])
    session.commit()
    item = session.scalars(select(models.KnowledgeOutlineReviewItem)).one()

    approve_review_item(session, item_id=item.id, sme_id="sme-bob")
    session.commit()
    assert item.status == STATUS_APPROVED
    assert item.sme_override_by == "sme-bob"

    events = list(session.scalars(
        select(models.AuditLog).where(models.AuditLog.target_id == item.id)
    ))
    assert any(e.event_type ==
               AuditEventType.KNOWLEDGE_OUTLINE_REVIEW_ITEM_APPROVED for e in events)


def test_override_sets_status_overridden_and_records_label(session):
    ref = _seed_ref(session, "ref-override")
    run = _seed_ai_run(session, ref)
    upsert_review_items(session, ref=ref, ai_run=run,
                         headings=[_mk_heading("b1", conf=0.5)])
    session.commit()
    item = session.scalars(select(models.KnowledgeOutlineReviewItem)).one()

    override_review_item(session, item_id=item.id, label="chapter",
                         reason="LLM 判定错了", sme_id="sme-carol")
    session.commit()
    assert item.status == STATUS_OVERRIDDEN
    assert item.sme_override_label == "chapter"
    assert item.sme_override_reason == "LLM 判定错了"


def test_dismiss_sets_status_dismissed(session):
    ref = _seed_ref(session, "ref-dismiss")
    run = _seed_ai_run(session, ref)
    upsert_review_items(session, ref=ref, ai_run=run,
                         headings=[_mk_heading("b1", conf=0.4)])
    session.commit()
    item = session.scalars(select(models.KnowledgeOutlineReviewItem)).one()

    dismiss_review_item(session, item_id=item.id, sme_id="sme-dave")
    session.commit()
    assert item.status == STATUS_DISMISSED


def test_missing_item_raises_key_error(session):
    with pytest.raises(KeyError):
        override_review_item(
            session, item_id="does-not-exist",
            label="chapter", reason="", sme_id="sme-x",
        )


# ---------------------------------------------------------------------------
# get_sme_decisions — what the rebuild path consumes
# ---------------------------------------------------------------------------


def test_get_sme_decisions_includes_approved_and_overridden_only(session):
    ref = _seed_ref(session, "ref-decisions")
    run = _seed_ai_run(session, ref)
    upsert_review_items(session, ref=ref, ai_run=run, headings=[
        _mk_heading("b-app", label="task", conf=0.6),
        _mk_heading("b-ovr", label="task", conf=0.6),
        _mk_heading("b-pend", label="task_step", conf=0.6),
        _mk_heading("b-dis", label="task_step", conf=0.4, bucket="low"),
    ])
    session.commit()
    items = {r.heading_block_id: r for r in session.scalars(
        select(models.KnowledgeOutlineReviewItem)
    )}
    approve_review_item(session, item_id=items["b-app"].id, sme_id="sme-a")
    override_review_item(session, item_id=items["b-ovr"].id,
                         label="knowledge_point", reason=None, sme_id="sme-a")
    dismiss_review_item(session, item_id=items["b-dis"].id, sme_id="sme-a")
    session.commit()

    decisions = get_sme_decisions(session, ref.id)
    assert set(decisions.keys()) == {"b-app", "b-ovr"}
    # Approved keeps LLM label; overridden uses SME's label.
    assert decisions["b-app"][0] == "task"
    assert decisions["b-ovr"][0] == "knowledge_point"


def test_list_review_items_filters_and_paginates(session):
    ref = _seed_ref(session, "ref-list")
    run = _seed_ai_run(session, ref)
    upsert_review_items(session, ref=ref, ai_run=run, headings=[
        _mk_heading(f"b{i}", conf=0.6) for i in range(5)
    ])
    session.commit()

    page1, cursor1 = list_review_items(session, ref.id, limit=2)
    assert len(page1) == 2
    assert cursor1 is not None
    page2, cursor2 = list_review_items(session, ref.id, limit=2, cursor=cursor1)
    assert len(page2) == 2
    # 4 pending remain visible; last page smaller than limit → no more cursor
    page3, cursor3 = list_review_items(session, ref.id, limit=10, cursor=cursor2)
    assert cursor3 is None
    assert len(page3) == 1


# ---------------------------------------------------------------------------
# Integration: SME override wins on next rebuild
# ---------------------------------------------------------------------------


class _FakeLiteLLM:
    """Returns a per-block label so tests can drive the classifier state."""

    def __init__(self, labels_by_block: dict[str, tuple[str, float]]):
        self.labels_by_block = labels_by_block

    def call(self, model_alias, messages, *, temperature, max_tokens, response_format):
        import json as _json
        user_content = messages[-1]["content"]
        m_start = user_content.find("[")
        parsed = _json.loads(user_content[m_start:])
        items = []
        for p in parsed:
            block_id = p.get("text", "")
            # match the payload block_id via heading_text; we key by text for simplicity
            label, conf = self.labels_by_block.get(block_id, ("knowledge_point", 0.6))
            items.append({"idx": p["idx"], "label": label, "confidence": conf, "reason": "fake"})
        content = _json.dumps({"items": items}, ensure_ascii=False)
        from nexus_app.ai_governance.litellm_client import LiteLLMCallSummary
        summary = LiteLLMCallSummary(
            model_alias=model_alias, request_id="req", latency_ms=1.0,
            status="success", input_hash="hash",
        )
        return content, summary


def test_sme_override_persists_across_rebuild(session):
    """SME overrides a heading's label; next rebuild uses the SME label
    even when the LLM re-classifies with mid confidence."""
    from nexus_app.knowledge_outline.llm_classifier import (
        build_and_persist_outline_llm,
    )

    ref = _seed_ref(session, "ref-integration")
    payload = {
        "title": "教材",
        "blocks": [
            {"block_id": "b1", "block_type": "heading", "heading_level": 1,
             "text": "第一章 引论", "page": 1},
            {"block_id": "b2", "block_type": "heading", "heading_level": 2,
             "text": "任务一 采集", "page": 1},   # LLM will say `task` at 0.6
            {"block_id": "b3", "block_type": "text", "text": "…", "page": 1},
        ],
    }
    # First rebuild — LLM says `task` at mid confidence (goes into tree via
    # gate, review item created).
    build_and_persist_outline_llm(
        session, ref=ref, payload=payload,
        client=_FakeLiteLLM({"第一章 引论": ("chapter", 0.95),
                             "任务一 采集": ("task", 0.6)}),
        model_alias="fake", rules_etag=None,
    )
    session.commit()
    item = session.scalars(select(models.KnowledgeOutlineReviewItem)
        .where(models.KnowledgeOutlineReviewItem.heading_block_id == "b2")
    ).one()
    assert item.llm_label == "task"

    # SME says: nope, that's actually a knowledge_point.
    override_review_item(
        session, item_id=item.id,
        label="knowledge_point", reason="实为知识点", sme_id="sme-e",
    )
    session.commit()

    # Second rebuild — LLM might say `task_step` at 0.4 (would be gated out)
    outcome2 = build_and_persist_outline_llm(
        session, ref=ref, payload=payload,
        client=_FakeLiteLLM({"第一章 引论": ("chapter", 0.95),
                             "任务一 采集": ("task_step", 0.4)}),
        model_alias="fake", rules_etag=None,
    )
    session.commit()
    # The SME override wins → the heading survives with knowledge_point label.
    kp_labels = [c.label for c in outcome2.classifications if c.label == "knowledge_point"]
    assert len(kp_labels) >= 1
    # And the tree should have at least 1 kp under chapter.
    kps_in_tree = [n for n in outcome2.tree.nodes if n.level == 2]
    assert kps_in_tree, "SME-overridden heading did not land in the tree"
