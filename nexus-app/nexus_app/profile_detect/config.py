"""Detector rules for `profile_detect`.

Lives HERE (not in `config/governance_rules.json`) per decision 8: detector
rules are TECHNICAL routing concerns, not business governance. Decision 12
(profile_detect vs governance classification boundary) allows the alias
sets to be *seeded* from the same source words as governance keywords in a
later refactor, but the storage stays separate.

Adding a new alias / pattern is a code change (not a runtime config edit)
on purpose: detector behavior changes need a code review + test update,
not an ops toggle.

All collections are `frozenset` so they cannot be mutated after import.
Regex patterns are pre-compiled at import time so detectors stay O(1) on
the hot path.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Detector version
# ---------------------------------------------------------------------------

# Pinned on the ProfileDetectResult so downstream audits and review queues
# can disjoin results emitted by different detector generations. Bump on
# any behavioral change to the detectors.
DETECTOR_VERSION: str = "record-profile-detector.v2"

# Threshold below which a successful match is downgraded to its `_candidate`
# variant and the asset version is parked in `review_required`. Detectors
# may override via per-record_type thresholds in B2.2; this is the floor.
DEFAULT_AUTO_ADMIT_THRESHOLD: float = 0.85


# ---------------------------------------------------------------------------
# Job demand (招聘岗位需求) detector inputs
# ---------------------------------------------------------------------------

# Required-ish headers — a worksheet must hit at least the configured minimum
# (B2.2 decides the threshold) to be considered job_demand_dataset.
# Aliases cover the variants observed across recruiting platforms (sample 1
# header words + common synonyms from Boss / 51job / Lagou export formats).
JOB_DEMAND_HEADER_ALIASES: frozenset[str] = frozenset({
    "岗位名称", "职位名称", "岗位", "职位", "岗位名", "招聘岗位",
    "job_title", "position", "position_name",
    "城市", "工作城市", "工作地点", "工作地",
    "city", "work_city", "location",
    "公司名称", "企业名称", "公司",
    "company", "company_name", "employer",
})

# Optional but boost-bearing headers. Hitting many of these raises confidence
# beyond the bare-minimum required set.
JOB_DEMAND_OPTIONAL_HEADERS: frozenset[str] = frozenset({
    "薪资", "薪水", "工资", "salary",
    "最低薪资", "最高薪资", "salary_min", "salary_max",
    "经验要求", "工作经验", "经验", "experience",
    "学历要求", "学历", "education",
    "岗位描述", "岗位说明", "职位描述", "job_description", "description",
    "岗位技能说明", "技能要求", "skills",
    "公司规模", "企业规模", "company_size", "enterprise_size",
    "所属产业", "所属行业", "所属产业/行业", "行业", "industry",
    "发布时间", "publish_time", "published_at",
    "岗位类型", "工作类型", "employment_type",
})


# ---------------------------------------------------------------------------
# PGSD ability_analysis detector inputs
# ---------------------------------------------------------------------------

# Required four-category set for the PGSD model. Detector demands all four
# to be present (in some sheet's first column or category column) before
# emitting `occupational_ability_analysis` at full confidence; any missing
# category downgrades to `occupational_ability_analysis_candidate`.
PGSD_REQUIRED_CATEGORIES: frozenset[str] = frozenset({
    "职业能力", "通用能力", "社会能力", "发展能力",
})

# Alias map — canonical → variant form. The detector lower-cases / strips
# whitespace before matching. The "职业技能 → 职业能力" alias is required
# per design §5.2 (P 的标准展示名统一为"职业能力","职业技能" 作为 alias).
PGSD_CATEGORY_ALIASES: dict[str, str] = {
    "职业技能": "职业能力",
}

# Ability-code prefix regex. The full match (P-1.1.1) is too restrictive —
# we match the prefix so detection works even before B2.2 parses individual
# segments. PGSD codes are 2- or 3-segment (G/S/D vs P) per design §5.7.
PGSD_CODE_PREFIX_PATTERN: re.Pattern[str] = re.compile(
    r"^[PGSD]-\d+(?:\.\d+){1,2}$"
)

# Sheet-name pattern for per-task ability analysis sub-sheets (e.g.
# "1.数据采集", "4.可视化图表制作"). Matches a leading digit-and-dot prefix
# followed by Chinese characters. Used to discriminate the canonical PGSD
# layout from generic spreadsheets.
PGSD_SHEET_NAME_PATTERN: re.Pattern[str] = re.compile(
    r"^\d+\.[\u4e00-\u9fa5].*$"
)

# Keywords identifying the overview sheet (sheet 0 in sample 2) that lists
# typical-work-task × work-content matrix. The detector uses this as a
# secondary signal — even if all per-task sheets are present, the overview
# sheet's presence raises confidence.
OVERVIEW_SHEET_KEYWORDS: frozenset[str] = frozenset({
    "典型工作任务", "工作内容分析", "能力分析",
})


# ---------------------------------------------------------------------------
# Major distribution (专业布点数) detector inputs
# ---------------------------------------------------------------------------

MAJOR_DISTRIBUTION_HEADER_ALIASES: dict[str, frozenset[str]] = {
    "year": frozenset({"年份", "年度", "统计年份", "year"}),
    "province_name": frozenset({
        "省份", "省市", "地区", "地域", "行政区", "province", "region",
    }),
    "major_name": frozenset({"专业名称", "专业", "专业名", "major_name"}),
    "major_code": frozenset({
        "专业代码", "专业编码", "专业目录代码", "major_code",
    }),
    "education_level": frozenset({
        "层次", "学历层次", "办学层次", "education_level",
    }),
    "distribution_count": frozenset({
        "布点数", "布点数量", "专业布点数量（个）", "专业布点数量",
        "开设数量", "院校数",
    }),
    "source_row_no": frozenset({"序号", "No.", "#"}),
}

MAJOR_DISTRIBUTION_TOTAL_MARKERS: frozenset[str] = frozenset({
    "全部", "全国", "合计",
})

MAJOR_DISTRIBUTION_FILENAME_KEYWORDS: frozenset[str] = frozenset({
    "专业布点数", "专业布点数量", "专业布点",
})

MAJOR_CODE_PATTERN: re.Pattern[str] = re.compile(r"^\d{6}$")
