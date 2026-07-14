"""Integration tests for the AI governance → index_submit pipeline (Review §6).

Covers:
- 6.1: run_governance_decision with mocked LLM + real DB session
- 6.2: run_index_submit with FakeRAGFlowAdapter + real session
- 6.3: governance_decision idempotency under job retry
- 6.4: VersionStateManager.transition_to_available concurrent race
- 6.5: RAGFlow adapter network errors handled as FAILED manifest
- 6.6: knowledge_emissions empty/missing/malformed edge cases
"""
from __future__ import annotations

import base64
import json
import threading
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from sqlalchemy import select


@pytest.fixture(autouse=True)
def _no_real_sleep():
    """Globally short-circuit time.sleep so retry-driven tests stay fast."""
    with patch("nexus_app.index.ragflow_adapter.time.sleep"):
        yield

from nexus_app import models, services
from nexus_app.ai_governance.litellm_client import LiteLLMClientProtocol
from nexus_app.ai_governance.rules_registry import GovernanceRulesRegistry
from nexus_app.config import get_settings
from nexus_app.enums import (
    AssetVersionStatus,
    AuditEventType,
    ChunkType,
    GovernanceResultStatus,
    IndexManifestStatus,
    JobStatus,
    PromptProfileStatus,
    StageStatus,
)
from nexus_app.governance.decision_service import GovernanceDecisionService
from nexus_app.index.kb_registry import KbRegistry, reset_kb_registry
from nexus_app.index.embedding_client import FakeEmbeddingClient
from nexus_app.index.ragflow_adapter import FakeRAGFlowAdapter
from nexus_app.ingest import gateway as ingest_gateway
from nexus_app.metadata.version_state import (
    StateTransitionError,
    VersionStateManager,
)
from nexus_app.mineru import FakeMinerUAdapter
from nexus_app.schemas import DataSourceCreate, IngestFileSubmit
from nexus_app.storage import InMemoryObjectStorage
from nexus_app.worker.claimer import claim_jobs
from nexus_app.worker.runner import execute_job


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _existing_job_for_ref(session, ref_id: str) -> models.Job:
    """Locate the Job row that was created when the ingest pipeline ran for this ref."""
    version = session.scalars(
        select(models.AssetVersion)
        .join(models.NormalizedAssetRef,
              models.NormalizedAssetRef.version_id == models.AssetVersion.id)
        .where(models.NormalizedAssetRef.id == ref_id)
    ).first()
    job = session.scalars(
        select(models.Job).where(models.Job.raw_object_id == version.raw_object_id)
    ).first()
    assert job is not None, "expected Job row from ingest gateway run"
    return job


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def rules_registry() -> GovernanceRulesRegistry:
    """A registry loaded from a minimal in-memory rules dict."""
    rules = {
        "schema_version": "1.0",
        "classifications": [
            {"code": "D1", "name": "Basic", "description": "d", "criteria": ["c"]},
            {"code": "D4", "name": "Teaching", "description": "d", "criteria": ["c"]},
        ],
        "levels": [
            {"code": "L1", "name": "Public", "description": "d", "criteria": ["c"]},
            {"code": "L2", "name": "Internal", "description": "d", "criteria": ["c"]},
            {"code": "L3", "name": "Confidential", "description": "d",
             "criteria": ["c"], "requires_approval": True},
            {"code": "L4", "name": "Secret", "description": "d",
             "criteria": ["c"], "requires_approval": True},
        ],
        "tags": [
            {"code": "pii", "name": "PII", "description": "d", "criteria": ["c"]},
        ],
        "quality_scoring": {
            "dimensions": [
                {"name": "completeness", "weight": 1.0, "description": "d",
                 "check_items": [{"name": "has_title", "description": "d",
                                  "severity": "blocking"}]},
            ],
            "thresholds": {"pass": 70, "warning": 50, "review_required_below": 50},
            "confidence_threshold_auto_adopt": 0.8,
        },
    }
    registry = GovernanceRulesRegistry()
    registry.load_dict(rules)
    return registry


@pytest.fixture
def make_ai_run(session):
    """Factory for persisted AIGovernanceRun rows tied to a real pipeline artifact.

    Builds the asset/version/ref via the ingest gateway (so all FK constraints and
    required fields are satisfied) and then adds an AIPromptProfile + AIGovernanceRun.
    """
    counter = {"n": 0}

    def _factory(*, ai_output: dict[str, Any], quality_summary: dict[str, Any] | None = None):
        counter["n"] += 1
        idx = counter["n"]
        source = services.create_data_source(
            session,
            DataSourceCreate(
                code=f"test-src-{idx}", name=f"t{idx}", source_type="file_upload",
            ),
        )
        storage = InMemoryObjectStorage()
        payload = IngestFileSubmit(
            data_source_id=source.id,
            idempotency_key=f"file-{idx}",
            filename=f"sample-{idx}.pdf",
            content_type="application/pdf",
            content_base64=base64.b64encode(f"hello {idx}".encode()).decode("ascii"),
        )
        accepted = ingest_gateway.submit_file_ingest(
            session, payload, storage=storage, trace_id=f"trace-{idx}",
        )
        # Drive the pipeline up to (but not including) governance, then capture state.
        mineru = FakeMinerUAdapter()
        settings = get_settings()
        jobs = claim_jobs(session, f"worker-{idx}", batch_size=1, lease_seconds=30)
        for job in jobs:
            try:
                execute_job(job, session, storage, mineru, settings)
            except Exception:
                pass

        asset_id = session.scalars(
            select(models.Asset.id).where(
                models.Asset.data_source_id == source.id
            )
        ).first()
        version = session.scalars(
            select(models.AssetVersion).where(
                models.AssetVersion.asset_id == asset_id
            )
        ).first()
        ref = session.scalars(
            select(models.NormalizedAssetRef).where(
                models.NormalizedAssetRef.version_id == version.id
            )
        ).first()

        # Reset state so individual tests can drive governance from a known point.
        version.version_status = AssetVersionStatus.PROCESSING
        session.flush()

        # Active prompt profile + AI run snapshot
        profile = session.scalars(
            select(models.AIPromptProfile).where(
                models.AIPromptProfile.profile_name == "governance",
                models.AIPromptProfile.status == PromptProfileStatus.ACTIVE,
            )
        ).first()
        if profile is None:
            profile = models.AIPromptProfile(
                profile_name="governance",
                profile_version=1,
                task_type="governance",
                status=PromptProfileStatus.ACTIVE,
                litellm_model_alias="fake",
                prompt_version="v1",
                prompt_template="t",
                output_schema_version="1.0",
                scoring_weight_version="1.0",
                temperature=0.2,
                max_input_tokens=1024,
                redaction_policy="masked_content",
            )
            session.add(profile)
            session.flush()

        run = models.AIGovernanceRun(
            normalized_ref_id=ref.id,
            profile_id=profile.id,
            model_alias="fake",
            prompt_version="v1",
            input_hash=f"h-{idx}",
            input_summary={},
            ai_output=ai_output,
            quality_summary=quality_summary,
            validation_status="schema_valid",
            adoption_status="pending_rule_guardrail",
        )
        session.add(run)
        session.flush()
        return run, version, ref

    return _factory


# ---------------------------------------------------------------------------
# 6.1 — GovernanceDecisionService integration (mocked LLM, real DB)
# ---------------------------------------------------------------------------

class TestGovernanceDecisionIntegration:
    """6.1: real DB session, real AIGovernanceRun row, GovernanceDecisionService."""

    def test_persists_result_and_decision_trail(self, session, rules_registry, make_ai_run):
        run, _, _ = make_ai_run(
            ai_output={"classification": "D1", "level": "L1", "tags": ["pii"],
                       "org_scope": "all", "confidence": 0.95},
            quality_summary={"quality_score": 85.0, "quality_level": "pass", "confidence": 0.95},
        )
        svc = GovernanceDecisionService(rules_registry)
        result = svc.execute_governance(session, run)

        assert result.status == GovernanceResultStatus.AVAILABLE
        assert result.index_admission is True
        assert len(result.decision_trail) == 4
        assert all(e["adoption_status"] == "auto_adopted" for e in result.decision_trail)
        assert result.rules_schema_version == "1.0"
        assert result.rules_content_hash and len(result.rules_content_hash) == 64

    def test_writes_audit_log(self, session, rules_registry, make_ai_run):
        run, _, _ = make_ai_run(
            ai_output={"classification": "D1", "level": "L1", "tags": [],
                       "org_scope": "all", "confidence": 0.95},
            quality_summary={"quality_score": 85.0, "quality_level": "pass", "confidence": 0.95},
        )
        svc = GovernanceDecisionService(rules_registry)
        result = svc.execute_governance(session, run)

        audits = session.scalars(
            select(models.AuditLog).where(
                models.AuditLog.target_type == "governance_result",
                models.AuditLog.target_id == result.id,
            )
        ).all()
        assert len(audits) == 1
        assert audits[0].event_type == AuditEventType.GOVERNANCE_RESULT_CREATED


# ---------------------------------------------------------------------------
# 6.2 — run_index_submit with FakeRAGFlowAdapter
# ---------------------------------------------------------------------------

class TestIndexSubmitIntegration:
    """6.2: end-to-end index_submit using FakeRAGFlowAdapter + real session."""

    def _make_chunks(self, session, normalized_ref_id: str, kt_code: str,
                     chunk_type: ChunkType, count: int) -> list[models.KnowledgeChunk]:
        chunks = []
        for i in range(count):
            chunk = models.KnowledgeChunk(
                normalized_ref_id=normalized_ref_id,
                knowledge_type_code=kt_code,
                chunk_type=chunk_type,
                chunking_strategy="passthrough_to_ragflow"
                if chunk_type == ChunkType.PASSTHROUGH_DESCRIPTOR else "qa_extract",
                chunk_index=i,
                content=f"chunk {i} content",
                chunk_metadata={},
            )
            session.add(chunk)
            chunks.append(chunk)
        session.flush()
        return chunks

    def test_passthrough_chunks_get_doc_id(self, session, make_ai_run, monkeypatch):
        from nexus_app.pipeline import stages

        _, version, ref = make_ai_run(ai_output={"classification": "D4",
                                                 "level": "L1", "tags": [],
                                                 "org_scope": "all",
                                                 "confidence": 0.9})
        version.version_status = AssetVersionStatus.AVAILABLE
        session.flush()

        fake_adapter = FakeRAGFlowAdapter()
        monkeypatch.setattr(stages, "_load_normalized_content",
                            lambda ctx, ref: "synthetic content")

        from nexus_app.index import ragflow_adapter as ra_mod
        from nexus_app.index import kb_registry as kb_mod
        monkeypatch.setattr(ra_mod, "get_ragflow_adapter", lambda settings=None: fake_adapter)
        kb_mod._default_registry = KbRegistry(adapter=fake_adapter, settings=get_settings())

        try:
            chunks = self._make_chunks(session, ref.id, "course_textbook",
                                        ChunkType.PASSTHROUGH_DESCRIPTOR, 1)

            class _Ctx:
                pass
            ctx = _Ctx()
            ctx.session = session
            ctx.settings = get_settings()
            ctx.storage = InMemoryObjectStorage()
            ctx.trace_id = "trace-x"
            ctx.job = _existing_job_for_ref(session, ref.id)

            manifests = stages.run_index_submit(ctx, version, ref, chunks)
            assert len(manifests) == 1
            assert manifests[0].index_status == IndexManifestStatus.INDEXED
            assert manifests[0].ragflow_doc_id is not None
        finally:
            reset_kb_registry()

    def test_nexus_owned_chunks_index_to_pgvector(self, session, make_ai_run, monkeypatch):
        from nexus_app.pipeline import stages

        _, version, ref = make_ai_run(ai_output={"classification": "D4",
                                                 "level": "L1", "tags": [],
                                                 "org_scope": "all",
                                                 "confidence": 0.9})
        version.version_status = AssetVersionStatus.AVAILABLE
        session.flush()

        fake_adapter = FakeRAGFlowAdapter()
        from nexus_app.index import ragflow_adapter as ra_mod
        from nexus_app.index import kb_registry as kb_mod
        monkeypatch.setattr(ra_mod, "get_ragflow_adapter", lambda settings=None: fake_adapter)
        monkeypatch.setattr(
            stages,
            "get_pgvector_embedding_client",
            lambda settings=None: FakeEmbeddingClient(dimension=settings.default_embedding_dimension),
        )
        kb_mod._default_registry = KbRegistry(adapter=fake_adapter, settings=get_settings())

        try:
            chunks = self._make_chunks(session, ref.id, "course_textbook",
                                        ChunkType.SEMANTIC_BLOCK, 2)

            class _Ctx:
                pass
            ctx = _Ctx()
            ctx.session = session
            ctx.settings = get_settings()
            ctx.storage = InMemoryObjectStorage()
            ctx.trace_id = "trace-skip-nexus"
            ctx.job = _existing_job_for_ref(session, ref.id)

            manifests = stages.run_index_submit(ctx, version, ref, chunks)
            assert len(manifests) == 1
            assert manifests[0].index_status == IndexManifestStatus.INDEXED
            assert manifests[0].ragflow_doc_id is None
            assert manifests[0].chunk_count == 2
            assert all(chunk.embedding_status.value == "embedded" for chunk in chunks)
            assert len(fake_adapter._docs) == 0
            assert session.scalar(
                select(models.KnowledgeEmbeddingPgvector).where(
                    models.KnowledgeEmbeddingPgvector.normalized_ref_id == ref.id
                )
            ) is not None

            stage_row = session.scalars(
                select(models.JobStage).where(
                    models.JobStage.job_id == ctx.job.id,
                    models.JobStage.stage_name == "index_submit",
                )
            ).all()[-1]
            assert stage_row.status == StageStatus.SUCCEEDED
            assert stage_row.detail["pgvector_knowledge_types"] == ["course_textbook"]
            assert stage_row.detail["ragflow_knowledge_types"] == []
            assert stage_row.detail["pgvector_index_summaries"][0]["embedded_chunk_count"] == 2
        finally:
            reset_kb_registry()


# ---------------------------------------------------------------------------
# 6.3 — Idempotency under retry
# ---------------------------------------------------------------------------

class TestIdempotencyOnRetry:
    """6.3: re-invoking governance_decision after a transient failure reuses result."""

    def test_governance_decision_idempotent(self, session, rules_registry, make_ai_run):
        run, _, _ = make_ai_run(
            ai_output={"classification": "D1", "level": "L1", "tags": [],
                       "org_scope": "all", "confidence": 0.95},
            quality_summary={"quality_score": 85.0, "quality_level": "pass", "confidence": 0.95},
        )
        svc = GovernanceDecisionService(rules_registry)
        first = svc.execute_governance(session, run)
        second = svc.execute_governance(session, run)
        assert first.id == second.id

        all_results = session.scalars(
            select(models.GovernanceResult).where(
                models.GovernanceResult.ai_run_id == run.id
            )
        ).all()
        assert len(all_results) == 1

    def test_knowledge_chunking_idempotent_skip(self, session, make_ai_run, monkeypatch):
        from nexus_app.pipeline import stages

        _, version, ref = make_ai_run(ai_output={"classification": "D4",
                                                 "level": "L1", "tags": [],
                                                 "org_scope": "all",
                                                 "confidence": 0.9})
        version.version_status = AssetVersionStatus.AVAILABLE
        ref.metadata_summary = {"knowledge_emissions": [{"code": "course_textbook"}]}
        session.flush()

        # Seed existing chunk
        seed = models.KnowledgeChunk(
            normalized_ref_id=ref.id,
            knowledge_type_code="course_textbook",
            chunk_type=ChunkType.PASSTHROUGH_DESCRIPTOR,
            chunking_strategy="passthrough_to_ragflow",
            chunk_index=0,
            content="seed",
            chunk_metadata={},
        )
        session.add(seed)
        session.flush()

        class _Ctx:
            pass
        ctx = _Ctx()
        ctx.session = session
        ctx.settings = get_settings()
        ctx.storage = InMemoryObjectStorage()
        ctx.trace_id = "trace-x"
        ctx.job = _existing_job_for_ref(session, ref.id)

        # Spy: run_knowledge_pipeline must not be called when chunks already exist
        call_count = {"n": 0}

        def _spy(*args, **kwargs):
            call_count["n"] += 1
            return []

        monkeypatch.setattr("nexus_app.knowledge.services.run_knowledge_pipeline", _spy)

        chunks = stages.run_knowledge_chunking(ctx, version, ref)
        assert len(chunks) == 1
        assert chunks[0].id == seed.id
        assert call_count["n"] == 0


# ---------------------------------------------------------------------------
# 6.4 — VersionStateManager concurrent transition race
# ---------------------------------------------------------------------------

class TestVersionStateRace:
    """6.4: concurrent transition_to_available with two versions of same asset.

    The DB partial unique index is PostgreSQL-only; the in-process SELECT FOR UPDATE
    serializes transitions on real PG. On SQLite we verify the archive-then-promote
    sequence still ends with exactly one available version.
    """

    def test_second_transition_archives_first(self, session, rules_registry, make_ai_run):
        run1, version1, _ = make_ai_run(
            ai_output={"classification": "D1", "level": "L1", "tags": [],
                       "org_scope": "all", "confidence": 0.95},
            quality_summary={"quality_score": 85.0, "quality_level": "pass", "confidence": 0.95},
        )
        svc = GovernanceDecisionService(rules_registry)
        result1 = svc.execute_governance(session, run1)

        mgr = VersionStateManager()
        mgr.transition_to_available(session, version1, result1)
        assert version1.version_status == AssetVersionStatus.AVAILABLE

        # Promote v2 (new version on the same asset)
        version2 = models.AssetVersion(
            asset_id=version1.asset_id,
            raw_object_id=version1.raw_object_id,
            version_no=2,
            version_status=AssetVersionStatus.PROCESSING,
            source_checksum="y",
            metadata_summary={},
        )
        session.add(version2)
        session.flush()

        # Build a 2nd governance result tied to v2
        ref2 = models.NormalizedAssetRef(
            version_id=version2.id, normalized_type="document",
            object_uri="s3://x/n2", schema_version="v1", checksum="c2",
            status="generated", source_type="file_upload",
            title="t", language="zh-CN", governance={}, quality={},
            lineage={}, metadata_summary={},
        )
        session.add(ref2)
        session.flush()
        run2 = models.AIGovernanceRun(
            normalized_ref_id=ref2.id, profile_id=run1.profile_id,
            model_alias="fake", prompt_version="v1",
            input_hash="h", input_summary={},
            ai_output={"classification": "D1", "level": "L1", "tags": [],
                       "org_scope": "all", "confidence": 0.95},
            quality_summary={"quality_score": 85.0, "quality_level": "pass",
                             "confidence": 0.95},
            validation_status="schema_valid",
            adoption_status="pending_rule_guardrail",
        )
        session.add(run2)
        session.flush()
        result2 = svc.execute_governance(session, run2)

        mgr.transition_to_available(session, version2, result2)
        session.refresh(version1)
        session.refresh(version2)

        assert version1.version_status == AssetVersionStatus.ARCHIVED
        assert version2.version_status == AssetVersionStatus.AVAILABLE

        all_available = session.scalars(
            select(models.AssetVersion).where(
                models.AssetVersion.asset_id == version1.asset_id,
                models.AssetVersion.version_status == AssetVersionStatus.AVAILABLE,
            )
        ).all()
        assert len(all_available) == 1


# ---------------------------------------------------------------------------
# 6.5 — RAGFlow adapter network error handling
# ---------------------------------------------------------------------------

class TestRagflowErrorHandling:
    """6.5: when create_document raises, an INDEXED manifest must NOT be created;
    a FAILED manifest is persisted instead and the stage is marked FAILED."""

    def test_create_document_failure_yields_failed_manifest(
        self, session, make_ai_run, monkeypatch
    ):
        from nexus_app.pipeline import stages

        _, version, ref = make_ai_run(
            ai_output={"classification": "D4", "level": "L1", "tags": [],
                       "org_scope": "all", "confidence": 0.9}
        )
        version.version_status = AssetVersionStatus.AVAILABLE
        session.flush()

        class _ExplodingAdapter(FakeRAGFlowAdapter):
            def create_document(self, *args, **kwargs):  # type: ignore[override]
                raise httpx.ConnectError("connection refused")

        bad_adapter = _ExplodingAdapter()
        from nexus_app.index import ragflow_adapter as ra_mod
        from nexus_app.index import kb_registry as kb_mod
        monkeypatch.setattr(ra_mod, "get_ragflow_adapter", lambda settings=None: bad_adapter)
        kb_mod._default_registry = KbRegistry(adapter=bad_adapter, settings=get_settings())
        monkeypatch.setattr(stages, "_load_normalized_content",
                            lambda ctx, ref: "synthetic")

        try:
            chunks = [
                models.KnowledgeChunk(
                    normalized_ref_id=ref.id,
                    knowledge_type_code="course_textbook",
                    chunk_type=ChunkType.PASSTHROUGH_DESCRIPTOR,
                    chunking_strategy="passthrough_to_ragflow",
                    chunk_index=0, content="c", chunk_metadata={},
                )
            ]
            for c in chunks:
                session.add(c)
            session.flush()

            class _Ctx:
                pass
            ctx = _Ctx()
            ctx.session = session
            ctx.settings = get_settings()
            ctx.storage = InMemoryObjectStorage()
            ctx.trace_id = "trace-fail"
            ctx.job = _existing_job_for_ref(session, ref.id)

            manifests = stages.run_index_submit(ctx, version, ref, chunks)
            assert len(manifests) == 1
            assert manifests[0].index_status == IndexManifestStatus.FAILED
            assert "connection refused" in (manifests[0].error_message or "")

            stage_row = session.scalars(
                select(models.JobStage).where(models.JobStage.job_id == ctx.job.id)
            ).all()[-1]
            assert stage_row.status == StageStatus.FAILED
        finally:
            reset_kb_registry()


# ---------------------------------------------------------------------------
# 6.6 — knowledge_emissions edge cases
# ---------------------------------------------------------------------------

class TestIndexSubmitPerKtIdempotency:
    """1.5: per-kt manifest uniqueness lets a retry skip already-indexed kts
    and only re-attempt the ones that failed."""

    def test_resumes_only_failed_kts(self, session, make_ai_run, monkeypatch):
        from nexus_app.pipeline import stages

        _, version, ref = make_ai_run(ai_output={"classification": "D4",
                                                 "level": "L1", "tags": [],
                                                 "org_scope": "all",
                                                 "confidence": 0.9})
        version.version_status = AssetVersionStatus.AVAILABLE
        session.flush()

        # Seed an already-indexed manifest for course_textbook
        seeded = models.IndexManifest(
            normalized_ref_id=ref.id,
            knowledge_type_code="course_textbook",
            index_status=IndexManifestStatus.INDEXED,
            ragflow_kb_id="kb-existing",
            ragflow_doc_id="doc-existing",
            chunk_count=3,
            indexed_at=models.utcnow(),
        )
        session.add(seeded)
        session.flush()

        fake_adapter = FakeRAGFlowAdapter()
        from nexus_app.index import ragflow_adapter as ra_mod
        from nexus_app.index import kb_registry as kb_mod
        monkeypatch.setattr(ra_mod, "get_ragflow_adapter", lambda settings=None: fake_adapter)
        kb_mod._default_registry = KbRegistry(adapter=fake_adapter, settings=get_settings())
        monkeypatch.setattr(stages, "_load_normalized_content",
                            lambda ctx, ref: "content")

        try:
            chunks = [
                models.KnowledgeChunk(
                    normalized_ref_id=ref.id,
                    knowledge_type_code="course_textbook",
                    chunk_type=ChunkType.PASSTHROUGH_DESCRIPTOR,
                    chunking_strategy="passthrough_to_ragflow",
                    chunk_index=0, content="x", chunk_metadata={},
                ),
            ]
            for c in chunks:
                session.add(c)
            session.flush()

            class _Ctx:
                pass
            ctx = _Ctx()
            ctx.session = session
            ctx.settings = get_settings()
            ctx.storage = InMemoryObjectStorage()
            ctx.trace_id = "trace-resume"
            ctx.job = _existing_job_for_ref(session, ref.id)

            manifests = stages.run_index_submit(ctx, version, ref, chunks)
            assert len(manifests) == 1
            # Manifest should be the seeded one — adapter must not have been
            # called for the already-indexed kt.
            assert manifests[0].id == seeded.id
            assert len(fake_adapter._docs) == 0
        finally:
            reset_kb_registry()


class TestRagflowDocIdempotency:
    """2.1: a RAGFlow doc that already exists for (kb, doc_name) is reused
    instead of duplicated when index_submit retries after a partial failure."""

    def test_reuses_existing_doc(self, session, make_ai_run, monkeypatch):
        from nexus_app.pipeline import stages

        _, version, ref = make_ai_run(ai_output={"classification": "D4",
                                                 "level": "L1", "tags": [],
                                                 "org_scope": "all",
                                                 "confidence": 0.9})
        version.version_status = AssetVersionStatus.AVAILABLE
        session.flush()

        fake_adapter = FakeRAGFlowAdapter()
        # Pre-seed the doc as if a previous attempt created it.
        doc_name = f"{(ref.title or ref.id)[:120]}__course_textbook"
        fake_adapter.create_dataset(name="nexus-test-course_textbook",
                                     chunk_method="book")
        kb_id = next(iter(fake_adapter._datasets.keys()))
        fake_adapter.create_document(
            kb_id=kb_id, doc_name=doc_name, content="x", chunk_method="book"
        )
        pre_existing_doc_id = next(iter(fake_adapter._docs.keys()))

        from nexus_app.index import ragflow_adapter as ra_mod
        from nexus_app.index import kb_registry as kb_mod
        monkeypatch.setattr(ra_mod, "get_ragflow_adapter", lambda settings=None: fake_adapter)
        # Force KbRegistry to map course_textbook -> our pre-seeded kb_id
        registry = KbRegistry(adapter=fake_adapter, settings=get_settings())
        registry._cache["course_textbook"] = kb_id
        kb_mod._default_registry = registry
        monkeypatch.setattr(stages, "_load_normalized_content",
                            lambda ctx, ref: "synthetic")

        try:
            chunks = [
                models.KnowledgeChunk(
                    normalized_ref_id=ref.id,
                    knowledge_type_code="course_textbook",
                    chunk_type=ChunkType.PASSTHROUGH_DESCRIPTOR,
                    chunking_strategy="passthrough_to_ragflow",
                    chunk_index=0, content="c", chunk_metadata={},
                ),
            ]
            for c in chunks:
                session.add(c)
            session.flush()

            class _Ctx:
                pass
            ctx = _Ctx()
            ctx.session = session
            ctx.settings = get_settings()
            ctx.storage = InMemoryObjectStorage()
            ctx.trace_id = "trace-idem"
            ctx.job = _existing_job_for_ref(session, ref.id)

            doc_count_before = len(fake_adapter._docs)
            manifests = stages.run_index_submit(ctx, version, ref, chunks)

            # No new doc should have been created.
            assert len(fake_adapter._docs) == doc_count_before
            assert manifests[0].ragflow_doc_id == pre_existing_doc_id
            assert manifests[0].index_status == IndexManifestStatus.INDEXED
        finally:
            reset_kb_registry()


class TestIndexSubmitPartialSuccess:
    """2.2: when some kts succeed and others fail, the stage is PARTIAL
    (not FAILED) so callers can distinguish from a total wipeout."""

    def test_one_kt_succeeds_one_fails(self, session, make_ai_run, monkeypatch):
        import httpx
        from nexus_app.pipeline import stages

        _, version, ref = make_ai_run(ai_output={"classification": "D4",
                                                 "level": "L1", "tags": [],
                                                 "org_scope": "all",
                                                 "confidence": 0.9})
        version.version_status = AssetVersionStatus.AVAILABLE
        session.flush()

        class _FlakyAdapter(FakeRAGFlowAdapter):
            def __init__(self):
                super().__init__()
                self._call_count = 0

            def create_document(self, *args, **kwargs):  # type: ignore[override]
                self._call_count += 1
                # First create succeeds, second fails
                if self._call_count == 1:
                    return super().create_document(*args, **kwargs)
                raise httpx.ConnectError("simulated transient")

        flaky = _FlakyAdapter()
        from nexus_app.index import ragflow_adapter as ra_mod
        from nexus_app.index import kb_registry as kb_mod
        monkeypatch.setattr(ra_mod, "get_ragflow_adapter", lambda settings=None: flaky)
        kb_mod._default_registry = KbRegistry(adapter=flaky, settings=get_settings())
        monkeypatch.setattr(stages, "_load_normalized_content",
                            lambda ctx, ref: "x")

        try:
            chunks = [
                models.KnowledgeChunk(
                    normalized_ref_id=ref.id,
                    knowledge_type_code="course_textbook",
                    chunk_type=ChunkType.PASSTHROUGH_DESCRIPTOR,
                    chunking_strategy="passthrough_to_ragflow",
                    chunk_index=0, content="c1", chunk_metadata={},
                ),
                models.KnowledgeChunk(
                    normalized_ref_id=ref.id,
                    knowledge_type_code="qa_corpus",
                    chunk_type=ChunkType.PASSTHROUGH_DESCRIPTOR,
                    chunking_strategy="passthrough_to_ragflow",
                    chunk_index=0, content="c2", chunk_metadata={},
                ),
            ]
            for c in chunks:
                session.add(c)
            session.flush()

            class _Ctx:
                pass
            ctx = _Ctx()
            ctx.session = session
            ctx.settings = get_settings()
            ctx.storage = InMemoryObjectStorage()
            ctx.trace_id = "trace-partial"
            ctx.job = _existing_job_for_ref(session, ref.id)

            manifests = stages.run_index_submit(ctx, version, ref, chunks)

            statuses = sorted(m.index_status.value for m in manifests)
            assert statuses == ["failed", "indexed"]

            from nexus_app.enums import StageStatus
            stage_row = session.scalars(
                select(models.JobStage)
                .where(
                    models.JobStage.job_id == ctx.job.id,
                    models.JobStage.stage_name == "index_submit",
                )
                .order_by(models.JobStage.created_at.desc())
            ).first()
            assert stage_row.status == StageStatus.PARTIAL
            assert stage_row.detail["indexed_count"] == 1
            assert stage_row.detail["failed_count"] == 1
        finally:
            reset_kb_registry()


class TestAIGovernanceFailureRestartable:
    """1.1: when AI run produces no output, version is marked FAILED and the
    governance_decision stage records `restartable=True` for the restart API."""

    def test_failed_ai_run_marks_version_failed_and_restartable(
        self, session, make_ai_run, monkeypatch
    ):
        """Stub AIGovernanceService.run_governance to return a failed run object;
        verify run_governance_decision flips the version to FAILED with restartable
        detail (so the restart-governance API can accept it later)."""
        from nexus_app.ai_governance import services as ai_services
        from nexus_app.enums import (
            AIGovernanceRunAdoptionStatus,
            AIGovernanceRunValidationStatus,
        )
        from nexus_app.pipeline import stages

        _, version, ref = make_ai_run(ai_output={"classification": "D4",
                                                 "level": "L1", "tags": [],
                                                 "org_scope": "all",
                                                 "confidence": 0.9})
        prompt = models.GovernancePromptTemplate(
            task_type="classification",
            template_name="classification",
            template_version=1,
            status="active",
            prompt_template="{{DOCUMENT}}",
            output_schema_version="1.0",
            litellm_model_alias="fake",
            temperature=0.1,
            max_input_tokens=1024,
            redaction_policy="metadata_only",
        )
        session.add(prompt)
        session.flush()

        from nexus_app.ai_governance.rules_registry import GovernanceRulesRegistry

        def _load_rules(self, session_):
            self.load_dict({
                "schema_version": "1.0",
                "classifications": [
                    {"code": "D4", "name": "Teaching", "description": "d", "criteria": ["c"]},
                ],
                "levels": [
                    {"code": "L1", "name": "Public", "description": "d", "criteria": ["c"]},
                ],
                "tags": [],
                "quality_scoring": {
                    "dimensions": [
                        {"name": "completeness", "weight": 1.0, "description": "d",
                         "check_items": []},
                    ],
                    "thresholds": {"pass": 70, "warning": 50, "review_required_below": 50},
                    "confidence_threshold_auto_adopt": 0.8,
                },
            })

        monkeypatch.setattr(GovernanceRulesRegistry, "load", _load_rules)

        def _fake_run_governance_multi(self, session_, normalized_ref_id, **_):
            run = models.AIGovernanceRun(
                normalized_ref_id=normalized_ref_id,
                profile_id=None,
                model_alias="fake",
                prompt_version="v1",
                input_hash="x",
                input_summary={},
                ai_output=None,
                validation_status=AIGovernanceRunValidationStatus.FAILED,
                adoption_status=AIGovernanceRunAdoptionStatus.REVIEW_REQUIRED,
                validation_error="simulated LLM failure",
            )
            session_.add(run)
            session_.flush()
            return run

        monkeypatch.setattr(
            ai_services.AIGovernanceService, "run_governance_multi", _fake_run_governance_multi
        )

        class _Ctx:
            pass
        ctx = _Ctx()
        ctx.session = session
        ctx.settings = get_settings()
        ctx.storage = InMemoryObjectStorage()
        ctx.trace_id = "trace-aifail"
        ctx.job = _existing_job_for_ref(session, ref.id)

        result = stages.run_governance_decision(ctx, version, ref)
        assert result is None
        assert version.version_status == AssetVersionStatus.FAILED
        assert version.failure_reason and "ai_governance_failed" in version.failure_reason

        # Pick the latest governance_decision stage — fixture's earlier pipeline
        # run already created an initial (SKIPPED) one before this test's call.
        stage = session.scalars(
            select(models.JobStage).where(
                models.JobStage.job_id == ctx.job.id,
                models.JobStage.stage_name == "governance_decision",
            ).order_by(models.JobStage.created_at.desc())
        ).first()
        assert stage is not None
        assert stage.status == StageStatus.FAILED
        assert stage.detail.get("restartable") is True


class TestKnowledgeEmissionsEdgeCases:
    """6.6: empty / missing / malformed metadata_summary handled safely."""

    def _ctx(self, session, ref):
        class _Ctx:
            pass
        ctx = _Ctx()
        ctx.session = session
        ctx.settings = get_settings()
        ctx.storage = InMemoryObjectStorage()
        ctx.trace_id = "trace-edge"
        ctx.job = _existing_job_for_ref(session, ref.id)
        return ctx

    def test_missing_metadata_summary(self, session, make_ai_run):
        from nexus_app.pipeline import stages

        _, version, ref = make_ai_run(ai_output={"classification": "D4",
                                                 "level": "L1", "tags": [],
                                                 "org_scope": "all",
                                                 "confidence": 0.9})
        version.version_status = AssetVersionStatus.AVAILABLE
        ref.metadata_summary = None  # missing
        session.flush()

        chunks = stages.run_knowledge_chunking(self._ctx(session, ref), version, ref)
        assert chunks == []

    def test_missing_emissions_continue_after_recovery(self, session, make_ai_run, monkeypatch):
        """A historical skipped job can catch up after deterministic recovery."""
        from nexus_app.pipeline import stages

        _, version, ref = make_ai_run(ai_output={"classification": "D4",
                                                 "level": "L1", "tags": [],
                                                 "org_scope": "all",
                                                 "confidence": 0.9})
        version.version_status = AssetVersionStatus.AVAILABLE
        ref.metadata_summary = None
        ctx = self._ctx(session, ref)
        self._put_minimal_textbook_payload(ctx, ref)
        monkeypatch.setattr(
            stages,
            "_recover_knowledge_emissions",
            lambda _ctx, _ref: (
                [{"code": "course_textbook", "primary": True}],
                {"recovery": "materialized", "ai_run_id": "late-run", "emission_count": 1},
            ),
        )

        chunks = stages.run_knowledge_chunking(ctx, version, ref)

        assert chunks
        stage = session.scalars(
            select(models.JobStage).where(
                models.JobStage.job_id == ctx.job.id,
                models.JobStage.stage_name == "knowledge_chunking",
            ).order_by(models.JobStage.created_at.desc())
        ).first()
        assert stage is not None
        assert stage.status == StageStatus.SUCCEEDED
        assert stage.detail["recovery"] == "materialized"

    def test_graph_emission_queues_one_idempotent_build(self, session, make_ai_run):
        from nexus_app.pipeline import stages

        _, version, ref = make_ai_run(ai_output={"classification": "D4",
                                                 "level": "L1", "tags": [],
                                                 "org_scope": "all",
                                                 "confidence": 0.9})
        session.add(models.KnowledgeChunk(
            normalized_ref_id=ref.id,
            knowledge_type_code="course_standard_authoring_process",
            chunk_type=ChunkType.PROCESS_STEP,
            chunking_strategy="process_step_extract",
            source_kind="extracted_from_normalized",
            chunk_index=0,
            content="培养规格要求学生具备跨境电商运营能力。",
            chunk_metadata={},
        ))
        session.flush()
        ctx = self._ctx(session, ref)
        emissions = [
            {"code": "course_standard_authoring_process", "primary": True},
            {"code": "course_knowledge_graph", "primary": False},
        ]

        queued = stages._enqueue_evidence_graph_build_if_requested(ctx, ref, emissions)
        reused = stages._enqueue_evidence_graph_build_if_requested(ctx, ref, emissions)

        assert queued is not None
        assert queued["status"] == "queued"
        assert reused is not None
        assert reused["status"] == "existing"
        assert session.query(models.KnowledgeGraphBuild).filter_by(
            normalized_ref_id=ref.id
        ).count() == 1

    def _put_minimal_textbook_payload(self, ctx, ref) -> None:
        normalized_key = ref.object_uri.split("/", 3)[-1]
        body_markdown = "\n".join([
            "# 项目一 短视频认知",
            "## 任务一 认识短视频",
            "本任务介绍短视频平台、账号定位和内容形态。",
        ])
        ctx.storage.put_bytes(
            normalized_key,
            json.dumps(
                {
                    "body_markdown": body_markdown,
                    "blocks": [
                        {
                            "block_id": "b1",
                            "block_type": "heading",
                            "seq_no": 1,
                            "page": 1,
                            "bbox": [0, 0, 100, 20],
                            "text": "项目一 短视频认知",
                            "heading_level": 1,
                            "md_char_range": [0, 12],
                        },
                        {
                            "block_id": "b2",
                            "block_type": "heading",
                            "seq_no": 2,
                            "page": 1,
                            "bbox": [0, 25, 100, 45],
                            "text": "任务一 认识短视频",
                            "heading_level": 2,
                            "md_char_range": [13, 26],
                        },
                        {
                            "block_id": "b3",
                            "block_type": "paragraph",
                            "seq_no": 3,
                            "page": 1,
                            "bbox": [0, 50, 500, 90],
                            "text": "本任务介绍短视频平台、账号定位和内容形态。",
                            "content": "本任务介绍短视频平台、账号定位和内容形态。",
                            "md_char_range": [27, len(body_markdown)],
                        },
                    ],
                },
                ensure_ascii=False,
            ).encode("utf-8"),
            "application/json",
        )

    def test_empty_emissions_list(self, session, make_ai_run):
        from nexus_app.pipeline import stages

        _, version, ref = make_ai_run(ai_output={"classification": "D4",
                                                 "level": "L1", "tags": [],
                                                 "org_scope": "all",
                                                 "confidence": 0.9})
        version.version_status = AssetVersionStatus.AVAILABLE
        ref.metadata_summary = {"knowledge_emissions": []}
        session.flush()

        chunks = stages.run_knowledge_chunking(self._ctx(session, ref), version, ref)
        assert chunks == []

    def test_version_not_available_skips(self, session, make_ai_run):
        from nexus_app.pipeline import stages

        _, version, ref = make_ai_run(ai_output={"classification": "D4",
                                                 "level": "L1", "tags": [],
                                                 "org_scope": "all",
                                                 "confidence": 0.9})
        # version stays PROCESSING
        ref.metadata_summary = {"knowledge_emissions": [{"code": "course_textbook"}]}
        session.flush()

        chunks = stages.run_knowledge_chunking(self._ctx(session, ref), version, ref)
        assert chunks == []

    def test_review_required_with_index_admitted_governance_builds_internal_chunks(
        self, session, make_ai_run
    ):
        from nexus_app.pipeline import stages

        run, version, ref = make_ai_run(
            ai_output={"classification": "D4", "level": "L1", "tags": [],
                       "org_scope": "all", "confidence": 0.9},
            quality_summary={
                "quality_score": 79.0,
                "quality_level": "warning",
                "confidence": 0.9,
                "blocking_reasons": [],
            },
        )
        version.version_status = AssetVersionStatus.REVIEW_REQUIRED
        ref.metadata_summary = {"knowledge_emissions": [{"code": "course_textbook"}]}
        result = models.GovernanceResult(
            normalized_ref_id=ref.id,
            ai_run_id=run.id,
            classification="D4",
            level="L1",
            tags=[],
            org_scope="all",
            index_admission=True,
            quality_summary=run.quality_summary,
            decision_trail=[
                {"field_name": "classification", "adoption_status": "auto_adopted"},
                {"field_name": "level", "adoption_status": "auto_adopted"},
                {"field_name": "tags", "adoption_status": "auto_adopted"},
                {"field_name": "quality", "adoption_status": "auto_adopted"},
            ],
            rules_schema_version="1.0",
            rules_content_hash="a" * 64,
            status=GovernanceResultStatus.AVAILABLE,
        )
        session.add(result)
        session.flush()

        ctx = self._ctx(session, ref)
        self._put_minimal_textbook_payload(ctx, ref)

        chunks = stages.run_knowledge_chunking(ctx, version, ref)
        assert chunks
        assert all(chunk.knowledge_type_code == "course_textbook" for chunk in chunks)

        stage = session.scalars(
            select(models.JobStage).where(
                models.JobStage.job_id == _existing_job_for_ref(session, ref.id).id,
                models.JobStage.stage_name == "knowledge_chunking",
                models.JobStage.status == StageStatus.SUCCEEDED,
            ).order_by(models.JobStage.created_at.desc())
        ).first()
        assert stage is not None
        assert stage.detail["chunking_admission"] == "governance_index_admitted"
        assert stage.detail["governance_result_id"] == result.id

        manifests = stages.run_index_submit(ctx, version, ref, chunks)
        assert manifests == []
        index_stage = session.scalars(
            select(models.JobStage).where(
                models.JobStage.job_id == _existing_job_for_ref(session, ref.id).id,
                models.JobStage.stage_name == "index_submit",
            ).order_by(models.JobStage.created_at.desc())
        ).first()
        assert index_stage is not None
        assert index_stage.status == StageStatus.SKIPPED
        assert index_stage.detail["reason"] == "version not available (status=review_required)"
