"""Add generic industry regulations/standards as an audited rules version.

No historical result/content is rewritten. Data repair is a separate reviewed
normalized-document scan, using scripts/classify_industry_regulation_standards.py.
"""
from alembic import op
from sqlalchemy.orm import Session
from uuid import uuid4

from nexus_app.ai_governance.regulation_reclassification import activate_rules

revision = "20261102_0130"
down_revision = "20261030_0129"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Bind to Alembic's transaction; only flush, never commit it here.
    with Session(bind=op.get_bind()) as session:
        if session.bind is not None:
            from sqlalchemy import select
            from nexus_app import models
            if session.scalar(select(models.GovernanceRulesVersion.id).where(
                    models.GovernanceRulesVersion.status == "active")) is not None:
                activate_rules(session, str(uuid4()))
                session.flush()


def downgrade() -> None:
    # Retain classification definitions referenced by immutable historical results.
    pass
