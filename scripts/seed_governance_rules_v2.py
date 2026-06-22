#!/usr/bin/env python3
"""Seed governance_rules_version with the proposal in config/governance_rules_v2.json.

Workflow (per docs/document_normalize_defects.md §12 — the rules-v2 review gate):

  1. A proposal is built in ``config/governance_rules_v2.json`` (this file
     contains the new schema_version 2.1 content: 11 v3.0 classifications
     with primary_knowledge_type + co_emission_rules, 16 knowledge_types
     including 2 added for industry / structured-record content).
  2. A human reviewer reads the JSON, validates the classification ↔ KT
     mapping, the new KT entries, and the quality_scoring thresholds.
  3. After approval, run this script ONCE:
         python scripts/seed_governance_rules_v2.py [--dry-run]
     It will:
       - read the JSON, compute SHA-256 of the canonical content,
       - find the current active GovernanceRulesVersion (currently v1),
       - mark it ARCHIVED,
       - insert a new row as version=N+1, status=ACTIVE,
       - write a GOVERNANCE_RULES_VERSION_CREATED audit event,
       - reload the in-process registry caches.

The script is idempotent on content_hash collision: if the JSON content
matches an existing active version exactly, the script skips with a
clear "already active" message rather than producing duplicate rows.

The pipeline parts that consume these rules will be wired up in the
follow-up index-fix work (knowledge_type_inference, run_index_submit,
kb_registry); this script does NOT touch any pipeline code.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from nexus_app import models
from nexus_app.audit import write_audit
from nexus_app.database import get_session_local
from nexus_app.enums import AuditEventType, GovernanceRulesVersionStatus

logger = logging.getLogger("seed_governance_rules_v2")
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

REPO_ROOT = Path(__file__).resolve().parents[1]
V2_PATH = REPO_ROOT / "config" / "governance_rules_v2.json"


def canonical_hash(content: dict) -> str:
    """Stable SHA-256 of the canonical JSON serialisation."""
    return hashlib.sha256(
        json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def main(dry_run: bool = False) -> int:
    if not V2_PATH.exists():
        logger.error("proposal file missing: %s", V2_PATH)
        return 2
    content = json.loads(V2_PATH.read_text(encoding="utf-8"))
    schema_version = content.get("schema_version", "2.1")
    content_hash = canonical_hash(content)
    logger.info(
        "proposal: schema_version=%s classifications=%d knowledge_types=%d hash=%s",
        schema_version,
        len(content.get("classifications") or []),
        len(content.get("knowledge_types") or []),
        content_hash[:16] + "…",
    )

    Session = get_session_local()
    session = Session()
    try:
        active = session.scalars(
            select(models.GovernanceRulesVersion)
            .where(models.GovernanceRulesVersion.status == GovernanceRulesVersionStatus.ACTIVE)
            .order_by(models.GovernanceRulesVersion.version.desc())
        ).first()
        next_version = (active.version + 1) if active else 1

        if active is not None:
            existing_hash = canonical_hash(active.rules_content or {})
            if existing_hash == content_hash:
                logger.info(
                    "active v%d already matches proposal content (hash=%s); nothing to do",
                    active.version, existing_hash[:16] + "…",
                )
                return 0
            logger.info(
                "current active: v%d (hash=%s) — will archive",
                active.version, existing_hash[:16] + "…",
            )

        if dry_run:
            logger.info(
                "[dry-run] would insert v%d active, archive v%s",
                next_version, active.version if active else "n/a",
            )
            return 0

        # 1. Archive current active.
        if active is not None:
            active.status = GovernanceRulesVersionStatus.ARCHIVED
            write_audit(
                session,
                AuditEventType.GOVERNANCE_RULES_VERSION_ARCHIVED,
                target_type="governance_rules_version",
                target_id=active.id,
                trace_id="seed_v2_rules",
                summary={
                    "version": active.version,
                    "previous_hash": existing_hash,
                    "reason": "superseded_by_v2_proposal",
                },
                actor_id="seed_script",
            )

        # 2. Insert new active.
        new_row = models.GovernanceRulesVersion(
            version=next_version,
            status=GovernanceRulesVersionStatus.ACTIVE,
            rules_content=content,
            schema_version=schema_version,
            change_summary=(
                "v2.1 proposal: bumped schema; added knowledge_types section "
                "(14 migrated + 2 new: industry_research_kb, "
                "structured_record_table); each classification now carries "
                "primary_knowledge_type + co_emission_rules; tags removed as "
                "they are derived per-classification via tag_dimensions."
            ),
            created_by="seed_script",
            trace_id="seed_v2_rules",
        )
        session.add(new_row)
        session.flush()
        write_audit(
            session,
            AuditEventType.GOVERNANCE_RULES_VERSION_CREATED,
            target_type="governance_rules_version",
            target_id=new_row.id,
            trace_id="seed_v2_rules",
            summary={
                "version": next_version,
                "schema_version": schema_version,
                "content_hash": content_hash,
                "classifications_count": len(content.get("classifications") or []),
                "knowledge_types_count": len(content.get("knowledge_types") or []),
            },
            actor_id="seed_script",
        )
        session.commit()
        logger.info(
            "wrote v%d active (content_hash=%s, %s)",
            next_version, content_hash[:16] + "…", new_row.id,
        )

        # 3. Reload in-process caches if the application is running on the
        # same process (no-op when called as a CLI from a separate process).
        try:
            from nexus_app.ai_governance.rules_registry import get_governance_rules_registry
            from nexus_app.knowledge.config_loader import reload_config

            registry = get_governance_rules_registry()
            registry.load(session)
            reload_config()
            logger.info("in-process rules + KT caches reloaded")
        except Exception as exc:  # noqa: BLE001
            logger.warning("cache reload skipped: %s", exc)
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true",
                        help="show what would change without writing to DB")
    args = parser.parse_args()
    sys.exit(main(dry_run=args.dry_run))
