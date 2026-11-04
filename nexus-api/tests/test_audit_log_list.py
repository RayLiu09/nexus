"""Administrator audit presentation, full-set filtering and access boundary."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from nexus_api.audit_presentation import present_audits
from nexus_app import models
from nexus_app.enums import AssetKind, AuditEventType, DataSourceType, UserRole


def _audit(session, id, event_type=AuditEventType.VERSION_STATUS_CHANGED, **kwargs):
    row = models.AuditLog(
        id=id, event_type=event_type,
        target_type=kwargs.pop("target_type", "asset"),
        target_id=kwargs.pop("target_id", "asset-1"),
        trace_id="audit-test-trace", summary=kwargs.pop("summary", {}), **kwargs,
    )
    session.add(row)
    return row


def test_filters_apply_before_pagination_and_event_choices_use_all_rows(app, session):
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(125):
        _audit(session, f"audit-{i:03d}", created_at=base + timedelta(seconds=i))
    _audit(session, "old-deletion", AuditEventType.ASSET_DELETED,
           created_at=base - timedelta(days=1))
    for i, kind in enumerate((AuditEventType.TOKEN_REFRESHED, AuditEventType.TOKEN_REFRESH_FAILED)):
        _audit(session, f"refresh-{i}", kind, created_at=base + timedelta(days=1))
    session.commit()

    with TestClient(app) as client:
        result = client.get("/internal/v1/audit-logs", params={
            "event_type": "VersionStatusChanged", "exclude_token_refresh": "true",
            "page": 3, "pageSize": 50,
        })
        assert result.status_code == 200, result.text
        body = result.json()
        assert body["meta"]["total"] == 125
        assert len(body["data"]) == 25
        assert body["data"][0]["id"] == "audit-024"
        assert {r["event_type"] for r in body["data"]} == {"VersionStatusChanged"}

        all_visible = client.get("/internal/v1/audit-logs?exclude_token_refresh=true").json()
        assert all_visible["meta"]["total"] == 126
        choices = client.get("/internal/v1/audit-logs/event-types?exclude_token_refresh=true")
        assert choices.status_code == 200, choices.text
        assert choices.json()["data"] == ["AssetDeleted", "VersionStatusChanged"]
        assert choices.json()["meta"]["total"] == 2
        # An explicit Token filter cannot bypass the list's exclusion flag.
        assert client.get("/internal/v1/audit-logs", params={
            "event_type": "TokenRefreshed", "exclude_token_refresh": "true",
        }).json()["meta"]["total"] == 0
        assert client.get("/internal/v1/audit-logs?event_type=invalid").status_code == 422
        # Exclusion is a read filter, preserving the original generic API default.
        assert client.get("/internal/v1/audit-logs").json()["meta"]["total"] == 128
    assert session.query(models.AuditLog).count() == 128


def _seed_named_targets(session, stub_user, stub_api_caller):
    session.add_all([
        stub_user, stub_api_caller,
        models.DataSource(id="source", code="source", name="文件接入", source_type=DataSourceType.FILE_UPLOAD),
        models.IngestBatch(id="batch", data_source_id="source", idempotency_key="batch", source_type=DataSourceType.FILE_UPLOAD),
        models.RawObject(id="raw", batch_id="batch", data_source_id="source",
                         source_type=DataSourceType.FILE_UPLOAD, object_uri="private/raw.pdf", checksum="raw",
                         metadata_summary={"filename": "人才报告.pdf", "content": "NEVER_RETURN_RAW"}),
        models.Asset(id="asset-1", data_source_id="source", source_object_key="asset", title="人才需求报告", asset_kind=AssetKind.DOCUMENT),
        models.AssetVersion(id="version", asset_id="asset-1", raw_object_id="raw", version_no=1, source_checksum="raw"),
        models.NormalizedAssetRef(id="ref", version_id="version", normalized_type="document",
                                  object_uri="private/ref.json", schema_version="v1", checksum="ref"),
        models.Job(id="job", job_type="ingest_process", raw_object_id="raw"),
        models.ParseArtifact(id="parse", raw_object_id="raw", artifact_uri="private/parse.json", parse_mode="pipeline", checksum="parse"),
    ])
    session.commit()


def test_resolves_names_without_leaking_content_and_keeps_missing_attribution(
    app, session, stub_user, stub_api_caller,
):
    _seed_named_targets(session, stub_user, stub_api_caller)
    for target_type, id in (("asset", "asset-1"), ("asset_version", "version"),
                            ("normalized_asset_ref", "ref"), ("raw_object", "raw"),
                            ("job", "job"), ("parse_artifact", "parse")):
        _audit(session, f"a-{id}", target_type=target_type, target_id=id,
               actor_type="user", actor_id=stub_user.id)
    _audit(session, "deleted", target_id="deleted-asset", summary={
        "asset_title": "已删除资产", "api_key": "NEVER_RETURN_KEY",
    }, actor_type="worker", actor_id="worker-123")
    _audit(session, "caller", target_type="api_caller", target_id=stub_api_caller.id,
           actor_type="api_caller", actor_id=stub_api_caller.id)
    _audit(session, "unknown", target_type="extension", target_id="ext-1")
    session.commit()
    with TestClient(app) as client:
        result = client.get("/internal/v1/audit-logs")
    assert result.status_code == 200, result.text
    assert "NEVER_RETURN_RAW" not in result.text
    assert "NEVER_RETURN_KEY" not in result.text
    assert "password_hash" not in result.text
    data = {row["id"]: row for row in result.json()["data"]}
    for id in ("asset-1", "version", "ref"):
        assert data[f"a-{id}"]["target_name"] == "人才需求报告"
        assert data[f"a-{id}"]["actor_name"] == "Test Admin"
    for id in ("raw", "job", "parse"):
        assert data[f"a-{id}"]["target_name"] == "人才报告.pdf"
    assert data["deleted"]["target_name"] == "已删除资产"
    assert data["deleted"]["actor_name"] == "worker-123"
    assert data["caller"]["actor_name"] == "Test Caller"
    assert data["caller"]["target_name"] == "Test Caller"
    assert data["unknown"]["target_name"] is None
    assert data["unknown"]["actor_name"] is None


@pytest.mark.parametrize("actor_type", ["system", "worker", "scheduler", "connector", "system_repair"])
def test_system_identities_display_the_recorded_executor(session, actor_type):
    row = _audit(session, "automatic", actor_type=actor_type, actor_id="internal-instance")
    session.flush()
    assert present_audits(session, [row])[0].actor_name == "internal-instance"
    assert row.actor_id == "internal-instance"  # Presentation does not rewrite evidence.


def test_system_type_without_a_recorded_executor_stays_unrecorded(session):
    row = _audit(session, "legacy-system", actor_type="system", actor_id=None)
    session.flush()
    assert present_audits(session, [row])[0].actor_name is None


def test_name_resolution_is_batched_for_a_large_page(session, stub_user, stub_api_caller):
    _seed_named_targets(session, stub_user, stub_api_caller)
    rows = [_audit(session, f"a-{i}", actor_type="user", actor_id=stub_user.id) for i in range(120)]
    session.flush()
    queries = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    engine = session.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        result = present_audits(session, rows)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(queries) == 2  # One target lookup and one actor lookup for all 120 rows.
    assert all(row.target_name == "人才需求报告" for row in result)


def test_missing_targets_for_supported_types_fall_back_without_join_errors(session):
    target_types = [
        "asset", "asset_version", "normalized_asset_ref", "raw_object", "job",
        "parse_artifact", "ingest_batch", "data_source", "crawler_plan", "crawler_run",
        "data_sync_config", "data_sync_run", "user_account", "api_caller", "org_unit",
        "ai_prompt_profile", "governance_prompt_template", "governance_result",
        "ai_governance_run", "knowledge_chunk",
    ]
    rows = [_audit(session, f"audit-{kind}", target_type=kind, target_id="missing")
            for kind in target_types]
    session.flush()
    result = present_audits(session, rows)
    assert len(result) == len(target_types)
    assert all(row.target_name is None and row.target_id == "missing" for row in result)


@pytest.mark.parametrize("path", ["/internal/v1/audit-logs", "/internal/v1/audit-logs/event-types"])
def test_only_data_administrators_can_read_audits(app, app_no_auth_override, stub_user, path):
    with TestClient(app_no_auth_override) as client:
        assert client.get(path).status_code == 401
    stub_user.role = UserRole.BUSINESS_EXPERT
    with TestClient(app) as client:
        assert client.get(path).status_code == 403


def test_same_timestamp_rows_have_stable_page_order(app, session):
    at = datetime(2026, 11, 4, tzinfo=timezone.utc)
    for id in ("audit-a", "audit-c", "audit-b"):
        _audit(session, id, created_at=at)
    session.commit()
    with TestClient(app) as client:
        first = client.get("/internal/v1/audit-logs?pageSize=2").json()["data"]
        second = client.get("/internal/v1/audit-logs?pageSize=2&page=2").json()["data"]
    assert [row["id"] for row in first + second] == ["audit-c", "audit-b", "audit-a"]
