"""Canonical names for province-level administrative divisions.

The major-distribution read model stores one province-level entity per row.
This helper accepts common aliases while deliberately keeping Xinjiang
Production and Construction Corps separate from Xinjiang Uygur Autonomous
Region.
"""
from __future__ import annotations

from typing import Final


_CANONICAL_ALIASES: Final[dict[str, tuple[str, ...]]] = {
    "北京市": ("北京", "北京市"), "天津市": ("天津", "天津市"),
    "河北省": ("河北", "河北省"), "山西省": ("山西", "山西省"),
    "辽宁省": ("辽宁", "辽宁省"), "吉林省": ("吉林", "吉林省"),
    "黑龙江省": ("黑龙江", "黑龙江省"), "上海市": ("上海", "上海市"),
    "江苏省": ("江苏", "江苏省"), "浙江省": ("浙江", "浙江省"),
    "安徽省": ("安徽", "安徽省"), "福建省": ("福建", "福建省"),
    "江西省": ("江西", "江西省"), "山东省": ("山东", "山东省"),
    "河南省": ("河南", "河南省"), "湖北省": ("湖北", "湖北省"),
    "湖南省": ("湖南", "湖南省"), "广东省": ("广东", "广东省"),
    "海南省": ("海南", "海南省"), "重庆市": ("重庆", "重庆市"),
    "四川省": ("四川", "四川省"), "贵州省": ("贵州", "贵州省"),
    "云南省": ("云南", "云南省"), "陕西省": ("陕西", "陕西省"),
    "甘肃省": ("甘肃", "甘肃省"), "青海省": ("青海", "青海省"),
    "内蒙古自治区": ("内蒙古", "内蒙古自治区"),
    "广西壮族自治区": ("广西", "广西壮族自治区"),
    "西藏自治区": ("西藏", "西藏自治区"),
    "宁夏回族自治区": ("宁夏", "宁夏回族自治区"),
    "新疆维吾尔自治区": ("新疆", "新疆维吾尔自治区"),
    "香港特别行政区": ("香港", "香港特别行政区"),
    "澳门特别行政区": ("澳门", "澳门特别行政区"),
    "台湾省": ("台湾", "台湾省"),
    "新疆生产建设兵团": ("新疆生产建设兵团", "新疆兵团", "兵团"),
}


def _key(value: str) -> str:
    return "".join(value.split())


_ALIAS_TO_CANONICAL: Final[dict[str, str]] = {
    _key(alias): canonical
    for canonical, aliases in _CANONICAL_ALIASES.items()
    for alias in aliases
}


def normalize_province_name(value: str | None) -> str | None:
    """Return a canonical name for a known alias; preserve unknown values."""
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    return _ALIAS_TO_CANONICAL.get(_key(text), text)


__all__ = ["normalize_province_name"]
