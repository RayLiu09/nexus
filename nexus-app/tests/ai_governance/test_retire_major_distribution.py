from copy import deepcopy
import importlib.util
from pathlib import Path
from sqlalchemy import select
from nexus_app import models
from nexus_app.ai_governance.retired_major_distribution import clean_rules, retire_database_config
from nexus_app.enums import GovernanceRulesVersionStatus


def test_custom_rules_history_and_shared_configuration_survive(session):
    content = {
        "schema_version": "3.0",
        "classifications": [{"code": "major_distribution"}, {"code": "custom"}],
        "tags": [
            {"code": "shared", "applicable_classifications": ["custom", "major_distribution"]}
        ],
        "knowledge_types": [
            {"code": "dedicated", "applicable_classifications": ["major_distribution"]},
            {"code": "shared", "applicable_classifications": ["major_distribution", "custom"]},
        ],
        "custom_policy": {"keep": True},
    }
    old = models.GovernanceRulesVersion(
        version=7,
        status=GovernanceRulesVersionStatus.ACTIVE,
        rules_content=deepcopy(content),
        schema_version="3.0",
    )
    dedicated = models.AIPromptProfile(
        profile_name="major_distribution.extract",
        task_type="extract",
        scenario="default",
        litellm_model_alias="mock",
        prompt_version="1",
        prompt_template="history",
    )
    shared = models.AIPromptProfile(
        profile_name="shared",
        task_type="extract",
        scenario="default",
        litellm_model_alias="mock",
        prompt_version="1",
        prompt_template="shared history",
    )
    rule = models.AIAnalysisRules(
        rule_set_code="major_distribution.v1",
        version="1",
        scenario="major_distribution",
        domain="occupation",
        target_type=[],
        output_contract={},
        output_item_schema={},
        field_whitelist=[],
        guardrails=[],
        auto_admit_threshold=0.9,
        schema_version="1",
    )
    session.add_all([old, dedicated, shared, rule])
    session.commit()
    assert retire_database_config(session.connection()) == 4
    session.commit()
    session.expire_all()
    assert session.get(models.GovernanceRulesVersion, old.id).rules_content == content
    assert session.get(models.GovernanceRulesVersion, old.id).status.value == "archived"
    active = session.scalar(
        select(models.GovernanceRulesVersion).where(
            models.GovernanceRulesVersion.status == "active"
        )
    )
    assert active.version == 8 and active.rules_content == clean_rules(content)
    assert active.rules_content["custom_policy"] == {"keep": True}
    assert active.rules_content["knowledge_types"] == [
        {"code": "shared", "applicable_classifications": ["custom"]}
    ]
    assert session.get(models.AIPromptProfile, dedicated.id).status.value == "disabled"
    assert session.get(models.AIPromptProfile, dedicated.id).prompt_template == "history"
    assert session.get(models.AIPromptProfile, shared.id).status.value == "active"
    assert session.get(models.AIAnalysisRules, rule.id).is_active is False
    assert len(list(session.scalars(select(models.AuditLog)))) == 4
    assert retire_database_config(session.connection()) == 0


def test_alembic_creates_direct_domain_table(session):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect

    path = (
        Path(__file__).resolve().parents[2] / "alembic/versions/20261023_0121_moe_major_offering.py"
    )
    spec = importlib.util.spec_from_file_location("moe_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    connection = session.connection()
    models.MajorOfferingRecord.__table__.drop(connection)
    with Operations.context(MigrationContext.configure(connection)):
        migration.upgrade()
    columns = {c["name"] for c in inspect(connection).get_columns("major_offering_record")}
    assert {"year", "school_code", "school_name", "study_duration", "sync_run_id"} <= columns
    assert not {"source_page", "content_hash", "normalized_ref_id", "raw_row"} & columns
    assert migration.down_revision == "20261021_0120"


def test_old_job_is_stopped_before_storage_or_ai(session, monkeypatch):
    from nexus_app.enums import JobStatus, JobType
    from nexus_app.worker.runner import execute_job

    job = models.Job(
        job_type=JobType.INGEST_PROCESS,
        status=JobStatus.RUNNING,
        payload={"pipeline_type": "record", "domain_profile": "major_distribution.v1"},
        trace_id="retired-job",
    )
    session.add(job)
    session.commit()
    monkeypatch.setattr(
        "nexus_app.worker.runner.get_object_storage",
        lambda *_: (_ for _ in ()).throw(AssertionError("must not touch storage")),
    )
    execute_job(job, session)
    assert job.status == JobStatus.DEAD_LETTERED
    assert job.last_error_code == "major_distribution_pipeline_retired"
    assert list(session.scalars(select(models.AIGovernanceRun))) == []
    assert list(session.scalars(select(models.AssetVersion))) == []


def test_retired_config_cannot_be_saved_or_reseeded(session):
    import pytest
    from nexus_app.ai_governance.rules_service import GovernanceRulesService

    with pytest.raises(ValueError, match="retired"):
        GovernanceRulesService.create_new_version(
            session, {"classifications": [{"code": "major_distribution"}]}
        )
    assert list(session.scalars(select(models.GovernanceRulesVersion))) == []


def test_historical_reference_cannot_be_sent_to_ai_even_by_direct_recompute():
    from types import SimpleNamespace
    import pytest
    from nexus_app.ai_governance.services import AIGovernanceService, AIGovernanceError

    ref = SimpleNamespace(
        metadata_summary={"domain_profile": "major_distribution.v1"}, governance={}
    )
    with pytest.raises(AIGovernanceError, match="retired"):
        AIGovernanceService._build_ref_dict(ref)
