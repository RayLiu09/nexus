"""Generic normative-document classification, independent of industry topics."""
from __future__ import annotations

from copy import deepcopy
import re
import unicodedata

RULE_ID = "normative_document.v1"


def normalized_text(payload: dict) -> str:
    """Use normalized body/blocks only, never raw or MinerU output."""
    body = payload.get("body_markdown")
    if isinstance(body, str) and body.strip():
        return body
    return "\n".join(
        block["text"] for block in payload.get("blocks", [])
        if isinstance(block, dict) and isinstance(block.get("text"), str)
    )


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value))


def classify_text(title: str | None, text: str) -> tuple[bool, float, list[str]]:
    """Require normative identity and structural evidence, across all industries.

    The evidence classes replace topic keyword scoring. News, interpretations,
    plans for standardization, and funding measures stay in their existing
    classes. A published law/ordinance remains normative even when it promotes
    an industry. Drafts have the same document class, a separate effect status.
    """
    name, body = _compact(title or ""), _compact(text)
    if len(body) < 180:
        return False, 0.0, ["标准化正文不足，无法确认规范条款"]
    if re.search(r"解读|问答|答记者问|常见问题|新闻|浅读|说明|审议结果的报告|近期将|将出台|微课堂|热议|一图读懂|应知应会|提案|答复", name):
        return False, 0.0, ["解读、新闻或说明，非规范正文"]
    if "编制说明" in body[:450]:
        return False, 0.0, ["标准编制说明，非标准条款正文"]
    if re.search(r"标准体系建设|标准化.*(?:计划|路线图)|申报指南|扶持办法|发展.*实施细则|资金.*(?:办法|细则)|投资专项管理办法|项目指南|年度工作指引", name):
        return False, 0.0, ["体系建设、发展支持或项目申报政策"]
    if re.search(r"(?:报告|白皮书|蓝皮书|洞察|简报|调研|研究|薪酬指南)(?:[（(].*?[）)])?$", name):
        return False, 0.0, ["研究/报告形态"]

    # Title identity includes operational rules/guides issued by authorities;
    # headings help historical assets whose title is just a host-site label.
    titles = name + _compact("\n".join(re.findall(r"^#{1,2}\s+(.+)$", text[:6000], re.M)))
    formal = re.search(r"条例|办法|规定|规则|(?:管理|审定|监管).{0,6}程序|规范|标准|实施细则|(?:最低性能|技术)要求|统计分类|分类方法|培训大纲|指南|指引|规程|咨询通告|指导材料|中华人民共和国.{1,30}法", titles)
    self_ref = re.search(r"本(?:文件|标准|规范|办法|条例|规定|规则|程序|咨询通告|分类|指导材料|.{0,3}指南|.{0,3}指引|大纲|方法).{0,20}(?:适用|规定|制定|遵守|要求|实行)|制定本(?:办法|规定|规则|条例|程序|标准|咨询通告|分类|指南|指引|大纲|方法)", body)
    # A law's self-reference must match the document identity; a country
    # investment guide quoting "本法" is not itself a law.
    if not self_ref and re.search(r"中华人民共和国.{1,30}法", name):
        self_ref = re.search(r"制定本法|本法.{0,20}(?:适用|规定|遵守|要求|实行)", body)
    articles = re.findall(r"第[一二三四五六七八九十百零〇\d.]+条", body)
    normative_terms = [term for term in ("适用范围", "术语和定义", "术语与定义", "术语、定义", "术语定义", "规范性引用文件", "技术要求", "试验方法", "检验规则", "基本要求", "生效与废止", "应当", "不得", "必须") if term in body]
    standard_structure = "规范性引用文件" in body and any(term in body for term in ("术语和定义", "术语与定义", "术语、定义", "术语定义"))
    requirements = sum(body.count(term) for term in ("应当", "不得", "必须", "应符合", "应具备", "应满足", "要求"))
    numbered = len(re.findall(r"^\s*#{1,6}\s*(?:\d|[一二三四五六七八九十]+[、.])", text, re.M))
    headings = len(re.findall(r"^#{1,6}\s+", text, re.M))
    clauses = len(set(articles)) >= 3 or standard_structure or ((numbered >= 3 or headings >= 5) and len(normative_terms) >= 2 and requirements >= 3)
    identifier = re.search(r"(?:GB(?:/T)?|[A-Z]{2}/T|DB\d{2,}(?:/T)?|T/[A-Z]+)[_\s]*\d{3,}|(?:AP|AC|MD|IB|WM)-[A-Z0-9-]+", text)
    issuer = re.search(r"发布|发文|下发日期|颁发日期|人民政府|管理局|委员会|协会|编[\s]*号|文[\s]*号", text[:6000])
    statistical_codes = bool("统计分类" in titles and "制定本分类" in body and "编码" in body and "GB/T" in body)
    cover = bool(formal and identifier and issuer and re.search(r"^\s*(?:GB(?:/T)?|[A-Z]{2}/T|DB\d{2,}(?:/T)?|T/[A-Z]+)\s*\d{3,}", text[:1000], re.M) and "发布" in body[:1000] and "实施" in body[:1000] and not re.search(r"计划号|正在批准|项目状态|项目进度", body))
    legal_excerpt = bool(re.search(r"(?:法|条例|规定|规则).*?第[一二三四五六七八九十百零〇\d]+条", name) and articles and re.search(r"法规文本来源|国家法律法规数据库|官方文本", body) and requirements >= 2)
    evidence = []
    if formal:
        evidence.append("规范文件身份：" + formal.group())
    if self_ref:
        evidence.append("正文自指：" + self_ref.group()[:70])
    if clauses:
        evidence.append(f"规范结构：{len(set(articles))} 个条号；" + "、".join(normative_terms[:8]))
    if identifier:
        evidence.append("规范编号：" + identifier.group())
    if issuer:
        evidence.append("发布/管理主体或文号信息")
    if cover:
        evidence.append("标准封面、编号及发布信息明确（不推定条款完整性）")
    if statistical_codes:
        evidence.append("官方统计分类的结构和行业编码规则")
    if legal_excerpt:
        evidence.append("法规条文摘录及官方文本来源明确（不推定全文完整性）")
    accepted = bool((formal and self_ref and clauses and (issuer or identifier)) or cover or statistical_codes or legal_excerpt)
    return accepted, (0.96 if accepted else 0.0), evidence or ["缺少规范正文身份与条款证据"]

CLASSIFICATION_CODE = "industry_regulation_standard"
CLASSIFICATION = {'code': 'industry_regulation_standard',
 'name': '行业法规标准',
 'parent_type': '行业、产业数据',
 'description': '面向任一行业的法律法规、部门规章、国家/行业/地方/团体标准、技术规范、管理规范、认证规则及其正式实施细则；按规范性文件的约束与执行属性归类，不限于特定产业。',
 'application_scenarios': ['行业合规检索', '标准条款问答', '技术规范查阅', '产业研究引用'],
 'title_keywords': ['法律',
                    '法规',
                    '法',
                    '条例',
                    '规章',
                    '办法',
                    '规定',
                    '标准',
                    '规范',
                    '技术规范',
                    '技术要求',
                    '检验规则',
                    '实施细则',
                    '团体标准',
                    '国家标准',
                    '行业标准',
                    '地方标准',
                    '强制性标准',
                    '推荐性标准',
                    '认证规则',
                    '安全规范',
                    '管理规范',
                    '管理办法',
                    '管理程序',
                    '审定程序',
                    '监管程序',
                    '运行规则',
                    '最低性能要求',
                    '指导材料',
                    '办赛指南',
                    '参赛指引',
                    '培训大纲'],
 'content_keywords': ['适用范围',
                      '术语和定义',
                      '规范性引用文件',
                      '基本要求',
                      '技术要求',
                      '试验方法',
                      '检验规则',
                      '判定规则',
                      '标志、包装、运输和贮存',
                      '实施日期',
                      '有效期',
                      '废止',
                      '条款',
                      '应当',
                      '必须',
                      '不得',
                      '符合本标准',
                      '本文件适用于',
                      '发布公告',
                      '标准编号',
                      '文号'],
 'criteria': ['规范性文件证据：标题或正文明确出现法律、法规、规章、标准、规范、技术要求、实施细则等规范性文件类型，且具有发布主体、文号/标准编号、发布日期或实施日期中的至少一项。',
              '约束性条款证据：正文以适用范围、术语定义、强制/推荐要求、检验方法、判定规则、实施/废止条款等结构规定统一执行要求。',
              '分类边界：文件主题涉及某个行业或产业不构成产业政策；若主体是目标、任务、财政支持、招商或发展规划，应归入产业政策；若主体是统计分析、趋势预测或市场研究，应归入产业报告/行业报告。',
              '通用范围：适用于制造、交通、能源、医疗、农业、信息技术、低空经济及其他行业，不以“低空经济”等单一行业词作为必要条件。',
              '监管程序、审定程序、行业办赛/参赛指引和主管部门颁布的岗位培训大纲，若正文规定统一资质、职责、申请审查、合规或安全要求，也属于此类。征求意见稿/试行文本仍按文件形态分类，生效状态必须独立标注，不能当作已生效依据。',
              '文件解读、新闻报道、标准体系建设计划、标准发展研究、统计年报、教学标准与教材不因引用规范性术语归入本类。',
              '编号和发布/实施信息明确的标准封面可确认文件类型，但不能据此推定条款完整性；标准立项登记、附件链接清单和编制说明不等于标准正文。'],
 'tagging_basis': {'professional_domain': [{'value': '按文件明确的行业、专业领域或标准适用对象打标；无法确定时标为“通用规范”并待复核',
                                            'criteria': '读取适用范围、标准名称、发布主体和正文对象，不因标题出现行业词而臆测'}],
                   'education_level': '全部'},
 'geo_scope': '按发布主体、适用范围和标准层级打标；国家标准/法律法规标为全国，地方标准标为对应省市，企业/团体标准按适用组织范围标注。',
 'timeliness': [{'value': '征求意见/草案', 'criteria': '正文或文件名明确征求意见稿或草案；不视为已生效'},
                {'value': '现行有效', 'criteria': '实施日期已到且未发现废止/替代文件'},
                {'value': '待生效', 'criteria': '已发布但实施日期尚未到'},
                {'value': '已废止/替代', 'criteria': '正文或来源明确废止、替代旧版'},
                {'value': '需复核', 'criteria': '缺少实施状态、发布日期或存在版本冲突'}],
 'data_source': [{'value': '官方发布', 'criteria': '政府部门、标准化管理机构、行业主管部门或官方标准平台'},
                 {'value': '行业机构', 'criteria': '依法登记的行业协会、标准技术组织或认证机构'},
                 {'value': '企业/团体发布', 'criteria': '企业标准、团体标准或组织内部规范，需保留发布主体和版本信息'},
                 {'value': '公开网络资料', 'criteria': '转载或聚合页面，必须回溯原始发布来源'}],
 'quality_dimensions': [{'name': '来源可靠性',
                         'weight': 0.4,
                         'description': '发布主体、文号/标准编号、原文来源和版本信息清晰可追溯。'},
                        {'name': '现行有效性', 'weight': 0.3, 'description': '发布日期、实施日期、有效期、废止/替代关系明确。'},
                        {'name': '条款完整性',
                         'weight': 0.3,
                         'description': '适用范围、规范性要求、检验/判定或实施条款完整，能够支持条款级检索。'}],
 'decomposition_note': '按规范性文件的章节、条款、附录进行语义切块，不建立领域模型。',
 'structure_description': '封面/发布信息、前言、范围、规范性引用文件、术语和定义、要求/技术指标、试验或检验方法、判定规则、实施与监督、附录。',
 'primary_knowledge_type': 'industry_research_kb',
 'default_level': 'L1',
 'co_emission_rules': [],
 'graph_profile': None}


def extend_rules(content: dict) -> dict:
    """Append the reviewed definition while preserving unrelated active rules."""
    updated = deepcopy(content)
    definitions = updated.setdefault("classifications", [])
    if not any(item.get("code") == CLASSIFICATION_CODE for item in definitions):
        definitions.append(deepcopy(CLASSIFICATION))
    for kt in updated.get("knowledge_types", []):
        if kt.get("code") == "industry_research_kb":
            applicable = kt.setdefault("applicable_classifications", [])
            if CLASSIFICATION_CODE not in applicable:
                applicable.append(CLASSIFICATION_CODE)
    return updated
