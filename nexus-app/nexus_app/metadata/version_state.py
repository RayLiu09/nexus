"""VersionStateManager — determines and transitions asset version status.

Admission criteria for `available`:
  1. governance_result exists with status=available
  2. quality_summary.quality_level == "pass"
  3. All decision_trail entries have adoption_status == "auto_adopted"
  4. index_admission == True
  5. No other available version for same asset (unique-available constraint)
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_app import models
from nexus_app.audit import write_audit
from nexus_app.enums import AssetVersionStatus, AuditEventType, GovernanceResultStatus

logger = logging.getLogger(__name__)


class StateTransitionError(Exception):
    pass


class VersionStateManager:
    """Manages asset version status transitions based on governance results."""

    def determine_version_status(
        self,
        session: Session,
        governance_result: models.GovernanceResult,
    ) -> AssetVersionStatus:
        """Determine target status from governance_result fields."""
        if governance_result.status == GovernanceResultStatus.AVAILABLE:
            return AssetVersionStatus.AVAILABLE
        return AssetVersionStatus.REVIEW_REQUIRED

    def transition_to_available(
        self,
        session: Session,
        version: models.DocumentVersion,
        governance_result: models.GovernanceResult,
        *,
        user_id: str | None = None,
    ) -> models.DocumentVersion:
        """Transition version to available, enforcing unique-available."""
        if not self._check_admission_criteria(governance_result):
            raise StateTransitionError(
                f"Admission criteria not met for version {version.id}"
            )

        self._archive_old_available(session, version.asset_id, exclude_version_id=version.id)

        version.version_status = AssetVersionStatus.AVAILABLE
        session.flush()

        trace_id = str(uuid.uuid4())
        write_audit(
            session,
            AuditEventType.VERSION_STATUS_CHANGED,
            target_type="document_version",
            target_id=version.id,
            trace_id=trace_id,
            summary={
                "asset_id": version.asset_id,
                "new_status": "available",
                "governance_result_id": governance_result.id,
            },
            actor_id=user_id,
        )
        return version

    def transition_to_review_required(
        self,
        session: Session,
        version: models.DocumentVersion,
        governance_result: models.GovernanceResult,
        *,
        user_id: str | None = None,
    ) -> models.DocumentVersion:
        """Transition version to review_required."""
        version.version_status = AssetVersionStatus.REVIEW_REQUIRED
        session.flush()

        trace_id = str(uuid.uuid4())
        write_audit(
            session,
            AuditEventType.VERSION_STATUS_CHANGED,
            target_type="document_version",
            target_id=version.id,
            trace_id=trace_id,
            summary={
                "asset_id": version.asset_id,
                "new_status": "review_required",
                "governance_result_id": governance_result.id,
                "review_reasons": self._extract_review_reasons(governance_result),
            },
            actor_id=user_id,
        )
        return version

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _check_admission_criteria(result: models.GovernanceResult) -> bool:
        if result.status != GovernanceResultStatus.AVAILABLE:
            return False
        if not result.index_admission:
            return False
        qs = result.quality_summary or {}
        if qs.get("quality_level") != "pass":
            return False
        for entry in (result.decision_trail or []):
            if entry.get("adoption_status") != "auto_adopted":
                return False
        return True

    def _archive_old_available(
        self, session: Session, asset_id: str, *, exclude_version_id: str
    ) -> None:
        old_available = session.scalars(
            select(models.DocumentVersion).where(
                models.DocumentVersion.asset_id == asset_id,
                models.DocumentVersion.version_status == AssetVersionStatus.AVAILABLE,
                models.DocumentVersion.id != exclude_version_id,
            )
        ).all()
        for old_v in old_available:
            old_v.version_status = AssetVersionStatus.ARCHIVED
            write_audit(
                session,
                AuditEventType.ASSET_VERSION_ARCHIVED,
                target_type="document_version",
                target_id=old_v.id,
                trace_id=str(uuid.uuid4()),
                summary={
                    "asset_id": asset_id,
                    "reason": "superseded_by_new_available",
                },
            )

    @staticmethod
    def _extract_review_reasons(result: models.GovernanceResult) -> list[str]:
        reasons: list[str] = []
        for entry in (result.decision_trail or []):
            if entry.get("review_reason"):
                reasons.append(entry["review_reason"])
        return reasons
