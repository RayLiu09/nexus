from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from nexus_app import models


def _load_script_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "backfill_major_distribution_provinces.py"
    spec = importlib.util.spec_from_file_location("backfill_major_distribution_provinces", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["backfill_major_distribution_provinces"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


BF = _load_script_module()


def _seed_dataset(session) -> models.MajorDistributionDataset:
    dataset = models.MajorDistributionDataset(
        id="dataset-province-backfill", normalized_ref_id="ref-province-backfill",
        asset_version_id="ver-province-backfill", source_channel="excel",
        major_scope="single_major", schema_version="v1", province_count=2,
    )
    session.add_all([
        dataset,
        models.MajorDistributionRecord(
            id="record-alias", dataset_id=dataset.id,
            normalized_ref_id=dataset.normalized_ref_id, source_record_key="row-1",
            year=2026, province_name="新疆", region_scope="province",
            major_name="电子商务", major_code="530701", distribution_count=22,
        ),
        models.MajorDistributionRecord(
            id="record-canonical", dataset_id=dataset.id,
            normalized_ref_id=dataset.normalized_ref_id, source_record_key="row-2",
            year=2026, province_name="新疆维吾尔自治区", region_scope="province",
            major_name="电子商务", major_code="530701", distribution_count=8,
        ),
        models.MajorDistributionRecord(
            id="record-corps", dataset_id=dataset.id,
            normalized_ref_id=dataset.normalized_ref_id, source_record_key="row-3",
            year=2026, province_name="新疆生产建设兵团", region_scope="province",
            major_name="电子商务", major_code="530701", distribution_count=3,
        ),
    ])
    session.flush()
    return dataset


def test_backfill_dry_run_does_not_mutate(session) -> None:
    _seed_dataset(session)

    outcome = BF.run_backfill(session, record_ids=None, apply_changes=False)

    assert outcome.dry_run is True
    assert outcome.records_changed == 1
    assert session.get(models.MajorDistributionRecord, "record-alias").province_name == "新疆"


def test_backfill_apply_normalizes_and_recomputes_distinct_province_count(session) -> None:
    dataset = _seed_dataset(session)

    outcome = BF.run_backfill(session, record_ids=None, apply_changes=True)

    assert outcome.dry_run is False
    assert outcome.records_changed == 1
    assert session.get(models.MajorDistributionRecord, "record-alias").province_name == "新疆维吾尔自治区"
    assert session.get(models.MajorDistributionRecord, "record-corps").province_name == "新疆生产建设兵团"
    assert session.get(models.MajorDistributionDataset, dataset.id).province_count == 2

    rerun = BF.run_backfill(session, record_ids=None, apply_changes=True)
    assert rerun.records_changed == 0
