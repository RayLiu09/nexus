from types import SimpleNamespace

from nexus_api.api.internal import governance_review
from nexus_api.dependencies import Pagination


def test_pending_governance_reviews_returns_page_slice_with_full_total(monkeypatch):
    results = [SimpleNamespace(id=f"review-{index}") for index in range(25)]
    monkeypatch.setattr(governance_review, "_latest_review_results", lambda _session: results)
    monkeypatch.setattr(
        governance_review,
        "_queue_item",
        lambda result: {"governance_result_id": result.id},
    )

    response = governance_review.list_pending_governance_reviews(
        request=SimpleNamespace(state=SimpleNamespace(trace_id="trace-pagination")),
        pagination=Pagination(page=2, page_size=20),
        session=object(),
    )

    assert response.meta.page == 2
    assert response.meta.page_size == 20
    assert response.meta.total == 25
    assert [item["governance_result_id"] for item in response.data] == [
        f"review-{index}" for index in range(20, 25)
    ]
