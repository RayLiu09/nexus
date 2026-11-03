from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier, Event

import pytest
from fastapi.testclient import TestClient

from nexus_api import asset_center_cache
from nexus_api.api.internal.asset_center import _classification_counts
from nexus_api.asset_center_cache import AssetCenterCountsCache
from nexus_app import auth_service, models
from nexus_app.config import get_settings
from nexus_app.enums import AssetVersionStatus, NormalizedAssetRefStatus, PrincipalStatus
from tests.test_asset_catalog_api import _seed_review_required_asset


def _clone(row, **changes):
    values = {
        column.key: getattr(row, column.key)
        for column in row.__table__.columns
        if column.key not in {"id", "created_at", "updated_at"}
    }
    values.update(changes)
    return type(row)(**values)


@pytest.mark.parametrize(
    ("older_status", "newer_status", "expected"),
    [
        (AssetVersionStatus.AVAILABLE, AssetVersionStatus.REVIEW_REQUIRED, 1),
        (AssetVersionStatus.AVAILABLE, AssetVersionStatus.PROCESSING, 1),
        (AssetVersionStatus.REVIEW_REQUIRED, AssetVersionStatus.ARCHIVED, 1),
        (AssetVersionStatus.REVIEW_REQUIRED, AssetVersionStatus.DISABLED, 1),
        (AssetVersionStatus.REVIEW_REQUIRED, AssetVersionStatus.PROCESSING, 0),
        (AssetVersionStatus.REVIEW_REQUIRED, AssetVersionStatus.FAILED, 0),
        (AssetVersionStatus.REVIEW_REQUIRED, AssetVersionStatus.REVIEW_REQUIRED, 0),
    ],
)
def test_counts_select_current_version_before_checking_refs(
    session, older_status, newer_status, expected
):
    seeded = _seed_review_required_asset(session)
    seeded["version"].version_status = older_status
    # The newer version has no generated ref. Never fall back to an older ref
    # if it wins selection; available wins even over a newer review version.
    session.add(_clone(seeded["version"], version_no=8, version_status=newer_status))
    session.commit()
    assert _classification_counts(session).get("policy/industry-reports", 0) == expected


def test_counts_use_latest_generated_ref_and_stable_result_tiebreak(session):
    seeded = _seed_review_required_asset(session)
    stamp = datetime(2030, 1, 1, tzinfo=timezone.utc)
    # All generated refs share a timestamp; id chooses the current one.
    seeded["ref"].created_at = stamp
    seeded["ref"].id = "ref-a"
    seeded["result"].normalized_ref_id = "ref-a"
    current = _clone(seeded["ref"], id="ref-b", created_at=stamp)
    failed = _clone(
        seeded["ref"], id="ref-z", created_at=stamp,
        status=NormalizedAssetRefStatus.FAILED,
    )
    session.add_all([current, failed])
    session.flush()
    session.add_all([
        _clone(seeded["result"], id="result-a", normalized_ref_id=current.id,
               created_at=stamp, classification="industry_policy"),
        _clone(seeded["result"], id="result-z", normalized_ref_id=current.id,
               created_at=stamp, classification="industry_regulation_standard"),
    ])
    session.commit()
    assert _classification_counts(session) == {"policy/industry-regulation-standards": 1}


def test_cache_expires_and_returns_independent_values(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(asset_center_cache, "monotonic", lambda: now[0])
    cache = AssetCenterCountsCache(ttl_seconds=15)
    source = {"policy/industry-reports": 1}
    assert cache.get_or_build(lambda: source) == source
    source["policy/industry-reports"] = 2
    returned = cache.get_or_build(lambda: source)
    assert returned["policy/industry-reports"] == 1
    returned.clear()
    now[0] = 14.99
    assert cache.get_or_build(lambda: source)["policy/industry-reports"] == 1
    now[0] = 15
    assert cache.get_or_build(lambda: source)["policy/industry-reports"] == 2
    assert AssetCenterCountsCache().get_or_build(lambda: {"other": 3}) == {"other": 3}


def test_concurrent_cache_misses_share_one_refresh():
    cache = AssetCenterCountsCache()
    ready = Barrier(9)
    started, release = Event(), Event()
    calls = []

    def build():
        calls.append(1)
        started.set()
        assert release.wait(5)
        return {"count": 7}

    def request():
        ready.wait(timeout=5)
        return cache.get_or_build(build)

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(request) for _ in range(8)]
        ready.wait(timeout=5)
        try:
            assert started.wait(5)
            assert len(calls) == 1
        finally:
            release.set()
        assert [future.result(timeout=5) for future in futures] == [{"count": 7}] * 8
    assert len(calls) == 1


def test_cache_refresh_failure_is_not_cached_or_served_as_old_data(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(asset_center_cache, "monotonic", lambda: now[0])
    cache = AssetCenterCountsCache()
    cache.get_or_build(lambda: {"count": 1})
    now[0] = 16

    def fail():
        raise RuntimeError("database unavailable")

    with pytest.raises(RuntimeError, match="database unavailable"):
        cache.get_or_build(fail)
    assert cache.get_or_build(lambda: {"count": 2}) == {"count": 2}


def test_cached_endpoint_still_authenticates_every_request(app_no_auth_override, session, stub_user):
    session.add(stub_user)
    session.commit()
    token, _ = auth_service.encode_access_token(get_settings(), user=stub_user, org_name=None)
    client = TestClient(app_no_auth_override)
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/internal/v1/asset-center/counts", headers=headers).status_code == 200
    assert client.get("/internal/v1/asset-center/counts").status_code == 401
    stub_user.status = PrincipalStatus.DISABLED
    session.commit()
    assert client.get("/internal/v1/asset-center/counts", headers=headers).status_code == 403
