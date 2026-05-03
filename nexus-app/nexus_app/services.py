from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_app import models

ModelT = TypeVar("ModelT")


class ResourceNotFoundError(Exception):
    def __init__(self, resource_name: str) -> None:
        super().__init__(f"{resource_name} not found")
        self.resource_name = resource_name


def list_rows(session: Session, model: type[ModelT]) -> list[ModelT]:
    return list(session.scalars(select(model).order_by(model.created_at.desc())).all())


def get_row(session: Session, model: type[ModelT], row_id: str, resource_name: str) -> ModelT:
    row = session.get(model, row_id)
    if row is None:
        raise ResourceNotFoundError(resource_name)
    return row


def create_org_unit(session: Session, payload) -> models.OrgUnit:
    row = models.OrgUnit(**payload.model_dump())
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def create_user(session: Session, payload) -> models.UserAccount:
    row = models.UserAccount(**payload.model_dump())
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def create_api_caller(session: Session, payload) -> models.ApiCaller:
    row = models.ApiCaller(**payload.model_dump())
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def create_data_source(session: Session, payload) -> models.DataSource:
    row = models.DataSource(**payload.model_dump())
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def create_ingest_batch(session: Session, payload) -> models.IngestBatch:
    row = models.IngestBatch(**payload.model_dump())
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def create_raw_object(session: Session, payload) -> models.RawObject:
    row = models.RawObject(**payload.model_dump())
    session.add(row)
    session.commit()
    session.refresh(row)
    return row
