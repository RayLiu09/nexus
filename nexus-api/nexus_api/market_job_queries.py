"""Narrow raw-job fact queries shared by public reads and statistics."""
from sqlalchemy import case, func, nulls_last, or_, select, true

from nexus_app import models


def job_facts(filters, *columns, with_provenance=False):
    job, provenance = models.RawJob, models.RawJobProvenance
    stmt = select(*columns).select_from(job)
    # raw_job_id is the provenance PK: this join cannot multiply job facts.
    if with_provenance or filters.collected_from or filters.collected_to or filters.received_to:
        stmt = stmt.outerjoin(provenance, provenance.raw_job_id == job.id)
    if filters.q:
        stmt = stmt.where(or_(*(column.icontains(filters.q, autoescape=True) for column in (
            job.title_raw, job.title_normalized, job.company_name_raw,
            job.description_raw, job.responsibilities_raw,
        ))))
    for field, column in {
        "job_title": job.title_raw, "company_name": job.company_name_raw,
        "industry": job.company_industry_raw, "education": job.degree_raw,
        "experience": job.experience_raw, "region": job.region,
    }.items():
        if value := getattr(filters, field):
            condition = column.icontains(value, autoescape=True)
            if field == "job_title":
                condition = or_(condition, job.title_normalized.icontains(value, autoescape=True))
            stmt = stmt.where(condition)
    if filters.collected_from:
        stmt = stmt.where(provenance.collected_at >= filters.collected_from)
    if filters.collected_to:
        stmt = stmt.where(provenance.collected_at <= filters.collected_to)
    if filters.received_to:
        stmt = stmt.where(provenance.received_at <= filters.received_to)
    return stmt


def job_page_statement(filters, pagination):
    job, provenance = models.RawJob, models.RawJobProvenance
    page = job_facts(filters, job.id.label("job_id"),
        provenance.collected_at.label("collected_at"), with_provenance=True).order_by(
            nulls_last(provenance.collected_at.desc()), job.id.desc(),
        ).offset(pagination.offset).limit(pagination.limit).subquery()
    # Fetch wide bodies/provenance JSON only after finding this page's IDs.
    return select(job, provenance).join(page, page.c.job_id == job.id).outerjoin(
        provenance, provenance.raw_job_id == job.id,
    ).order_by(nulls_last(page.c.collected_at.desc()), job.id.desc())


def job_group_statement(filters, group_by, groups, pagination):
    columns = [groups[key].label(key) for key in group_by]
    grouped = job_facts(filters, *columns, func.count().label("record_count")).group_by(
        *(groups[key] for key in group_by),
    ).cte("job_groups")
    dimensions = [grouped.c[key] for key in group_by]
    # Derive all scope statistics from the same grouped facts, including blank
    # and NULL groups. Referencing the CTE twice shares its source scan on PG.
    summary = select(
        func.count().label("group_total"),
        func.coalesce(func.sum(grouped.c.record_count), 0).label("sample_count"),
        *(func.coalesce(func.sum(case(
            (or_(column.is_(None), func.trim(column) == ""), grouped.c.record_count),
            else_=0,
        )), 0).label("missing_" + key) for key, column in zip(group_by, dimensions)),
    ).select_from(grouped).subquery()
    page = select(grouped).order_by(grouped.c.record_count.desc(), *dimensions).offset(
        pagination.offset,
    ).limit(pagination.limit).subquery()
    # The summary survives empty matches and pages beyond the last group.
    return select(summary, page).select_from(summary.outerjoin(page, true())).order_by(
        page.c.record_count.desc(), *(page.c[key] for key in group_by),
    )
