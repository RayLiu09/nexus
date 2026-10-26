from datetime import datetime, timezone
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from nexus_app import models
from nexus_app.enums import AssetVersionStatus
from test_open_asset_catalog_filters import _seed_asset
from test_teaching_standard_library_api import _seed_library


def seed_document(session, suffix, classification="course_textbook", **kwargs):
    _seed_asset(session, suffix=suffix, classification=classification, tag_type="industry",
                tag_value="低空经济", tag_value_normalized="低空经济", **kwargs)
    return session.get(models.NormalizedAssetRef, f"ref-{suffix}")


@pytest.mark.parametrize("path", ["data-resources", "market-jobs", "industrial-parks", "enterprises", "teaching-standard-libraries", "teaching-standard-courses", "course-textbooks", "major-profile-documents", "record-assets/ability-items", "normalized-refs/missing/sections", "normalized-refs/missing/knowledge-outline", "normalized-refs/missing/task-outline", "normalized-refs/missing/knowledge-graph", "talent-training-plans/missing/courses"])
def test_public_reads_require_credentials(app_no_auth_override, path):
    assert TestClient(app_no_auth_override).get(f"/open/v1/{path}").status_code == 401


@pytest.mark.parametrize("path,body", [("entity-resolutions", {"entity_type": "major", "query": "电子商务"}), ("evidence-resolutions", {"references": [{"kind": "normalized_ref", "id": "missing"}]})])
def test_public_posts_require_credentials(app_no_auth_override, path, body):
    assert TestClient(app_no_auth_override).post(f"/open/v1/{path}", json=body).status_code == 401


def test_market_jobs_same_source_filters_and_full_aggregate(app, session):
    session.add_all([models.RawJob(id=f"job-{i}", title_raw="运营", degree_raw="专科" if i < 2 else None,
        company_name_raw="示例", company_industry_raw="数字商务", salary_raw="面议") for i in range(3)])
    session.add(models.RawJob(id="outside", title_raw="机械设计", company_industry_raw="制造"))
    session.flush()
    session.add(models.RawJobProvenance(raw_job_id="job-0", provider_code="crawler", source_name="示例站点", external_task_id="task", source_page=1, keyword="运营", raw_record={}, raw_record_hash="record-hash", upstream_payload_hash="payload-hash", upstream_record_id="upstream-1", collected_at=datetime(2026, 10, 1, tzinfo=timezone.utc), source_url="https://example.test/job/1"))
    session.commit()
    client = TestClient(app)
    data = client.get("/open/v1/market-jobs", params={"industry": "数字商务", "pageSize": 1}).json()
    assert data["meta"]["total"] == 3
    assert len(data["data"]) == 1
    aggregation = client.get("/open/v1/market-jobs/aggregate", params={"industry": "数字商务", "group_by": "education", "pageSize": 1})
    assert aggregation.status_code == 200, aggregation.text
    data = aggregation.json()
    assert data["aggregations"]["sample_count"] == 3
    assert data["aggregations"]["missing_counts"] == {"education": 1}
    assert data["data"][0]["record_count"] == 2
    assert data["aggregations"]["source"] == "raw_jobs"
    detail = client.get("/open/v1/market-jobs/job-0").json()["data"]
    assert detail["provider_code"] == "crawler" and detail["upstream_record_id"] == "upstream-1"
    assert detail["salary_range"] == "面议" and detail["source_type"] == "raw_jobs"
    assert client.get("/open/v1/market-jobs", params={"collected_from": "2026-10-01T00:00:00Z"}).json()["meta"]["total"] == 1
    assert client.get("/open/v1/market-jobs/aggregate?group_by=education&group_by=education").status_code == 422
    assert client.get("/open/v1/market-jobs/aggregate?group_by=salary").status_code == 422
    assert client.get("/open/v1/market-jobs?collected_from=2026-11-01&collected_to=2026-01-01").status_code == 422
    audits = session.scalars(select(models.AuditLog).where(models.AuditLog.target_type == "public_data_read")).all()
    assert len(audits) == 4
    assert all(row.trace_id and row.actor_id for row in audits)
    assert "example.test" not in json.dumps([row.summary for row in audits])


@pytest.mark.parametrize("status", ["review", "active", "superseded"])
def test_standards_ignore_lifecycle_but_require_current_available_classified_document(app, session, status):
    ref = seed_document(session, status, "teaching_standard")
    library, course = _seed_library(session, status=status)
    client = TestClient(app)
    response = client.get("/open/v1/teaching-standard-courses", params={"major_code": "530701", "tag": "网店运营"})
    assert response.status_code == 200, response.text
    item = response.json()["data"][0]
    assert item["hours_semantics"] == "suggested" and item["tag_semantics"] == "derived"
    assert item["evidence_bindings"] and item["normalized_ref_id"] == ref.id
    assert client.get(f"/open/v1/teaching-standard-libraries/{library.id}").json()["data"]["course_count"] == 1
    library.status = "review"
    session.commit()
    assert client.get(f"/open/v1/teaching-standard-courses/{course.id}").status_code == 200
    discovered = {r["code"]: r for r in client.get("/open/v1/data-resources").json()["data"]}
    assert discovered["teaching_standard"]["count"] == 1
    assert discovered["standard_course"]["count"] == 1
    assert client.post("/open/v1/entity-resolutions", json={"entity_type":"major", "query":"530701"}).json()["data"]
    session.get(models.AssetVersion, ref.version_id).version_status = AssetVersionStatus.REVIEW_REQUIRED
    session.commit()
    assert client.get("/open/v1/teaching-standard-libraries").json()["meta"]["total"] == 0
    assert client.get(f"/open/v1/teaching-standard-courses/{course.id}").status_code == 404


def test_market_region_is_applied_before_pagination_and_aggregation(app, session):
    session.add_all([
        models.RawJob(id="hz-1", title_raw="电商运营", address_raw="杭州·滨江", degree_raw="专科"),
        models.RawJob(id="hz-2", title_raw="电商运营", address_raw="杭州·西湖", degree_raw="专科"),
        models.RawJob(id="bj", title_raw="电商运营", address_raw="北京", degree_raw="本科"),
        models.RawJob(id="literal", title_raw="电商运营", address_raw="园区100%"),
        models.RawJob(id="no-address", title_raw="电商运营"),
    ])
    session.commit()
    client = TestClient(app)
    params = {"job_title":"电商", "region":"杭州", "pageSize":1}
    first = client.get("/open/v1/market-jobs", params=params).json()
    second = client.get("/open/v1/market-jobs", params={**params,"page":2}).json()
    assert first["meta"]["total"] == second["meta"]["total"] == 2
    assert first["data"][0]["id"] != second["data"][0]["id"]
    aggregate = client.get("/open/v1/market-jobs/aggregate", params={**params,"group_by":"education"}).json()
    assert aggregate["aggregations"]["sample_count"] == 2
    assert aggregate["aggregations"]["filters"]["region"] == "杭州"
    assert aggregate["data"][0]["record_count"] == 2
    assert client.get("/open/v1/market-jobs",params={"region":"%"}).json()["meta"]["total"] == 1
    assert client.get("/open/v1/market-jobs",params={"region":"杭州","education":"本科"}).json()["meta"]["total"] == 0


def test_career_orientation_search_filters_facts_without_duplicates_or_certificate_matches(app, session):
    ref = seed_document(session, "review", "teaching_standard")
    library, _ = _seed_library(session)
    session.add_all([
        models.TeachingStandardOccupation(library_id=library.id, dimension_type="occupation_type", item_index=1,
            source_name="电子商务师",source_code="4-01-06-01",source_text="电子商务师 | 培训证书",evidence_block_ids=["b1"],locator={"page":1}),
        models.TeachingStandardOccupation(library_id=library.id, dimension_type="primary_position", item_index=1,
            source_name="电子商务运营",evidence_block_ids=["b1"],locator={"page":1}),
        models.TeachingStandardOccupation(library_id=library.id, dimension_type="certificate_type", item_index=1,
            source_name="培训证书",evidence_block_ids=["b1"],locator={"page":1}),
    ])
    session.commit()
    client = TestClient(app)
    result = client.get("/open/v1/teaching-standard-libraries",params={"occupation":"电子商务","pageSize":1}).json()
    assert result["meta"]["total"] == 1
    assert len(result["data"][0]["career_orientation"]) == 3
    assert result["data"][0]["career_orientation"][0]["evidence_block_ids"] == ["b1"]
    assert client.get("/open/v1/teaching-standard-libraries",params={"occupation":"4-01-06-01"}).json()["meta"]["total"] == 1
    assert client.get("/open/v1/teaching-standard-libraries",params={"occupation":"培训证书"}).json()["meta"]["total"] == 0
    assert client.get("/open/v1/teaching-standard-libraries",params={"occupation":"%"}).json()["meta"]["total"] == 0
    assert client.get("/open/v1/teaching-standard-libraries",params={"occupation":"电子商务","major_code":"999999"}).json()["meta"]["total"] == 0
    assert client.get(f"/open/v1/teaching-standard-libraries/{library.id}").json()["data"]["career_orientation"]
    session.get(models.AssetVersion,ref.version_id).version_status = AssetVersionStatus.REVIEW_REQUIRED
    session.commit()
    assert client.get("/open/v1/teaching-standard-libraries",params={"occupation":"电子商务"}).json()["meta"]["total"] == 0


def test_parks_enterprises_entity_candidates_keep_ambiguity(app, session):
    session.add_all([models.IndustrialPark(id="park", source_park_id="source-park", park_name="数字商务园", industry_tags="电商", introduction="园区"),
        models.Enterprise(id="company1", source_record_key="source-company1", enterprise_name="云商", business_scope="电商运营", industrial_park_id="park"),
        models.Enterprise(id="company2", source_record_key="source-company2", enterprise_name="云商服务", business_scope="咨询")])
    session.commit()
    client = TestClient(app)
    parks = client.get("/open/v1/industrial-parks?industry=电商").json()["data"]
    assert parks[0]["enterprise_count"] == 1
    enterprises = client.get("/open/v1/enterprises?park_id=park").json()["data"]
    assert len(enterprises) == 1 and enterprises[0]["park_name"] == "数字商务园"
    assert client.get("/open/v1/enterprises/company1").status_code == 200
    assert client.get("/open/v1/industrial-parks/park").status_code == 200
    result = client.post("/open/v1/entity-resolutions", json={"entity_type": "enterprise", "query": "云商"}).json()["data"]
    assert [item["id"] for item in result] == ["company1", "company2"]
    assert [item["match_type"] for item in result] == ["exact", "substring"]


def test_discovery_has_16_resources_and_public_counts(app, session):
    from test_occupation_dictionary import seed_rows
    from nexus_api.function_tools import generate_catalog

    seed_rows(session)
    seed_document(session, "policy", "industry_policy")
    seed_document(session, "hidden", "industry_policy", status=AssetVersionStatus.REVIEW_REQUIRED)
    session.add(models.RawJob(id="job", title_raw="运营"))
    session.commit()
    result = TestClient(app).get("/open/v1/data-resources")
    assert result.status_code == 200, result.text
    data = {item["code"]: item for item in result.json()["data"]}
    assert len(data) == 16
    assert data["industry_policy"]["count"] == 1
    assert data["market_job"]["count"] == 1
    assert "tags_match" in data["industry_policy"]["filter_parameters"]
    assert all("/internal/" not in item["endpoint"] for item in data.values())
    assert data["occupation_dictionary"]["count"] == 3
    assert data["occupation_dictionary"]["name"] == "职业分类大典"
    assert {"major_group", "minor_group", "occupation_name"} <= set(data["occupation_dictionary"]["filter_parameters"])
    bindings = generate_catalog(app.openapi())["bindings"]
    get_paths = {item["path"] for item in bindings if item["method"] == "GET"}
    assert all(item["endpoint"] in get_paths for item in data.values())


def test_major_documents_use_metadata_overrides_filters_and_no_retired_projection(app, session):
    ref = seed_document(session, "major", "major_profile")
    ref.document_metadata = {"publish_date": "2026-09-01", "major_profile": {"major_name": "电子商务", "major_code": "530701", "institution_name": "旧院校", "education_level": "高职专科"}}
    ref.metadata_summary = {"major_profile_manual_metadata": {"institution_name": "新院校"}}
    session.commit()
    client = TestClient(app)
    params = {"institution_name": "新院校", "major_code": "530701", "published_from": "2026-01-01", "published_to": "2026-12-31"}
    result = client.get("/open/v1/major-profile-documents", params=params)
    assert result.status_code == 200, result.text
    assert result.json()["data"][0]["business_metadata"]["institution_name"] == "新院校"
    assert client.get("/open/v1/major-profile-documents?institution_name=旧院校").json()["meta"]["total"] == 0
    ref.metadata_summary = {"major_profile_manual_metadata": {"institution_name": None}}
    session.commit()
    assert client.get("/open/v1/major-profile-documents?institution_name=旧院校").json()["meta"]["total"] == 0
    assert client.get("/open/v1/assets?published_from=2026-12-01&published_to=2026-01-01").status_code == 422
    assert client.get("/open/v1/assets?domains=major_profile&industry=低空经济").json()["meta"]["total"] == 1
    assert client.get("/open/v1/assets?tags=低空经济&tags=不存在&tags_match=all&is_exact_matched=true").json()["meta"]["total"] == 0


def test_textbook_metadata_outline_capabilities_and_classification(app, session):
    ref = seed_document(session, "textbook")
    ref.document_metadata = {"title": "商务数据分析", "publisher": "教育出版社", "chief_editors": ["张某"], "publish_date": "2025-09"}
    profile = models.CourseTextbook(id="textbook", normalized_ref_id=ref.id, asset_version_id=ref.version_id,
        asset_profile="course_textbook", title="商务数据分析", textbook_subtype="theory_knowledge", processing_profile="semantic_repack", evidence_graph_admission="recommended")
    session.add(profile)
    session.add(models.KnowledgeOutlineNode(normalized_ref_id=ref.id, title="数据分析", level=1, order_index=1, build_run_id="existing"))
    session.commit()
    client = TestClient(app)
    result = client.get("/open/v1/course-textbooks", params={"title": "商务", "publisher": "教育", "chief_editor": "张某", "publication_year": 2025, "textbook_type": "theory"})
    assert result.status_code == 200, result.text
    assert result.json()["data"][0]["outline_types"] == ["knowledge"]
    assert client.get("/open/v1/course-textbooks/textbook").json()["data"]["publication_year"] == 2025
    governance = session.get(models.GovernanceResult, "governance-textbook")
    governance.classification = "industry_report"
    session.commit()
    assert client.get("/open/v1/course-textbooks/textbook").status_code == 404


def test_training_plan_courses_paginate_and_source_publication_dates(app, session):
    from test_talent_training_plan_api import _seed
    from nexus_app.enums import GovernanceResultStatus
    plan = _seed(session, suffix="courses", status=AssetVersionStatus.AVAILABLE)
    ref = session.get(models.NormalizedAssetRef, plan.normalized_ref_id)
    ref.document_metadata = {"publish_date": "2026-01-03"}
    session.add(models.GovernanceResult(normalized_ref_id=ref.id, classification="talent_training_plan", index_admission=True, status=GovernanceResultStatus.AVAILABLE))
    session.add(models.TalentTrainingPlanCourse(id="second-course", plan_id=plan.id, normalized_ref_id=ref.id, item_index=2, course_name="运营", curriculum_group="professional_core", course_type="course"))
    session.commit()
    client = TestClient(app)
    page = client.get(f"/open/v1/talent-training-plans/{plan.id}/courses?pageSize=1&page=2")
    assert page.status_code == 200, page.text
    assert page.json()["meta"]["total"] == 2
    assert page.json()["data"][0]["id"] == "second-course"
    result = client.get("/open/v1/talent-training-plans?published_from=2026-01-01&published_to=2026-01-31")
    assert result.status_code == 200, result.text
    assert result.json()["meta"]["total"] == 1
    assert client.get("/open/v1/talent-training-plans?published_from=2026-02-01").json()["meta"]["total"] == 0
    session.get(models.AssetVersion, ref.version_id).version_status = AssetVersionStatus.DISABLED
    session.commit()
    assert client.get(f"/open/v1/talent-training-plans/{plan.id}/courses").status_code == 404


def test_ability_items_cross_analysis_major_code_and_record_boundary(app, session):
    from test_b6_ability_analysis_api import _seed_full_analysis
    ids = _seed_full_analysis(session)
    analysis = session.get(models.OccupationalAbilityAnalysis, ids["analysis_id"])
    analysis.major_code = "710205"
    session.commit()
    client = TestClient(app)
    result = client.get("/open/v1/record-assets/ability-items?major_code=710205")
    assert result.status_code == 200, result.text
    assert result.json()["meta"]["total"] == 1
    assert result.json()["data"][0]["major_name"] == analysis.major_name
    assert client.get("/open/v1/record-assets/ability-analyses?major_code=710205").json()["meta"]["total"] == 1
    assert client.get("/open/v1/record-assets/ability-items?major_code=999999").json()["meta"]["total"] == 0
