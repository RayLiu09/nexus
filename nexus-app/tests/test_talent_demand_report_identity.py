from nexus_app.normalize.talent_demand_report_identity import extract


def test_report_cover_identity_and_surveyed_school_not_attributed():
    result = extract(
        "大数据与会计专业人才需求分析与预测调研报告.pdf",
        [
            {"block_id": "cover", "text": "大数据与会计专业人才需求分析与预测调研报告"},
            {"block_id": "survey", "text": "调查湖南财经工业职业技术学院等17所学校"},
        ],
    )
    assert result is not None
    assert result["major_name"] == "大数据与会计"
    assert result["major_code"] is None
    assert result["institution_name"] is None


def test_spaced_cover_labels_and_explicit_institution():
    result = extract(
        "大数据技术专业人才需求与培养调研报告.pdf",
        [
            {"block_id": "name", "text": "专 业 名 称 ： 大数据技术（含地理信息应用方向）"},
            {"block_id": "code", "text": "专 业 代 码 ： 510205"},
            {"block_id": "college", "text": "所 属 学 院 ： 信息工程学院"},
            {"block_id": "owner", "text": "编制单位：湖南工程职业技术学院"},
        ],
    )
    assert result is not None
    assert result["major_name"] == "大数据技术（含地理信息应用方向）"
    assert result["major_code"] == "510205"
    assert result["institution_name"] == "湖南工程职业技术学院"
