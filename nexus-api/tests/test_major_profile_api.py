from __future__ import annotations

import pytest

from nexus_api.api import major_profiles
from nexus_api.dependencies import Pagination
from nexus_app import models
from nexus_app.enums import (
    AssetKind,
    AssetVersionStatus,
    DataSourceType,
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
