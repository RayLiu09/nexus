from __future__ import annotations

import pytest
from sqlalchemy import event

from nexus_api.api import major_profiles
from nexus_api.dependencies import Pagination
from nexus_app import models
from nexus_app.enums import (
    AssetKind,
    AssetVersionStatus,
    DataSourceType,
    GovernanceResultStatus,
    IngestBatchStatus,
    NormalizedAssetRefStatus,
    NormalizedType,
    RawObjectStatus,
)

PAGE = Pagination(page=1, page_size=20)


def _body(resp):
    return resp.model_dump(mode="json")


def _seed_anchor(
    session,
    *,
    ref_id: str,
    version_id: str,
    status: AssetVersionStatus = AssetVersionStatus.AVAILABLE,
) -> models.NormalizedAssetRef:
    ds = models.DataSource(
        id=f"ds-{ref_id}", code=f"ds-{ref_id}", name="major-profile-api",
        source_type=DataSourceType.FILE_UPLOAD,
    )
    batch = models.IngestBatch(
        id=f"batch-{ref_id}", data_source_id=ds.id,
        idempotency_key=f"idem-{ref_id}",
        source_type=DataSourceType.FILE_UPLOAD,
        status=IngestBatchStatus.COMPLETED,
    )
    raw = models.RawObject(
        id=f"raw-{ref_id}", batch_id=batch.id, data_source_id=ds.id,
        source_type=DataSourceType.FILE_UPLOAD,
        object_uri=f"s3://bucket/raw/{ref_id}.pdf",
        checksum=f"cs-{ref_id}", mime_type="application/pdf",
        status=RawObjectStatus.RAW_PERSISTED,
    )
    asset = models.Asset(
        id=f"asset-{ref_id}", data_source_id=ds.id,
        source_object_key=f"{ref_id}.pdf",
        title="major profile", asset_kind=AssetKind.DOCUMENT,
        status=status,
    )
    version = models.AssetVersion(
        id=version_id, asset_id=asset.id, raw_object_id=raw.id,
        version_no=1, source_checksum=raw.checksum,
        version_status=status,
    )
    ref = models.NormalizedAssetRef(
        id=ref_id, version_id=version.id,
        normalized_type=NormalizedType.DOCUMENT,
        object_uri=f"s3://bucket/normalized/{ref_id}.json",
        schema_version="normalized-document-v1",
        checksum=f"cs-ref-{ref_id}",
        status=NormalizedAssetRefStatus.GENERATED,
        governance={}, quality={}, lineage={},
        metadata_summary={"domain_profile": "major_profile.v1"},
        title="5307 电子商务类",
    )
    session.add_all([ds, batch, raw, asset, version, ref])
    session.commit()
    return ref


def _seed_profile(
    session,
    *,
    ref: models.NormalizedAssetRef,
    profile_id: str = "mp-api",
    major_code: str = "5307",
    major_name: str = "电子商务类",
) -> models.MajorProfile:
    profile = models.MajorProfile(
        id=profile_id,
        normalized_ref_id=ref.id,
        asset_version_id=ref.version_id,
        domain_profile="major_profile.v1",
        major_code=major_code,
        major_name=major_name,
        education_level="高职",
        basic_study_duration="三年",
        training_goal="培养能够从事网络营销、网店运营、客户服务等工作的技术技能人才。",
        source_title=ref.title,
        extractor_version="major_profile_extractor.v1",
        confidence=0.9,
        evidence={},
        quality_flags={},
        status="generated",
    )
    session.add(profile)
    session.flush()
    session.add_all([
        models.MajorProfileOccupation(
            id=f"{profile_id}-occ",
            profile_id=profile.id,
            normalized_ref_id=ref.id,
            item_index=1,
            text="电子商务师",
            source_text="电子商务师",
            evidence_block_ids=["b1"],
            locator={},
            confidence=0.9,
            normalized_name="电子商务师",
            occupation_type="occupation",
        ),
        models.MajorProfileAbility(
            id=f"{profile_id}-abi",
            profile_id=profile.id,
            normalized_ref_id=ref.id,
            item_index=1,
            text="具有网店运营能力",
            source_text="具有网店运营能力",
            evidence_block_ids=["b2"],
            locator={},
            confidence=0.9,
        ),
        models.MajorProfileCourse(
            id=f"{profile_id}-course",
            profile_id=profile.id,
            normalized_ref_id=ref.id,
            item_index=1,
            text="电子商务基础",
            source_text="电子商务基础",
            evidence_block_ids=["b3"],
            locator={},
            confidence=0.9,
            course_group="foundation",
            course_type="course",
        ),
        models.MajorProfileCertificate(
            id=f"{profile_id}-cert",
            profile_id=profile.id,
            normalized_ref_id=ref.id,
            item_index=1,
            text="网店运营推广职业技能等级证书",
            source_text="网店运营推广职业技能等级证书",
            evidence_block_ids=["b4"],
            locator={},
            confidence=0.9,
            certificate_type="vocational_skill_level",
        ),
        models.MajorProfileContinuation(
            id=f"{profile_id}-cont",
            profile_id=profile.id,
            normalized_ref_id=ref.id,
            item_index=1,
            text="电子商务",
            source_text="电子商务",
            evidence_block_ids=["b5"],
            locator={},
            confidence=0.9,
        ),
    ])
    session.commit()
    return profile


def test_internal_list_filters_by_occupation(fake_request, session) -> None:
    ref = _seed_anchor(session, ref_id="ref-mp-api", version_id="ver-mp-api")
    _seed_profile(session, ref=ref)

    resp = major_profiles.list_internal_major_profiles(
        request=fake_request,
        major_code=None,
        major_name=None,
        occupation="电子商务师",
        training_goal=None,
        ability=None,
        course=None,
        course_group=None,
        certificate=None,
        continuation=None,
        education_level=None,
        normalized_ref_id=None,
        pagination=PAGE,
        session=session,
    )

    body = _body(resp)
    assert body["meta"]["total"] == 1
    assert body["data"][0]["major_code"] == "5307"


def test_internal_list_filters_by_major_name_and_education_level(fake_request, session) -> None:
    ref = _seed_anchor(session, ref_id="ref-mp-api", version_id="ver-mp-api")
    _seed_profile(session, ref=ref, major_name="电子商务类")

    resp = major_profiles.list_internal_major_profiles(
        request=fake_request,
        major_code=None,
        major_name="商务",
        occupation=None,
        training_goal=None,
        ability=None,
        course=None,
        course_group=None,
        certificate=None,
        continuation=None,
        education_level="高职",
        normalized_ref_id=None,
        pagination=PAGE,
        session=session,
    )

    body = _body(resp)
    assert body["meta"]["total"] == 1
    assert body["data"][0]["major_name"] == "电子商务类"


def test_internal_get_by_normalized_ref(fake_request, session) -> None:
    ref = _seed_anchor(session, ref_id="ref-mp-api", version_id="ver-mp-api")
    profile = _seed_profile(session, ref=ref)

    resp = major_profiles.get_internal_major_profile_by_ref(
        ref_id=ref.id,
        request=fake_request,
        session=session,
    )

    body = _body(resp)["data"]
    assert body["id"] == profile.id
    assert body["counts"]["ability_count"] == 1
    assert body["occupations"][0]["text"] == "电子商务师"
    assert body["courses"][0]["course_group"] == "foundation"


def test_internal_list_filters_by_domain_child_fields(fake_request, session) -> None:
    ref = _seed_anchor(session, ref_id="ref-mp-api", version_id="ver-mp-api")
    _seed_profile(session, ref=ref)

    resp = major_profiles.list_internal_major_profiles(
        request=fake_request,
        major_code=None,
        major_name=None,
        occupation=None,
        training_goal="网店运营",
        ability="网店运营能力",
        course="电子商务基础",
        course_group="foundation",
        certificate="职业技能等级证书",
        continuation="电子商务",
        education_level=None,
        normalized_ref_id=None,
        pagination=PAGE,
        session=session,
    )

    body = _body(resp)
    assert body["meta"]["total"] == 1
    assert body["data"][0]["major_code"] == "5307"


def test_internal_list_by_normalized_ref_returns_multiple_profiles(fake_request, session) -> None:
    ref = _seed_anchor(session, ref_id="ref-mp-api", version_id="ver-mp-api")
    _seed_profile(
        session,
        ref=ref,
        profile_id="mp-530701",
        major_code="530701",
        major_name="电子商务",
    )
    _seed_profile(
        session,
        ref=ref,
        profile_id="mp-530702",
        major_code="530702",
        major_name="跨境电子商务",
    )

    resp = major_profiles.list_internal_major_profiles_by_ref(
        ref_id=ref.id,
        request=fake_request,
        session=session,
    )

    body = _body(resp)["data"]
    assert [item["major_code"] for item in body] == ["530701", "530702"]
    assert body[1]["major_name"] == "跨境电子商务"


def test_internal_list_by_normalized_ref_returns_empty_list(fake_request, session) -> None:
    ref = _seed_anchor(session, ref_id="ref-mp-api", version_id="ver-mp-api")

    resp = major_profiles.list_internal_major_profiles_by_ref(
        ref_id=ref.id,
        request=fake_request,
        session=session,
    )

    assert _body(resp)["data"] == []


def test_internal_business_list_uses_official_current_projection_without_child_queries(
    fake_request, session
) -> None:
    candidates = [
        ("available", AssetVersionStatus.AVAILABLE, "major_profile", "mp-available"),
        ("review", AssetVersionStatus.REVIEW_REQUIRED, "program_profile", "mp-review"),
        ("wrong", AssetVersionStatus.AVAILABLE, "teaching_standard", "mp-wrong"),
        ("failed", AssetVersionStatus.FAILED, "major_profile", "mp-failed"),
        (
            "superseded",
            AssetVersionStatus.REVIEW_REQUIRED,
            "major_profile",
            "mp-superseded",
        ),
    ]
    for suffix, status, classification, profile_id in candidates:
        ref = _seed_anchor(
            session,
            ref_id=f"ref-mp-{suffix}",
            version_id=f"ver-mp-{suffix}",
            status=status,
        )
        profile = _seed_profile(
            session,
            ref=ref,
            profile_id=profile_id,
            major_code=f"code-{suffix}",
            major_name=f"专业-{suffix}",
        )
        profile.institution_name = "浙江职业技术学院"
        session.add(
            models.GovernanceResult(
                normalized_ref_id=ref.id,
                classification=classification,
                index_admission=status == AssetVersionStatus.AVAILABLE,
                status=(
                    GovernanceResultStatus.AVAILABLE
                    if status == AssetVersionStatus.AVAILABLE
                    else GovernanceResultStatus.REVIEW_REQUIRED
                ),
            )
        )
    superseded_ref = session.get(models.NormalizedAssetRef, "ref-mp-superseded")
    superseded_version = session.get(models.AssetVersion, "ver-mp-superseded")
    assert superseded_ref is not None
    assert superseded_version is not None
    successor_version = models.AssetVersion(
        id="ver-mp-successor",
        asset_id=superseded_version.asset_id,
        raw_object_id=superseded_version.raw_object_id,
        version_no=2,
        source_checksum="cs-mp-successor",
        version_status=AssetVersionStatus.AVAILABLE,
    )
    successor_ref = models.NormalizedAssetRef(
        id="ref-mp-successor",
        version_id=successor_version.id,
        normalized_type=NormalizedType.DOCUMENT,
        object_uri="s3://bucket/normalized/ref-mp-successor.json",
        schema_version="normalized-document-v1",
        checksum="cs-ref-mp-successor",
        status=NormalizedAssetRefStatus.GENERATED,
        governance={},
        quality={},
        lineage={},
        metadata_summary={"domain_profile": "major_profile.v1"},
        title="后续版本专业简介",
    )
    session.add_all(
        [
            successor_version,
            successor_ref,
            models.GovernanceResult(
                normalized_ref_id=successor_ref.id,
                classification="major_profile",
                index_admission=True,
                status=GovernanceResultStatus.AVAILABLE,
            ),
        ]
    )
    session.commit()

    statements: list[str] = []

    def record_statement(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(session.bind, "before_cursor_execute", record_statement)
    try:
        resp = major_profiles.list_internal_major_profiles(
            request=fake_request,
            institution_name="浙江职业",
            official_only=True,
            catalog_visible_only=True,
            pagination=PAGE,
            session=session,
        )
    finally:
        event.remove(session.bind, "before_cursor_execute", record_statement)

    body = _body(resp)
    assert body["meta"]["total"] == 2
    assert {item["id"] for item in body["data"]} == {"mp-available", "mp-review"}
    assert len(statements) == 2
    joined_sql = "\n".join(statements)
    for child_table in (
        "major_profile_occupation",
        "major_profile_ability",
        "major_profile_course",
        "major_profile_certificate",
    ):
        assert child_table not in joined_sql


def test_open_list_returns_only_available(fake_request, session) -> None:
    available_ref = _seed_anchor(
        session, ref_id="ref-mp-api-ok", version_id="ver-mp-api-ok",
        status=AssetVersionStatus.AVAILABLE,
    )
    review_ref = _seed_anchor(
        session, ref_id="ref-mp-api-review", version_id="ver-mp-api-review",
        status=AssetVersionStatus.REVIEW_REQUIRED,
    )
    _seed_profile(session, ref=available_ref, profile_id="mp-ok")
    _seed_profile(
        session, ref=review_ref, profile_id="mp-review",
        major_code="7307", major_name="电子商务类",
    )

    resp = major_profiles.list_open_major_profiles(
        request=fake_request,
        major_code=None,
        major_name=None,
        occupation=None,
        training_goal=None,
        ability="网店运营能力",
        course=None,
        course_group=None,
        certificate=None,
        continuation=None,
        education_level=None,
        pagination=PAGE,
        session=session,
    )

    body = _body(resp)
    assert body["meta"]["total"] == 1
    assert body["data"][0]["id"] == "mp-ok"


def test_open_get_404_for_non_available(fake_request, session) -> None:
    ref = _seed_anchor(
        session, ref_id="ref-mp-api-review", version_id="ver-mp-api-review",
        status=AssetVersionStatus.REVIEW_REQUIRED,
    )
    _seed_profile(session, ref=ref, profile_id="mp-review")

    with pytest.raises(Exception) as exc:
        major_profiles.get_open_major_profile(
            profile_id="mp-review",
            request=fake_request,
            session=session,
        )

    assert getattr(exc.value, "status_code") == 404
