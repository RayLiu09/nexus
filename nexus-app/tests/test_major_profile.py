from __future__ import annotations

import json

from sqlalchemy import select

from nexus_app import models
from nexus_app.enums import (
    AssetKind,
    AssetVersionStatus,
    ChunkingStrategy,
    ChunkType,
    DataSourceType,
    IngestBatchStatus,
    NormalizedAssetRefStatus,
    NormalizedType,
    RawObjectStatus,
)
from nexus_app.knowledge.services import run_knowledge_pipeline
from nexus_app.major_profile.schema import blocking_reasons_from_flags, validate_profile_payload
from nexus_app.major_profile.extractor import extract, extract_institution_identity
from nexus_app.major_profile.presentation import reconcile_presentation
from nexus_app.major_profile.writer import write, write_many
from nexus_app.major_profile.llm_fallback import (
    _document_content,
    extract as extract_institution_fallback,
)
from nexus_app.ai_governance.litellm_client import FakeLiteLLMClient


def _blocks() -> list[dict]:
    return [
        _block("b1", "heading", "5307 电子商务类", 1),
        _block("b2", "paragraph", "专业代码 5307\n专业名称 电子商务类\n基本修业年限 三年", 1),
        _block("b3", "heading", "一、职业面向", 2),
        _block("b4", "paragraph", "面向电子商务师、互联网营销师、网店运营专员等职业。", 2),
        _block("b5", "heading", "二、培养目标定位", 2),
        _block("b6", "paragraph", "培养能够从事网络营销、网店运营、客户服务等工作的技术技能人才。", 2),
        _block("b7", "heading", "三、主要专业能力要求", 3),
        _block("b8", "paragraph", "1. 具有互联网产品信息采集、编辑、发布和维护的能力。", 3),
        _block("b9", "paragraph", "2. 具有网店运营、网络营销、客户服务等能力。", 3),
        _block("b10", "heading", "四、主要专业课程与实习实训", 4),
        _block("b11", "paragraph", "专业基础课程：电子商务基础、市场营销。", 4),
        _block("b12", "paragraph", "专业核心课程：网店运营、网络营销。", 4),
        _block("b13", "paragraph", "实习实训：电子商务综合实训、岗位实习。", 4),
        _block("b14", "heading", "五、职业类证书举例", 5),
        _block("b15", "paragraph", "网店运营推广职业技能等级证书、电子商务数据分析职业技能等级证书。", 5),
        _block("b16", "heading", "六、接续专业举例", 5),
        _block(
            "b17",
            "paragraph",
            "接续高职专科专业举例：电子商务、跨境电子商务。\n"
            "接续高职本科专业举例：电子商务、跨境电子商务。\n"
            "接续普通本科专业举例：电子商务、电子商务及法律。",
            5,
        ),
    ]


def _block(block_id: str, block_type: str, text: str, page: int) -> dict:
    idx = int(block_id[1:])
    return {
        "block_id": block_id,
        "block_type": block_type,
        "text": text,
        "page": page,
        "bbox": [72.0, 100.0 + idx, 520.0, 130.0 + idx],
        "md_char_range": [idx * 100, idx * 100 + len(text)],
    }


def _payload() -> dict:
    blocks = _blocks()
    return {
        "content_type": "document",
        "title": "（高职电子商务类专业简介）5307 电子商务类",
        "blocks": blocks,
        "body_markdown": "\n\n".join(b["text"] for b in blocks),
    }


def _seed_ref(session) -> models.NormalizedAssetRef:
    ds = models.DataSource(
        id="ds-mp", code="ds-mp", name="major-profile",
        source_type=DataSourceType.FILE_UPLOAD,
    )
    batch = models.IngestBatch(
        id="batch-mp", data_source_id=ds.id,
        idempotency_key="idem-mp",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.COMPLETED,
    )
    raw = models.RawObject(
        id="raw-mp", batch_id=batch.id, data_source_id=ds.id,
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri="s3://bucket/raw/major-profile.pdf",
        checksum="cs-mp", mime_type="application/pdf",
        status=RawObjectStatus.RAW_PERSISTED,
    )
    asset = models.Asset(
        id="asset-mp", data_source_id=ds.id,
        source_object_key="major-profile.pdf",
        title="major profile", asset_kind=AssetKind.DOCUMENT,
        status=AssetVersionStatus.PROCESSING,
    )
    version = models.AssetVersion(
        id="ver-mp", asset_id=asset.id, raw_object_id=raw.id,
        version_no=1, source_checksum=raw.checksum,
        version_status=AssetVersionStatus.PROCESSING,
    )
    ref = models.NormalizedAssetRef(
        id="ref-mp", version_id=version.id,
        normalized_type=NormalizedType.DOCUMENT,
        object_uri="s3://bucket/normalized/ref-mp.json",
        schema_version="normalized-document-v1",
        checksum="cs-ref-mp",
        status=NormalizedAssetRefStatus.GENERATED,
        governance={}, quality={}, lineage={},
        metadata_summary={"domain_profile": "major_profile.v1"},
        title="（高职电子商务类专业简介）5307 电子商务类",
    )
    session.add_all([ds, batch, raw, asset, version, ref])
    session.commit()
    return ref


def test_extract_major_profile_sections_and_items() -> None:
    profile = extract(_payload())

    assert profile is not None
    assert profile["major_code"] == "5307"
    assert profile["major_name"] == "电子商务类"
    assert profile["education_level"] == "高职"
    assert profile["basic_study_duration"] == "三年"
    assert profile["training_goal"]["text"].startswith("培养能够从事")
    assert len(profile["ability_requirements"]) == 2
    assert profile["courses_and_training"]["foundation_courses"][0]["name"] == "电子商务基础"
    assert profile["courses_and_training"]["core_courses"][0]["name"] == "网店运营"
    practice_training = profile["courses_and_training"]["practice_trainings"]
    assert len(practice_training) == 1
    assert practice_training[0]["name"] == "电子商务综合实训、岗位实习"
    continuations = profile["continuation_majors"]
    assert len(continuations) == 3
    assert continuations[0]["text"] == "接续高职专科专业举例：电子商务、跨境电子商务"
    assert continuations[1]["text"] == "接续高职本科专业举例：电子商务、跨境电子商务"
    assert continuations[2]["text"] == "接续普通本科专业举例：电子商务、电子商务及法律"
    assert {s["section_key"] for s in profile["sections"]} >= {
        "occupation_oriented",
        "training_goal",
        "ability_requirements",
        "courses_and_training",
        "certificates",
        "continuation_majors",
    }
    assert profile["quality_flags"] == {}


def test_institution_profile_llm_fallback_adopts_only_normalized_block_evidence() -> None:
    blocks = [
        _block("b1", "heading", "浙江商业职业技术学院电子商务专业介绍", 1),
        _block("b2", "paragraph", "浙江商业职业技术学院位于浙江省杭州市，开设电子商务专业。", 1),
        _block("b3", "heading", "就业方向", 2),
        _block("b4", "paragraph", "毕业生可从事电商运营、直播运营和网络营销等岗位。", 2),
        _block("b5", "heading", "主要课程", 2),
        _block("b6", "paragraph", "开设电子商务基础、网店运营、直播电商等课程。", 2),
        _block("b7", "heading", "校企合作", 3),
        _block("b8", "paragraph", "专业与杭州数云信息技术有限公司共建直播电商实训基地。", 3),
    ]
    response = {
        "schema_version": "major_profile.institution_extract.v1",
        "institution_name": "浙江商业职业技术学院",
        "major_name": "电子商务专业",
        "region_tags": ["浙江省", "杭州市"],
        "region_evidence_block_ids": ["b2"],
        "occupation_oriented": [{"text": "电商运营、直播运营和网络营销等岗位", "source_text": "电商运营、直播运营和网络营销等岗位", "evidence_block_ids": ["b4"], "confidence": 0.9}],
        "courses_and_training": {"foundation_courses": [{"name": "电子商务基础、网店运营、直播电商等课程", "text": "电子商务基础、网店运营、直播电商等课程", "source_text": "电子商务基础、网店运营、直播电商等课程", "evidence_block_ids": ["b6"], "confidence": 0.9}]},
        "certificates": [],
        "industry_partnerships": [{"text": "专业与杭州数云信息技术有限公司共建直播电商实训基地", "source_text": "专业与杭州数云信息技术有限公司共建直播电商实训基地", "partner_name": "杭州数云信息技术有限公司", "partnership_type": "industry_education", "evidence_block_ids": ["b8"], "confidence": 0.9}],
        "confidence": 0.9,
    }
    result = extract_institution_fallback(
        {"content_type": "document", "title": "电子商务专业介绍", "trusted_title_identity": True, "blocks": blocks},
        llm_client=FakeLiteLLMClient(response_override=json.dumps(response, ensure_ascii=False)),
        model_alias="extraction-test",
    )

    assert result.payload is not None
    assert result.payload["profile_source"] == "institution_profile"
    assert result.payload["institution_name"] == "浙江商业职业技术学院"
    assert result.payload["major_code"] is None
    assert result.payload["region_tags"] == ["浙江省", "杭州市"]
    assert result.payload["industry_partnerships"][0]["partner_name"] == "杭州数云信息技术有限公司"
    assert {section["section_key"] for section in result.payload["sections"]} == {
        "occupation_oriented",
        "courses_and_training",
        "industry_partnerships",
    }


def test_institution_profile_llm_fallback_rejects_unknown_schema_field() -> None:
    response = {
        "schema_version": "major_profile.institution_extract.v1",
        "institution_name": "浙江商业职业技术学院",
        "region_tags": [],
        "major_code": None,
        "major_name": "电子商务专业",
        "courses_and_training": {"foundation_courses": [], "core_courses": [], "practice_trainings": []},
        "confidence": 0.9,
        "hallucinated_field": "must be rejected",
    }
    result = extract_institution_fallback(
        {"content_type": "document", "title": "电子商务专业介绍", "blocks": [_block("b1", "paragraph", "浙江商业职业技术学院电子商务专业", 1)]},
        llm_client=FakeLiteLLMClient(response_override=json.dumps(response, ensure_ascii=False)),
        model_alias="extraction-test",
    )

    assert result.payload is None
    assert result.metadata["reason"] == "llm_schema_invalid"


def test_institution_identity_is_recovered_from_generic_title_body_evidence() -> None:
    identity = extract_institution_identity({
        "content_type": "document",
        "title": "专业介绍",
        "source_url": "https://jgxy.mju.edu.cn/zyjs/list.htm",
        "blocks": [
            _block("b1", "paragraph", "旅游管理专业作为闽江学院首批6个本科专业之一。", 1),
        ],
    })

    assert identity == {
        "institution_name": "闽江学院",
        "evidence_source": "normalized_block",
        "evidence_block_ids": ["b1"],
        "source_url": "https://jgxy.mju.edu.cn/zyjs/list.htm",
    }


def test_institution_profile_repairs_only_exact_block_evidence() -> None:
    blocks = [
        _block("b1", "paragraph", "浙江商业职业技术学院开设电子商务专业。", 1),
        _block("b2", "paragraph", "毕业生可从事电商运营岗位。", 2),
        _block("b3", "paragraph", "开设网店运营课程。", 3),
    ]
    response = {
        "schema_version": "major_profile.institution_extract.v1",
        "institution_name": "浙江商业职业技术学院",
        "region_tags": [],
        "region_evidence_block_ids": [],
        "major_code": None,
        "major_name": "电子商务专业",
        "education_level": None,
        "occupation_oriented": [{"text": "电商运营岗位", "source_text": "电商运营岗位", "evidence_block_ids": ["b1", "b2"], "confidence": 0.9}],
        "courses_and_training": {"foundation_courses": [{"name": "网店运营", "text": "网店运营", "source_text": "网店运营", "evidence_block_ids": ["b2"], "confidence": 0.9}]},
        "certificates": [{"text": "不存在的证书", "source_text": "不存在的证书", "evidence_block_ids": ["b3"], "confidence": 0.9}],
        "industry_partnerships": [],
        "confidence": 0.9,
    }

    result = extract_institution_fallback(
        {"content_type": "document", "title": "电子商务专业介绍", "blocks": blocks},
        llm_client=FakeLiteLLMClient(response_override=json.dumps(response, ensure_ascii=False)),
        model_alias="extraction-test",
    )

    assert result.payload is not None
    assert result.payload["occupation_oriented"][0]["evidence_block_ids"] == ["b2"]
    assert result.payload["courses_and_training"]["foundation_courses"][0]["evidence_block_ids"] == ["b3"]
    assert result.payload["certificates"] == []
    assert result.metadata["evidence_validation"] == {
        "verified_items": 2,
        "discarded_items": 1,
        "rebound_items": 2,
    }


def test_institution_profile_expands_delimited_courses_into_aggregation_rows() -> None:
    blocks = [
        _block("b1", "paragraph", "浙江商业职业技术学院开设电子商务专业。", 1),
        _block("b2", "paragraph", "开设电子商务基础、网店运营、直播电商等课程。", 2),
    ]
    response = {
        "schema_version": "major_profile.institution_extract.v1",
        "institution_name": "浙江商业职业技术学院", "region_tags": [], "region_evidence_block_ids": [],
        "major_code": None, "major_name": "电子商务专业", "education_level": None,
        "occupation_oriented": [],
        "courses_and_training": {"foundation_courses": [{"name": "电子商务基础、网店运营、直播电商等课程", "text": "电子商务基础、网店运营、直播电商等课程", "source_text": "开设电子商务基础、网店运营、直播电商等课程", "evidence_block_ids": ["b2"], "confidence": 0.9}]},
        "certificates": [], "industry_partnerships": [], "confidence": 0.9,
    }
    result = extract_institution_fallback(
        {"content_type": "document", "title": "电子商务专业介绍", "blocks": blocks},
        llm_client=FakeLiteLLMClient(response_override=json.dumps(response, ensure_ascii=False)),
        model_alias="extraction-test",
    )

    assert result.payload is not None
    courses = result.payload["courses_and_training"]["foundation_courses"]
    assert [course["name"] for course in courses] == ["电子商务基础", "网店运营", "直播电商"]
    assert all(course["source_text"] == "开设电子商务基础、网店运营、直播电商等课程" for course in courses)


def test_institution_profile_rejects_when_no_professional_fact_is_verbatim() -> None:
    response = {
        "schema_version": "major_profile.institution_extract.v1",
        "institution_name": "浙江商业职业技术学院",
        "region_tags": [],
        "region_evidence_block_ids": [],
        "major_code": None,
        "major_name": "电子商务专业",
        "education_level": None,
        "occupation_oriented": [{"text": "电商运营", "source_text": "模型概括的职业方向", "evidence_block_ids": ["b2"], "confidence": 0.9}],
        "courses_and_training": {"foundation_courses": [], "core_courses": [], "practice_trainings": []},
        "certificates": [],
        "industry_partnerships": [],
        "confidence": 0.9,
    }
    result = extract_institution_fallback(
        {"content_type": "document", "title": "电子商务专业介绍", "blocks": [
            _block("b1", "paragraph", "浙江商业职业技术学院开设电子商务专业。", 1),
            _block("b2", "paragraph", "毕业生可从事电商运营岗位。", 2),
        ]},
        llm_client=FakeLiteLLMClient(response_override=json.dumps(response, ensure_ascii=False)),
        model_alias="extraction-test",
    )

    assert result.payload is None
    assert result.metadata["reason"] == "llm_evidence_or_confidence_invalid"


def test_institution_profile_recovers_source_spelling_for_layout_only_differences() -> None:
    blocks = [
        _block("b1", "paragraph", "浙江商业职业技术学院开设电子商务专业。", 1),
        _block("b2", "paragraph", "毕业生可从事电商运营、直播运营岗位。", 2),
    ]
    response = {
        "schema_version": "major_profile.institution_extract.v1",
        "institution_name": "浙江商业职业技术学院",
        "region_tags": [], "region_evidence_block_ids": [], "major_code": None,
        "major_name": "电子商务专业", "education_level": None,
        "occupation_oriented": [{"text": "电商运营、直播运营岗位", "source_text": "电商运营, 直播运营岗位", "evidence_block_ids": ["b2"], "confidence": 0.9}],
        "courses_and_training": {"foundation_courses": [], "core_courses": [], "practice_trainings": []},
        "certificates": [], "industry_partnerships": [], "confidence": 0.9,
    }
    result = extract_institution_fallback(
        {"content_type": "document", "title": "电子商务专业介绍", "blocks": blocks},
        llm_client=FakeLiteLLMClient(response_override=json.dumps(response, ensure_ascii=False)),
        model_alias="extraction-test",
    )

    assert result.payload is not None
    assert result.payload["occupation_oriented"][0]["source_text"] == "电商运营、直播运营岗位"


def test_institution_profile_accepts_institution_identity_from_normalized_title() -> None:
    blocks = [
        _block("b1", "heading", "跨境电子商务", 1),
        _block("b2", "paragraph", "开设跨境电子商务基础、跨境电商运营管理课程。", 2),
        _block("b3", "paragraph", "可从事跨境电商运营、海外推广等岗位。", 3),
    ]
    response = {
        "schema_version": "major_profile.institution_extract.v1",
        "institution_name": "浙江工贸职业技术学院", "region_tags": [], "region_evidence_block_ids": [],
        "major_code": None, "major_name": "跨境电子商务", "education_level": None,
        "occupation_oriented": [{"text": "跨境电商运营、海外推广等岗位", "source_text": "可从事跨境电商运营、海外推广等岗位。", "evidence_block_ids": ["b3"], "confidence": 0.9}],
        "courses_and_training": {"foundation_courses": [{"name": "跨境电子商务基础", "text": "跨境电子商务基础", "source_text": "开设跨境电子商务基础、跨境电商运营管理课程。", "evidence_block_ids": ["b2"], "confidence": 0.9}]},
        "certificates": [], "industry_partnerships": [], "confidence": 0.9,
    }
    result = extract_institution_fallback(
        {"content_type": "document", "title": "浙江工贸职业技术学院 跨境电子商务专业简介.docx", "trusted_title_identity": True, "blocks": blocks},
        llm_client=FakeLiteLLMClient(response_override=json.dumps(response, ensure_ascii=False)),
        model_alias="extraction-test",
    )

    assert result.payload is not None
    assert result.metadata["evidence_validation"]["identity_from_normalized_title"] == 1


def test_institution_profile_accepts_major_identity_from_normalized_title() -> None:
    blocks = [
        _block("b1", "paragraph", "浙江工贸职业技术学院开设跨境电商基础课程。", 1),
        _block("b2", "paragraph", "毕业生可从事跨境电商运营岗位。", 2),
    ]
    response = {
        "schema_version": "major_profile.institution_extract.v1",
        "institution_name": "浙江工贸职业技术学院", "region_tags": [], "region_evidence_block_ids": [],
        "major_code": None, "major_name": "跨境电子商务专业", "education_level": None,
        "occupation_oriented": [{"text": "跨境电商运营岗位", "source_text": "跨境电商运营岗位", "evidence_block_ids": ["b2"], "confidence": 0.9}],
        "courses_and_training": {"foundation_courses": [], "core_courses": [], "practice_trainings": []},
        "certificates": [], "industry_partnerships": [], "confidence": 0.9,
    }
    result = extract_institution_fallback(
        {"content_type": "document", "title": "浙江工贸职业技术学院 跨境电子商务专业简介.docx", "trusted_title_identity": True, "blocks": blocks},
        llm_client=FakeLiteLLMClient(response_override=json.dumps(response, ensure_ascii=False)),
        model_alias="extraction-test",
    )

    assert result.payload is not None
    assert result.metadata["evidence_validation"]["major_identity_from_normalized_title"] == 1


def test_institution_llm_input_contains_every_normalized_block_once() -> None:
    blocks = [
        {"block_id": f"b-{index}", "block_type": "paragraph", "text": f"完整正文第 {index} 段"}
        for index in range(1, 121)
    ]

    content = _document_content(blocks)

    assert "[b-1] (paragraph)\n完整正文第 1 段" in content
    assert "[b-120] (paragraph)\n完整正文第 120 段" in content
    assert content.count("[b-") == 120


def test_report_with_cip_number_and_professional_terms_is_not_major_profile() -> None:
    """Publication metadata must not become a professional identity."""
    blocks = [
        _block("b1", "heading", "北京市人才发展报告 9085 号", 1),
        _block("b2", "heading", "职业面向", 1),
        _block("b3", "paragraph", "报告讨论人才服务机构的职业面向。", 1),
        _block("b4", "heading", "培养目标", 2),
        _block("b5", "paragraph", "报告分析人才培养目标。", 2),
        _block("b6", "heading", "专业能力要求", 2),
        _block("b7", "paragraph", "报告汇总专业能力要求的政策背景。", 2),
        _block("b8", "heading", "课程设置", 3),
        _block("b9", "paragraph", "报告比较课程设置与人才发展关系。", 3),
    ]
    payload = {
        "content_type": "document",
        "title": "北京市人才发展报告 9085 号",
        "blocks": blocks,
        "body_markdown": "\n\n".join(block["text"] for block in blocks),
    }

    assert extract(payload) is None


def test_major_profile_schema_adds_blocking_quality_flags() -> None:
    profile = {
        "schema_version": "major_profile.v1",
        "domain": "major",
        "domain_profile": "major_profile.v1",
        "major_code": "530701",
        "major_name": "电子商务",
        "courses_and_training": {
            "foundation_courses": [{"text": "电子商务基础"}],
            "core_courses": [],
            "practice_trainings": [{"text": "岗位实习"}],
        },
    }

    validated, flags = validate_profile_payload(profile)

    assert validated["quality_flags"]["missing_occupation_oriented"] is True
    assert validated["quality_flags"]["missing_training_goal"] is True
    assert validated["quality_flags"]["missing_ability_requirements"] is True
    assert validated["quality_flags"]["missing_core_courses"] is True
    assert "major_profile.missing_training_goal" in blocking_reasons_from_flags(flags)


def test_reconcile_presentation_suppresses_incompatible_official_classification(session) -> None:
    ref = _seed_ref(session)
    ref.metadata_summary = {
        "domain_profile": "major_profile.v1",
        "domain_profiles": [{"major_code": "9085", "major_name": "号"}],
        "major_profile_count": 1,
        "knowledge_emissions": [{"code": "industry_research_kb"}],
    }

    detail = reconcile_presentation(ref, "industry_report")

    assert detail is not None
    assert detail["reason"] == "official_classification_incompatible"
    assert "domain_profile" not in ref.metadata_summary
    assert "domain_profiles" not in ref.metadata_summary
    assert "major_profile_count" not in ref.metadata_summary
    assert ref.metadata_summary["knowledge_emissions"] == [{"code": "industry_research_kb"}]


def test_reconcile_presentation_keeps_legacy_program_profile(session) -> None:
    ref = _seed_ref(session)

    assert reconcile_presentation(ref, "program_profile") is None
    assert ref.metadata_summary["domain_profile"] == "major_profile.v1"


def test_extract_multiple_major_profiles_from_one_document() -> None:
    blocks = _blocks() + [
        _block("b18", "paragraph", "专业代码 530701\n专业名称 电子商务\n基本修业年限 三年", 6),
        _block("b19", "heading", "一、职业面向", 6),
        _block("b20", "paragraph", "面向电子商务师、客户服务管理员等职业。", 6),
        _block("b21", "heading", "二、培养目标定位", 6),
        _block("b22", "paragraph", "培养能够从事店铺运营辅助、客户服务等工作的技术技能人才。", 6),
        _block("b23", "heading", "三、主要专业能力要求", 7),
        _block("b24", "paragraph", "1. 具有店铺运营维护能力。", 7),
        _block("b25", "heading", "四、主要专业课程与实习实训", 7),
        _block("b26", "paragraph", "专业基础课程：电子商务基础。专业核心课程：网店运营。实习实训：岗位实习。", 7),
        _block("b27", "paragraph", "专业代码 530702\n专业名称 跨境电子商务\n基本修业年限 三年", 8),
        _block("b28", "heading", "一、职业面向", 8),
        _block("b29", "paragraph", "面向跨境运营助理、跨境客服专员等岗位。", 8),
        _block("b30", "heading", "二、培养目标定位", 8),
        _block("b31", "paragraph", "培养能够从事跨境店铺运营辅助等工作的技术技能人才。", 8),
        _block("b32", "heading", "三、主要专业能力要求", 9),
        _block("b33", "paragraph", "1. 具有跨境商品发布能力。", 9),
        _block("b34", "heading", "四、主要专业课程与实习实训", 9),
        _block("b35", "paragraph", "专业基础课程：跨境电子商务基础。专业核心课程：跨境店铺运维。实习实训：岗位实习。", 9),
    ]
    payload = {
        "content_type": "document",
        "title": "5307 电子商务类",
        "blocks": blocks,
        "body_markdown": "\n\n".join(b["text"] for b in blocks),
    }

    profile = extract(payload)

    assert profile is not None
    assert profile["profile_count"] == 2
    assert [p["major_code"] for p in profile["profiles"]] == ["530701", "530702"]
    assert profile["profiles"][1]["major_name"] == "跨境电子商务"


def test_extract_multiple_major_profiles_when_identity_spans_adjacent_blocks() -> None:
    blocks = [
        _block("b1", "heading", "7307 电子商务类", 1),
        _block("b2", "paragraph", "专业代码 730701", 1),
        _block("b3", "paragraph", "专业名称 电子商务", 1),
        _block("b4", "paragraph", "基本修业年限 三年", 1),
        _block("b5", "heading", "职业面向", 1),
        _block("b6", "paragraph", "面向电子商务师、互联网营销师等职业。", 1),
        _block("b7", "heading", "培养目标定位", 1),
        _block("b8", "paragraph", "培养能够从事店铺运营辅助等工作的技术技能人才。", 1),
        _block("b9", "heading", "主要专业能力要求", 1),
        _block("b10", "paragraph", "1. 具有店铺运营维护能力。", 1),
        _block("b11", "heading", "主要专业课程与实习实训", 1),
        _block("b12", "paragraph", "专业基础课程：电子商务基础。专业核心课程：网店运营。实习实训：岗位实习。", 1),
        _block("b13", "paragraph", "专业代码 730702", 2),
        _block("b14", "paragraph", "专业名称 跨境电子商务", 2),
        _block("b15", "paragraph", "基本修业年限 三年", 2),
        _block("b16", "heading", "职业面向", 2),
        _block("b17", "paragraph", "面向跨境运营助理、跨境客服专员等岗位。", 2),
        _block("b18", "heading", "培养目标定位", 2),
        _block("b19", "paragraph", "培养能够从事跨境店铺运营辅助等工作的技术技能人才。", 2),
        _block("b20", "heading", "主要专业能力要求", 2),
        _block("b21", "paragraph", "1. 具有跨境商品发布能力。", 2),
        _block("b22", "heading", "主要专业课程与实习实训", 2),
        _block("b23", "paragraph", "专业基础课程：跨境电子商务基础。专业核心课程：跨境店铺运维。实习实训：岗位实习。", 2),
    ]
    payload = {
        "content_type": "document",
        "title": "7307 电子商务类",
        "blocks": blocks,
        "body_markdown": "\n\n".join(b["text"] for b in blocks),
    }

    profile = extract(payload)

    assert profile is not None
    assert profile["profile_count"] == 2
    assert [p["major_code"] for p in profile["profiles"]] == ["730701", "730702"]
    assert [p["major_name"] for p in profile["profiles"]] == ["电子商务", "跨境电子商务"]
    assert profile["profiles"][0]["sections"][0]["source_block_ids"] == ["b6"]


def test_extract_continuation_categories_when_heading_and_content_are_split() -> None:
    blocks = [
        _block("b1", "heading", "专业代码 730701\n专业名称 电子商务\n基本修业年限 三年", 1),
        _block("b2", "heading", "职业面向", 1),
        _block("b3", "paragraph", "面向电子商务师等职业。", 1),
        _block("b4", "heading", "培养目标定位", 1),
        _block("b5", "paragraph", "培养能够从事店铺运营等工作的技术技能人才。", 1),
        _block("b6", "heading", "主要专业能力要求", 1),
        _block("b7", "paragraph", "1. 具有店铺运营维护能力。", 1),
        _block("b8", "heading", "主要专业课程与实习实训", 1),
        _block("b9", "paragraph", "专业基础课程：电子商务基础。专业核心课程：网店运营。实习实训：校内综合实训、岗位实习。", 1),
        _block("b10", "heading", "接续高职专科专业举例", 2),
        _block("b11", "paragraph", "电子商务、网络营销与直播电商、跨境电子商务。", 2),
        _block("b12", "heading", "接续高职本科专业举例", 2),
        _block("b13", "paragraph", "电子商务、跨境电子商务、全媒体电商运营。", 2),
        _block("b14", "heading", "接续普通本科专业举例", 2),
        _block("b15", "paragraph", "电子商务、电子商务及法律、市场营销。", 2),
    ]
    payload = {
        "content_type": "document",
        "title": "730701 电子商务",
        "blocks": blocks,
        "body_markdown": "\n\n".join(b["text"] for b in blocks),
    }

    profile = extract(payload)

    assert profile is not None
    continuations = profile["continuation_majors"]
    assert [item["text"] for item in continuations] == [
        "接续高职专科专业举例：电子商务、网络营销与直播电商、跨境电子商务",
        "接续高职本科专业举例：电子商务、跨境电子商务、全媒体电商运营",
        "接续普通本科专业举例：电子商务、电子商务及法律、市场营销",
    ]


def test_write_major_profile_domain_tables(session) -> None:
    ref = _seed_ref(session)
    profile_payload = extract(_payload())

    profile = write(session, ref, profile_payload)
    session.commit()

    assert profile is not None
    assert profile.major_code == "5307"
    assert profile.major_name == "电子商务类"
    assert profile.training_goal.startswith("培养能够从事")
    assert len(list(session.scalars(select(models.MajorProfileAbility)).all())) == 2
    courses = list(session.scalars(select(models.MajorProfileCourse)).all())
    assert {c.course_group for c in courses} == {"foundation", "core", "practice_training"}
    assert session.scalar(select(models.MajorProfileCertificate)) is not None
    assert session.scalar(select(models.MajorProfileContinuation)) is not None


def test_write_multiple_major_profiles_for_one_ref(session) -> None:
    ref = _seed_ref(session)
    profile_payload = {
        "schema_version": "major_profile.v1",
        "profiles": [
            {**extract(_payload()), "major_code": "530701", "major_name": "电子商务"},
            {**extract(_payload()), "major_code": "530702", "major_name": "跨境电子商务"},
        ],
    }

    profiles = write_many(session, ref, profile_payload)
    session.commit()

    assert len(profiles) == 2
    rows = list(session.scalars(select(models.MajorProfile).order_by(models.MajorProfile.major_code)).all())
    assert [(row.major_code, row.major_name) for row in rows] == [
        ("530701", "电子商务"),
        ("530702", "跨境电子商务"),
    ]


def test_major_profile_chunks_are_section_level_not_item_level() -> None:
    payload = _payload()
    profile = extract(payload)
    chunks = run_knowledge_pipeline(
        payload["body_markdown"],
        [{
            "code": "major_profile_knowledge",
            "name": "专业介绍知识",
            "primary": True,
            "confidence": 0.9,
            "source": "test",
            "major_profile": profile,
        }],
        "ref-mp",
        content_blocks=payload["blocks"],
    )

    section_keys = {chunk.chunk_metadata["section_key"] for chunk in chunks}
    assert section_keys == {
        "occupation_oriented",
        "training_goal",
        "ability_requirements",
        "courses_and_training",
        "certificates",
        "continuation_majors",
    }
    assert len(chunks) == 6
    ability_chunks = [
        c for c in chunks if c.chunk_metadata["section_key"] == "ability_requirements"
    ]
    assert len(ability_chunks) == 1
    assert "1. 具有互联网产品信息采集" in ability_chunks[0].content
    assert "2. 具有网店运营" in ability_chunks[0].content
    assert ability_chunks[0].chunk_type == ChunkType.SEMANTIC_BLOCK
    assert ability_chunks[0].chunking_strategy == ChunkingStrategy.MAJOR_PROFILE_DECOMPOSE
    assert ability_chunks[0].source_block_ids == ["b8", "b9"]
    assert ability_chunks[0].locator is not None
