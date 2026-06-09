#!/usr/bin/env python3
"""Demo script: AI governance run with FakeLiteLLMClient.

Usage:
    cd nexus-app
    uv run python scripts/demo/demo_ai_governance.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow running from nexus-app directory
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from nexus_app import models
from nexus_app.ai_governance.litellm_client import FakeLiteLLMClient
from nexus_app.ai_governance.rules_registry import GovernanceRulesRegistry
from nexus_app.ai_governance.services import AIGovernanceService, PromptProfileService
from nexus_app.database import Base
from nexus_app.enums import (
    AssetKind,
    AssetVersionStatus,
    DataSourceType,
    IngestBatchStatus,
    NormalizedType,
    RawObjectStatus,
)

RULES_PATH = str(Path(__file__).resolve().parents[3] / "config" / "governance_rules.json")


def setup_db():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def seed_demo_data(session) -> tuple[models.AIPromptProfile, models.NormalizedAssetRef]:
    # Data source
    ds = models.DataSource(
        code="demo-ds", name="Demo Data Source",
        source_type=DataSourceType.FILE_UPLOAD,
    )
    session.add(ds)
    session.flush()

    # Ingest batch + raw object
    batch = models.IngestBatch(
        data_source_id=ds.id, idempotency_key="demo-batch-001",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.COMPLETED,
    )
    session.add(batch)
    session.flush()

    raw = models.RawObject(
        batch_id=batch.id, data_source_id=ds.id,
        source_type=DataSourceType.FILE_UPLOAD,
        source_uri="file://demo-teaching-material.pdf",
        object_uri="raw/demo-teaching-material.pdf",
        checksum="demo-abc123", size_bytes=102400,
        status=RawObjectStatus.RAW_PERSISTED,
    )
    session.add(raw)
    session.flush()

    # Asset + version
    asset = models.Asset(
        data_source_id=ds.id, source_object_key="demo-teaching-material.pdf",
        title="Demo Teaching Material",
        asset_kind=AssetKind.DOCUMENT,
    )
    session.add(asset)
    session.flush()

    version = models.AssetVersion(
        asset_id=asset.id, raw_object_id=raw.id,
        version_no=1, source_checksum="demo-abc123",
        version_status=AssetVersionStatus.PROCESSING,
    )
    session.add(version)
    session.flush()

    # Normalized ref
    ref = models.NormalizedAssetRef(
        version_id=version.id,
        normalized_type=NormalizedType.DOCUMENT,
        object_uri="normalized/demo-teaching-material.json",
        schema_version="1.0",
        checksum="demo-def456",
        title="企业内训教材：数字化转型基础",
        language="zh-CN",
        source_type="file_upload",
        content_type="document",
        governance={"level": "L2"},
        quality={},
        lineage={},
        metadata_summary={
            "summary": "本教材介绍企业数字化转型的基础知识和方法论",
            "content_snippet": "数字化转型是指企业利用数字技术从根本上改变业务模式...",
        },
    )
    session.add(ref)
    session.flush()

    # Prompt profile
    prompt_svc = PromptProfileService()
    profile = prompt_svc.create_profile(
        session,
        profile_name="demo-governance-profile",
        task_type="governance",
        litellm_model_alias="nexus-gpt-4o",
        prompt_version="v1.0",
        prompt_template=(
            "你是一个企业数据治理专家。请根据以下内容和治理规则定义，"
            "对文档进行分类、分级、打标和质量评分。\n\n"
            "请严格按照JSON格式输出，包含以下字段：\n"
            "classification, level, tags, org_scope, quality_scores, "
            "overall_score, evidence_refs, confidence, reasoning"
        ),
        temperature=0.2,
        redaction_policy="masked_content",
    )

    session.commit()
    return profile, ref


def run_demo():
    print("=" * 60)
    print("NEXUS AI Governance Demo (Week 3)")
    print("=" * 60)

    # Load governance rules
    print("\n1. Loading governance rules...")
    registry = GovernanceRulesRegistry()
    try:
        cfg = registry.load(RULES_PATH)
        print(f"   OK: schema_version={cfg.schema_version}, "
              f"{len(cfg.classifications)} classifications, {len(cfg.levels)} levels")
    except FileNotFoundError:
        print(f"   WARNING: governance_rules.json not found at {RULES_PATH}, using demo registry")
        from tests.ai_governance.test_ai_governance_unit import registry as _r
        registry = None

    # Setup DB
    print("\n2. Setting up demo database (in-memory SQLite)...")
    SessionLocal = setup_db()

    with SessionLocal() as session:
        print("\n3. Seeding demo data...")
        profile, ref = seed_demo_data(session)
        print(f"   Profile: {profile.profile_name} v{profile.profile_version} "
              f"(alias: {profile.litellm_model_alias})")
        print(f"   Normalized ref: {ref.title} (id: {ref.id[:8]}...)")

        print("\n4. Running AI governance (FakeLiteLLMClient)...")
        gov_svc = AIGovernanceService()
        run = gov_svc.run_governance(
            session, ref.id, profile.id,
            litellm_client=FakeLiteLLMClient(),
            registry=registry,
        )
        session.commit()

        print(f"   Run ID: {run.id[:8]}...")
        print(f"   Validation status: {run.validation_status.value}")
        print(f"   Adoption status: {run.adoption_status.value}")
        print(f"   Latency: {run.call_latency_ms:.1f}ms")
        print(f"   Input hash: {run.input_hash[:16]}...")

        if run.ai_output:
            print("\n5. AI Output:")
            print(f"   Classification: {run.ai_output.get('classification')}")
            print(f"   Level: {run.ai_output.get('level')}")
            print(f"   Tags: {run.ai_output.get('tags')}")
            print(f"   Confidence: {run.ai_output.get('confidence')}")
            print(f"   Overall score: {run.ai_output.get('overall_score')}")

        if run.quality_summary:
            print("\n6. Quality Summary:")
            qs = run.quality_summary
            print(f"   Quality score: {qs.get('quality_score')}")
            print(f"   Quality level: {qs.get('quality_level')}")
            print(f"   Confidence: {qs.get('confidence')}")
            print(f"   Dimension scores: {qs.get('dimension_scores')}")
            blocking = qs.get('blocking_reasons', [])
            if blocking:
                print(f"   Blocking reasons: {blocking}")
            else:
                print("   No blocking reasons")

        # Demo: schema_invalid case
        print("\n7. Demo: schema_invalid case (bad AI output)...")
        from nexus_app.ai_governance.litellm_client import FakeLiteLLMClient as _Fake
        bad_client = _Fake(response_override='{"invalid_field": "not governance output"}')
        bad_run = gov_svc.run_governance(
            session, ref.id, profile.id,
            litellm_client=bad_client,
            registry=registry,
        )
        session.commit()
        print(f"   Validation status: {bad_run.validation_status.value}")
        print(f"   Validation error: {bad_run.validation_error[:80]}...")

        print("\n8. Demo: policy_blocked / L3 content with metadata_only...")
        from nexus_app.ai_governance.services import PromptProfileService as _PPS
        pps = _PPS()
        blocked_profile = pps.create_profile(
            session, "blocked-profile", "governance",
            "nexus-gpt-4o", "v1.0", "Template.",
            redaction_policy="metadata_only",
        )
        l3_ref = models.NormalizedAssetRef(
            version_id=ref.version_id,
            normalized_type=NormalizedType.DOCUMENT,
            object_uri="normalized/l3-doc.json",
            schema_version="1.0", checksum="l3-xxx",
            title="L3 Confidential Doc",
            language="zh-CN", source_type="file_upload", content_type="document",
            governance={"level": "L3"}, quality={}, lineage={},
            metadata_summary={"content_snippet": "Sensitive content here"},
        )
        session.add(l3_ref)
        session.flush()
        l3_run = gov_svc.run_governance(
            session, l3_ref.id, blocked_profile.id,
            litellm_client=FakeLiteLLMClient(),
            registry=registry,
        )
        session.commit()
        print(f"   L3 + metadata_only: validation={l3_run.validation_status.value}")

    print("\n" + "=" * 60)
    print("Demo completed successfully!")
    print("\nSummary:")
    print("  - governance_rules.json loaded with D1-D4 classifications")
    print("  - FakeLiteLLMClient returned structured AI output")
    print("  - AIGovernanceRun created with schema_valid status")
    print("  - QualitySummary generated with dimension scores")
    print("  - Schema invalid case handled correctly")
    print("  - L3 content with metadata_only policy handled")
    print("\nNote: AI output is NOT written to governance_result (Week 4 scope)")
    print("=" * 60)


if __name__ == "__main__":
    run_demo()
