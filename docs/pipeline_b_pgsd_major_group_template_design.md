# Pipeline B PGSD 专业群与非固定模板适配设计稿

> Review draft. 本文用于评审“专业群职业能力分析表/报告”与非固定 PGSD 编码模板在 Pipeline B 中的解析、拆分、语义映射和人工审核方案。本文不变更当前冻结合同，评审通过后再同步更新 `ARCHITECT.md`、`SPEC.md`、`pipeline_b_*_contract` 与具体任务包。

## 1. 背景与样本

现有 Pipeline B 已支持 canonical PGSD 职业能力分析表，例如：

- `docs/samples/2.（职业能力分析）大数据技术应用专业职业能力分析表.xlsx`

该样本结构较固定：

```text
典型工作任务和工作内容分析表
1.数据采集
2.数据标注
3.数据ETL处理
4.可视化图表制作
```

任务 sheet 内含明确 PGSD 编码：

```text
能力类别 | 编号 | 内容
职业能力 | P-1.1.1 | ...
通用能力 | G-1.1   | ...
社会能力 | S-1.1   | ...
发展能力 | D-1.1   | ...
```

新增待适配样本：

- `docs/samples/20231017电子商务专业岗位（群）职业能力及素养分析表.xlsx`
- `docs/samples/智能建造专业群职业能力分析报告.docx`

这两类样本带来四个新的业务约束：

1. 上述文档是“专业群/岗位群分析材料”，不能默认等同于单个专业分析表；一个专业分析表对应一个 PGSD 分析报告/表。
2. PGSD 模型解析过程不能严格依赖某一种固定编码或模板模式。
3. 没有明确分类为职业能力、通用能力、社会能力、发展能力的数据报告，需要通过语义分析映射到 P/G/S/D 四个维度。
4. 具有特殊结构导致歧义无法明确映射的，应进入低置信人工审核流程，不能强行自动归类为正式结果。

## 2. 当前实现差距

当前实现主要依赖三个环节：

- `profile_detect.detector.detect_ability_analysis_pgsd`
  - 依赖四类分类词、`P/G/S/D-...` 编码和 `1.xxx` sheet 名。
- `structured_parse.record_body_adapter._project_ability_analysis_pgsd`
  - 只从 `1.xxx` sheet 中抽取任务和能力项。
- `domain_normalize.ability_analysis_writer`
  - 只消费 canonical `{analysis, tasks}` record_body，并按 PGSD profile 校验编码。

电子商务 xlsx 当前会被低置信识别为 `occupational_ability_analysis_candidate`，但投影结果为空：

```json
{
  "analysis": {
    "analysis_model": "PGSD",
    "task_count": 0,
    "work_content_count": 0,
    "ability_item_count": 0
  },
  "tasks": []
}
```

智能建造 docx 当前没有 `structured_parse` docx parser，默认不会走 record pipeline 的 `structured_parse -> profile_detect -> normalized_record -> domain_normalize` 路径。

## 3. 目标设计原则

### 3.1 专业群 fan-out

专业群原始文件必须先拆分成专业级 PGSD 分析候选：

```text
专业群原始文档
  -> structured_parse
  -> 专业群拆分
  -> 每个专业生成一个 PGSD 分析候选
  -> P/G/S/D 语义映射
  -> 置信度与歧义评估
  -> 高置信自动生成专业级 normalized_record + 领域表
  -> 低置信进入人工审核
```

推荐边界：

```text
raw_object: 智能建造专业群职业能力分析报告.docx
asset_version: 原文件版本
normalized_asset_ref A: 工程造价专业 PGSD 分析
normalized_asset_ref B: 建筑工程技术专业 PGSD 分析
normalized_asset_ref C: 建筑装饰工程技术专业 PGSD 分析
normalized_asset_ref D: 智能建造技术专业 PGSD 分析
```

每个专业级 `normalized_asset_ref` 仍需满足 v3.0 M22 字段要求：`source_type`、`content_type`、`title`、`language`、`governance`、`quality`、`lineage` 不得缺失。

`lineage` 应记录专业群来源：

```json
{
  "raw_object_id": "...",
  "object_uri": "...",
  "source_document_title": "智能建造专业群职业能力分析报告",
  "source_group_title": "智能建造专业群",
  "specialty_name": "工程造价专业",
  "split_index": 1,
  "split_strategy": "major_group_to_specialty_pgsd.v1",
  "source_ranges": []
}
```

### 3.2 PGSD 编码是 canonical 表达，不是解析前提

源文档可以有 PGSD 编码，也可以没有。系统应先识别语义维度，再生成或规范化 canonical 编码。

源文档已有编码时：

```text
保留原编码到 trace.source_code。
若原编码符合 PGSD pattern，可作为 ability_code。
若原编码不符合，保留 source_code，并生成 canonical ability_code。
```

源文档无编码时：

```text
P: P-{task_seq}.{work_content_seq}.{ability_seq}
G: G-{task_seq}.{ability_seq}
S: S-{task_seq}.{ability_seq}
D: D-{task_seq}.{ability_seq}
```

落库字段仍使用 canonical `ability_code`，以兼容现有 `ability_analysis_profile.code_pattern` 与 writer/governance 规则。

### 3.3 低置信不自动放行

当专业边界、结构识别或 P/G/S/D 语义分类存在歧义时，应显式进入 `review_required`，并保留候选映射、置信度和证据。

不得出现以下行为：

- 悄悄丢弃低置信能力项。
- 将无法判断的能力项强行写入某一类。
- 因源文档没有 PGSD 编码而跳过整个分析表。

## 4. 样本结构解析

### 4.1 电子商务 xlsx

文件：`20231017电子商务专业岗位（群）职业能力及素养分析表.xlsx`

结构：

```text
sheet: 电子商务专业岗位（群）职业能力及素养分析表

row 1: 电子商务专业岗位（群）职业能力及素养分析表
row 2: 岗位类别 | 岗位名称 | 工作内容 | 职业能力 | 职业素养
row 3+: 运营类 | 店铺运营专员 | 店铺创建与日常运营；... | 1.能... | 1.具备...
```

业务含义：

```text
专业：电子商务专业
岗位群：运营类、营销类、销售类、设计类、客服类、数据分析类
每个岗位：一个任务/岗位任务视角
工作内容：work_content
职业能力：P 类为主
职业素养：映射到 G/S/D
```

该样本不是多专业文档，应生成一个专业级 PGSD 分析：

```text
电子商务专业 PGSD 分析
```

### 4.2 智能建造 docx

文件：`智能建造专业群职业能力分析报告.docx`

文档分节：

```text
一、工程造价专业
二、建筑工程技术专业
三、建筑装饰工程技术专业
四、智能建造技术专业
```

应生成四个专业级 PGSD 分析：

```text
工程造价专业 PGSD 分析
建筑工程技术专业 PGSD 分析
建筑装饰工程技术专业 PGSD 分析
智能建造技术专业 PGSD 分析
```

文档包含至少两种表格结构：

```text
模板 A:
岗位名称 | 岗位职责 | 能力与素质要求

模板 B:
职业范畴或工作岗位 | 主要工作任务 | 职业行动领域描述
                  |              | 知识要求 | 能力要求
```

## 5. 专业群拆分规则

新增专业群拆分模块：

```text
nexus_app/structured_parse/major_group_splitter.py
```

输入：

```text
ParsedWorkbook
source_filename
profile_detect evidence
```

输出：

```python
@dataclass
class SpecialtySlice:
    specialty_name: str
    specialty_code: str | None
    rows_or_tables: list[SourceRange]
    confidence: float
    slice_payload: dict
```

专业标题识别规则：

```regex
^[一二三四五六七八九十]+、(.+专业)$
^第[一二三四五六七八九十]+部分\s*(.+专业)$
^(.+专业)$
```

最后一个正则只能在标题样式、文件名上下文或文档结构强匹配时启用，避免把普通段落误判为专业边界。

归属规则：

- 表格位于两个专业标题之间时，归属前一个专业标题。
- 表格无前置专业标题时：
  - 如果文件标题只包含一个专业名，归属该专业。
  - 如果文件标题是专业群且无法判断，进入 `review_required`。
- 单专业 xlsx 可生成一个 `SpecialtySlice`。
- 多专业 docx 应生成多个 `SpecialtySlice`。

拆分置信度：

```text
0.95: 明确编号标题 + 表格顺序完整
0.85: 专业标题明确，但部分表格边界需根据上下文归属
0.60-0.85: 标题或表格归属存在局部歧义，进入人工审核
<0.60: 不自动执行领域表写入
```

## 6. P/G/S/D 语义映射规则

映射优先级：

```text
结构显式分类 > 表头/段落标签 > 语义关键词 > LLM 结构化判定 > 人工审核
```

### 6.1 P：职业能力

定义：完成岗位工作任务、工作内容、业务流程、专业操作、工具使用、技术实施所需的专业能力。

典型信号：

```text
能完成、能根据、能使用、能操作、能编制、能审核、能建模、能施工、
能设计、能分析、能采集、能处理、能维护、专业技能、BIM、预算、结算、
施工图、店铺运营、直播、推广、客服、数据分析
```

结构来源：

```text
职业能力、能力要求、专业能力、技能要求、岗位能力
```

示例：

```text
能根据平台规则进行店铺日常维护，完成店铺管理、交易管理、客户关系管理等工作。
具备运用信息化工具完成建设工程全过程工程量计量、概预算、结算等专业技能。
```

### 6.2 G：通用能力

定义：跨岗位、跨专业可迁移的一般能力、基础方法能力、信息处理、问题分析、表达写作等。

典型信号：

```text
信息检索、数据整理、逻辑分析、问题分析、书面写作、语言表达、办公软件、
基础知识、学习方法、计划管理、时间管理
```

示例：

```text
具有较强的语言表达和书面写作能力。
具备收集、整理、分析信息的能力。
```

注意：表达沟通如果强调“团队协作/客户互动”，更偏 S；如果强调一般表达或写作，归 G。

### 6.3 S：社会能力

定义：与组织、团队、客户、协作、职业伦理、沟通互动、服务意识、规则意识相关的能力和素养。

典型信号：

```text
团队、协作、沟通、客户、服务、职业道德、诚实守信、遵纪守法、安全意识、
责任感、社会责任、服从管理
```

示例：

```text
具备良好的团队合作精神，能与其他部门协作。
具有诚实守信的职业道德和互联网安全意识。
```

### 6.4 D：发展能力

定义：面向个人持续成长、职业发展、创新创业、适应变化、反思改进、抗压韧性、终身学习的能力。

典型信号：

```text
持续学习、创新、开拓创新、精益求精、工匠精神、自我提升、职业发展、
抗压、进取、适应变化、更新知识
```

示例：

```text
具备持续学习、不断更新自身知识的素质。
具有精益求精、开拓创新的工匠精神。
具备较强的抗压能力，能调节运营工作中的压力。
```

### 6.5 冲突处理

当一条文本同时命中多个维度：

1. 若直接描述完成专业工作任务、工具操作、业务流程，优先 P。
2. 若主要描述团队、客户、职业伦理、合规，优先 S。
3. 若主要描述持续学习、创新、抗压、成长，优先 D。
4. 若是基础方法、表达、信息处理、通用问题分析，归 G。
5. 若一句话包含多个独立能力，应先拆句，再分别分类。

示例：

```text
具备良好的表达沟通能力，能与团队成员开展高效沟通。
```

映射为 S，因为上下文是团队协作。

```text
具备较强的语言表达和书面写作能力。
```

映射为 G，因为这是一般表达能力。

```text
具有认真负责、科学严谨、实事求是的工作态度和精益求精、开拓创新的工匠精神。
```

应拆分为：

```text
认真负责、科学严谨、实事求是 -> S
精益求精、开拓创新 -> D
```

无法可靠拆分时进入人工审核。

## 7. 置信度与审核规则

### 7.1 单条能力置信度

每条能力项应记录：

```json
{
  "ability_code": "S-1.1",
  "ability_major_category_code": "S",
  "ability_content": "...",
  "mapping_confidence": 0.86,
  "mapping_evidence": {
    "matched_keywords": ["团队合作", "协作"],
    "source_label": "职业素养",
    "strategy": "keyword_semantic_rule.v1"
  },
  "mapping_flags": []
}
```

建议阈值：

```text
mapping_confidence >= 0.80
  可自动采纳。

0.60 <= mapping_confidence < 0.80
  保留候选，但专业分析进入 review_required。

mapping_confidence < 0.60
  不自动写入正式 ability item，进入人工审核候选池。
```

### 7.2 专业级置信度

专业级分析应记录：

```json
{
  "analysis_confidence": 0.91,
  "split_confidence": 0.96,
  "mapping_confidence_avg": 0.88,
  "low_confidence_item_count": 3,
  "ambiguous_item_count": 1
}
```

建议自动通过条件：

```text
split_confidence >= 0.85
analysis_confidence >= 0.85
P 类能力数量 > 0
低置信能力项占比 <= 20%
无 blocking ambiguity
```

非固定模板缺少 G/S/D 时不应自动失败，但应记录：

```json
{
  "missing_pgsd_categories": ["G", "D"]
}
```

P0 建议：非编码模板只要缺任一 G/S/D，默认 `review_required`，但仍生成候选 normalized_record，等待业务专家确认是否接受部分维度。

### 7.3 blocking ambiguity

以下情况应阻止自动 available：

- 无法确定专业边界。
- 无法确定某表属于哪个专业。
- 岗位/任务行跨表断裂。
- 能力与素质混在一起且无法拆分。
- 同一条能力 P/S/D 多类得分接近。
- P 类能力无法挂接到任何 work_content。
- 同一专业下任务/岗位重复严重。

判定建议：

```text
top_category_score - second_category_score < 0.15 -> ability_category_ambiguous
专业标题定位置信度 < 0.80 -> specialty_split_ambiguous
表格 header 置信度 < 0.75 -> structure_ambiguous
P ability 无 work_content parent -> p_work_content_missing
```

## 8. 目标 record_body 结构

最终仍输出现有 writer 支持的 canonical 结构：

```json
{
  "analysis": {
    "analysis_model": "PGSD",
    "major_name": "工程造价专业",
    "major_direction": null,
    "source_group_name": "智能建造专业群",
    "task_count": 3,
    "work_content_count": 18,
    "ability_item_count": 42
  },
  "tasks": [
    {
      "task_code": "1",
      "task_name": "BIM造价工程师",
      "task_description": "...",
      "display_order": 1,
      "trace": {},
      "work_contents": [
        {
          "content_code": "1.1",
          "content_name": "审查施工图纸",
          "abilities": [
            {
              "ability_code": "P-1.1.1",
              "ability_major_category_code": "P",
              "ability_content": "具有参与施工图纸会审工作的能力",
              "mapping_confidence": 0.92
            }
          ]
        }
      ],
      "general_abilities": {
        "G": [],
        "S": [],
        "D": []
      }
    }
  ],
  "mapping_meta": {
    "source_template": "docx_major_group_job_role_report.v1",
    "source_is_major_group": true,
    "specialty_split": {
      "specialty_name": "工程造价专业",
      "split_confidence": 0.96,
      "source_heading": "一、工程造价专业"
    },
    "pgsd_mapping": {
      "strategy": "semantic_rules_with_llm_fallback.v1",
      "average_confidence": 0.87,
      "low_confidence_count": 2,
      "ambiguous_count": 1
    },
    "review": {
      "required": true,
      "reasons": ["ability_category_ambiguous"]
    }
  }
}
```

`mapping_meta` 不应破坏 `ability_analysis_writer`，writer 可以忽略它；治理和人工审核可以读取它。

## 9. 两个样本映射示例

### 9.1 电子商务 xlsx

源：

```text
岗位名称：店铺运营专员
工作内容：店铺创建与日常运营；商品管理；订单管理；店铺数据收集与分析；平台活动执行。
职业能力：
1.能根据平台规则，在电商平台完成店铺入驻...
2.能根据平台规则进行店铺日常维护...
职业素养：
1.具备良好的团队合作精神...
2.具备良好的表达沟通能力...
3.具备较强的抗压能力...
```

目标：

```json
{
  "task_code": "1",
  "task_name": "店铺运营专员",
  "work_contents": [
    {
      "content_code": "1.1",
      "content_name": "店铺创建与日常运营",
      "abilities": [
        {
          "ability_code": "P-1.1.1",
          "ability_major_category_code": "P",
          "ability_content": "能根据平台规则，在电商平台完成店铺入驻，完善店铺基础信息",
          "mapping_confidence": 0.93
        }
      ]
    }
  ],
  "general_abilities": {
    "G": [],
    "S": [
      {
        "ability_code": "S-1.1",
        "ability_major_category_code": "S",
        "ability_content": "具备良好的团队合作精神，能与其他部门协作",
        "mapping_confidence": 0.91
      }
    ],
    "D": [
      {
        "ability_code": "D-1.1",
        "ability_major_category_code": "D",
        "ability_content": "具备较强的抗压能力，能调节运营工作中的压力",
        "mapping_confidence": 0.86
      }
    ]
  }
}
```

### 9.2 智能建造 docx

专业分节：

```text
一、工程造价专业
```

岗位：

```text
BIM造价工程师
```

能力与素质要求：

```text
能力要求：
1.具有参与施工图纸会审工作的能力；
2.具备运用信息化工具完成建设工程全过程的工程量计量、概预算、结算等专业技能。

素质要求：
1.具有爱岗敬业、奋发进取、团结协作的品质；
2.具有较强的语言表达和书面写作能力。
```

目标映射：

```text
工程造价专业 PGSD 分析
task: BIM造价工程师
work_content: 审查施工图纸 / BIM算量模型 / 造价成果分析 / 采购材料设备价格分析 ...
P: 参与施工图纸会审、运用信息化工具完成工程计量/概预算/结算
S: 爱岗敬业、团结协作
G: 语言表达和书面写作
D: 奋发进取
```

其中“具有爱岗敬业、奋发进取、团结协作的品质”应拆句：

```text
爱岗敬业 -> S
奋发进取 -> D
团结协作 -> S
```

如拆句置信度不足，进入人工审核。

## 10. 代码落地方案

### 10.1 新增 docx parser

新增：

```text
nexus-app/nexus_app/structured_parse/docx_parser.py
```

导出：

```python
def parse_docx(
    source: bytes | str | Path | BinaryIO,
    *,
    source_filename: str | None = None,
    source_mime_type: str | None = None,
    timezone_name: str = DEFAULT_TIMEZONE,
) -> ParsedWorkbook:
    ...
```

实现要点：

- 用 `zipfile` + `word/document.xml` 解析，避免新增运行时依赖。
- 按文档顺序遍历 `w:body` 子节点。
- 遇到段落标题如 `一、工程造价专业`，记录 `current_section`。
- 遇到 `w:tbl`，转换为 `ParsedSheet`。
- `sheet.name = current_section` 或 `f"{current_section}#table{n}"`。
- 每个 table row 转为 `ParsedRow`。
- 每个 cell 转为 `ParsedCell`。
- 保留段落、表格、行列 trace。
- `parser_version = "docx_parser.v1"`。

同步更新：

```text
nexus-app/nexus_app/structured_parse/__init__.py
```

### 10.2 接入层 docx route 到 record pipeline

新增 MIME：

```python
DOCX_MIME_TYPES = frozenset({
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
})
```

新增配置：

```python
pipeline_b_docx_enabled: bool = False
```

路由策略：

```python
if normalized_mime in DOCX_MIME_TYPES and cfg.pipeline_b_docx_enabled:
    return PipelineType.RECORD
```

worker 新增：

```python
elif mime in DOCX_MIME_TYPES:
    raw_payload = _run_structured_parse_docx(...)
```

profile_detect 覆盖 docx：

```python
if mime in XLSX_MIME_TYPES or mime in CSV_MIME_TYPES or mime in DOCX_MIME_TYPES:
    profile_result = _run_profile_detect(...)
```

### 10.3 新增专业群拆分模块

新增：

```text
nexus-app/nexus_app/structured_parse/major_group_splitter.py
```

职责：

- 判断是否专业群文档。
- 将 `ParsedWorkbook` 拆成一个或多个 `SpecialtySlice`。
- 每个 slice 对应一个专业。
- 不做 P/G/S/D 映射。

### 10.4 新增 PGSD 语义映射模块

新增：

```text
nexus-app/nexus_app/structured_parse/pgsd_semantic_mapper.py
```

职责：

- 从 `SpecialtySlice` 抽取 task/work_content/raw ability text。
- 根据结构标签和语义规则映射 P/G/S/D。
- 必要时调用 LLM 做结构化兜底。
- 生成 canonical PGSD 编码。
- 计算 item-level 与 analysis-level confidence。
- 输出 review flags。

LLM 兜底触发条件：

```text
最高分 < 0.80
或最高分与第二名差值 < 0.15
或一条文本包含多个明显语义片段
```

LLM 输出必须通过：

- schema validation
- P/G/S/D whitelist
- confidence threshold
- evidence required
- audit log
- state-machine decision

### 10.5 调整 profile_detect

`detect_ability_analysis_pgsd` 不应只检测 encoded PGSD，而应支持多模板：

```python
def detect_ability_analysis_pgsd(workbook: ParsedWorkbook) -> ProfileDetectResult:
    candidates = [
        _detect_encoded_pgsd_workbook(workbook),
        _detect_job_role_ability_matrix(workbook),
        _detect_major_group_ability_report(workbook),
    ]
    return max(candidates, key=lambda r: r.confidence)
```

新增模板：

```text
ability_matrix.job_role.v1
major_group_ability_report.docx.v1
action_field_report.docx.v1
```

输出仍为：

```text
domain_profile = ability_analysis.pgsd.v1
```

evidence 建议包含：

```json
{
  "template_kind": "major_group_ability_report.docx.v1",
  "source_is_major_group": true,
  "specialty_count": 4,
  "matched_headers": []
}
```

### 10.6 调整 record_body_adapter

保留旧函数：

```python
def project_to_record_body(raw_payload, profile_dict) -> dict[str, Any]:
    ...
```

新增多候选函数：

```python
def project_to_record_body_candidates(
    raw_payload: dict[str, Any],
    profile_dict: dict[str, Any] | None,
) -> list[RecordBodyCandidate]:
    ...
```

候选结构：

```python
@dataclass
class RecordBodyCandidate:
    record_body: dict[str, Any]
    title: str
    specialty_name: str | None
    split_confidence: float
    mapping_confidence: float
    review_required: bool
    review_reasons: list[str]
```

旧函数可兼容：

```python
candidates = project_to_record_body_candidates(...)
return candidates[0].record_body if candidates else raw_payload
```

### 10.7 Pipeline fan-out

新增：

```python
def run_normalize_record_many(...) -> list[NormalizedAssetRef]:
    ...
```

行为：

- 单专业候选：生成一个 normalized_ref，兼容旧路径。
- 专业群候选：生成多个专业级 normalized_ref。
- 每个 normalized_ref 都带独立 `lineage.specialty_name`、`quality.review` 和 `mapping_meta`。

`JobStage` detail 应记录：

```json
{
  "normalized_ref_count": 4,
  "split_strategy": "major_group_to_specialty_pgsd.v1",
  "specialties": ["工程造价专业", "建筑工程技术专业", "建筑装饰工程技术专业", "智能建造技术专业"]
}
```

任一 specialty 进入 review 时，建议整体 asset_version 为 `review_required`。

## 11. 人工审核 payload

低置信候选应保留给审核界面：

```json
{
  "mapping_candidates": [
    {
      "source_text": "具有爱岗敬业、奋发进取、团结协作的品质",
      "suggested_splits": [
        {
          "text": "具有爱岗敬业的品质",
          "category": "S",
          "confidence": 0.82
        },
        {
          "text": "具有奋发进取的品质",
          "category": "D",
          "confidence": 0.78
        },
        {
          "text": "具有团结协作的品质",
          "category": "S",
          "confidence": 0.90
        }
      ],
      "review_required": true,
      "reason": "compound_literacy_statement"
    }
  ]
}
```

审核动作：

```text
accept category
change category
split item
merge item
discard item
assign work_content
```

审核后重新生成 canonical PGSD `record_body`，再执行 domain_normalize。

## 12. 状态机建议

高置信专业 slice：

```text
normalized_ref.status = generated
domain_normalize 写入 occupational_ability_analysis
后续治理按现有 PGSD 规则执行
```

中置信专业 slice：

```text
normalized_ref.status = generated
payload.quality.manual_review_status = required
asset_version.status = review_required
domain_normalize 可写领域表，但不得使版本自动 available
```

低置信或结构歧义严重：

```text
normalized_ref.status = generated
domain_normalize 跳过
asset_version.status = review_required
review_queue 展示候选拆分与候选映射
```

建议 review reasons：

```text
pgsd_mapping_low_confidence
specialty_split_ambiguous
ability_category_ambiguous
structure_ambiguous
p_work_content_missing
compound_literacy_statement
```

## 13. 前端影响

若专业群文档 fan-out 为多个 normalized_ref，资产详情页需要支持：

```text
record 类型为专业群时：
  先展示专业列表
  点击某个专业后进入现有 PGSD 能力分析视图
```

如果保持一个 asset_version 下多个 normalized_ref，现有“latest_normalized_ref”读取模型需要明确选择策略：

- 默认显示第一个高置信专业。
- 或显示专业列表，不默认进入单个专业。

建议新增专业列表视图，避免用户误以为专业群只生成了一个专业分析。

## 14. 测试计划

新增测试：

```text
nexus-app/tests/structured_parse/test_docx_parser.py
nexus-app/tests/profile_detect/test_ability_analysis_templates.py
nexus-app/tests/test_record_body_adapter_ability_templates.py
nexus-app/tests/integration/test_pipeline_b_major_group_pgsd_e2e.py
```

电子商务 xlsx 断言：

```text
detect.record_type == occupational_ability_analysis
detect.domain_profile == ability_analysis.pgsd.v1
detect.confidence >= 0.85
specialty_count == 1
major_name == 电子商务专业
record_body.analysis.analysis_model == PGSD
存在 P 类 ability
存在 S/D/G 候选 ability
所有 canonical P code 满足 ^P-\d+\.\d+\.\d+$
所有 canonical G/S/D code 满足 ^[GSD]-\d+\.\d+$
```

智能建造 docx 断言：

```text
parse_docx 产出表格 sheet
detect.record_type == occupational_ability_analysis
source_is_major_group == true
specialty_count == 4
专业列表包含 工程造价专业、建筑工程技术专业、建筑装饰工程技术专业、智能建造技术专业
每个专业生成一个 PGSD record_body candidate
岗位名称成为 task
岗位职责/主要工作任务成为 work_content
能力要求生成 P
素质要求通过语义映射到 G/S/D
歧义条目带 review_required
```

domain writer 集成断言：

```text
每个高置信 specialty 写入 1 条 occupational_ability_analysis
occupational_work_task > 0
occupational_work_content > 0
occupational_ability_item > 0
P 类 item.work_content_id 不为空
G/S/D 类 item.work_content_id 为空
review_required candidate 不自动 available
```

## 15. 不建议做法

不建议新增：

```text
ability_analysis.ecommerce.v1
ability_analysis.major_group_report.v1
```

原因：目标是统一转换为 PGSD 领域模型结构，新增 domain_profile 会导致治理、图谱 staging、前端视图和 API 读模型分叉。

不建议改领域表结构：

```text
occupational_ability_analysis
occupational_work_task
occupational_work_content
occupational_ability_item
```

现有表可以表达专业级 PGSD 分析，缺口在上游拆分与语义映射。

不建议把 docx 直接走 MinerU document 后从 markdown 写领域表。

原因：

- 会绕开 record pipeline 合同。
- 治理输入链路和领域写入链路不可追踪。
- 难以保留表格行列级 trace 和专业拆分证据。

## 16. 推荐实施顺序

1. 支持电子商务 xlsx 单专业单表。
   - 改 detector、adapter、semantic mapper。
   - 不涉及 fan-out。
2. 新增 PGSD semantic mapper。
   - 将“职业能力/能力要求/职业素养/素质要求”语义映射到 P/G/S/D。
   - 不再依赖源文件 PGSD 编码。
3. 新增 docx parser。
   - 默认 feature flag 关闭。
   - 先通过 parser 和 adapter 单元测试。
4. 新增专业群 splitter。
   - 支持智能建造 docx 拆成 4 个专业。
5. 增加 pipeline fan-out。
   - 每个专业一个 normalized_ref。
6. 增加 review_required gate。
   - 结构歧义、语义低置信、专业边界不清晰时进入人工审核。
7. 更新前端。
   - 资产详情中专业群显示专业列表，再进入单专业 PGSD 能力分析视图。

## 17. Review 待确认问题

1. 一个专业群 asset_version 下多个 normalized_ref 是否符合当前读取模型，还是需要新增“专业级子资产”概念？
2. 任一专业 slice `review_required` 时，整个 asset_version 是否必须 `review_required`？
3. 非编码模板缺失 G/S/D 时，是否一律人工审核，还是允许高置信 P/S 自动 available？
4. “知识要求”是否应作为 G 类 ability，还是仅进入 trace/normalized_terms？
5. LLM 语义映射是否允许在 P0 自动采纳，还是只能产生候选建议？
6. 前端专业群列表应放在资产详情哪个页签：知识块页签、能力分析页签，还是新增“专业分析”子视图？
