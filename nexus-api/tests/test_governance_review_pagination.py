from types import SimpleNamespace

from nexus_api.api.internal import governance_review
from nexus_api.dependencies import Pagination


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
