"""Tests for `profile_detect.schemas` Pydantic models.

These pin the contract-freeze §二 field set so downstream consumers
(normalized_record.payload.profile, normalized_asset_ref.metadata_summary.profile,
governance review queue, console UI) can rely on the shape.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from nexus_app.profile_detect import DETECTOR_VERSION
from nexus_app.profile_detect.schemas import ProfileDetectResult, ProfileEvidence


# ---------------------------------------------------------------------------
# ProfileEvidence defaults & shape
# ---------------------------------------------------------------------------


class TestProfileEvidenceDefaults:
    def test_default_construction(self):
        ev = ProfileEvidence()
        assert ev.matched_headers == []
        assert ev.sheet_names == []
        assert ev.sample_row_count == 0
        assert ev.matched_categories == []
        assert ev.matched_code_prefixes == []

    def test_populated_evidence_roundtrips_through_json(self):
        ev = ProfileEvidence(
            matched_headers=["岗位名称", "城市"],
            sheet_names=["Sheet1"],
            sample_row_count=3,
            matched_categories=["职业能力"],
            matched_code_prefixes=["P", "G"],
        )
        # contract-freeze §二 requires the result to be JSON-serializable
        # (it lives inside normalized_record.payload which gets uploaded
        # to MinIO as JSON bytes).
        as_dict = ev.model_dump()
        rebuilt = ProfileEvidence.model_validate(as_dict)
        assert rebuilt == ev


# ---------------------------------------------------------------------------
# ProfileDetectResult — full payload
# ---------------------------------------------------------------------------


class TestProfileDetectResultHappyPath:
    def test_job_demand_full_payload(self):
        result = ProfileDetectResult(
            record_type="job_demand_dataset",
            domain="occupation",
            domain_profile="job_demand.v1",
            detector_version=DETECTOR_VERSION,
            confidence=0.96,
            evidence=ProfileEvidence(
                matched_headers=["岗位名称", "城市", "公司名称"],
                sheet_names=["Sheet1"],
                sample_row_count=3,
            ),
        )
        assert result.record_type == "job_demand_dataset"
        assert result.analysis_model is None  # not an ability_analysis
        assert result.confidence == 0.96

    def test_ability_analysis_pgsd_payload(self):
        result = ProfileDetectResult(
            record_type="occupational_ability_analysis",
            domain="occupation",
            domain_profile="ability_analysis.pgsd.v1",
            analysis_model="PGSD",
            detector_version=DETECTOR_VERSION,
            confidence=0.98,
            evidence=ProfileEvidence(
                matched_categories=["职业能力", "通用能力", "社会能力", "发展能力"],
                matched_code_prefixes=["P", "G", "S", "D"],
                sheet_names=["典型工作任务和工作内容分析表", "1.数据采集"],
            ),
        )
        assert result.record_type == "occupational_ability_analysis"
        assert result.analysis_model == "PGSD"


# ---------------------------------------------------------------------------
# Validation rules
# ---------------------------------------------------------------------------


class TestValidation:
    def test_confidence_below_zero_rejected(self):
        with pytest.raises(ValidationError):
            ProfileDetectResult(
                record_type="job_demand_dataset",
                domain="occupation",
                domain_profile="job_demand.v1",
                detector_version=DETECTOR_VERSION,
                confidence=-0.01,
            )

    def test_confidence_above_one_rejected(self):
        with pytest.raises(ValidationError):
            ProfileDetectResult(
                record_type="job_demand_dataset",
                domain="occupation",
                domain_profile="job_demand.v1",
                detector_version=DETECTOR_VERSION,
                confidence=1.01,
            )

    def test_unknown_record_type_rejected(self):
        # Literal constraint catches typos at the boundary so downstream
        # code doesn't have to defensively whitelist.
        with pytest.raises(ValidationError):
            ProfileDetectResult(
                record_type="unknown_thing",  # type: ignore[arg-type]
                domain="occupation",
                domain_profile="job_demand.v1",
                detector_version=DETECTOR_VERSION,
                confidence=0.5,
            )


# ---------------------------------------------------------------------------
# Serialization — pinned because normalized_record.payload is JSON-uploaded
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_full_result_roundtrips_through_json(self):
        original = ProfileDetectResult(
            record_type="occupational_ability_analysis",
            domain="occupation",
            domain_profile="ability_analysis.pgsd.v1",
            analysis_model="PGSD",
            detector_version=DETECTOR_VERSION,
            confidence=0.91,
            evidence=ProfileEvidence(
                matched_categories=["职业能力", "通用能力"],
                matched_code_prefixes=["P", "G"],
                sheet_names=["1.数据采集"],
                sample_row_count=27,
            ),
        )
        # mode="json" mirrors how the worker persists this to MinIO
        as_dict = original.model_dump(mode="json")
        rebuilt = ProfileDetectResult.model_validate(as_dict)
        assert rebuilt == original

    def test_candidate_record_type_serializable(self):
        # Low-confidence path must also serialize cleanly so review_required
        # queues can store and re-read it.
        result = ProfileDetectResult(
            record_type="occupational_ability_analysis_candidate",
            domain="occupation",
            domain_profile="ability_analysis.pgsd.v1",
            analysis_model="PGSD",
            detector_version=DETECTOR_VERSION,
            confidence=0.62,
        )
        rebuilt = ProfileDetectResult.model_validate(result.model_dump(mode="json"))
        assert rebuilt.record_type == "occupational_ability_analysis_candidate"
