from __future__ import annotations

from nexus_app import models
from nexus_app.enums import AssetKind, AssetVersionStatus, DataSourceType, IngestBatchStatus, NormalizedAssetRefStatus, NormalizedType, RawObjectStatus
from nexus_app.talent_training_plan.extractor import extract
from nexus_app.talent_training_plan.writer import write


def _block(block_id: str, text: str = "", html: str | None = None) -> dict:
    return {"block_id": block_id, "block_type": "table" if html else "paragraph", "text": text, "html": html, "source_locator": {"page_no": 3}}


def _payload() -> dict:
    return {"content_type": "document", "title": "杭州万向职业技术学院 跨境电子商务专业人才培养方案", "blocks": [
        _block("b1", "专业名称：跨境电子商务\n专业代码：630805\n基本修业年限：三年"),
        _block("b2", "培养目标\n培养具有跨境电商运营能力的技术技能人才。"),
        _block("b3", "培养规格\n具有跨境平台运营、国际物流及通关处理能力。"),
        _block("b4", html="<table><tr><td>行业类别及代码</td><td>职业名称及代码</td><td>主要岗位群或技术领域</td></tr><tr><td>互联网和相关服务（64）；批发业（51）</td><td>销售人员（4-01-02）</td><td>跨境电商B2C运营岗；跨境电商客服岗</td></tr></table>"),
        _block("b5", html="<table><tr><td>序号</td><td>职业岗位（群）</td><td>岗位核心能力</td><td>学习领域</td></tr><tr><td>1</td><td>跨境电商B2C运营岗</td><td>跨境电商产品挖掘能力；跨境电商平台操作能力</td><td>跨境电子商务实务</td></tr></table>"),
        _block("b6", html="<table><tr><td>序号</td><td>课程名称</td><td>课程目标</td><td>主要教学内容</td></tr><tr><td>1</td><td>跨境电子商务实务（64课时）</td><td>培养跨境平台运营能力</td><td>跨境平台规则、选品、订单处理、国际物流</td></tr></table>"),
        _block("b7", html="<table><tr><td>职业类证书举例</td></tr><tr><td>1+X跨境电商运营职业技能等级证书；1+X电子商务数据分析职业技能等级证书</td></tr></table>"),
    ]}


def _ref(session) -> models.NormalizedAssetRef:
    ds = models.DataSource(id="ttp-ds", code="ttp-ds", name="ttp", source_type=DataSourceType.FILE_UPLOAD)
    batch = models.IngestBatch(id="ttp-batch", data_source_id=ds.id, idempotency_key="ttp", source_type=DataSourceType.FILE_UPLOAD, status=IngestBatchStatus.COMPLETED)
    raw = models.RawObject(id="ttp-raw", batch_id=batch.id, data_source_id=ds.id, source_type=DataSourceType.FILE_UPLOAD, object_uri="s3://bucket/raw/ttp.pdf", checksum="ttp-raw", mime_type="application/pdf", status=RawObjectStatus.RAW_PERSISTED)
    asset = models.Asset(id="ttp-asset", data_source_id=ds.id, source_object_key="ttp.pdf", title="ttp", asset_kind=AssetKind.DOCUMENT, status=AssetVersionStatus.PROCESSING)
    version = models.AssetVersion(id="ttp-version", asset_id=asset.id, raw_object_id=raw.id, version_no=1, source_checksum=raw.checksum, version_status=AssetVersionStatus.PROCESSING)
    ref = models.NormalizedAssetRef(id="ttp-ref", version_id=version.id, normalized_type=NormalizedType.DOCUMENT, object_uri="s3://bucket/normalized/ttp.json", schema_version="normalized-document-v1", checksum="ttp-ref", status=NormalizedAssetRefStatus.GENERATED, governance={}, quality={}, lineage={}, metadata_summary={}, title="杭州万向职业技术学院 跨境电子商务专业人才培养方案")
    session.add_all([ds, batch, raw, asset, version, ref]); session.commit(); return ref


def test_extracts_plan_local_facts_and_courses() -> None:
    plan = extract(_payload())
    assert plan is not None
    assert plan["major_name"] == "跨境电子商务"
    assert plan["major_code"] == "630805"
    assert plan["institution_name"] == "杭州万向职业技术学院"
    assert plan["career_orientation"]["industries"][0]["code"] == "64"
    assert plan["career_orientation"]["occupations"][0]["code"] == "4-01-02"
    assert {item["name"] for item in plan["career_orientation"]["positions"]} == {"跨境电商B2C运营岗", "跨境电商客服岗"}
    mapped_position = next(item for item in plan["career_orientation"]["positions"] if item["name"] == "跨境电商B2C运营岗")
    assert {skill["name"] for skill in mapped_position["skills"]} == {"跨境电商产品挖掘能力", "跨境电商平台操作能力"}
    assert mapped_position["learning_domains"][0]["name"] == "跨境电子商务实务"
    assert plan["courses"][0]["course_name"] == "跨境电子商务实务"
    assert plan["courses"][0]["course_objective"] == "培养跨境平台运营能力"
    assert "国际物流" in plan["courses"][0]["course_content"]
    assert {skill["name"] for skill in plan["courses"][0]["skill_refs"]} == {"跨境电商产品挖掘能力", "跨境电商平台操作能力"}
    assert len(plan["certificates"]) == 2


def test_course_extraction_drops_table_noise_and_requires_content() -> None:
    payload = _payload()
    payload["blocks"].append(_block("b8", html="""
        <table><tr><td>序号</td><td>课程名称</td><td>课程目标</td><td>课程内容</td></tr>
        <tr><td>1</td><td>1</td><td>—</td><td>—</td></tr>
        <tr><td>2</td><td>A</td><td>测试</td><td>内容</td></tr>
        <tr><td>3</td><td>课程名称</td><td>测试</td><td>内容</td></tr>
        <tr><td>4</td><td>Python程序设计</td><td>编程</td><td></td></tr>
        <tr><td>5</td><td>掌握跨境平台运营的基础知识和方法，能够完成店铺日常维护。</td><td>课程目标</td><td>跨境平台运营</td></tr>
        <tr><td>6</td><td>课程内容</td><td>课程目标</td><td>跨境平台运营</td></tr>
        <tr><td>7</td><td>网络营销实务（64课时）</td><td>掌握网络营销</td><td>市场分析、内容运营与效果评估</td></tr>
        </table>
    """))

    plan = extract(payload)

    assert plan is not None
    assert [course["course_name"] for course in plan["courses"]] == [
        "跨境电子商务实务", "网络营销实务",
    ]


def test_course_extraction_accepts_teaching_objective_column_alias() -> None:
    payload = _payload()
    payload["blocks"].append(_block("b9", html="""
        <table><tr><td>序号</td><td>课程名称</td><td>教学目标</td><td>主要教学内容</td></tr>
        <tr><td>1</td><td>客户服务与管理（32课时）</td><td>掌握客户服务与管理方法，具备客户关系维护能力。</td><td>客户服务工具、客户投诉处理与客户关系管理。</td></tr>
        </table>
    """))

    plan = extract(payload)

    assert plan is not None
    course = next(item for item in plan["courses"] if item["course_name"] == "客户服务与管理")
    assert course["course_objective"] == "掌握客户服务与管理方法，具备客户关系维护能力。"
    assert course["course_content"] == "客户服务工具、客户投诉处理与客户关系管理。"


def test_course_extraction_normalizes_semantic_column_headers() -> None:
    payload = _payload()
    payload["blocks"].append(_block("b10", html="""
        <table><tr><td>课程 名称</td><td>课程定位与学习目标</td><td>主 要 教 学 内 容</td><td>课程性质</td></tr>
        <tr><td>客户关系管理（32课时）</td><td>理解客户价值，具备客户关系维护与管理能力。</td><td>客户价值分析、客户分层、客户维护与投诉处理。</td><td>专业核心课</td></tr>
        </table>
    """))

    plan = extract(payload)

    assert plan is not None
    course = next(item for item in plan["courses"] if item["course_name"] == "客户关系管理")
    assert course["course_objective"] == "理解客户价值，具备客户关系维护与管理能力。"
    assert course["course_content"] == "客户价值分析、客户分层、客户维护与投诉处理。"


def test_position_capabilities_split_only_at_preserved_table_structure() -> None:
    payload = _payload()
    payload["blocks"].append(_block("b11", html="""
        <table><tr><td>职业岗位（群）</td><td>岗位核心能力</td><td>学习领域</td></tr>
        <tr><td>跨境电商运营岗</td><td>跨境平台操作能力<br/>网店运营分析能力<div>网络营销推广能力</div></td><td>跨境电子商务实务</td></tr>
        </table>
    """))

    plan = extract(payload)

    assert plan is not None
    position = next(item for item in plan["career_orientation"]["positions"] if item["name"] == "跨境电商运营岗")
    assert [item["name"] for item in position["skills"]] == [
        "跨境平台操作能力", "网店运营分析能力", "网络营销推广能力",
    ]
    assert all(item["evidence"]["table_column"] == "岗位核心能力" for item in position["skills"])


def test_position_capabilities_do_not_guess_boundaries_after_structure_loss() -> None:
    payload = _payload()
    block = _block("b12", html="""
        <table><tr><td>职业岗位（群）</td><td>岗位核心能力</td><td>学习领域</td></tr>
        <tr><td>跨境电商运营岗</td><td>跨境平台操作能力网店运营分析能力网络营销推广能力</td><td>跨境电子商务实务</td></tr>
        </table>
    """)
    block["table_structure_recovery"] = {"status": "structure_lost", "affected_row_indexes": [1]}
    payload["blocks"].append(block)

    plan = extract(payload)

    assert plan is not None
    position = next(item for item in plan["career_orientation"]["positions"] if item["name"] == "跨境电商运营岗")
    assert position["skills"] == []


def test_position_capabilities_use_validated_structure_recovery() -> None:
    payload = _payload()
    block = _block("b13", html="""
        <table><tr><td>职业岗位（群）</td><td>岗位核心能力</td><td>学习领域</td></tr>
        <tr><td>跨境电商运营岗</td><td>跨境平台操作能力网店运营分析能力</td><td>跨境电子商务实务网络营销</td></tr>
        </table>
    """)
    block["table_structure_recovery"] = {
        "status": "recovered",
        "affected_row_indexes": [1],
        "recovered_rows": [{
            "row_index": 1,
            "position_name": "跨境电商运营岗",
            "skills": [{"text": "跨境平台操作能力", "segment_index": 1}, {"text": "网店运营分析能力", "segment_index": 2}],
            "learning_domains": [{"text": "跨境电子商务实务", "segment_index": 1}, {"text": "网络营销", "segment_index": 2}],
        }],
    }
    payload["blocks"].append(block)

    plan = extract(payload)

    assert plan is not None
    position = next(item for item in plan["career_orientation"]["positions"] if item["name"] == "跨境电商运营岗")
    assert [item["name"] for item in position["skills"]] == ["跨境平台操作能力", "网店运营分析能力"]
    assert [item["name"] for item in position["learning_domains"]] == ["跨境电子商务实务", "网络营销"]
    assert position["skills"][1]["evidence"]["cell_segment_index"] == 2
    assert position["skills"][1]["evidence"]["structure_recovery"] == "litellm_default_governance_model"


def test_position_merge_normalizes_layout_whitespace() -> None:
    payload = _payload()
    payload["blocks"].append(_block("b14", html="""
        <table><tr><td>职业岗位（群）</td><td>岗位核心能力</td></tr>
        <tr><td>跨境电商B2C运营 岗</td><td>跨境平台操作能力；网店运营分析能力</td></tr>
        </table>
    """))

    plan = extract(payload)

    assert plan is not None
    matching = [item for item in plan["career_orientation"]["positions"] if item["name"] == "跨境电商B2C运营岗"]
    assert len(matching) == 1
    assert {item["name"] for item in matching[0]["skills"]} >= {"跨境电商平台操作能力", "网店运营分析能力"}


def test_writer_defensively_filters_noise_and_decodes_skill_refs(session) -> None:
    ref = _ref(session)
    payload = extract(_payload())
    assert payload is not None
    payload["courses"] = [
        {"course_name": "1", "course_content": "噪音", "skill_refs": []},
        {"course_name": "电子商务数据分析", "course_content": "", "skill_refs": []},
        {
            "course_name": "跨境运营实务",
            "course_content": "选品、刊登与订单履约",
            "skill_refs": [{"name": r"\u8de8\u5883\u5e73\u53f0\u64cd\u4f5c\u80fd\u529b"}],
        },
    ]

    plan = write(session, ref, payload)

    assert plan is not None
    assert len(plan.courses) == 1
    assert plan.courses[0].course_name == "跨境运营实务"
    assert plan.courses[0].skill_refs == [{"name": "跨境平台操作能力"}]


def test_writer_is_idempotent_and_does_not_create_master_data(session) -> None:
    ref = _ref(session); payload = extract(_payload()); assert payload is not None
    first = write(session, ref, payload); second = write(session, ref, payload)
    assert first is not None and second is not None
    assert session.query(models.TalentTrainingPlan).count() == 1
    assert session.query(models.TalentTrainingPlanCourse).count() == 1
    assert second.career_orientation["positions"][0]["name"] == "跨境电商B2C运营岗"
