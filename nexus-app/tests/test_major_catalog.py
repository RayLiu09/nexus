from __future__ import annotations

import pytest

from nexus_app.major_catalog import FINANCE_COMMERCE_MAJORS, complete_major_identity


def test_finance_commerce_catalog_is_deduplicated_and_read_only():
    assert len(FINANCE_COMMERCE_MAJORS) == 52
    assert FINANCE_COMMERCE_MAJORS["730702"] == ("跨境电子商务", "中职")
    assert FINANCE_COMMERCE_MAJORS["730704"] == ("网络营销专业", "中职")
    assert FINANCE_COMMERCE_MAJORS["330701"] == ("电子商务", "职业本科")
    with pytest.raises(TypeError):
        FINANCE_COMMERCE_MAJORS["730704"] = ("x", "中职")


@pytest.mark.parametrize("code, name, level, expected", [
    ("730702", None, None, ("730702", "跨境电子商务", "中职")),
    (None, "跨境电子商务", "中职", ("730702", "跨境电子商务", "中职")),
    (None, "电子商务", None, (None, "电子商务", None)),
    (None, "电子商务", "高职", ("530701", "电子商务", "高职")),
    ("530701", "电子商务", "高职", ("530701", "电子商务", "高职")),
    ("730704", "网络营销", None, ("730704", "网络营销", "中职")),
    ("730702", "其他专业", None, ("730702", "其他专业", None)),
    ("999999", None, None, ("999999", None, None)),
])
def test_complete_major_identity_fills_only_unambiguous_gaps(code, name, level, expected):
    assert complete_major_identity(code, name, level) == expected
