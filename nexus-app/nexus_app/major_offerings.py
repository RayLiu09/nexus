"""Read model for directly synchronized school/year/major facts."""

from sqlalchemy import func, select

from nexus_app import models
from nexus_app.domain_normalize.administrative_division import normalize_province_name


def statement(
    *,
    year=None,
    province_name=None,
    province_code=None,
    major_name=None,
    major_code=None,
    school_name=None,
    school_code=None
):
    model = models.MajorOfferingRecord
    stmt = select(model)
    for column, value in (
        (model.year, year),
        (model.province_code, province_code),
        (model.major_code, major_code),
        (model.school_code, school_code),
    ):
        if value is not None:
            stmt = stmt.where(column == value)
    if province_name:
        stmt = stmt.where(model.province_name == normalize_province_name(province_name))
    for column, value in ((model.major_name, major_name), (model.school_name, school_name)):
        if value:
            stmt = stmt.where(column.icontains(value.strip(), autoescape=True))
    return stmt


def serialize(row):
    return {
        name: getattr(row, name)
        for name in (
            "id",
            "year",
            "province_code",
            "province_name",
            "major_code",
            "major_name",
            "school_code",
            "school_name",
            "study_duration",
            "remark",
            "source_url",
            "provider_code",
            "sync_run_id",
            "fetched_at",
            "created_at",
        )
    }


def list_records(session, *, offset=0, limit=20, **filters):
    stmt = statement(**filters)
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = session.scalars(
        stmt.order_by(
            models.MajorOfferingRecord.year.desc(),
            models.MajorOfferingRecord.province_code,
            models.MajorOfferingRecord.major_code,
            models.MajorOfferingRecord.school_name,
            models.MajorOfferingRecord.id,
        )
        .offset(offset)
        .limit(limit)
    ).all()
    return [serialize(row) for row in rows], total
