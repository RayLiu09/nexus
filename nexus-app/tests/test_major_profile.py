from __future__ import annotations

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
from nexus_app.major_profile.extractor import extract
from nexus_app.major_profile.writer import write


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
        _block("b17", "paragraph", "电子商务、跨境电子商务。", 5),
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
    assert profile["courses_and_training"]["practice_trainings"][0]["name"] == "电子商务综合实训"
    assert {s["section_key"] for s in profile["sections"]} >= {
        "occupation_oriented",
        "training_goal",
        "ability_requirements",
        "courses_and_training",
        "certificates",
        "continuation_majors",
    }


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

