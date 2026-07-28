"""Contract tests for official governance-result tracking history."""
from __future__ import annotations

from fastapi.testclient import TestClient

from nexus_app import models
from nexus_app.enums import GovernanceResultStatus, UserRole

from test_asset_catalog_api import _seed_review_required_asset


def test_governance_traces_are_result_centric_and_include_human_review(app, session):
    seeded = _seed_review_required_asset(session)
    reviewer = models.UserAccount(
        username="trace-expert",
        display_name="治理专家",
        role=UserRole.BUSINESS_EXPERT,
    )
    final_result = models.GovernanceResult(
        normalized_ref_id=seeded["ref"].id,
        ai_run_id=seeded["run"].id,
        classification="industry_report",
        level="L1",
        tags=["report"],
        org_scope="all",
        index_admission=True,
        quality_summary={"quality_level": "pass", "quality_score": 92.0},
        decision_trail=[
            {"field_name": "classification", "adoption_status": "human_confirmed"},
            {"field_name": "quality", "adoption_status": "human_overridden"},
        ],
        status=GovernanceResultStatus.AVAILABLE,
    )
    session.add_all([reviewer, final_result])
    session.flush()
    session.add(models.GovernanceReviewDecision(
        normalized_ref_id=seeded["ref"].id,
        base_governance_result_id=seeded["result"].id,
        base_ai_run_id=seeded["run"].id,
        resulting_governance_result_id=final_result.id,
        decision_payload={},
        review_reason="专家确认并调整质量结论",
        feedback_labels=[],
        reviewer_id=reviewer.id,
        idempotency_key="trace-test-1",
    ))
    session.commit()

    with TestClient(app) as client:
        response = client.get("/internal/v1/governance-traces?page=1&pageSize=20")

    assert response.status_code == 200
    rows = response.json()["data"]
    final_row = next(item for item in rows if item["governance_result_id"] == final_result.id)
    assert final_row["asset_id"] == seeded["asset"].id
    assert final_row["asset_title"] == "Catalog Review Required Asset"
    assert final_row["governance_status"] == "available"
    assert final_row["decision_mode"] == "human_overridden"
    assert final_row["review_decision_id"] is not None
    assert final_row["reviewer_name"] == "治理专家"
    assert final_row["review_reason"] == "专家确认并调整质量结论"
    assert {item["governance_result_id"] for item in rows} >= {
        seeded["result"].id,
        final_result.id,
    }
