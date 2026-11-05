from types import SimpleNamespace

import pytest

from nexus_api.api.internal import governance_review
from nexus_api.dependencies import Pagination
from nexus_app import models
from nexus_app.governance.review_service import RetiredAssetGovernanceReviewError


def test_pending_governance_reviews_returns_page_slice_with_full_total(monkeypatch):
    result_ids = [f"review-{index}" for index in range(20, 25)]
    monkeypatch.setattr(
        governance_review,
        "_pending_review_result_ids",
        lambda _session, *, limit, offset: (result_ids, 25),
    )
    monkeypatch.setattr(
        governance_review,
        "_queue_items",
        lambda _session, ids: [{"governance_result_id": result_id} for result_id in ids],
    )

    response = governance_review.list_pending_governance_reviews(
        request=SimpleNamespace(state=SimpleNamespace(trace_id="trace-pagination")),
        pagination=Pagination(page=2, page_size=20),
        session=object(),
    )

    assert response.meta.page == 2
    assert response.meta.page_size == 20
    assert response.meta.total == 25
    assert [item["governance_result_id"] for item in response.data] == result_ids


def test_submit_retired_asset_review_returns_conflict(monkeypatch):
    class RetiredReviewService:
        def __init__(self, _registry):
            pass

        def submit(self, *_args, **_kwargs):
            raise RetiredAssetGovernanceReviewError("asset is manually retired")

    monkeypatch.setattr(governance_review, "GovernanceReviewService", RetiredReviewService)
    user = models.UserAccount(id="reviewer", role="business_expert")
    request = SimpleNamespace(state=SimpleNamespace(trace_id="trace-retired"))

    with pytest.raises(governance_review.HTTPException) as exc_info:
        governance_review.submit_governance_review_decision(
            result_id="result-retired",
            payload={
                "classification": "industry_report",
                "level": "L1",
                "org_scope": "all",
                "tags": {},
                "quality_review": {"disposition": "pass", "reason": "reviewed"},
                "review_reason": "reviewed",
            },
            request=request,
            idempotency_key="review-retired",
            user=user,
            session=SimpleNamespace(rollback=lambda: None),
        )

    assert exc_info.value.status_code == 409
    assert str(exc_info.value.detail) == "asset is manually retired"
