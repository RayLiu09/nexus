"""Tests for DataSource L1/L2 default-level enforcement."""
from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from nexus_app import models, services
from nexus_app.enums import AuditEventType, DataSourceType
from nexus_app.schemas import DataSourceCreate


def _audit_events(session, target_type: str):
    return list(
        session.scalars(
            select(models.AuditLog)
            .where(models.AuditLog.target_type == target_type)
            .order_by(models.AuditLog.created_at.desc())
        )
    )


def _payload(level=None, evidence=None, code="ds-test-001"):
    hints: dict = {}
    if level is not None:
        hints["level"] = level
    if evidence is not None:
        hints["approval_evidence"] = evidence
    return DataSourceCreate(
        code=code,
        name="Test Source",
        source_type=DataSourceType.FILE_UPLOAD,
        default_governance_hints=hints,
    )


class TestDataSourceLevelPolicy:
    def test_no_level_allowed(self):
        payload = _payload()
        assert payload.default_governance_hints == {}

    def test_l1_allowed(self):
        payload = _payload(level="L1")
        assert payload.default_governance_hints["level"] == "L1"

    def test_l2_allowed(self):
        payload = _payload(level="L2")
        assert payload.default_governance_hints["level"] == "L2"

    def test_l3_without_evidence_rejected(self):
        with pytest.raises(ValidationError, match="approval_evidence"):
            _payload(level="L3")

    def test_l4_without_evidence_rejected(self):
        with pytest.raises(ValidationError, match="approval_evidence"):
            _payload(level="L4")

    def test_l3_with_evidence_allowed(self):
        payload = _payload(
            level="L3",
            evidence={"approver": "alice", "approved_at": "2026-05-29", "reason": "compliance"},
        )
        assert payload.default_governance_hints["level"] == "L3"
        assert payload.default_governance_hints["approval_evidence"]["approver"] == "alice"

    def test_invalid_level_code_rejected(self):
        with pytest.raises(ValidationError):
            _payload(level="L5")


class TestDataSourceAudit:
    def test_l1_source_audit_no_elevation(self, session):
        services.create_data_source(session, _payload(level="L1", code="ds-l1"))
        events = _audit_events(session, "data_source")
        created = [e for e in events if e.event_type == AuditEventType.DATA_SOURCE_CREATED]
        assert created
        assert "level_elevated" not in (created[0].summary or {})

    def test_l3_source_audit_with_elevation(self, session):
        services.create_data_source(
            session,
            _payload(
                level="L3",
                evidence={"approver": "bob", "approved_at": "2026-05-29"},
                code="ds-l3",
            ),
        )
        events = _audit_events(session, "data_source")
        created = [e for e in events if e.event_type == AuditEventType.DATA_SOURCE_CREATED]
        assert created
        summary = created[0].summary
        assert summary["level_elevated"] is True
        assert summary["approval_evidence"]["approver"] == "bob"
