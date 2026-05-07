import pytest
from sqlalchemy.exc import IntegrityError

from nexus_app import models, services
from nexus_app.schemas import (
    ApiCallerCreate,
    DataSourceCreate,
    IngestBatchCreate,
    OrgUnitCreate,
    RawObjectCreate,
    UserCreate,
)


def create_foundation(session):
    org = services.create_org_unit(session, OrgUnitCreate(code="D1", name="Domain One"))
    user = services.create_user(
        session,
        UserCreate(
            username="admin",
            display_name="Platform Admin",
            role="platform_data_admin",
            org_unit_id=org.id,
        ),
    )
    source = services.create_data_source(
        session,
        DataSourceCreate(
            code="upload-d4",
            name="D4 Upload",
            source_type="file_upload",
            owner_user_id=user.id,
            org_scope_hint=[org.id],
            default_governance_hints={"domain": "D4", "level": "L2"},
        ),
    )
    return org, user, source


def test_identity_api_caller_and_data_source_services(session):
    org, user, source = create_foundation(session)
    caller = services.create_api_caller(
        session,
        ApiCallerCreate(
            caller_key="upper-system-a",
            name="Upper System A",
            org_scope=[org.id],
            permission_scope=["asset:read"],
            owner_user_id=user.id,
        ),
    )

    assert caller.caller_key == "upper-system-a"
    assert services.list_rows(session, models.UserAccount)[0].username == "admin"
    assert services.list_rows(session, models.DataSource)[0].id == source.id


def test_ingest_batch_idempotency_constraint(session):
    _org, user, source = create_foundation(session)
    payload = IngestBatchCreate(
        data_source_id=source.id,
        idempotency_key="same-key",
        source_type="file_upload",
        owner_user_id=user.id,
    )

    first = services.create_ingest_batch(session, payload)
    assert first.id

    with pytest.raises(IntegrityError):
        services.create_ingest_batch(session, payload)


def test_raw_object_checksum_constraint(session):
    _org, user, source = create_foundation(session)
    batch = services.create_ingest_batch(
        session,
        IngestBatchCreate(
            data_source_id=source.id,
            idempotency_key="checksum-batch",
            source_type="file_upload",
            owner_user_id=user.id,
        ),
    )
    first = services.create_raw_object(
        session,
        RawObjectCreate(
            batch_id=batch.id,
            data_source_id=source.id,
            source_type="file_upload",
            object_uri="minio://raw/d4/dup.pdf",
            checksum="sha256:dup",
        ),
    )
    assert first.id

    with pytest.raises(IntegrityError):
        services.create_raw_object(
            session,
            RawObjectCreate(
                batch_id=batch.id,
                data_source_id=source.id,
                source_type="file_upload",
                object_uri="minio://raw/d4/dup2.pdf",
                checksum="sha256:dup",
            ),
        )
