"""Auth boundary tests for the `/internal/v1` and `/open/v1` routers.

These tests use the `app_no_auth_override` fixture so dependency injection
runs for real — they're the only place the live `require_user` and
`require_api_caller` code paths are exercised.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from nexus_app import auth_service, models
from nexus_app.config import get_settings
from nexus_app.enums import (
    AssetKind,
    AssetVersionStatus,
    DataSourceType,
    IngestBatchStatus,
    NormalizedAssetRefStatus,
    NormalizedType,
    PrincipalStatus,
    RawObjectStatus,
    UserRole,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def admin_user(session: Session) -> models.UserAccount:
    user = models.UserAccount(
        id="user-admin-1",
        username="boundary-admin",
        display_name="Boundary Admin",
        role=UserRole.PLATFORM_DATA_ADMIN,
        org_unit_id=None,
        email=None,
        status=PrincipalStatus.ACTIVE,
        password_hash=auth_service.hash_password("hunter2"),
    )
    session.add(user)
    session.commit()
    return user


@pytest.fixture()
def disabled_user(session: Session) -> models.UserAccount:
    user = models.UserAccount(
        id="user-disabled-1",
        username="boundary-disabled",
        display_name="Disabled Admin",
        role=UserRole.PLATFORM_DATA_ADMIN,
        org_unit_id=None,
        email=None,
        status=PrincipalStatus.DISABLED,
        password_hash=auth_service.hash_password("hunter2"),
    )
    session.add(user)
    session.commit()
    return user


@pytest.fixture()
def admin_access_token(admin_user: models.UserAccount) -> str:
    settings = get_settings()
    token, _ = auth_service.encode_access_token(
        settings, user=admin_user, org_name=None
    )
    return token


@pytest.fixture()
def disabled_access_token(disabled_user: models.UserAccount) -> str:
    settings = get_settings()
    token, _ = auth_service.encode_access_token(
        settings, user=disabled_user, org_name=None
    )
    return token


@pytest.fixture()
def active_caller(session: Session) -> tuple[models.ApiCaller, str]:
    plaintext = auth_service.generate_api_caller_key()
    caller = models.ApiCaller(
        id="caller-active-1",
        name="Active Caller",
        caller_key=None,
        caller_key_hash=auth_service.hash_api_caller_key(plaintext),
        org_scope=[],
        permission_scope=[],
        revoked_at=None,
        expired_at=None,
    )
    session.add(caller)
    session.commit()
    return caller, plaintext


@pytest.fixture()
def revoked_caller(session: Session) -> tuple[models.ApiCaller, str]:
    plaintext = auth_service.generate_api_caller_key()
    caller = models.ApiCaller(
        id="caller-revoked-1",
        name="Revoked Caller",
        caller_key=None,
        caller_key_hash=auth_service.hash_api_caller_key(plaintext),
        org_scope=[],
        permission_scope=[],
        revoked_at=datetime.now(timezone.utc),
        expired_at=None,
    )
    session.add(caller)
    session.commit()
    return caller, plaintext


@pytest.fixture()
def expired_caller(session: Session) -> tuple[models.ApiCaller, str]:
    plaintext = auth_service.generate_api_caller_key()
    caller = models.ApiCaller(
        id="caller-expired-1",
        name="Expired Caller",
        caller_key=None,
        caller_key_hash=auth_service.hash_api_caller_key(plaintext),
        org_scope=[],
        permission_scope=[],
        revoked_at=None,
        expired_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    session.add(caller)
    session.commit()
    return caller, plaintext


# ---------------------------------------------------------------------------
# /health is public
# ---------------------------------------------------------------------------


def test_health_is_public(app_no_auth_override):
    with TestClient(app_no_auth_override) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["status"] == "ok"


# ---------------------------------------------------------------------------
# /internal/v1 — JWT enforcement
# ---------------------------------------------------------------------------


def _error_message(resp_json: dict) -> str:
    """Pull the human-readable message from the project's error envelope."""
    return resp_json.get("error", {}).get("message", "")


def test_internal_endpoint_rejects_missing_token(app_no_auth_override):
    with TestClient(app_no_auth_override) as client:
        resp = client.get("/internal/v1/jobs")
    assert resp.status_code == 401
    assert "authentication required" in _error_message(resp.json())


def test_internal_endpoint_rejects_invalid_token(app_no_auth_override):
    with TestClient(app_no_auth_override) as client:
        resp = client.get(
            "/internal/v1/jobs",
            headers={"Authorization": "Bearer not-a-real-token"},
        )
    assert resp.status_code == 401


def test_internal_endpoint_accepts_bearer_token(
    app_no_auth_override, admin_access_token
):
    with TestClient(app_no_auth_override) as client:
        resp = client.get(
            "/internal/v1/jobs",
            headers={"Authorization": f"Bearer {admin_access_token}"},
        )
    assert resp.status_code == 200


def test_internal_endpoint_accepts_cookie_token(
    app_no_auth_override, admin_access_token
):
    with TestClient(app_no_auth_override) as client:
        resp = client.get(
            "/internal/v1/jobs",
            cookies={"nexus_access_token": admin_access_token},
        )
    assert resp.status_code == 200


def test_internal_endpoint_rejects_disabled_user(
    app_no_auth_override, disabled_access_token
):
    with TestClient(app_no_auth_override) as client:
        resp = client.get(
            "/internal/v1/jobs",
            headers={"Authorization": f"Bearer {disabled_access_token}"},
        )
    assert resp.status_code == 403
    assert "disabled" in _error_message(resp.json())


def test_internal_auth_login_is_public(app_no_auth_override, admin_user):
    """The login endpoint must be reachable without a token — it mints one."""
    with TestClient(app_no_auth_override) as client:
        resp = client.post(
            "/internal/v1/auth/login",
            json={"username": admin_user.username, "password": "hunter2"},
        )
    assert resp.status_code == 200
    assert "access_token" in resp.json()["data"]


# ---------------------------------------------------------------------------
# /open/v1 — ApiCaller enforcement
# ---------------------------------------------------------------------------


def test_open_endpoint_rejects_missing_key(app_no_auth_override):
    with TestClient(app_no_auth_override) as client:
        resp = client.get("/open/v1/assets")
    assert resp.status_code == 401


def test_open_endpoint_rejects_invalid_key(app_no_auth_override):
    with TestClient(app_no_auth_override) as client:
        resp = client.get(
            "/open/v1/assets",
            headers={"X-API-Key": "nx_bogus_key"},
        )
    assert resp.status_code == 401


def test_open_endpoint_rejects_revoked_caller(app_no_auth_override, revoked_caller):
    _, plaintext = revoked_caller
    with TestClient(app_no_auth_override) as client:
        resp = client.get(
            "/open/v1/assets",
            headers={"X-API-Key": plaintext},
        )
    assert resp.status_code == 403


def test_open_endpoint_rejects_expired_caller(app_no_auth_override, expired_caller):
    _, plaintext = expired_caller
    with TestClient(app_no_auth_override) as client:
        resp = client.get(
            "/open/v1/assets",
            headers={"X-API-Key": plaintext},
        )
    assert resp.status_code == 403


def test_open_endpoint_accepts_active_caller(app_no_auth_override, active_caller):
    _, plaintext = active_caller
    with TestClient(app_no_auth_override) as client:
        resp = client.get(
            "/open/v1/assets",
            headers={"X-API-Key": plaintext},
        )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# /open/v1 visibility filter — only `available` versions reach upstream apps.
# ---------------------------------------------------------------------------


def _seed_data_source(session: Session) -> models.DataSource:
    ds = models.DataSource(
        id="ds-open-1",
        code="ds-open-1",
        name="Open Test Source",
        source_type=DataSourceType.FILE_UPLOAD,
    )
    session.add(ds)
    session.flush()
    batch = models.IngestBatch(
        id="batch-open-1",
        data_source_id=ds.id,
        idempotency_key="batch-open-1",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.COMPLETED,
    )
    session.add(batch)
    session.commit()
    return ds


def _seed_asset_with_version(
    session: Session,
    *,
    asset_id: str,
    ds: models.DataSource,
    version_no: int,
    version_status: AssetVersionStatus,
) -> tuple[models.Asset, models.AssetVersion]:
    asset = session.get(models.Asset, asset_id)
    if asset is None:
        asset = models.Asset(
            id=asset_id,
            data_source_id=ds.id,
            source_object_key=f"{asset_id}-key",
            title=f"Asset {asset_id}",
            asset_kind=AssetKind.DOCUMENT,
        )
        session.add(asset)
        session.flush()

    raw = models.RawObject(
        id=f"raw-{asset_id}-v{version_no}",
        batch_id="batch-open-1",
        data_source_id=ds.id,
        source_type=DataSourceType.FILE_UPLOAD,
        source_uri=f"file://{asset_id}-v{version_no}",
        object_uri=f"raw/{asset_id}-v{version_no}",
        checksum=f"{asset_id}-v{version_no}-checksum",
        size_bytes=1,
        status=RawObjectStatus.RAW_PERSISTED,
    )
    session.add(raw)
    session.flush()

    version = models.AssetVersion(
        id=f"{asset_id}-v{version_no}",
        asset_id=asset.id,
        raw_object_id=raw.id,
        version_no=version_no,
        source_checksum=raw.checksum,
        version_status=version_status,
    )
    session.add(version)
    session.commit()
    return asset, version


def test_open_assets_only_returns_available(
    app_no_auth_override, session, active_caller
):
    _, plaintext = active_caller
    ds = _seed_data_source(session)
    _seed_asset_with_version(
        session,
        asset_id="asset-available",
        ds=ds,
        version_no=1,
        version_status=AssetVersionStatus.AVAILABLE,
    )
    _seed_asset_with_version(
        session,
        asset_id="asset-review",
        ds=ds,
        version_no=1,
        version_status=AssetVersionStatus.REVIEW_REQUIRED,
    )
    _seed_asset_with_version(
        session,
        asset_id="asset-archived",
        ds=ds,
        version_no=1,
        version_status=AssetVersionStatus.ARCHIVED,
    )

    with TestClient(app_no_auth_override) as client:
        resp = client.get(
            "/open/v1/assets",
            headers={"X-API-Key": plaintext},
        )
    assert resp.status_code == 200
    asset_ids = {item["id"] for item in resp.json()["data"]}
    assert asset_ids == {"asset-available"}


def test_open_asset_versions_only_returns_available(
    app_no_auth_override, session, active_caller
):
    _, plaintext = active_caller
    ds = _seed_data_source(session)
    # Same asset, two versions: one available, one review_required.
    _seed_asset_with_version(
        session,
        asset_id="asset-mixed",
        ds=ds,
        version_no=1,
        version_status=AssetVersionStatus.ARCHIVED,
    )
    _seed_asset_with_version(
        session,
        asset_id="asset-mixed",
        ds=ds,
        version_no=2,
        version_status=AssetVersionStatus.AVAILABLE,
    )
    _seed_asset_with_version(
        session,
        asset_id="asset-mixed",
        ds=ds,
        version_no=3,
        version_status=AssetVersionStatus.REVIEW_REQUIRED,
    )

    with TestClient(app_no_auth_override) as client:
        resp = client.get(
            "/open/v1/assets/asset-mixed/versions",
            headers={"X-API-Key": plaintext},
        )
    assert resp.status_code == 200
    version_nos = {item["version_no"] for item in resp.json()["data"]}
    assert version_nos == {2}


def test_open_normalized_ref_404_when_version_not_available(
    app_no_auth_override, session, active_caller
):
    _, plaintext = active_caller
    ds = _seed_data_source(session)
    _, version = _seed_asset_with_version(
        session,
        asset_id="asset-archived-only",
        ds=ds,
        version_no=1,
        version_status=AssetVersionStatus.ARCHIVED,
    )
    ref = models.NormalizedAssetRef(
        id="ref-archived",
        version_id=version.id,
        normalized_type=NormalizedType.DOCUMENT,
        object_uri="normalized/archived.json",
        schema_version="1.0",
        checksum="ref-archived-checksum",
        title="Archived",
        language="en",
        source_type="file_upload",
        content_type="document",
        governance={"level": "L2"},
        quality={},
        lineage={},
        metadata_summary={},
        status=NormalizedAssetRefStatus.GENERATED,
    )
    session.add(ref)
    session.commit()

    with TestClient(app_no_auth_override) as client:
        resp = client.get(
            "/open/v1/normalized-refs/ref-archived",
            headers={"X-API-Key": plaintext},
        )
    assert resp.status_code == 404
