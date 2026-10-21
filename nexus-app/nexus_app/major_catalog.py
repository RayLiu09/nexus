"""Confirmed finance-and-commerce professional identities used for missing-field completion."""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping


# Code is the unique key. The supplied 730704 row appeared twice with identical values.
FINANCE_COMMERCE_MAJORS: Mapping[str, tuple[str, str]] = MappingProxyType({
    "330201": ("金融管理", "职业本科"),
    "330301": ("大数据与财务管理", "职业本科"),
    "330302": ("大数据与会计", "职业本科"),
    "330501": ("国际经济与贸易", "职业本科"),
    "330602": ("市场营销", "职业本科"),
    "330701": ("电子商务", "职业本科"),
    "330802": ("现代物流管理", "职业本科"),
    "530101": ("财税大数据应用", "高职专科"),
    "530201": ("金融服务与管理", "高职专科"),
    "530202": ("金融科技应用", "高职专科"),
    "530203": ("保险实务", "高职专科"),
    "530205": ("财富管理", "高职专科"),
    "530206": ("证券实务", "高职专科"),
    "530301": ("大数据与财务管理", "高职专科"),
    "530302": ("大数据与会计", "高职专科"),
    "530303": ("大数据与审计", "高职专科"),
    "530304": ("会计信息管理", "高职专科"),
    "530401": ("统计与大数据分析", "高职专科"),
    "530403": ("市场调查与统计分析", "高职专科"),
    "530501": ("国际经济与贸易", "高职专科"),
    "530502": ("国际商务", "高职专科"),
    "530503": ("关务与外贸服务", "高职专科"),
    "530601": ("工商企业管理", "高职专科"),
    "530602": ("连锁经营与管理", "高职专科"),
    "530603": ("商务管理", "高职专科"),
    "530604": ("中小企业创业与经营", "高职专科"),
    "530605": ("市场营销", "高职专科"),
    "530701": ("电子商务", "高职专科"),
    "530702": ("跨境电子商务", "高职专科"),
    "530703": ("移动商务", "高职专科"),
    "530704": ("网络营销与直播电商", "高职专科"),
    "530705": ("农村电子商务", "高职专科"),
    "530802": ("现代物流管理", "高职专科"),
    "530803": ("航空物流管理", "高职专科"),
    "530804": ("铁路物流管理", "高职专科"),
    "530806": ("港口物流管理", "高职专科"),
    "530809": ("智能物流技术", "高职专科"),
    "730101": ("纳税事务", "中职"),
    "730201": ("金融事务", "中职"),
    "730301": ("会计事务", "中职"),
    "730501": ("国际商务", "中职"),
    "730502": ("服务外包", "中职"),
    "730602": ("市场营销", "中职"),
    "730701": ("电子商务", "中职"),
    "730702": ("跨境电子商务", "中职"),
    "730703": ("移动商务", "中职"),
    "730704": ("网络营销专业", "中职"),
    "730705": ("直播电商服务", "中职"),
    "730801": ("物流服务与管理", "中职"),
    "730802": ("冷链物流服务与管理", "中职"),
    "730803": ("国际货运代理", "中职"),
    "730804": ("物流设施运行与维护", "中职"),
})


def _level_key(value: str | None) -> str | None:
    if not value:
        return None
    if value in {"本科", "职业本科", "高职本科", "高等职业教育本科"}:
        return "职业本科"
    if value in {"高职", "专科", "高职专科", "高等职业教育专科"}:
        return "高职专科"
    if value in {"中职", "中等职业教育"}:
        return "中职"
    return value


def complete_major_identity(
    major_code: str | None,
    major_name: str | None,
    education_level: str | None = None,
) -> tuple[str | None, str | None, str | None]:
    """Fill missing fields only when catalog evidence uniquely identifies a major."""
    code = major_code.strip() if major_code else None
    name = major_name.strip() if major_name else None
    level = education_level.strip() if education_level else None

    if code:
        entry = FINANCE_COMMERCE_MAJORS.get(code)
        if entry is None:
            return code, name, level
        catalog_name, catalog_level = entry
        if name and name.removesuffix("专业") != catalog_name.removesuffix("专业"):
            return code, name, level
        if level and _level_key(level) != catalog_level:
            return code, name, level
        return code, name or catalog_name, level or catalog_level

    if not name:
        return code, name, level
    candidates = [
        (candidate_code, candidate_name, candidate_level)
        for candidate_code, (candidate_name, candidate_level) in FINANCE_COMMERCE_MAJORS.items()
        if candidate_name.removesuffix("专业") == name.removesuffix("专业")
        and (not level or _level_key(level) == candidate_level)
    ]
    if len(candidates) != 1:
        return code, name, level
    candidate_code, _, candidate_level = candidates[0]
    return candidate_code, name, level or candidate_level
