"""Plan or apply historical professional teaching-standard projections.

The command is dry-run by default and emits one bounded JSON report. Use
``--apply`` explicitly to write review-state library/course facts and invoke
the existing whole-standard derivation service.

Examples::

    uv run python scripts/backfill_teaching_standard_library.py --limit 20
    uv run python scripts/backfill_teaching_standard_library.py --apply --limit 5
    uv run python scripts/backfill_teaching_standard_library.py --apply --no-llm
    uv run python scripts/backfill_teaching_standard_library.py \
        --ref-id 31df3090-...
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from uuid import uuid4

_APP_ROOT = Path(__file__).resolve().parent.parent
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))

from nexus_app.ai_governance.services import _create_default_litellm_client
from nexus_app.config import get_settings
from nexus_app.database import get_session_local
from nexus_app.storage import get_object_storage
from nexus_app.teaching_standard_library.backfill import run_backfill


def _parse_date_bound(value: str, *, end: bool) -> datetime:
    try:
        if "T" in value:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        parsed_date = datetime.fromisoformat(value).date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"expected ISO date or datetime, got {value!r}"
        ) from exc
    bound = datetime.combine(parsed_date, time.min, tzinfo=timezone.utc)
    return bound + timedelta(days=1) if end else bound


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="Write changes; default is dry-run."
    )
    parser.add_argument(
        "--ref-id", help="Restrict processing to one normalized ref ID."
    )
    parser.add_argument(
        "--limit", type=int, help="Maximum generated document refs to inspect."
    )
    parser.add_argument(
        "--from-date",
        type=lambda value: _parse_date_bound(value, end=False),
        help="Inclusive normalized-ref creation date/datetime (ISO format).",
    )
    parser.add_argument(
        "--to-date",
        type=lambda value: _parse_date_bound(value, end=True),
        help="Inclusive date or exclusive datetime upper bound (ISO format).",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Restrict to refs whose latest course derivation failed.",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="With --apply, project source facts without course derivation.",
    )
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be positive")
    if (
        args.from_date is not None
        and args.to_date is not None
        and args.from_date >= args.to_date
    ):
        parser.error("--from-date must be earlier than --to-date")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    settings = get_settings()
    storage = get_object_storage(settings)
    llm_client = None
    if args.apply and not args.no_llm:
        try:
            llm_client = _create_default_litellm_client(settings)
        except (
            Exception
        ):  # noqa: BLE001 - derivation records client-unavailable failure
            llm_client = None

    with get_session_local()() as session:
        outcome = run_backfill(
            session,
            storage=storage,
            llm_client=llm_client,
            default_governance_model=settings.default_governance_model,
            apply_changes=args.apply,
            ref_id=args.ref_id,
            limit=args.limit,
            from_date=args.from_date,
            to_date=args.to_date,
            retry_failed=args.retry_failed,
            no_llm=args.no_llm,
            trace_id=str(uuid4()),
        )
        if not args.apply:
            session.rollback()

    print(json.dumps(outcome.to_json(), ensure_ascii=False, sort_keys=True))
    return 1 if outcome.failed_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
