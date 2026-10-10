from fastapi.testclient import TestClient

from nexus_app import models


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
