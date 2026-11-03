"""Classification uses document purpose/structure across industries, never topic keywords."""
import json
from copy import deepcopy
from pathlib import Path

import pytest

from nexus_app.ai_governance.industry_regulation_standard import CLASSIFICATION, classify_text, extend_rules, normalized_text
from nexus_app.ai_governance.knowledge_type_inference import infer_knowledge_emissions_for_classification
from nexus_app.ai_governance.rules_registry import GovernanceRulesRegistry


@pytest.mark.parametrize('title', [
    '直播电商监督管理办法', '食品生产安全管理规定', '新能源汽车安全管理规则',
    '药品生产监督管理暂行办法', '信息系统等级保护实施办法', '铁路运输安全条例',
    '海上风电设备审定和监督程序（征求意见稿）', '民用航空安全信息主动报告管理办法',
])
def test_generic_regulatory_articles(title):
    body = f'# {title}\n市场监督管理局发布。为规范生产和服务，制定本办法。\n'
    body += '\n'.join(f'第{n}条 企业应当满足安全要求，不得违反审批程序。' for n in range(1, 12))
    accepted, confidence, evidence = classify_text(title, body)
    assert accepted and confidence >= .9 and evidence


@pytest.mark.parametrize('industry', ['食品加工', '机械制造', '电力巡检', '云计算', '医疗器械', '农业机械'])
def test_generic_technical_standard_and_ocr(industry):
    body = f'# {industry}技术规范\nGB/T 12345-2026\n国家标准化管理委员会发布\n'
    body += '# 范围\n本文件适用于相关产品。\n# 规范性引用文件\n# 术语与定义\n# 技术要求\n'
    body += '设备应符合检验要求。企业必须建立安全制度，不得绕过检验。' * 15
    assert classify_text(industry + '技术规范', body)[0]
    assert classify_text(industry + '技术规范', body.replace('本文件', '本 文 件'))[0]


@pytest.mark.parametrize('title,opening', [
    ('关于促进电子商务发展的若干意见', '发展目标和重点任务，推进标准体系建设，鼓励产业发展。'),
    ('新能源标准体系建设指南', '推进标准化工作与产业布局，制定行动计划。'),
    ('电商发展资金管理办法', '对项目给予奖励补贴，资金申请及审核程序。'),
    ('投资专项管理办法', '项目补助的建设目标和申请程序。'),
    ('直播电商监督管理办法解读', '本办法适用于平台，第1条应当遵守，第2条必须，第3条不得。'),
    ('工业品供应商能力建设指南', '标准项目计划号20243550-T-469，项目状态正在批准，主要起草单位。'),
    ('食品规范（征求意见稿）', '编制说明。描述标准编制过程、各方意见及采纳情况。'),
    ('统计应知应会手册', 'GB/T 4754—2017发布实施的历史沿革和分类举例。'),
    ('制造业年度研究报告', '引用GB/T12345，分析市场规模、趋势与样本数据。'),
])
def test_non_normative_documents(title, opening):
    assert not classify_text(title, opening * 25)[0]


def test_standard_cover_can_identify_type_without_inventing_completeness():
    text = '# 中华人民共和国国内贸易行业标准\nSB/T 11240—2023\n# 直播电子商务平台管理与服务规范\n2023年发布，2024年实施\n商务部发布\n## 前言\n' + '本文件按标准化工作导则起草。' * 15
    accepted, _, evidence = classify_text('直播电子商务平台管理与服务规范', text)
    assert accepted
    assert any('不推定条款完整性' in item for item in evidence)


def test_rules_definition_is_consistent_immutable_and_semantic_only():
    path = Path(__file__).resolve().parents[3] / 'config' / 'governance_rules_v2.json'
    # tests/ai_governance -> tests -> nexus-app -> repo
    content = json.loads(path.read_text())
    actual = next(c for c in content['classifications'] if c['code'] == CLASSIFICATION['code'])
    assert actual == CLASSIFICATION
    old = deepcopy(content)
    old['classifications'] = [c for c in old['classifications'] if c['code'] != CLASSIFICATION['code']]
    snapshot = deepcopy(old)
    patched = extend_rules(old)
    assert old == snapshot
    assert extend_rules(patched) == patched
    # Even an inherited knowledge-type graph default must not produce a graph.
    next(k for k in patched['knowledge_types'] if k['code'] == 'industry_research_kb')['graph_profile'] = 'unwanted.v1'
    registry = GovernanceRulesRegistry()
    registry.load_dict(patched)
    emissions = infer_knowledge_emissions_for_classification(CLASSIFICATION['code'], registry)
    assert len(emissions) == 1
    assert emissions[0]['code'] == 'industry_research_kb'
    assert 'graph_profile' not in emissions[0]


def test_only_normalized_body_or_blocks_are_used():
    assert normalized_text({'body_markdown': '正文', 'raw': '原始文件'}) == '正文'
    assert normalized_text({'blocks': [{'text': '段落'}, {'image': 'image'}], 'mineru': '原始'}) == '段落'


def test_identified_legal_article_excerpt_is_still_a_regulation():
    body = "第八条 从事食品生产的企业应当申请许可，应当建立安全制度。" * 8 + "法规文本来源：国家法律法规数据库。"
    assert classify_text("食品安全法第八条", body)[0]


def test_national_law_uses_its_own_legal_self_reference():
    body = "# 中华人民共和国食品安全法\n全国人民代表大会常务委员会发布。制定本法。\n" + "\n".join(f"第{n}条 企业应当建立食品安全制度，不得违反本法。" for n in range(1, 20))
    assert classify_text("中华人民共和国食品安全法", body)[0]
