"""Adapt active major-profile knowledge rules for institution introductions.

Revision ID: 20260820_0092
Revises: 20260820_0091
Create Date: 2026-08-20
"""
from collections.abc import Sequence
import json

import sqlalchemy as sa
from alembic import op

revision: str = "20260820_0092"
down_revision: str | None = "20260820_0091"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DESCRIPTION = "专业介绍/简介文档的来源绑定语义块。国家标准简介按职业面向、培养目标、能力、课程实训、证书、接续专业等章节组织；院校/官网简介按院校名称、区域、专业名称、职业定位/就业方向、主干课程/实践、证书、校企合作/产教融合等事实组织。"
_CRITERIA = [
    "国家标准格式：包含专业代码、专业名称、基本修业年限，并包含职业面向/培养目标/能力/课程实训等核心章节；证书、接续专业为可选补充",
    "院校/官网格式：包含院校名称、专业名称和区域标签或明确院校所在地；国家专业代码、修业年限、接续专业均可缺失",
    "院校/官网格式至少有一类可追溯专业事实：职业定位/就业方向、主干课程/课程体系/实践实训、职业证书、合作企业/校企合作/产教融合/实训基地",
    "所有语义块必须从 normalized_document 提取，并保留 block 级来源定位；不得依据常识补全学校、企业、课程或岗位",
]


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, rules_content FROM governance_rules_version WHERE status = 'active'")).fetchall()
    for row in rows:
        content = row.rules_content if isinstance(row.rules_content, dict) else json.loads(row.rules_content)
        for knowledge_type in content.get("knowledge_types", []):
            if not isinstance(knowledge_type, dict) or knowledge_type.get("code") != "major_profile_knowledge":
                continue
            knowledge_type["description"] = _DESCRIPTION
            knowledge_type["source_criteria"] = _CRITERIA
            config = knowledge_type.setdefault("chunking_config", {})
            sections = config.setdefault("include_sections", [])
            if "industry_partnerships" not in sections:
                sections.append("industry_partnerships")
        bind.execute(sa.text("UPDATE governance_rules_version SET rules_content = CAST(:content AS jsonb), updated_at = now() WHERE id = :id"), {"id": row.id, "content": json.dumps(content, ensure_ascii=False)})


def downgrade() -> None:
    # Forward-only: old criteria incorrectly reject institution profile assets.
    pass
