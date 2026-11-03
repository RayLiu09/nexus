"""Current catalog repair preserves security/state/history and is audited/idempotent."""
from copy import deepcopy
import json
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from nexus_app import models
from nexus_app.ai_governance.regulation_reclassification import activate_rules, current_documents, reclassify
from nexus_app.ai_governance.rules_registry import GovernanceRulesRegistry
from nexus_app.enums import AuditEventType
from tests.test_asset_catalog_api import _seed_review_required_asset


def setup_repair(session):
    seed = _seed_review_required_asset(session)
    seed['asset'].title = seed['ref'].title = '直播电商监督管理办法（征求意见稿）'
    seed['result'].classification = 'industry_policy'
    seed['result'].level = 'L2'
    seed['result'].org_scope = 'restricted-org'
    seed['ref'].metadata_summary = {'knowledge_emissions': [{'code': 'industry_research_kb', 'graph_profile': 'old.v1'}]}
    config = json.loads((Path(__file__).resolve().parents[2] / 'config/governance_rules_v2.json').read_text())
    config['classifications'] = [c for c in config['classifications'] if c['code'] != 'industry_regulation_standard']
    for kt in config['knowledge_types']:
        kt['applicable_classifications'] = [c for c in kt.get('applicable_classifications', []) if c != 'industry_regulation_standard']
    old_rules = models.GovernanceRulesVersion(version=1, status='active', rules_content=config, schema_version='2.1')
    session.add(old_rules)
    session.commit()
    return seed, old_rules


def test_append_only_repair_audit_and_repeat_with_current_catalog(session, app):
    seed, old_rules = setup_repair(session)
    old_content = deepcopy(old_rules.rules_content)
    old_result = seed['result']
    old_trail, old_status = deepcopy(old_result.decision_trail), old_result.status
    version_status, quality = seed['version'].version_status, deepcopy(seed['ref'].quality)
    trace = str(uuid4())
    active = activate_rules(session, trace)
    registry = GovernanceRulesRegistry()
    registry.load_dict(active.rules_content, active.id)
    candidate = current_documents(session)[0]
    payload = {'body_markdown': '# 直播电商监督管理办法\n市场监督管理局发布，制定本办法。\n' + '\n'.join(f'第{n}条 企业应当建立安全制度，不得违反管理规定。' for n in range(1, 20))}
    assert reclassify(session, candidate, payload, registry=registry, trace_id=trace)
    session.commit()
    assert old_result.classification == 'industry_policy'
    assert old_result.decision_trail == old_trail and old_result.status == old_status
    assert old_rules.rules_content == old_content and old_rules.status == 'archived'
    current = current_documents(session)[0]
    assert current['classification'] == 'industry_regulation_standard'
    assert not reclassify(session, current, payload, registry=registry, trace_id=trace)
    assert activate_rules(session, trace).id == active.id
    results = session.scalars(select(models.GovernanceResult).where(models.GovernanceResult.normalized_ref_id == seed['ref'].id)).all()
    assert len(results) == 2
    new = next(r for r in results if r.id != old_result.id)
    for field in ('level', 'tags', 'org_scope', 'index_admission', 'quality_summary', 'status'):
        assert getattr(new, field) == getattr(old_result, field)
    assert new.rules_content_hash == registry.get_rules_content_hash() and new.trace_id == trace
    assert seed['version'].version_status == version_status and seed['ref'].quality == quality
    assert seed['ref'].metadata_summary['regulation_standard']['effect_status'] == 'draft'
    assert 'graph_profile' not in seed['ref'].metadata_summary['knowledge_emissions'][0]
    assert 'governance_result_id' not in seed['ref'].metadata_summary['regulation_standard']
    audits = session.scalars(select(models.AuditLog).where(models.AuditLog.trace_id == trace)).all()
    assert len(audits) == 3
    assert any(a.event_type == AuditEventType.GOVERNANCE_RESULT_CREATED and a.target_id == new.id for a in audits)
    # Reload SQLite timestamps consistently before catalog comparisons.
    session.expire_all()
    client = TestClient(app)
    url = '/internal/v1/industry-regulation-standards'
    assert client.get(url).json()['meta']['total'] == 1
    assert client.get('/internal/v1/industry-policies').json()['meta']['total'] == 0
    assert client.get('/internal/v1/asset-center/counts').json()['data']['counts']['policy/industry-regulation-standards'] == 1
    assert client.get(url, params={'topic': 'finance_commerce'}).json()['meta']['total'] == 1
    assert client.get(url, params={'topic': 'low_altitude'}).json()['meta']['total'] == 0


def test_changed_official_result_is_not_overwritten(session):
    seed, _ = setup_repair(session)
    candidate = current_documents(session)[0]
    active = activate_rules(session, str(uuid4()))
    registry = GovernanceRulesRegistry()
    registry.load_dict(active.rules_content, active.id)
    session.add(models.GovernanceResult(normalized_ref_id=seed['ref'].id, classification='teaching_case', level='L1', tags=[], status=seed['result'].status))
    session.flush()
    with pytest.raises(RuntimeError, match='changed during review'):
        reclassify(session, candidate, {'body_markdown': 'text'}, registry=registry, trace_id=str(uuid4()))


def test_rules_migration_joins_outer_transaction_without_rewriting_content(session, monkeypatch):
    import importlib.util
    _, original = setup_repair(session)
    content = deepcopy(original.rules_content)
    path = Path(__file__).resolve().parents[2] / 'nexus-app/alembic/versions/20261102_0130_industry_regulation_standard.py'
    spec = importlib.util.spec_from_file_location('regulation_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    monkeypatch.setattr(migration.op, 'get_bind', lambda: session.connection())
    migration.upgrade()
    session.expire_all()
    active = session.scalar(select(models.GovernanceRulesVersion).where(models.GovernanceRulesVersion.status == 'active'))
    assert active.id != original.id
    assert original.rules_content == content and original.status == 'archived'
    migration.upgrade()
    assert len(session.scalars(select(models.GovernanceRulesVersion)).all()) == 2
    session.commit()


def test_unreadable_normalized_document_aborts_apply_before_rules_or_results_change(session, monkeypatch):
    import importlib.util
    from contextlib import contextmanager
    seed, original = setup_repair(session)
    path = Path(__file__).resolve().parents[2] / 'nexus-app/scripts/classify_industry_regulation_standards.py'
    spec = importlib.util.spec_from_file_location('regulation_script', path)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)

    @contextmanager
    def local_session():
        yield session

    class MissingStorage:
        def get_bytes(self, key):
            raise FileNotFoundError(key)

    monkeypatch.setattr(script, 'get_session_local', lambda: local_session)
    monkeypatch.setattr(script, 'get_object_storage', lambda: MissingStorage())
    report = script.run()
    assert report['scanned'] == report['read_errors'] == 1
    assert not report['items'][0]['accepted']
    with pytest.raises(RuntimeError, match='no changes applied'):
        script.run(apply=True)
    assert original.status == 'active'
    assert seed['result'].classification == 'industry_policy'
    assert len(session.scalars(select(models.GovernanceRulesVersion)).all()) == 1
