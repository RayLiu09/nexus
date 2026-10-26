import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from nexus_app import models
from nexus_app.reference_data.occupation_dictionary import (
    CatalogSeed,
    Entry,
    import_catalog,
)


def seed_rows(session):
    entries = [
        Entry(
            occupation_code=f"2-02-10-{i:02d}",
            occupation_category="2 专业技术人员",
            major_group="2-02 工程技术人员",
            minor_group="2-02-10 通信技术人员",
            occupation_name=name,
            definition="从事通信网络工作的人员。",
            work_tasks="1.设计网络。\n2.维护网络。",
            source_rows=[i + 1],
        )
        for i, name in enumerate(["通信网络工程师", "通信设备工程师", "测试%工程师"], 1)
    ]
    import_catalog(
        session.connection(), CatalogSeed(source_file="名录.xlsx", records=entries)
    )
    session.commit()


@pytest.mark.parametrize(
    "path", ["/v1/occupation-dictionary", "/open/v1/occupation-dictionary", "/internal/v1/occupation-dictionary"]
)
def test_combined_filters_pagination_literal_wildcard_and_audit(app, session, path):
    seed_rows(session)
    with TestClient(app) as client:
        response = client.get(
            path,
            params={
                "major_group": " 2-02 ",
                "minor_group": "通信技术",
                "occupation_name": "通信",
                "pageSize": 1,
                "page": 2,
            },
        )
        assert response.status_code == 200
        result = response.json()
        assert result["meta"]["total"] == 2 and len(result["data"]) == 1
        assert result["data"][0]["occupation_name"] == "通信设备工程师"
        assert result["data"][0]["work_tasks"] == "1.设计网络。\n2.维护网络。"
        assert (
            client.get(path, params={"occupation_name": "%"}).json()["meta"]["total"]
            == 1
        )
        assert (
            client.get(path, params={"major_group": "其他"}).json()["meta"]["total"]
            == 0
        )
        assert client.get(path, params={"pageSize": 201}).status_code == 422
        for method in (client.post, client.patch, client.delete):
            assert method(path).status_code == 405
        counts = client.get("/internal/v1/asset-center/counts").json()["data"]["counts"]
        assert counts["major/occupation-dictionary"] == 3
    audits = list(
        session.scalars(
            select(models.AuditLog).where(
                models.AuditLog.target_type == "occupation_dictionary"
            )
        )
    )
    assert any(
        row.target_id == "list" and row.summary["result_count"] == 2 for row in audits
    )


@pytest.mark.parametrize(
    "path", ["/v1/occupation-dictionary", "/open/v1/occupation-dictionary", "/internal/v1/occupation-dictionary"]
)
def test_occupation_dictionary_requires_authentication(app_no_auth_override, path):
    with TestClient(app_no_auth_override) as client:
        assert client.get(path).status_code == 401
