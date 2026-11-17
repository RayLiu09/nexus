from datetime import datetime, timezone
from io import BytesIO

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from nexus_app import models


def test_raw_jobs_list_filters_by_created_range(app, session):
    session.add_all(
        [
            models.RawJob(
                id="raw-job-early",
                title_raw="早期岗位",
                created_at=datetime(2026, 1, 10, tzinfo=timezone.utc),
            ),
            models.RawJob(
                id="raw-job-late",
                title_raw="近期岗位",
                created_at=datetime(2026, 3, 10, tzinfo=timezone.utc),
            ),
        ]
    )
    session.commit()

    with TestClient(app) as client:
        response = client.get(
            "/internal/v1/raw-jobs",
            params={
                "created_from": "2026-02-01T00:00:00+08:00",
                "created_to": "2026-03-31T23:59:59.999+08:00",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["total"] == 1
    assert [row["id"] for row in body["data"]] == ["raw-job-late"]


def test_raw_jobs_list_rejects_invalid_created_range(app, session):
    with TestClient(app) as client:
        naive = client.get("/internal/v1/raw-jobs", params={"created_from": "2026-02-01T00:00:00"})
        inverted = client.get(
            "/internal/v1/raw-jobs",
            params={
                "created_from": "2026-03-01T00:00:00+08:00",
                "created_to": "2026-02-01T00:00:00+08:00",
            },
        )

    assert naive.status_code == 422
    assert inverted.status_code == 422


def test_raw_jobs_list_reads_raw_intake_fields_only(app, session):
    session.add_all(
        [
            models.RawJob(
                id="raw-job-1",
                title_raw="数据分析师",
                company_name_raw="示例科技",
                address_raw="上海市浦东新区",
                salary_raw="15-25K",
                experience_raw="3-5年",
                degree_raw="本科",
                responsibilities_raw="负责经营数据分析",
                company_industry_raw="互联网",
                company_scale_raw="100-499人",
            ),
            models.RawJob(id="raw-job-2", title_raw="前端工程师", company_name_raw="另一家公司"),
        ]
    )
    session.commit()

    with TestClient(app) as client:
        response = client.get("/internal/v1/raw-jobs", params={"q": "数据分析师"})

    assert response.status_code == 200
    body = response.json()
    assert body["meta"]["total"] == 1
    assert body["data"] == [
        {
            "id": "raw-job-1",
            "job_title": "数据分析师",
            "title_normalized": None,
            "region": None,
            "job_responsibilities": "负责经营数据分析",
            "experience_requirement": "3-5年",
            "education": "本科",
            "salary_range": "15-25K",
            "industry": "互联网",
            "company_name": "示例科技",
            "company_size": "100-499人",
            "address": "上海市浦东新区",
            "source_url": None,
            "collected_at": None,
            "created_at": body["data"][0]["created_at"],
        }
    ]


def test_raw_jobs_export_includes_every_matching_row_and_business_columns(app, session):
    session.add_all([
        models.RawJob(
            id=f"raw-job-{index}",
            title_raw=f"数据岗位{index}",
            company_industry_raw="互联网",
            responsibilities_raw="分析业务数据",
            company_name_raw="示例科技",
        )
        for index in range(25)
    ])
    session.add(models.RawJob(
        id="raw-job-other", title_raw="其它岗位", company_industry_raw="制造业"
    ))
    session.commit()

    with TestClient(app) as client:
        response = client.get("/internal/v1/raw-jobs/export", params={"industry": "互联网"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    sheet = load_workbook(BytesIO(response.content), read_only=True).active
    rows = list(sheet.values)
    assert rows[0] == (
        "岗位名称", "岗位职责要求", "经验要求", "学历", "薪资范围",
        "所在行业", "公司名称", "规模", "地址",
        "标准化岗位名称", "采集地区",
    )
    assert len(rows) == 26
    assert {row[0] for row in rows[1:]} == {f"数据岗位{index}" for index in range(25)}
    assert all(row[5] == "互联网" for row in rows[1:])


def test_raw_jobs_export_keeps_untrusted_text_as_excel_string(app, session):
    session.add(models.RawJob(
        id="raw-job-formula", title_raw="=1+1", description_raw="=HYPERLINK(\"x\")"
    ))
    session.commit()

    with TestClient(app) as client:
        response = client.get("/internal/v1/raw-jobs/export")

    assert response.status_code == 200
    sheet = load_workbook(BytesIO(response.content), read_only=True).active
    cells = list(sheet.rows)[1]
    assert cells[0].value == "'=1+1"
    assert cells[0].data_type == "s"
    assert cells[1].value == "'=HYPERLINK(\"x\")"


def test_internal_region_filter_uses_collection_region_for_pages_totals_and_export(app, session):
    session.add_all([
        models.RawJob(id="hz-1", title_raw="运营", region="杭州市", address_raw="北京市",
                      title_normalized="运营", company_industry_raw="数字商务"),
        models.RawJob(id="hz-2", title_raw="运营", region="杭州市", company_industry_raw="数字商务"),
        models.RawJob(id="address-only", title_raw="运营", region="北京市", address_raw="杭州市"),
        models.RawJob(id="missing-region", title_raw="运营", address_raw="杭州市"),
        models.RawJob(id="literal", title_raw="运营", region="园区100%_A"),
    ])
    session.commit()
    client = TestClient(app)
    params = {"region": "杭州", "industry": "数字商务", "pageSize": 1}
    first = client.get("/internal/v1/raw-jobs", params=params)
    second = client.get("/internal/v1/raw-jobs", params={**params, "page": 2})
    assert first.status_code == second.status_code == 200
    assert first.json()["meta"]["total"] == second.json()["meta"]["total"] == 2
    assert {first.json()["data"][0]["id"], second.json()["data"][0]["id"]} == {"hz-1", "hz-2"}
    assert first.json()["data"][0]["region"] == "杭州市"
    for literal in ("%", "_"):
        result = client.get("/internal/v1/raw-jobs", params={"region": literal}).json()
        assert [row["id"] for row in result["data"]] == ["literal"]
    assert client.get("/internal/v1/raw-jobs", params={"region": ""}).status_code == 422
    exported = client.get("/internal/v1/raw-jobs/export", params=params)
    assert exported.status_code == 200
    rows = list(load_workbook(BytesIO(exported.content), read_only=True).active.values)
    assert len(rows) == 3
    assert all(row[-1] == "杭州市" for row in rows[1:])
    assert any(row[-2] == "运营" for row in rows[1:])


def test_internal_query_searches_cleaned_title_without_replacing_original(app, session):
    session.add(models.RawJob(id="clean", title_raw="【急聘】ＡＩ运营",
                              title_normalized="AI运营", region="昆明市"))
    session.commit()
    result = TestClient(app).get("/internal/v1/raw-jobs", params={"q": "AI运营"})
    assert result.status_code == 200
    row = result.json()["data"][0]
    assert row["job_title"] == "【急聘】ＡＩ运营"
    assert row["title_normalized"] == "AI运营"
    assert row["region"] == "昆明市"
