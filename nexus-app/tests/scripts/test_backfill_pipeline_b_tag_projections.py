"""Pipeline B tag-index backfill is intentionally retired."""

from scripts.backfill_pipeline_b_tag_projections import run_backfill


def test_retired_backfill_performs_no_projection(session) -> None:
    outcomes = run_backfill(
        session=session,
        domains=["job_demand", "major_distribution", "ability_analysis"],
        dataset_ids=None,
        apply=True,
    )

    assert set(outcomes) == {"job_demand", "major_distribution", "ability_analysis"}
    assert all(outcome.total_rows_persisted == 0 for outcome in outcomes.values())
