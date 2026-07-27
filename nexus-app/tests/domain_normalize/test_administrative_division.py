from nexus_app.domain_normalize.administrative_division import normalize_province_name


def test_normalize_province_name_handles_common_aliases() -> None:
    assert normalize_province_name("新疆") == "新疆维吾尔自治区"
    assert normalize_province_name(" 浙江省 ") == "浙江省"
    assert normalize_province_name("内蒙古") == "内蒙古自治区"


def test_normalize_province_name_preserves_independent_corps_and_unknowns() -> None:
    assert normalize_province_name("新疆生产建设兵团") == "新疆生产建设兵团"
    assert normalize_province_name("未知区域") == "未知区域"
    assert normalize_province_name("  ") is None
