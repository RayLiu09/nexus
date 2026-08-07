"""Cron helpers for CrawlerPlan scheduling.

Kept independent of `crawler.service` to avoid a circular import: the
service module owns `CrawlerPlanError` and imports these helpers, so
these helpers raise their own `InvalidCronError` and let the service
layer decide how to surface it.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import CroniterBadCronError, croniter


class InvalidCronError(ValueError):
    """Raised when a cron expression is missing or malformed."""


def validate_cron(cron_expr: str | None) -> None:
    if not cron_expr or not cron_expr.strip():
        raise InvalidCronError("schedule_cron must not be blank")
    if not croniter.is_valid(cron_expr):
        raise InvalidCronError(f"invalid cron expression: {cron_expr!r}")


def compute_next_run(
    cron_expr: str,
    base: datetime | None = None,
    *,
    tz: str = "UTC",
) -> datetime:
    """Return the next fire time strictly after `base`.

    `tz` (IANA zone name) is the wall-clock timezone in which the cron
    expression is interpreted — for example, `"Asia/Shanghai"` makes
    `0 16 * * *` mean "16:00 Beijing time". The returned datetime is
    always UTC so callers (DB / scheduler comparisons) don't need to
    reason about zones.

    Missed ticks are skipped: callers advancing after a fire pass
    `base=now`, which lets croniter pick the next tick relative to the
    wall clock rather than replaying every interval since the previous
    fire.
    """
    validate_cron(cron_expr)
    try:
        zone = ZoneInfo(tz)
    except ZoneInfoNotFoundError as exc:
        raise InvalidCronError(f"unknown timezone: {tz!r}") from exc
    reference = base or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    reference = reference.astimezone(zone)
    try:
        nxt = croniter(cron_expr, reference).get_next(datetime)
    except CroniterBadCronError as exc:
        raise InvalidCronError(f"invalid cron expression: {cron_expr!r}") from exc
    if nxt.tzinfo is None:
        nxt = nxt.replace(tzinfo=zone)
    return nxt.astimezone(timezone.utc)
