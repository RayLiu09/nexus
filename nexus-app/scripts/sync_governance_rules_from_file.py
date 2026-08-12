"""Create an audited active governance-rules version from the staged JSON file.

The database ``governance_rules_version`` row is the governance authority.
The repository JSON is a reviewed deployment mirror used by knowledge-type
consumers.  This utility compares the two and, only with ``--apply``, creates
a new immutable active DB version through ``GovernanceRulesService``.

Usage:
    uv run python scripts/sync_governance_rules_from_file.py
    uv run python scripts/sync_governance_rules_from_file.py --apply
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nexus_app.ai_governance.rules_service import GovernanceRulesService
from nexus_app.database import get_session_local

RULES_PATH = Path(__file__).resolve().parents[2] / "config" / "governance_rules_v2.json"
CHANGE_SUMMARY = (
    "Talent-training-plan RAG projection: replace generic structured_decompose "
    "with bounded talent_training_plan_decompose supplementary semantic chunks"
)


def _digest(value: dict) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="Create and activate a new DB rules version")
    args = parser.parse_args()
    staged = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    with get_session_local()() as session:
        active = GovernanceRulesService.get_active_or_raise(session)
        same = _digest(active.rules_content) == _digest(staged)
        print(json.dumps({
            "dry_run": not args.apply,
            "active_version": active.version,
            "active_version_id": active.id,
            "active_hash": _digest(active.rules_content),
            "staged_hash": _digest(staged),
            "same": same,
        }, ensure_ascii=False, indent=2))
        if same or not args.apply:
            return 0
        created = GovernanceRulesService.create_new_version(
            session,
            staged,
            change_summary=CHANGE_SUMMARY,
            user_id="system",
        )
        session.commit()
        print(json.dumps({
            "created_version": created.version,
            "created_version_id": created.id,
            "status": created.status.value,
        }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
