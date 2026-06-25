"""Deterministic Markdown templates for the body_markdown fallback path.

When the LLM is unavailable, fails, or produces output that violates the
skeleton, the dispatcher falls back to one of these code-side renderers.
The templates MUST satisfy the corresponding skeleton from
`config/ai_analysis_rules.json::occupation.*.body_markdown_render.rules` so
the validator passes on the fallback path too — otherwise the fallback
would itself fall back and the loop would terminate with no markdown.

Both renderers:
- Never raise (incomplete `record_body` simply omits the missing sections)
- Respect the inline-count caps so big datasets don't produce 5MB markdown
- Use raw values from `record_body`; no translation / normalisation
- Emit blockquotes for long free-text fields (`job_description`,
  `task_description`) per skeleton hints

These renderers are paired with the validator — bug fixes here that change
heading hierarchy MUST keep the skeleton patterns satisfied.
"""
from __future__ import annotations

from typing import Any


# Hard caps that match the B0 seed values; exceeding either causes the
# overflow notice to be appended and the omitted-count returned to the
# caller for audit.
_MAX_RECORDS_INLINE_DEFAULT = 50
_MAX_ABILITIES_PER_WC_INLINE_DEFAULT = 30
_LONG_TEXT_TRUNCATE_DEFAULT = 240
_OVERFLOW_NOTICE_JOB_DEMAND = (
    "_其余 {n} 条记录已省略，详见 record_body JSON。_"
)
_OVERFLOW_NOTICE_ABILITY = (
    "_其余 {n} 条能力条目已省略，详见 record_body JSON。_"
)


def render_job_demand(
    record_body: dict[str, Any], skeleton: dict[str, Any] | None = None
) -> tuple[str, int, int]:
    """Render `{dataset, records}` payload → Markdown.

    Returns `(markdown, records_inline, records_omitted)` so the caller can
    populate `body_markdown_meta.truncation` without re-counting.
    """
    skel = skeleton or {}
    max_inline = int(skel.get("max_records_inline", _MAX_RECORDS_INLINE_DEFAULT))
    truncate_chars = int(skel.get("long_text_truncate_chars", _LONG_TEXT_TRUNCATE_DEFAULT))
    overflow_template = str(
        skel.get("overflow_notice_template", _OVERFLOW_NOTICE_JOB_DEMAND)
    )
    long_text_fields = skel.get("long_text_blockquote_fields") or ["job_description"]

    dataset = record_body.get("dataset") or {}
    records = record_body.get("records") or []
    inline = records[:max_inline]
    omitted = max(0, len(records) - len(inline))

    lines: list[str] = []
    lines.append("# 岗位需求数据集")
    lines.append("")
    lines.append("## 数据集概要")
    lines.append("")
    lines.append(f"- 专业：{_fmt(dataset.get('major_name'))}")
    lines.append(f"- 默认行业：{_fmt(dataset.get('industry_name'))}")
    lines.append(f"- 来源渠道：{_fmt(dataset.get('source_channel'))}")
    lines.append(f"- 记录总数：{dataset.get('record_count', len(records))}")
    lines.append(f"- 有效记录数：{max(0, dataset.get('record_count', len(records)) - int(dataset.get('invalid_count') or 0))}")
    lines.append(f"- 无效记录数：{dataset.get('invalid_count', 0)}")
    lines.append(f"- 重复记录数：{dataset.get('duplicate_count', 0)}")
    lines.append("")
    lines.append("## 岗位记录")
    lines.append("")

    for idx, rec in enumerate(inline, start=1):
        title = _fmt(rec.get("job_title"))
        company = _fmt(rec.get("company_name"))
        # Skeleton's per_record_h2_pattern is "^## 记录 \\d+：.+$".
        lines.append(f"## 记录 {idx}：{title}")
        lines.append("")
        lines.append(f"- 公司：{company}")
        lines.append(f"- 城市：{_fmt(rec.get('city'))}")
        lines.append(f"- 薪资：{_fmt(rec.get('salary_text'))}")
        lines.append(f"- 经验：{_fmt(rec.get('experience_requirement'))}")
        lines.append(f"- 学历：{_fmt(rec.get('education_requirement'))}")
        lines.append(f"- 企业规模：{_fmt(rec.get('enterprise_size'))}")
        lines.append(f"- 行业：{_fmt(rec.get('industry_name'))}")
        skill = rec.get("job_skill_text")
        if skill:
            lines.append(f"- 技能：{_truncate(skill, truncate_chars)}")
        for field in long_text_fields:
            value = rec.get(field)
            if not value:
                continue
            lines.append("")
            for ln in _truncate(str(value), truncate_chars).splitlines():
                lines.append(f"> {ln}" if ln else ">")
        lines.append("")

    if omitted:
        lines.append(overflow_template.format(n=omitted))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n", len(inline), omitted


def render_ability_analysis(
    record_body: dict[str, Any], skeleton: dict[str, Any] | None = None
) -> tuple[str, int, int]:
    """Render `{analysis, tasks}` payload → Markdown.

    Returns `(markdown, abilities_inline, abilities_omitted)` — counts are
    aggregated across all tasks, not per-task.
    """
    skel = skeleton or {}
    max_inline = int(skel.get(
        "max_abilities_per_work_content_inline",
        _MAX_ABILITIES_PER_WC_INLINE_DEFAULT,
    ))
    overflow_template = str(
        skel.get("overflow_notice_template", _OVERFLOW_NOTICE_ABILITY)
    )

    analysis = record_body.get("analysis") or {}
    tasks = record_body.get("tasks") or []
    major = _fmt(analysis.get("major_name"))
    task_count = int(analysis.get("task_count", len(tasks)))
    work_count = int(analysis.get("work_content_count", 0))
    ability_count = int(analysis.get("ability_item_count", 0))

    lines: list[str] = []
    # required_h1_pattern: ^# .+ · 职业能力分析（PGSD）$
    lines.append(f"# {major} · 职业能力分析（PGSD）")
    lines.append("")
    # required_overview_line_regex: ^总览：\d+ 任务 · \d+ 工作内容 · \d+ 能力条目$
    lines.append(f"总览：{task_count} 任务 · {work_count} 工作内容 · {ability_count} 能力条目")
    lines.append("")
    lines.append("## 分析概要")
    lines.append("")
    lines.append(f"- 分析模型：{_fmt(analysis.get('analysis_model'))}")
    lines.append(f"- 专业：{major}")
    lines.append(f"- 任务总数：{task_count}")
    lines.append(f"- 工作内容总数：{work_count}")
    lines.append(f"- 能力条目总数：{ability_count}")
    lines.append("")
    lines.append("## 工作任务与能力")
    lines.append("")

    inline_total = 0
    omitted_total = 0
    for task in tasks:
        if not isinstance(task, dict):
            continue
        task_code = _fmt(task.get("task_code"))
        task_name = _fmt(task.get("task_name"))
        # per_task_h2_pattern: ^## 任务 \d+：.+$
        lines.append(f"## 任务 {task_code}：{task_name}")
        lines.append("")
        # per_task_required_blocks: task_description_blockquote
        desc = task.get("task_description") or ""
        for ln in str(desc).splitlines():
            lines.append(f"> {ln}" if ln else ">")
        lines.append("")
        # per_task_required_blocks: work_contents_h3 + ability_item_bullet
        for wc in task.get("work_contents") or []:
            if not isinstance(wc, dict):
                continue
            wc_code = _fmt(wc.get("content_code"))
            wc_name = _fmt(wc.get("content_name"))
            # work_content_h3_pattern: ^### 工作内容 \d+\.\d+：.+$
            lines.append(f"### 工作内容 {wc_code}：{wc_name}")
            lines.append("")
            abilities = wc.get("abilities") or []
            shown = abilities[:max_inline]
            inline_total += len(shown)
            omitted = max(0, len(abilities) - len(shown))
            omitted_total += omitted
            for ab in shown:
                if not isinstance(ab, dict):
                    continue
                code = _fmt(ab.get("ability_code"))
                content = _fmt(ab.get("ability_content"))
                # ability_item_bullet_pattern: ^- \*\*[PGSD]-\d+(?:\.\d+)+\*\* .+$
                lines.append(f"- **{code}** {content}")
            if omitted:
                lines.append(overflow_template.format(n=omitted))
            lines.append("")
        # per_task_required_blocks: general_abilities_h3 + categories
        # general_abilities_categories: 通用能力（G） / 社会能力（S） / 发展能力（D）
        general = task.get("general_abilities") or {}
        if any(general.get(k) for k in ("G", "S", "D")):
            lines.append("### 通用 / 社会 / 发展能力")
            lines.append("")
            for cat_code, cat_label in (
                ("G", "通用能力（G）"),
                ("S", "社会能力（S）"),
                ("D", "发展能力（D）"),
            ):
                items = general.get(cat_code) or []
                lines.append(f"#### {cat_label}")
                lines.append("")
                if not items:
                    lines.append("- _（无）_")
                else:
                    shown = items[:max_inline]
                    inline_total += len(shown)
                    omitted = max(0, len(items) - len(shown))
                    omitted_total += omitted
                    for ab in shown:
                        if not isinstance(ab, dict):
                            continue
                        code = _fmt(ab.get("ability_code"))
                        content = _fmt(ab.get("ability_content"))
                        lines.append(f"- **{code}** {content}")
                    if omitted:
                        lines.append(overflow_template.format(n=omitted))
                lines.append("")

    return "\n".join(lines).rstrip() + "\n", inline_total, omitted_total


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fmt(value: Any) -> str:
    """Cell → display string. None / empty → `（未提供）`."""
    if value is None:
        return "（未提供）"
    text = str(value).strip()
    return text if text else "（未提供）"


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "…"


__all__ = ["render_job_demand", "render_ability_analysis"]
