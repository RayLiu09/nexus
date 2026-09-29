from datetime import datetime, timezone

from nexus_app.data_sync.plans import next_run_time


def test_monthly_schedule_clamps_to_short_month():
    start = datetime(2025, 1, 31, 9, 30, tzinfo=timezone.utc)
    assert next_run_time(start, "1_month") == datetime(2025, 2, 28, 9, 30, tzinfo=timezone.utc)
    assert next_run_time(start, "1_year") == datetime(2026, 1, 31, 9, 30, tzinfo=timezone.utc)
