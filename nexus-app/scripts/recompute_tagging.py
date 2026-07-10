"""Narrow tagging-only recompute driver for v1.3 §16.4.

Runs :func:`nexus_app.governance.recompute.execute_tagging_recompute` against
every ``GovernanceResult`` whose ``rules_schema_version`` differs from the
currently-active ``GovernanceRulesVersion``.  Uses the production LiteLLM
wiring by default (via
:func:`nexus_app.ai_governance.tagging_recompute.default_tagging_llm_call`).

Only ``governance_result.tags`` and ``rules_schema_version`` /
``rules_version_id`` are mutated — classification, level, quality summary,
index admission, and version status are all preserved.  See
`docs/knowledge_retrieval_result_enhancement_v1.3.md §16.4` for the design
rationale.

Usage
-----
Dry-run (safe, no side effects, no LLM calls)::

    uv run python scripts/recompute_tagging.py --dry-run

Real run in dev mode (include AVAILABLE assets)::

    uv run python scripts/recompute_tagging.py --actor system

Prod-safe (skip AVAILABLE assets — matches the ``trigger_recompute``
default)::

    uv run python scripts/recompute_tagging.py --exclude-available --actor system

Options
-------
``--dry-run``           Only print the plan; no ``AIGovernanceRun`` /
                        ``governance_result`` writes; no LLM calls.
``--exclude-available`` Skip ``AVAILABLE``-status asset versions (prod
                        default).
``--actor ID``          Value stored in the audit trail
                        (``actor_id`` field).  Defaults to ``"system"``.
``--trace-id ID``       Override the auto-generated batch trace id.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nexus_app.ai_governance.prompt_registry import (  # noqa: E402
    get_governance_prompt_registry,
)
from nexus_app.ai_governance.rules_registry import (  # noqa: E402
    GovernanceRulesRegistry,
)
from nexus_app.ai_governance.services import AIGovernanceService  # noqa: E402
from nexus_app.ai_governance.tagging_recompute import (  # noqa: E402
    default_tagging_llm_call,
)
from nexus_app.database import get_session_local  # noqa: E402
from nexus_app.governance.recompute import (  # noqa: E402
    execute_tagging_recompute,
    plan_tagging_recompute,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Only print the plan.")
    parser.add_argument(
        "--exclude-available",
        action="store_true",
        help="Skip AVAILABLE-status asset versions (prod default).",
    )
    parser.add_argument("--actor", default="system", help="Audit actor id.")
    parser.add_argument("--trace-id", default=None, help="Override batch trace id.")
    args = parser.parse_args()

    include_available = not args.exclude_available

    session_factory = get_session_local()
    with session_factory() as session:
        rules_registry = GovernanceRulesRegistry()
        try:
            rules_registry.load(session)
        except Exception as exc:
            print(f"ERROR: failed to load governance rules: {exc}", file=sys.stderr)
            return 2

        current_schema_version = rules_registry.get_rules_content()["schema_version"]
        current_rules_version_id = rules_registry.get_rules_version_id()

        if args.dry_run:
            plan = plan_tagging_recompute(
                session,
                current_schema_version=current_schema_version,
                current_rules_version_id=current_rules_version_id,
                include_available=include_available,
            )
            print(json.dumps(plan, indent=2, ensure_ascii=False))
            return 0

        prompt_registry = get_governance_prompt_registry()
        if not prompt_registry.is_loaded():
            prompt_registry.load(session)
        ai_service = AIGovernanceService()
        tagging_call = default_tagging_llm_call(
            session,
            ai_service=ai_service,
            prompt_registry=prompt_registry,
            rules_registry=rules_registry,
        )

        summary = execute_tagging_recompute(
            session,
            current_schema_version=current_schema_version,
            current_rules_version_id=current_rules_version_id,
            include_available=include_available,
            tagging_llm_call=tagging_call,
            actor_id=args.actor,
            trace_id=args.trace_id,
        )
        session.commit()

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if summary["failed_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
