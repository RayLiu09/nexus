"""Read-only job title master data for crawler-engine sync plans."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from nexus_app import models


def list_job_catalog(session: Session) -> list[dict]:
    categories = list(session.scalars(
        select(models.JobCollectionCategory)
        .order_by(models.JobCollectionCategory.name)
    ))
    titles = list(session.scalars(
        select(models.JobCollectionTitle)
        .order_by(models.JobCollectionTitle.name, models.JobCollectionTitle.id)
    ))
    by_category: dict[str, list[dict]] = {category.id: [] for category in categories}
    seen_names: dict[str, set[str]] = {category.id: set() for category in categories}
    for title in titles:
        if title.category_id in by_category and title.name not in seen_names[title.category_id]:
            seen_names[title.category_id].add(title.name)
            by_category[title.category_id].append({"id": title.id, "name": title.name})
    return [{
        "id": category.id,
        "name": category.name,
        "titles": by_category[category.id],
    } for category in categories]


def titles_are_available(session: Session, names: list[str]) -> bool:
    rows = session.execute(
        select(models.JobCollectionTitle.name)
        .join(models.JobCollectionCategory)
        .where(models.JobCollectionTitle.name.in_(names))
    ).scalars().all()
    return set(rows) == set(names)
