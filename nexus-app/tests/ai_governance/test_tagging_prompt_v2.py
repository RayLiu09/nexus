"""Static + shape guards for tagging prompt v2 (v1.3 §4.1)."""

from __future__ import annotations

import importlib.util
import pathlib

import pytest


def _load_migration_module():
    root = pathlib.Path(__file__).resolve().parents[2]
    path = root / "alembic" / "versions" / "20260710_0069_seed_tagging_prompt_v2.py"
    assert path.exists(), f"missing: {path}"
    spec = importlib.util.spec_from_file_location(
        "alembic.versions._m0069_test", path,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestPromptConstant:
    def test_v1_3_prompt_upgrades_registers_tagging(self) -> None:
        from nexus_app.ai_governance.default_prompts import V1_3_PROMPT_UPGRADES

        assert "tagging" in V1_3_PROMPT_UPGRADES
        cfg = V1_3_PROMPT_UPGRADES["tagging"]
        for required in (
            "template_name",
            "prompt_template",
            "output_schema_version",
            "litellm_model_alias",
            "temperature",
            "max_input_tokens",
            "redaction_policy",
            "change_summary",
        ):
            assert required in cfg, f"missing key: {required}"

    def test_prompt_body_mentions_all_seven_categories(self) -> None:
        """Guard against the prompt drifting out of sync with the
        7-category taxonomy — the LLM has to know exactly what bucket
        names to emit."""
        from nexus_app.ai_governance.default_prompts import V1_3_PROMPT_UPGRADES

        body = V1_3_PROMPT_UPGRADES["tagging"]["prompt_template"]
        for bucket in (
            "regions",
            "industries",
            "occupations",
            "majors",
            "abilities",
            "topics",
            "time_ranges",
        ):
            assert bucket in body, f"prompt missing bucket name: {bucket}"
        # Every tag must carry these three fields per §4.1
        for field in ("value", "confidence", "evidence_span"):
            assert field in body, f"prompt missing tag field: {field}"

    def test_output_schema_version_is_v1_3(self) -> None:
        from nexus_app.ai_governance.default_prompts import V1_3_PROMPT_UPGRADES

        assert V1_3_PROMPT_UPGRADES["tagging"]["output_schema_version"] == "v1.3"

    def test_topics_专项约束_present(self) -> None:
        """Guard: A4 二轮 topics 补丁必须包含准入判定 + 负例 + 上限。
        Without these the LLM regresses to dumping unrelated keywords into
        topics (measured precision 0.048 in first-round evaluation)."""
        from nexus_app.ai_governance.default_prompts import V1_3_PROMPT_UPGRADES

        body = V1_3_PROMPT_UPGRADES["tagging"]["prompt_template"]
        # 兜底桶定位
        assert "兜底桶" in body
        # 准入判定顺序（前 6 步各自命中即归其他桶）
        assert "准入判定" in body
        # 负例集合
        assert "负例" in body
        assert "学历层次" in body or "教育类型" in body
        # 上限
        assert "5 条" in body or "5条" in body

    def test_evidence_span_强约束_present(self) -> None:
        """Guard: A4 二轮 evidence_span 补丁必须要求原文连续字符串 + 禁止重述。
        First-round evaluation showed evidence_span in-text hit rate only
        79.2%; without this constraint frontend hover-to-source lookup
        and audit trace fail."""
        from nexus_app.ai_governance.default_prompts import V1_3_PROMPT_UPGRADES

        body = V1_3_PROMPT_UPGRADES["tagging"]["prompt_template"]
        # 关键约束词
        assert "连续出现的字符串" in body or "连续字符串" in body
        assert "复制粘贴" in body
        # 禁止行为
        for forbidden in ("重述", "总结"):
            assert forbidden in body, f"prompt missing forbidden keyword: {forbidden}"
        # 自检要求
        assert "自检" in body

    def test_change_summary_records_a4_round2_patches(self) -> None:
        from nexus_app.ai_governance.default_prompts import V1_3_PROMPT_UPGRADES

        summary = V1_3_PROMPT_UPGRADES["tagging"]["change_summary"]
        assert "topics 专项约束" in summary
        assert "evidence_span 强约束" in summary or "evidence_span" in summary
        assert "A4 二轮" in summary or "A4" in summary


class TestMigration0069Static:
    def test_revision_chain(self) -> None:
        m = _load_migration_module()
        assert m.revision == "20260710_0069"
        assert m.down_revision == "20260709_0068"
        assert m.branch_labels is None
        assert m.depends_on is None

    def test_seed_trace_id(self) -> None:
        m = _load_migration_module()
        assert m._SEED_TRACE_ID == "seed_0069_tagging"
        assert m._TASK_TYPE == "tagging"
        assert m._NEW_VERSION == 2

    def test_upgrade_downgrade_callable(self) -> None:
        m = _load_migration_module()
        assert callable(m.upgrade)
        assert callable(m.downgrade)

    def test_migration_reads_v1_3_prompt_upgrades(self) -> None:
        """Regression: if V1_3_PROMPT_UPGRADES ever drops the ``tagging``
        key, the migration would raise KeyError at apply time.  Fail
        fast in tests instead."""
        from nexus_app.ai_governance.default_prompts import V1_3_PROMPT_UPGRADES

        assert "tagging" in V1_3_PROMPT_UPGRADES
