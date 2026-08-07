"""Cron helpers for CrawlerPlan scheduling.

Kept independent of `crawler.service` to avoid a circular import: the
service module owns `CrawlerPlanError` and imports these helpers, so
these helpers raise their own `InvalidCronError` and let the service
layer decide how to surface it.
"""
from __future__ import annotations

from datetime import datetime, timezone

from croniter import CroniterBadCronError, croniter


class InvalidCronError(ValueError):
    """Raised when a cron expression is missing or malformed."""


def validate_cron(cron_expr: str | None) -> None:
    if not cron_expr or not cron_expr.strip():
        raise InvalidCronError("schedule_cron must not be blank")
    if not croniter.is_valid(cron_expr):
        raise InvalidCronError(f"invalid cron expression: {cron_expr!r}")


def compute_next_run(cron_expr: str, base: datetime | None = None) -> datetime:
    """Return the next fire time strictly after `base` (default: now, UTC).

    Missed ticks are skipped: callers advancing after a fire pass `base=now`,
    which lets croniter pick the next tick relative to the wall clock rather
    than replaying every interval since the previous fire.
    """
    validate_cron(cron_expr)
    reference = base or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    try:
        return croniter(cron_expr, reference).get_next(datetime)
    except CroniterBadCronError as exc:
        raise InvalidCronError(f"invalid cron expression: {cron_expr!r}") from exc
