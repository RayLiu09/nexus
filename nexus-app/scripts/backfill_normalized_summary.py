"""Backfill summary + content_snippet on a NormalizedAssetRef, then rerun governance.

Why this script exists
----------------------
Historical refs created before NormalizeService started writing
``metadata_summary.summary`` and ``metadata_summary.content_snippet`` are stuck
in review_required with a spurious "Missing content" blocking reason, even
though the normalized payload object on MinIO contains a full body_markdown.

This script:
  1. Loads the NormalizedAssetRef row.
  2. Reads the normalized payload from object storage.
  3. Runs NormalizeService.normalize() over the payload so the new
     ``_inject_summary_and_snippet`` step regenerates summary (LLM) +
     content_snippet (deterministic).
  4. Writes the regenerated metadata_summary back to the ref row.
  5. Optionally re-runs AI governance + decision + version state machine so the
     workbench surfaces the corrected state immediately.

Usage
-----
    uv run python scripts/backfill_normalized_summary.py \
        --ref-id 31df3090-8745-4cd9-87ce-8c68c81784bd
    # add --skip-governance-rerun to only refresh metadata_summary

The script is idempotent: re-running it after success is a no-op for the
metadata refresh path; the governance-rerun path always creates a fresh
AIGovernanceRun and GovernanceResult, matching workbench "rerun" semantics.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nexus_app import models
from nexus_app.database import get_session_local
from nexus_app.enums import AssetVersionStatus
from nexus_app.normalize.service import NormalizeService
from nexus_app.storage import get_object_storage
from nexus_app.worker.runner import _build_normalize_service


def _load_payload(storage, object_uri: str) -> dict:
    key = object_uri.split("/", 3)[-1] if object_uri.startswith("s3://") else object_uri
    raw_bytes = storage.get_bytes(key)
    return json.loads(raw_bytes.decode("utf-8"))


def _regenerate_metadata(
    service: NormalizeService,
    payload: dict,
    *,
    source_type: str,
    content_type: str,
) -> dict:
    result = service.normalize(
        payload,
        source_type=source_type,
        content_type=content_type,
    )
    return dict(result.payload.get("metadata") or {})


def backfill(ref_id: str, *, skip_governance_rerun: bool) -> int:
    from nexus_app.config import get_settings
    from nexus_app.normalize.config_loader import get_normalize_schemas_registry

    SessionLocal = get_session_local()
    storage = get_object_storage()
    # Standalone scripts don't go through the app lifespan, so the singleton
    # registries are still empty here. Load them lazily before NormalizeService
    # / governance services touch them.
    schemas_registry = get_normalize_schemas_registry()
    if schemas_registry._config is None:  # noqa: SLF001 standalone bootstrap
        schemas_registry.load()
    # Build NormalizeService just like the worker does (LiteLLM optional).
    normalize_service = _build_normalize_service(get_settings())

    with SessionLocal() as session:
        ref = session.get(models.NormalizedAssetRef, ref_id)
        if ref is None:
            print(f"ERROR: NormalizedAssetRef '{ref_id}' not found")
            return 1
        if not ref.object_uri or ref.object_uri == "pending":
            print(f"ERROR: ref '{ref_id}' has no object_uri")
            return 1

        version = session.get(models.AssetVersion, ref.version_id)
        if version is None:
            print(f"ERROR: AssetVersion '{ref.version_id}' not found for ref {ref_id}")
            return 1

        print(f"Loading normalized payload from {ref.object_uri}")
        payload = _load_payload(storage, ref.object_uri)

        source_type = ref.source_type or "file_upload"
        # NormalizeService keys contracts by raw MIME for documents and by
        # actual record content-type for records; when we no longer have the
        # raw MIME on hand we fall back to a generic value — that just lands
        # on the fallback_contract, which still triggers our
        # summary/snippet injection.
        content_type = (ref.content_type or "document")
        raw_mime = (ref.metadata_summary or {}).get("mime_type")
        if raw_mime:
            content_type = raw_mime

        print(f"Regenerating summary + content_snippet (source_type={source_type}, content_type={content_type})")
        new_metadata = _regenerate_metadata(
            normalize_service,
            payload,
            source_type=source_type,
            content_type=content_type,
        )

        merged = dict(ref.metadata_summary or {})
        for key in ("summary", "content_snippet"):
            value = new_metadata.get(key)
            if value:
                merged[key] = value
        ref.metadata_summary = merged
        session.flush()
        snippet_len = len(merged.get("content_snippet", ""))
        summary_len = len(merged.get("summary", ""))
        print(f"  metadata_summary refreshed: snippet={snippet_len} chars, summary={summary_len} chars")

        if skip_governance_rerun:
            session.commit()
            print("Skipping governance rerun (--skip-governance-rerun).")
            return 0

        print("Re-running AI governance + decision + version state machine")
        rc = _rerun_governance(session, ref, version)
        if rc != 0:
            session.rollback()
            return rc
        session.commit()
        print("Done.")
        return 0


def _rerun_governance(
    session,
    ref: models.NormalizedAssetRef,
    version: models.AssetVersion,
) -> int:
    """Mirror pipeline/stages.run_governance_decision but standalone."""
    from nexus_app.ai_governance.prompt_registry import (
        GovernancePromptNotFoundError,
        get_governance_prompt_registry,
    )
    from nexus_app.ai_governance.rules_registry import GovernanceRulesRegistry
    from nexus_app.ai_governance.services import AIGovernanceService
    from nexus_app.governance.decision_service import GovernanceDecisionService
    from nexus_app.metadata.version_state import VersionStateManager

    rules_registry = GovernanceRulesRegistry()
    try:
        rules_registry.load(session)
    except Exception as exc:
        print(f"ERROR: governance_rules not available: {exc}")
        return 2

    prompt_registry = get_governance_prompt_registry()
    if not prompt_registry.is_loaded():
        try:
            prompt_registry.load(session)
        except Exception as exc:
            print(f"ERROR: prompt registry not available: {exc}")
            return 2

    try:
        prompt_registry.get_prompt("classification")
    except GovernancePromptNotFoundError:
        print("ERROR: no active governance prompt templates")
        return 2

    ai_svc = AIGovernanceService()
    ai_run = ai_svc.run_governance_multi(
        session,
        normalized_ref_id=ref.id,
        prompt_registry=prompt_registry,
        rules_registry=rules_registry,
    )
    print(f"  AIGovernanceRun: {ai_run.id} (validation={ai_run.validation_status.value})")
    if ai_run.ai_output is None:
        print(f"  AI run produced no output (error={ai_run.validation_error})")
        return 3

    decision_svc = GovernanceDecisionService(rules_registry)
    result = decision_svc.execute_governance(session, ai_run)
    print(f"  GovernanceResult: {result.id} (status={result.status.value})")
    ai_svc.write_knowledge_emissions(session, ai_run, rules_registry)

    state_mgr = VersionStateManager()
    target_status = state_mgr.determine_version_status(session, result)
    if target_status == AssetVersionStatus.AVAILABLE:
        state_mgr.transition_to_available(session, version, result)
    else:
        state_mgr.transition_to_review_required(session, version, result)
    print(f"  AssetVersion {version.id} → {version.version_status.value}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ref-id", required=True, help="NormalizedAssetRef id to backfill")
    parser.add_argument(
        "--skip-governance-rerun",
        action="store_true",
        help="Only refresh metadata_summary; do not re-run AI governance.",
    )
    args = parser.parse_args()
    return backfill(args.ref_id, skip_governance_rerun=args.skip_governance_rerun)


if __name__ == "__main__":
    raise SystemExit(main())
