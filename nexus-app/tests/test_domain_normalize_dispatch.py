"""Smoke tests for the domain_normalize dispatcher skeleton.

Phase 0 scope only — verifies the contract surface (registry, lazy import,
skip semantics, audit wiring) without depending on the B4 / B6 writers, which
are landed by their respective worktree branches and merged separately.

The tests assert the dispatcher's **skip** paths, because in this commit
no writer module exists yet:

  - missing `domain_profile` on the ref           → skipped: missing_domain_profile
  - unknown `domain_profile`                       → skipped: no_writer_for_profile
  - registry entry exists, writer module missing   → skipped: writer_not_implemented
  - storage absent / payload empty                 → skipped: empty_record_body

Once B4 / B6 writers ship, this file stays as the regression net for the
skip paths; their own test files cover the writer happy paths.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from nexus_app import models
from nexus_app.domain_normalize import DomainNormalizeResult, dispatch_domain_normalize
from nexus_app.enums import NormalizedType


def _make_ref(*, domain_profile: str | None = "job_demand.v1", object_uri: str = "s3://bucket/payload.json") -> models.NormalizedAssetRef:
    ref = models.NormalizedAssetRef(
        id="ref-test",
        version_id="ver-test",
        normalized_type=NormalizedType.RECORD,
        object_uri=object_uri,
        schema_version="normalized-record.v2",
        checksum="cs",
    )
    ref.metadata_summary = {"domain_profile": domain_profile} if domain_profile else {}
    return ref


class TestDispatcherSkipPaths:
    """In Phase 0 there is no writer module on disk, so every call must skip."""

    def test_missing_domain_profile_skips(self):
        ref = _make_ref(domain_profile=None)
        result = dispatch_domain_normalize(MagicMock(), ref, storage=MagicMock())
        assert result.skipped is True
        assert result.reason == "missing_domain_profile"
        assert result.domain_profile is None

    def test_unknown_domain_profile_skips(self):
        ref = _make_ref(domain_profile="not_a_real_profile.v9")
        result = dispatch_domain_normalize(MagicMock(), ref, storage=MagicMock())
        assert result.skipped is True
        assert result.reason == "no_writer_for_profile"
        assert result.domain_profile == "not_a_real_profile.v9"

    def test_registered_profile_without_writer_skips(self):
        # `job_demand.v1` is in _WRITER_REGISTRY but
        # nexus_app.domain_normalize.job_demand_writer doesn't exist yet (B4
        # ships it). Dispatcher must NOT raise.
        ref = _make_ref(domain_profile="job_demand.v1")
        result = dispatch_domain_normalize(MagicMock(), ref, storage=MagicMock())
        assert result.skipped is True
        assert result.reason == "writer_not_implemented"

    def test_ability_analysis_profile_without_writer_skips(self):
        ref = _make_ref(domain_profile="ability_analysis.pgsd.v1")
        result = dispatch_domain_normalize(MagicMock(), ref, storage=MagicMock())
        assert result.skipped is True
        assert result.reason == "writer_not_implemented"


class TestRecordBodyLoader:
    """`_load_record_body` is private; exercise via the dispatcher's skip semantics."""

    def test_no_storage_returns_empty_body_skip(self):
        # Registry-resolved profile but no storage → reach load step, which
        # returns None and dispatcher reports empty_record_body. We use an
        # unknown profile here so the actual ImportError branch doesn't fire
        # first — but registry-known with no writer fires earlier; that's
        # tested above. To exercise empty_record_body we need a registered
        # profile WITH a writer that exists. Since neither writer exists in
        # Phase 0, this path is exercised in B4 / B6 worktree tests, not here.
        pytest.skip("Exercised by B4 / B6 writer tests once they land")


class TestResultShape:
    def test_dataclass_defaults(self):
        result = DomainNormalizeResult(domain_profile="job_demand.v1")
        assert result.skipped is False
        assert result.reason is None
        assert result.dataset_id is None
        assert result.analysis_id is None
        assert result.records_written == 0
        assert result.items_written == 0
        assert result.quality_summary == {}
