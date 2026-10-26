"""Deterministic occupation reference import and read model."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from nexus_app import models
from nexus_app.enums import AuditEventType

SEED_PATH = Path(__file__).with_name("occupation_dictionary_2022.json")
HEADERS = ("职业类别", "所属大类(中类)", "所属小类", "职业名称", "职业定义", "工作任务")
CODE = re.compile(r"^(\d-\d{2}-\d{2}-\d{2})\s+(.+)$")
HIERARCHY = re.compile(r"^\d(?:-\d{2}){1,3}(?:\s|[（(])")
DEFINITION_START = re.compile(
    r"^(?:从事|在|运用|操作|使用|利用|根据|对|为|通过|以|专门|负责|驾驶|辅助|代表|各级|接受|操纵|由|经|受理|应用|依|综合|策划|提供|选择|研制|采用)"
)


class Entry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    occupation_code: str = Field(pattern=r"^\d-\d{2}-\d{2}-\d{2}$")
    occupation_category: str = Field(min_length=1)
    major_group: str = Field(min_length=1)
    minor_group: str | None
    occupation_name: str = Field(min_length=1)
    definition: str = Field(min_length=1)
    work_tasks: str = Field(min_length=1)
    source_rows: list[int] = Field(min_length=1)
    pdf_pages: list[int] = Field(default_factory=list)
    supplemented_fields: list[str] = Field(default_factory=list)

    @field_validator("occupation_name", "definition", "work_tasks")
    @classmethod
    def meaningful_text(cls, value):
        if not re.search(r"[\u4e00-\u9fff]", value):
            raise ValueError("required occupation text must contain Chinese content")
        return value

    @model_validator(mode="after")
    def matching_hierarchy(self):
        if not self.occupation_category.startswith(self.occupation_code[0]):
            raise ValueError("category/code mismatch")
        if not self.major_group.startswith(self.occupation_code[:4]):
            raise ValueError("major group/code mismatch")
        if self.minor_group and not self.minor_group.startswith(
            self.occupation_code[:7]
        ):
            raise ValueError("minor group/code mismatch")
        return self


class CatalogSeed(BaseModel):
    model_config = ConfigDict(extra="forbid")
    edition: int = 2022
    source_file: str
    supplement_file: str | None = None
    records: list[Entry]

    @model_validator(mode="after")
    def unique_codes(self):
        codes = [r.occupation_code for r in self.records]
        if len(codes) != len(set(codes)):
            raise ValueError("duplicate occupation codes in seed")
        return self


def parse_pdf_lines(lines: list[tuple[str, int]]) -> tuple[dict, dict]:
    """Read complete code-bound bodies, never a table-of-contents occurrence."""
    headers = [i for i, (line, _) in enumerate(lines) if HIERARCHY.match(line)]
    entries, minors = {}, {}
    for index, start in enumerate(headers):
        end = headers[index + 1] if index + 1 < len(headers) else len(lines)
        block = lines[start:end]
        header = block[0][0]
        match = CODE.match(header)
        if match:
            code, name = match.groups()
            body = [line for line, _ in block[1:]]
            definition_start = next(
                (i for i, line in enumerate(body) if DEFINITION_START.match(line)), None
            )
            marker = next(
                (
                    i
                    for i, line in enumerate(body)
                    if re.match(r"^主要工作任务\s*[:：]", line)
                ),
                None,
            )
            if definition_start is None or marker is None or definition_start >= marker:
                continue
            name = re.sub(r"[LS/\s]+$", "", "".join([name] + body[:definition_start]))
            task_lines = body[marker + 1 :]
            # Subtypes are explanatory text, rather than additional work tasks.
            note = next(
                (i for i, line in enumerate(task_lines) if line.startswith("本职业")),
                len(task_lines),
            )
            paragraphs = []
            for line in task_lines[:note]:
                if re.match(r"^\d+\s*[.．、]", line) or not paragraphs:
                    paragraphs.append(line)
                else:
                    paragraphs[-1] += line
            tasks = "\n".join(paragraphs).strip()
            definition = "".join(body[definition_start:marker]).strip()
            if not re.search(r"[\u4e00-\u9fff]", name) or not definition or not tasks:
                continue
            record = {
                "occupation_name": name,
                "definition": definition,
                "work_tasks": tasks,
                "pdf_pages": sorted({page for _, page in block}),
            }
            if code in entries and any(
                entries[code][key] != record[key]
                for key in ("occupation_name", "definition", "work_tasks")
            ):
                raise ValueError(f"conflicting complete PDF bodies for {code}")
            entries[code] = record
        else:
            match = re.match(r"^(\d-\d{2}-\d{2})\s*[（(]GBM\s*\d+[）)]\s*(.*)", header)
            if not match:
                continue
            names = [match[2]]
            for line, _ in block[1:]:
                if DEFINITION_START.match(line) or line.startswith("本小类"):
                    break
                names.append(line)
            name = "".join(names).strip()
            if name and len(name) < 90:
                minors[match[1]] = f"{match[1]} {name}"
    return entries, minors


def read_pdf(path: Path) -> tuple[dict, dict]:
    import pypdfium2 as pdfium

    lines = []
    with pdfium.PdfDocument(path) as document:
        for page_number in range(len(document)):
            page = document[page_number]
            text = page.get_textpage()
            try:
                for line in text.get_text_range().splitlines():
                    line = line.strip()
                    if (
                        not line
                        or line.isdigit()
                        or line == "中华人民共和国"
                        or re.match(r"^\d\s*[（(]GBM\s*\d+[）)]", line)
                        or re.match(r"^职\s*业\s*分\s*类\s*大\s*典", line)
                    ):
                        continue
                    lines.append((line, page_number + 1))
            finally:
                text.close()
                page.close()
    return parse_pdf_lines(lines)


def build_seed(workbook: Path, pdf: Path | None = None) -> tuple[CatalogSeed, dict]:
    from openpyxl import load_workbook

    grouped = defaultdict(list)
    book = load_workbook(workbook, read_only=True, data_only=True)
    try:
        sheet = book["职业名录"]
        rows = sheet.iter_rows(values_only=True)
        if tuple(next(rows)) != HEADERS:
            raise ValueError("unexpected occupation workbook headers")
        for number, values in enumerate(rows, 2):
            if not any(value is not None for value in values):
                continue
            values = [
                str(value).strip() if value is not None else None for value in values
            ]
            match = CODE.match(values[3] or "")
            if not match:
                raise ValueError(f"invalid occupation code on row {number}")
            grouped[match[1]].append((number, values, match[2]))
    finally:
        book.close()
    pdf_entries, minors = read_pdf(pdf) if pdf else ({}, {})
    records, dropped, supplemented = [], [], []
    for code, candidates in sorted(grouped.items()):
        formal = [item for item in candidates if re.search(r"[\u4e00-\u9fff]", item[2])]
        if len({tuple(item[1]) for item in formal}) > 1:
            raise ValueError(f"conflicting formal workbook rows for {code}")
        _, values, name = (formal or candidates)[0]
        fields = {
            "occupation_name": name if formal else None,
            "definition": values[4],
            "work_tasks": values[5],
        }
        missing_before = [key for key, value in fields.items() if not value]
        source = pdf_entries.get(code)
        # PDF code-bound bodies also repair damaged, non-empty spreadsheet extraction.
        if source:
            fields.update({key: source[key] for key in fields})
        missing_after = [
            key
            for key, value in fields.items()
            if not value or not re.search(r"[\u4e00-\u9fff]", value)
        ]
        if missing_after:
            dropped.append(
                {
                    "occupation_code": code,
                    "source_rows": [r[0] for r in candidates],
                    "missing_fields": missing_after,
                }
            )
            continue
        minor = values[2] or minors.get(code[:7])
        repaired = missing_before if source else []
        if not values[2] and minor:
            repaired = [*repaired, "minor_group"]
        entry = Entry(
            occupation_code=code,
            occupation_category=values[0],
            major_group=values[1],
            minor_group=minor,
            **fields,
            source_rows=[r[0] for r in candidates],
            pdf_pages=source["pdf_pages"] if source else [],
            supplemented_fields=repaired,
        )
        records.append(entry)
        if repaired:
            supplemented.append(
                {
                    "occupation_code": code,
                    "fields": repaired,
                    "pdf_pages": entry.pdf_pages,
                }
            )
    seed = CatalogSeed(
        source_file=workbook.name,
        supplement_file=pdf.name if pdf else None,
        records=records,
    )
    report = {
        "source_rows": sum(map(len, grouped.values())),
        "unique_codes": len(grouped),
        "duplicate_rows_merged": sum(len(g) - 1 for g in grouped.values()),
        "accepted": len(records),
        "pdf_body_records": sum(bool(r.pdf_pages) for r in records),
        "supplemented": supplemented,
        "dropped": dropped,
        "missing_minor_group": sum(not r.minor_group for r in records),
    }
    return seed, report


def load_seed(path: Path = SEED_PATH) -> CatalogSeed:
    return CatalogSeed.model_validate_json(path.read_text(encoding="utf-8"))


def import_catalog(
    connection, seed: CatalogSeed, *, actor_id="system-migration"
) -> dict:
    """Caller owns the transaction. Complete validation precedes any write."""
    seed = CatalogSeed.model_validate(seed.model_dump())
    table = models.OccupationDictionary.__table__
    insert = pg_insert if connection.dialect.name == "postgresql" else sqlite_insert
    existing = {
        r.occupation_code: r
        for r in connection.execute(
            select(table).where(table.c.edition == seed.edition)
        ).mappings()
    }
    now = datetime.now(timezone.utc)
    inserted = 0
    for entry in seed.records:
        values = {
            **entry.model_dump(),
            "edition": seed.edition,
            "source_file": seed.source_file,
            "supplement_file": seed.supplement_file,
        }
        previous = existing.get(entry.occupation_code)
        if previous:
            if any(previous[key] != value for key, value in values.items()):
                raise ValueError(
                    f"existing reference differs for {entry.occupation_code}"
                )
            continue
        row_id = str(
            uuid5(
                NAMESPACE_URL,
                f"nexus:occupation-dictionary:{seed.edition}:{entry.occupation_code}",
            )
        )
        result = connection.execute(
            insert(table)
            .values(id=row_id, **values, created_at=now, updated_at=now)
            .on_conflict_do_nothing(index_elements=["edition", "occupation_code"])
            .returning(table.c.id)
        )
        if result.scalar_one_or_none():
            inserted += 1
    summary = {
        "edition": seed.edition,
        "source_file": seed.source_file,
        "supplement_file": seed.supplement_file,
        "inserted": inserted,
        "skipped": len(seed.records) - inserted,
    }
    if inserted:
        connection.execute(
            models.AuditLog.__table__.insert().values(
                id=str(
                    uuid5(
                        NAMESPACE_URL,
                        f"nexus:occupation-import:{seed.edition}:{now.isoformat()}",
                    )
                ),
                event_type=AuditEventType.OCCUPATION_DICTIONARY_IMPORTED,
                actor_type="system",
                actor_id=actor_id,
                target_type="occupation_dictionary",
                target_id=str(seed.edition),
                trace_id=f"occupation-import-{seed.edition}",
                summary=summary,
                created_at=now,
                updated_at=now,
            )
        )
    return summary


def list_records(
    session,
    *,
    major_group=None,
    minor_group=None,
    occupation_name=None,
    offset=0,
    limit=20,
):
    model = models.OccupationDictionary
    stmt = select(model)
    for column, code_length, value in (
        (model.major_group, 4, major_group),
        (model.minor_group, 7, minor_group),
    ):
        if value and value.strip():
            stmt = stmt.where(
                or_(
                    column.icontains(value.strip(), autoescape=True),
                    func.substr(model.occupation_code, 1, code_length).icontains(
                        value.strip(), autoescape=True
                    ),
                )
            )
    if occupation_name and occupation_name.strip():
        stmt = stmt.where(
            model.occupation_name.icontains(occupation_name.strip(), autoescape=True)
        )
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = session.scalars(
        stmt.order_by(model.edition.desc(), model.occupation_code)
        .offset(offset)
        .limit(limit)
    )
    fields = (
        "id",
        "edition",
        "occupation_code",
        "occupation_category",
        "major_group",
        "minor_group",
        "occupation_name",
        "definition",
        "work_tasks",
    )
    return [{field: getattr(row, field) for field in fields} for row in rows], total
