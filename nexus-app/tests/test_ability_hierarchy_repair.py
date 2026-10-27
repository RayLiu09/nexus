from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path

from openpyxl import Workbook
import pytest
from sqlalchemy import select

from nexus_app import models
from nexus_app.capability_graph.builders import build_ability_analysis
from nexus_app.domain_normalize.ability_analysis_writer import write
from nexus_app.storage import InMemoryObjectStorage
from nexus_app.structured_parse.record_body_adapter import project_to_record_body
from nexus_app.structured_parse.xlsx_parser import parse_xlsx
from scripts.repair_ability_hierarchy import repair_one
from test_b6_ability_analysis import _make_ref_with_payload, _seed_pgsd_profile


def workbook_bytes():
    book = Workbook()
    book.remove(book.active)
    for code in ("A", "B"):
        sheet = book.create_sheet(code)
        sheet.append(["典型工作任务及编号", f"{code}测试任务", "工作内容及编号", f"{code}1内容准备、{code}2成果验收"])
        sheet.append(["典型工作任务描述", "1.由测试岗位完成"])
        sheet.append([None, "2.在工作环境中协作"])
        sheet.append(["能力类别", "编号", "内容"])
        sheet.append(["职业能力", f"P-{code}1.1", "能整理任务所需资料"])
        sheet.append(["通用能力", "G-A1", "能清楚表达工作结果"])
        sheet.append(["通用能力", "G-A1", "能准确理解协作要求"])
    stream = BytesIO()
    book.save(stream)
    return stream.getvalue()


PROFILE = {"domain_profile": "ability_analysis.pgsd.v1", "record_type": "occupational_ability_analysis"}


def test_explicit_headers_multiline_descriptions_and_duplicate_source_rows():
    body = project_to_record_body(parse_xlsx(workbook_bytes()).model_dump(mode="json"), PROFILE)
    for task in body["tasks"]:
        assert "协作" in task["task_description"]
        assert [w["content_name"] for w in task["work_contents"]] == ["内容准备", "成果验收"]
        assert task["work_contents"][0]["content_code"] == f"{task['task_code']}1"
        entries = task["general_abilities"]["G"]
        assert len({a["source_item_key"] for a in entries}) == 2
        assert all(a["quality_flags"]["cross_sheet_inconsistency"] for a in entries)
        assert len(task["trace"]["description_evidence"]) == 2


def test_repair_preserves_ids_enrichment_audit_and_is_idempotent(session):
    _seed_pgsd_profile(session)
    storage = InMemoryObjectStorage()
    content = workbook_bytes()
    body = project_to_record_body(parse_xlsx(content).model_dump(mode="json"), PROFILE)
    original = deepcopy(body)
    original["tasks"][0]["task_description"] = None
    ref = _make_ref_with_payload(session, storage, record_body=original)
    payload = {"record_body": original, "profile": PROFILE, "governance": {"keep": "unchanged"}}
    normalized = storage.put_bytes("normalized/test.json", json.dumps(payload).encode(), "application/json")
    ref.object_uri, ref.checksum = normalized.object_uri, normalized.checksum
    raw = session.get(models.RawObject, session.get(models.AssetVersion, ref.version_id).raw_object_id)
    source = storage.put_bytes("raw/test.xlsx", content, "application/octet-stream")
    raw.object_uri, raw.checksum = source.object_uri, source.checksum
    raw.metadata_summary = {"filename": "test.xlsx"}
    outcome = write(session, ref, original)
    analysis = session.get(models.OccupationalAbilityAnalysis, outcome.analysis_id)
    before = set(session.scalars(select(models.OccupationalAbilityItem.id)))
    item = session.scalar(select(models.OccupationalAbilityItem))
    item.confidence = 0.9
    item.normalized_terms = {"keep": True}
    dry_run = repair_one(session, storage, analysis)
    assert dry_run["changed"] and ref.object_uri == normalized.object_uri
    result = repair_one(session, storage, analysis, apply=True)
    assert result["preserved_ability_ids"] == len(before) == 6
    assert set(session.scalars(select(models.OccupationalAbilityItem.id))) == before
    assert float(item.confidence) == 0.9 and item.normalized_terms == {"keep": True}
    assert analysis.id == outcome.analysis_id
    assert not repair_one(session, storage, analysis)["changed"]
    assert json.loads(storage.get_bytes(ref.object_uri.split("/", 3)[-1]))["governance"] == {"keep": "unchanged"}
    assert session.scalar(select(models.AuditLog).where(models.AuditLog.actor_id == "ability_hierarchy_repair_v1"))


def test_all_fourteen_real_workbooks_preserve_every_source_row(session):
    directory = Path("/tmp/nexus-ability-inventory")
    if not (directory / "inventory.json").exists():
        pytest.skip("Read-only real-asset verification cache is not present")
    inventory = json.loads((directory / "inventory.json").read_text())
    assert len(inventory) == 14
    _seed_pgsd_profile(session)
    totals = [0, 0]
    for entry in inventory:
        base = directory / entry["analysis_id"]
        parsed = json.loads((base / "parsed.json").read_text())
        payload = json.loads((base / "normalized.json").read_text())
        body = project_to_record_body(parsed, payload["profile"])
        ref = _make_ref_with_payload(session, InMemoryObjectStorage(), record_body=body)
        result = write(session, ref, body)
        assert result.items_written == body["analysis"]["ability_item_count"]
        assert result.records_written == len(body["tasks"])
        analysis = session.get(models.OccupationalAbilityAnalysis, result.analysis_id)
        tasks = list(session.scalars(select(models.OccupationalWorkTask).where(models.OccupationalWorkTask.analysis_id == analysis.id)))
        contents = list(session.scalars(select(models.OccupationalWorkContent).where(models.OccupationalWorkContent.analysis_id == analysis.id)))
        abilities = list(session.scalars(select(models.OccupationalAbilityItem).where(models.OccupationalAbilityItem.analysis_id == analysis.id)))
        nodes, edges = build_ability_analysis(analysis=analysis, tasks=tasks, work_contents=contents, abilities=abilities)
        assert len({(n.node_type, n.node_key) for n in nodes}) == len(nodes)
        assert len(edges) == len(contents) + len(abilities)
        assert all(t.task_description for t in tasks)
        totals[0] += result.records_written
        totals[1] += result.items_written
    assert totals == [109, 3093]
