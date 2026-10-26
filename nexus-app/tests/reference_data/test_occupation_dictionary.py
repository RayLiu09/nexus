import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from openpyxl import Workbook
from sqlalchemy import func, select

from nexus_app import models
from nexus_app.enums import AuditEventType
from nexus_app.reference_data import occupation_dictionary as catalog


def small_seed():
    return catalog.CatalogSeed(
        source_file="名录.xlsx",
        records=[
            catalog.Entry(
                occupation_code="2-02-10-01",
                occupation_category="2 专业技术人员",
                major_group="2-02 工程技术人员",
                minor_group="2-02-10 通信技术人员",
                occupation_name="通信工程技术人员",
                definition="从事通信网络规划的人员。",
                work_tasks="1.规划通信网络。\n2.维护通信网络。",
                source_rows=[2],
            )
        ],
    )


def test_pdf_skips_index_occurrence_and_never_uses_next_occupation_body():
    lines = [
        ("2-02-10-01 通信工程技术人员", 1),
        ("2-02-10-02 计算机硬件工程技术人员", 1),
        ("2-02-10-01 通信工程技术人员S", 2),
        ("从事通信网络规划的人员。", 2),
        ("主要工作任务:", 2),
        ("1.规划通信", 2),
        ("网络。", 3),
        ("2-02-10-02 计算机硬件工程技术人员", 3),
        ("从事硬件设计的人员。", 3),
        ("主要工作任务:", 3),
        ("1.设计硬件。", 3),
    ]
    records, _ = catalog.parse_pdf_lines(lines)
    assert records["2-02-10-01"] == {
        "occupation_name": "通信工程技术人员",
        "definition": "从事通信网络规划的人员。",
        "work_tasks": "1.规划通信网络。",
        "pdf_pages": [2, 3],
    }
    assert "硬件" not in records["2-02-10-01"]["work_tasks"]


def test_workbook_supplements_by_code_deduplicates_and_drops_incomplete(
    tmp_path, monkeypatch
):
    book = Workbook()
    sheet = book.active
    sheet.title = "职业名录"
    sheet.append(catalog.HEADERS)
    sheet.append(
        ["2 专业技术人员", "2-02 工程技术人员", None, "2-02-10-01 S", None, None]
    )
    sheet.append(
        [
            "2 专业技术人员",
            "2-02 工程技术人员",
            None,
            "2-02-10-01 通信工程技术人员",
            "旧定义",
            None,
        ]
    )
    sheet.append(
        [
            "2 专业技术人员",
            "2-02 工程技术人员",
            None,
            "2-02-10-02 未完成职业",
            "有定义",
            None,
        ]
    )
    path = tmp_path / "名录.xlsx"
    book.save(path)
    monkeypatch.setattr(
        catalog,
        "read_pdf",
        lambda _: (
            {
                "2-02-10-01": {
                    "occupation_name": "通信工程技术人员",
                    "definition": "从事通信工作的人员。",
                    "work_tasks": "1.设计网络。",
                    "pdf_pages": [40],
                }
            },
            {"2-02-10": "2-02-10 通信技术人员"},
        ),
    )
    seed, report = catalog.build_seed(path, Path("原文.pdf"))
    assert len(seed.records) == 1
    row = seed.records[0]
    assert row.source_rows == [2, 3]
    assert row.minor_group == "2-02-10 通信技术人员"
    assert row.supplemented_fields == ["work_tasks", "minor_group"]
    assert row.pdf_pages == [40]
    assert report["duplicate_rows_merged"] == 1
    assert report["dropped"] == [
        {
            "occupation_code": "2-02-10-02",
            "source_rows": [4],
            "missing_fields": ["work_tasks"],
        }
    ]


def test_import_is_idempotent_and_audited(session):
    seed = small_seed()
    first = catalog.import_catalog(session.connection(), seed)
    assert (first["inserted"], first["skipped"]) == (1, 0)
    session.commit()
    repeated = catalog.import_catalog(session.connection(), seed)
    session.commit()
    assert (repeated["inserted"], repeated["skipped"]) == (0, 1)
    assert session.scalar(select(func.count(models.OccupationDictionary.id))) == 1
    assert (
        session.scalar(
            select(func.count(models.AuditLog.id)).where(
                models.AuditLog.event_type
                == AuditEventType.OCCUPATION_DICTIONARY_IMPORTED
            )
        )
        == 1
    )
    for model in (models.Asset, models.NormalizedAssetRef, models.AIGovernanceRun):
        assert session.scalar(select(func.count()).select_from(model)) == 0
    changed = seed.model_copy(deep=True)
    changed.records[0].definition = "不同定义"
    with pytest.raises(ValueError, match="existing reference differs"):
        catalog.import_catalog(session.connection(), changed)


def test_bundled_seed_required_fields_and_known_pdf_repairs():
    seed = catalog.load_seed()
    assert len(seed.records) == 1329
    assert all(
        r.occupation_name
        and r.definition
        and r.work_tasks
        and r.minor_group
        and r.pdf_pages
        for r in seed.records
    )
    rows = {r.occupation_code: r for r in seed.records}
    assert rows["2-02-07-11"].occupation_name == "汽车工程技术人员"
    assert (
        "职业" not in rows["4-10-03-01"].work_tasks.splitlines()[-1]
    )  # excludes subtype notes
    assert rows["4-13-04-04"].occupation_name == "研学旅行指导师"
    assert "1-01-00-01" not in rows
    assert "8-00-00-00" not in rows
    assert len({r.occupation_code for r in seed.records}) == len(seed.records)


def test_migration_creates_and_seeds_reference_without_source_files(session):
    models.OccupationDictionary.__table__.drop(session.connection())
    path = (
        Path(__file__).parents[2]
        / "alembic/versions/20261026_0122_occupation_dictionary.py"
    )
    spec = importlib.util.spec_from_file_location("occupation_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with Operations.context(MigrationContext.configure(session.connection())):
        module.upgrade()
    assert session.scalar(select(func.count(models.OccupationDictionary.id))) == 1329
    rows, total = catalog.list_records(
        session,
        major_group="2-02",
        minor_group="2-02-07",
        occupation_name="汽车",
        limit=1,
    )
    assert total > 0 and len(rows) == 1
    assert rows[0]["occupation_name"] == "汽车工程技术人员"
