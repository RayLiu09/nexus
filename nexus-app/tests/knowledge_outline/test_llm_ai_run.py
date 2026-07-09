"""Confidence gating + AIGovernanceRun bookkeeping tests."""

from __future__ import annotations

from sqlalchemy import select

from nexus_app import models
from nexus_app.enums import (
    AIGovernanceRunAdoptionStatus,
    AIGovernanceRunValidationStatus,
)
from nexus_app.knowledge_outline.llm_classifier import (
    AUTO_ADOPT_HIGH_RATIO,
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    HeadingClassification,
    apply_confidence_gate,
    compute_adoption_status,
)

VALID = AIGovernanceRunValidationStatus.SCHEMA_VALID
INVALID = AIGovernanceRunValidationStatus.SCHEMA_INVALID
AUTO = AIGovernanceRunAdoptionStatus.AUTO_ADOPTED
REVIEW = AIGovernanceRunAdoptionStatus.REVIEW_REQUIRED
REJECTED = AIGovernanceRunAdoptionStatus.REJECTED


# ---------------------------------------------------------------------------
# apply_confidence_gate
# ---------------------------------------------------------------------------


def _cls(label: str, conf: float, idx: int = 0) -> HeadingClassification:
    return HeadingClassification(idx=idx, label=label, confidence=conf)


def test_gate_downgrades_low_confidence_non_noise_to_noise():
    adjusted, buckets = apply_confidence_gate(
        [
            _cls("chapter", CONFIDENCE_HIGH + 0.05, idx=0),
            _cls("knowledge_point", CONFIDENCE_LOW + 0.05, idx=1),
            _cls("knowledge_point", CONFIDENCE_LOW - 0.05, idx=2),
        ]
    )
    assert buckets == {"high": 1, "mid": 1, "low": 1}
    assert adjusted[0].label == "chapter"
    assert adjusted[1].label == "knowledge_point"
    assert adjusted[2].label == "noise"
    assert adjusted[2].reason.startswith("[gated<")


def test_gate_preserves_low_confidence_noise():
    adjusted, buckets = apply_confidence_gate(
        [_cls("noise", 0.1, idx=0)]
    )
    assert buckets == {"high": 0, "mid": 0, "low": 1}
    assert adjusted[0].label == "noise"
    assert not adjusted[0].reason.startswith("[gated<")


def test_gate_confidence_boundary_inclusive_on_high():
    # exactly at HIGH → still 'high' bucket
    adjusted, buckets = apply_confidence_gate(
        [_cls("chapter", CONFIDENCE_HIGH, idx=0)]
    )
    assert buckets["high"] == 1
    assert adjusted[0].label == "chapter"


# ---------------------------------------------------------------------------
# compute_adoption_status
# ---------------------------------------------------------------------------


def test_auto_adopted_when_all_high():
    assert compute_adoption_status(VALID, {"high": 10, "mid": 0, "low": 0}) == AUTO


def test_review_required_when_ratio_below_threshold():
    # 89% high, no low → still review because we require ≥ 90% + zero low
    buckets = {"high": 89, "mid": 11, "low": 0}
    assert compute_adoption_status(VALID, buckets) == REVIEW


def test_review_required_when_any_low_present():
    buckets = {"high": 100, "mid": 0, "low": 1}
    assert compute_adoption_status(VALID, buckets) == REVIEW


def test_auto_adopted_boundary_at_ratio():
    # exactly at threshold → auto_adopted
    total = 10
    high = int(AUTO_ADOPT_HIGH_RATIO * total)
    assert compute_adoption_status(
        VALID, {"high": high, "mid": total - high, "low": 0}
    ) == AUTO


def test_rejected_when_validation_invalid():
    assert compute_adoption_status(
        INVALID, {"high": 100, "mid": 0, "low": 0}
    ) == REJECTED


def test_rejected_when_all_buckets_empty():
    assert compute_adoption_status(VALID, {"high": 0, "mid": 0, "low": 0}) == REJECTED


# ---------------------------------------------------------------------------
# AIGovernanceRun persistence — end-to-end through the classifier
# ---------------------------------------------------------------------------


class _FakeLiteLLM:
    """Deterministic fake so we can assert on run bookkeeping without live LLM."""

    def __init__(self, per_heading_label: str = "knowledge_point", conf: float = 0.95):
        self.per_heading_label = per_heading_label
        self.conf = conf

    def call(self, model_alias, messages, *, temperature, max_tokens, response_format):
        import json as _json
        import time
        # Extract idxs from the user message payload.
        user_content = messages[-1]["content"]
        m_start = user_content.find("[")
        parsed = _json.loads(user_content[m_start:])
        items = [
            {
                "idx": p["idx"],
                "label": self.per_heading_label,
                "confidence": self.conf,
                "reason": "fake",
            }
            for p in parsed
        ]
        content = _json.dumps({"items": items}, ensure_ascii=False)

        from nexus_app.ai_governance.litellm_client import LiteLLMCallSummary
        summary = LiteLLMCallSummary(
            model_alias=model_alias, request_id="fake-req", latency_ms=1.0,
            status="success", input_hash="hash",
        )
        return content, summary


def _seed_ref_for_llm(session, ref_id: str = "ref-ai-run"):
    from nexus_app.enums import (
        AssetKind, AssetVersionStatus, DataSourceType, IngestBatchStatus,
        NormalizedAssetRefStatus, NormalizedType, RawObjectStatus,
    )
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


def _payload():
    return {
        "title": "教材T",
        "blocks": [
            {"block_id": "b1", "block_type": "heading", "heading_level": 1,
             "text": "第一章 引论", "page": 1},
            {"block_id": "b2", "block_type": "heading", "heading_level": 2,
             "text": "一、概念", "page": 1},
            {"block_id": "b3", "block_type": "text", "text": "…", "page": 1},
        ],
    }


def test_build_creates_one_ai_run_with_bookkeeping(session):
    from nexus_app.knowledge_outline.llm_classifier import (
        build_and_persist_outline_llm,
    )
    ref = _seed_ref_for_llm(session)
    outcome = build_and_persist_outline_llm(
        session, ref=ref, payload=_payload(),
        client=_FakeLiteLLM("knowledge_point", 0.95),
        model_alias="fake-alias", rules_etag=None,
    )
    session.commit()

    runs = list(session.scalars(
        select(models.AIGovernanceRun)
        .where(models.AIGovernanceRun.normalized_ref_id == ref.id)
    ))
    assert len(runs) == 1
    run = runs[0]
    assert run.id == outcome.ai_run_id
    assert run.adoption_status == AUTO
    assert run.validation_status == VALID
    assert run.input_hash and len(run.input_hash) == 64
    assert run.ai_output and "classifications" in run.ai_output
    assert len(run.ai_output["classifications"]) == 2
    assert run.input_summary["confidence_buckets"]["high"] == 2
    assert run.model_alias == "fake-alias"


def test_low_confidence_downgraded_and_flags_review(session):
    from nexus_app.knowledge_outline.llm_classifier import (
        build_and_persist_outline_llm,
    )
    ref = _seed_ref_for_llm(session, "ref-lowconf")
    outcome = build_and_persist_outline_llm(
        session, ref=ref, payload=_payload(),
        client=_FakeLiteLLM("knowledge_point", 0.30),
        model_alias="fake", rules_etag=None,
    )
    session.commit()
    assert outcome.adoption_status == REJECTED.value or outcome.adoption_status == REVIEW.value
    # low-confidence knowledge_point should have been downgraded to noise.
    labels = [c.label for c in outcome.classifications]
    assert "knowledge_point" not in labels
    assert outcome.confidence_buckets["low"] == 2
