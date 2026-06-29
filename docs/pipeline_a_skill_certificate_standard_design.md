# Pipeline A 职业技能证书标准文档领域模型设计稿

> Review Draft. 本文用于评审“职业技能证书标准 / 职业技能等级标准 / 国家职业技能标准”PDF 文档类资产的解析、领域抽取、PGSD-compatible 能力映射、治理和 API 方案。本文不变更当前实现合同；评审通过后再同步更新 `ARCHITECT.md`、`SPEC.md`、Pipeline 合同文档和任务包。

## 0. 背景与样本

样本文件：

- `docs/samples/（电子商务1+X证书）电子商务数据分析职业技能等级标准（v2021-2.0）.pdf`
- `docs/samples/（电子商务职业技能等级证书）电子商务师国家职业技能标准.pdf`

业务判断：

- 这类资产以 PDF 文档为主，内容主要说明职业岗位信息、职业概况、工作内容、职业功能、职业技能要求、知识要求、职业道德、评价要求等。
- 原始处理路径必须走 Pipeline A 文档解析链路，调用 MinerU，产出 `parse_artifact` 和 `normalized_document`。
- 领域模型目标类似 PGSD 职业能力分析模型，服务人才培养方案建设、院校专业群建设、课证融通、能力图谱和课程体系对标。
- 治理输入必须是 `normalized_document` via `normalized_asset_ref`，不得直接使用 raw PDF、MinerU raw output 或 parse 原始中间件结果作为治理输入。

核心结论：

```text
职业技能证书 PDF 是 Pipeline A 文档资产，不是 Pipeline B 结构化记录资产；
但在 normalized_document 后应增加 skill_certificate_standard 文档领域抽取，
将证书标准中的职业功能、工作任务、技能要求、知识要求抽取为证书标准领域表，
并生成 PGSD-compatible 能力映射，用于人才培养方案和专业群建设。
```

## 1. 与现有 Pipeline 边界的关系

### 1.1 Pipeline A 路径

职业技能证书标准 PDF 按文档资产处理：

```text
PDF 文件
  -> raw_object
  -> ingest_validate
  -> Job(payload.pipeline_type="document")
  -> assetize(asset / asset_version)
  -> parse(MinerU)
       - model_version 自动选择
       - PDF 自动 OCR
       - 图片存储 parsed/<version_id>/<artifact_id>/images/
       - 生成 parse_artifact
  -> normalize(normalized_document)
       - body_markdown
       - blocks
       - toc / headings / tables / images
       - normalized_asset_ref(type=document)
  -> document_profile_detect
  -> certificate_domain_extract
  -> AI governance
  -> governance rules
  -> available / review_required
  -> knowledge_chunk / index
```

约束：

- 必须调用 MinerU；不得因为后续要生成能力模型就绕过 Pipeline A。
- `parse_artifact` 只作为 normalize 上游产物和解析追溯证据。
- 治理输入是 `normalized_asset_ref` 引用的 `normalized_document`。
- `governance_result` target 仍然是 `normalized_asset_ref`，不是 `asset_version` 或领域表。
- 不增加 `asset.current_version_id`、`asset_version.normalized_ref_id` 等反向指针。

### 1.2 与 Pipeline B PGSD 的区别

| 对象 | 原始形态 | 管道 | 领域目标 |
| --- | --- | --- | --- |
| 职业能力分析表 | XLSX / 结构化表 | Pipeline B | 直接落 PGSD 职业能力分析模型 |
| 专业布点表 | XLSX / 结构化统计表 | Pipeline B | 专业布点领域表 |
| 职业技能证书标准 | PDF / Word 文档 | Pipeline A | 从文档抽取岗位、任务、技能、知识、等级，并映射 PGSD-compatible 能力模型 |

设计边界：

- Pipeline B 的 `occupational_ability_analysis` 是结构化输入直接标准化。
- 证书标准 PDF 是非结构化文档，需要先 MinerU 解析为 `normalized_document`，再做领域抽取。
- 不应把 PDF 强行塞进 `structured_parse -> profile_detect -> domain_normalize`。

## 2. 业务定位

建议新增业务分类：

```text
classification.code = vocational_skill_certificate_standard
classification.name = 职业技能证书标准
domain = occupation
document_profile = skill_certificate_standard.v1
ability_mapping_profile = certificate_pgsd_mapping.v1
```

同义业务名：

```text
职业技能证书标准
职业技能等级标准
国家职业技能标准
1+X 职业技能等级标准
职业技能等级证书标准
```

主要服务场景：

- 人才培养方案建设
- 专业群建设
- 课程体系设计
- 课证融通
- 岗课赛证综合育人
- 职业能力图谱构建
- 课程标准 / 实训项目 / 评价标准对标

## 3. 文档 Profile 识别

新增文档 profile：

```json
{
  "document_type": "skill_certificate_standard",
  "domain": "occupation",
  "document_profile": "skill_certificate_standard.v1",
  "ability_mapping_profile": "certificate_pgsd_mapping.v1",
  "detector_version": "document-profile-detector.v1"
}
```

识别证据：

| 证据类型 | 示例 |
| --- | --- |
| 文件名关键词 | `1+X证书`、`职业技能等级标准`、`国家职业技能标准`、`电子商务师`、`职业技能等级证书` |
| 标题关键词 | `职业技能等级标准`、`国家职业技能标准`、`职业标准` |
| 章节关键词 | `职业概况`、`基本要求`、`工作要求`、`职业功能`、`工作内容`、`技能要求`、`相关知识要求` |
| 等级关键词 | `初级`、`中级`、`高级`、`五级`、`四级`、`三级`、`二级`、`一级` |
| 表格结构 | `职业功能 / 工作内容 / 技能要求 / 相关知识要求` |
| 发布主体 | `人力资源和社会保障部`、`教育部`、`培训评价组织`、`职业技能等级证书` |

建议输出：

```json
{
  "document_type": "skill_certificate_standard",
  "domain": "occupation",
  "document_profile": "skill_certificate_standard.v1",
  "confidence": 0.93,
  "evidence": {
    "title": "电子商务数据分析职业技能等级标准",
    "matched_keywords": ["1+X证书", "职业技能等级标准", "技能要求", "知识要求"],
    "matched_sections": ["职业概况", "工作要求", "职业功能", "工作内容"],
    "detected_levels": ["初级", "中级", "高级"],
    "issuer": "培训评价组织",
    "source_blocks": ["block-001", "block-018", "block-042"]
  }
}
```

低置信时：

```text
document_type = skill_certificate_standard_candidate
status = review_required
```

## 4. 领域抽取目标

从 `normalized_document` 中抽取：

- 证书/职业基本信息
- 职业岗位或职业方向
- 职业等级
- 工作领域 / 职业功能
- 工作任务 / 工作内容
- 技能要求
- 知识要求
- 素养 / 职业道德 / 安全规范要求
- 评价要求 / 权重 / 考核方式
- 适用专业 / 相关职业 / 职业编码
- 版本、发布机构、发布日期、证书类型

抽取来源：

- `normalized_document.body_markdown`
- `normalized_document.blocks`
- `normalized_asset_ref.title`
- `normalized_asset_ref.lineage`
- `normalized_asset_ref.quality`
- `normalized_asset_ref.governance`

不得直接读取：

- raw PDF
- MinerU raw output
- 未标准化 JSON
- 大段原始明文日志

## 5. 领域数据模型建议

### 5.1 主表：`skill_certificate_standard`

一份证书标准文档对应一条主记录。

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | UUID | 主键 |
| `normalized_ref_id` | UUID | FK -> `normalized_asset_ref.id`，唯一 |
| `asset_version_id` | UUID | FK -> `asset_version.id` |
| `standard_name` | TEXT | 标准名称 |
| `certificate_name` | TEXT | 证书名称 |
| `certificate_type` | TEXT | `1+x` / `national_occupation_standard` / `industry_certificate` / `unknown` |
| `occupation_name` | TEXT | 职业名称，如电子商务师 |
| `occupation_code` | TEXT | 职业编码，可空 |
| `major_name` | TEXT | 关联专业，如电子商务 |
| `major_code` | TEXT | 专业代码，可空 |
| `issuer` | TEXT | 发布/制定机构 |
| `version_text` | TEXT | 版本，如 `v2021-2.0` |
| `published_date` | DATE | 发布日期，可空 |
| `effective_date` | DATE | 实施日期，可空 |
| `source_channel` | TEXT | `file_upload` / `nas` |
| `document_profile` | TEXT | `skill_certificate_standard.v1` |
| `mapping_profile` | TEXT | `certificate_pgsd_mapping.v1` |
| `level_count` | INT | 识别到的等级数 |
| `occupation_count` | INT | 职业/岗位数 |
| `task_count` | INT | 任务数 |
| `skill_requirement_count` | INT | 技能要求数 |
| `knowledge_requirement_count` | INT | 知识要求数 |
| `quality_summary` | JSON | 抽取质量摘要 |
| `created_at` / `updated_at` | TIMESTAMP | 时间戳 |

约束：

```text
UNIQUE(normalized_ref_id)
INDEX(asset_version_id)
INDEX(certificate_type)
INDEX(occupation_name)
INDEX(major_code)
```

### 5.2 等级表：`skill_certificate_level`

| 字段 | 说明 |
| --- | --- |
| `id` | 主键 |
| `standard_id` | FK -> `skill_certificate_standard.id` |
| `level_code` | `level_5` / `level_4` / `level_3` / `primary` / `intermediate` / `advanced` |
| `level_name` | 五级/四级/三级/初级/中级/高级 |
| `level_order` | 排序 |
| `description` | 等级说明 |
| `trace` | 来源 block/page/heading |

等级规范化建议：

| 原文 | 规范值 |
| --- | --- |
| 五级 / 初级 | `level_5` 或 `primary` |
| 四级 / 中级 | `level_4` 或 `intermediate` |
| 三级 / 高级 | `level_3` 或 `advanced` |
| 二级 / 技师 | `level_2` |
| 一级 / 高级技师 | `level_1` |

保留原文，不强制猜测缺失等级。

### 5.3 职业/岗位方向表：`skill_certificate_occupation`

| 字段 | 说明 |
| --- | --- |
| `id` | 主键 |
| `standard_id` | FK |
| `occupation_name` | 职业/岗位/方向名称 |
| `occupation_code` | 职业编码，可空 |
| `direction_name` | 方向，如数据分析、运营推广 |
| `description` | 职业描述 |
| `trace` | 来源位置 |

示例：

```text
电子商务师
电子商务数据分析
网店运营推广
直播电商运营
```

### 5.4 职业功能 / 工作领域表：`skill_certificate_work_domain`

| 字段 | 说明 |
| --- | --- |
| `id` | 主键 |
| `standard_id` | FK |
| `level_id` | FK，可空 |
| `occupation_id` | FK，可空 |
| `domain_name` | 职业功能 / 工作领域 |
| `display_order` | 排序 |
| `description` | 原文描述 |
| `trace` | 来源位置 |

### 5.5 工作任务 / 工作内容表：`skill_certificate_work_task`

| 字段 | 说明 |
| --- | --- |
| `id` | 主键 |
| `standard_id` | FK |
| `level_id` | FK，可空 |
| `occupation_id` | FK，可空 |
| `work_domain_id` | FK，可空 |
| `task_name` | 工作任务名称 |
| `task_description` | 工作内容描述 |
| `task_code` | 系统生成 canonical code |
| `display_order` | 排序 |
| `trace` | 来源位置 |

任务编码建议：

```text
CERT-P-<level_order>.<domain_seq>.<task_seq>
```

不要依赖源文档必须有编码。

### 5.6 技能要求表：`skill_requirement_item`

| 字段 | 说明 |
| --- | --- |
| `id` | 主键 |
| `standard_id` | FK |
| `task_id` | FK |
| `level_id` | FK，可空 |
| `requirement_text` | 技能要求原文 |
| `normalized_terms` | JSON，技能关键词 |
| `requirement_type` | `skill` |
| `pgsd_category` | `P` / `G` / `S` / `D` |
| `ability_code` | canonical PGSD-compatible code |
| `confidence` | 映射置信度 |
| `quality_flags` | JSON |
| `trace` | 来源位置 |

### 5.7 知识要求表：`knowledge_requirement_item`

| 字段 | 说明 |
| --- | --- |
| `id` | 主键 |
| `standard_id` | FK |
| `task_id` | FK |
| `level_id` | FK，可空 |
| `knowledge_text` | 知识要求原文 |
| `knowledge_domain` | 电商运营 / 数据分析 / 法规 / 安全等 |
| `normalized_terms` | JSON |
| `confidence` | 抽取置信度 |
| `trace` | 来源位置 |

### 5.8 评价要求表：`certificate_assessment_requirement`

P0 可暂缓落表，先放入 `quality_summary` 或 `extraction_result.assessment_requirements`。P1 再独立建表。

建议字段：

```text
assessment_method
assessment_content
weight
level_id
task_id
trace
```

## 6. PGSD-compatible 映射

证书标准中的“技能要求 / 知识要求 / 职业素养”不一定显式区分 PGSD，但可以映射为 PGSD-compatible 能力模型。

建议映射规则：

| 来源内容 | PGSD 类别 | 说明 |
| --- | --- | --- |
| 职业功能、工作任务、操作技能、业务处理能力 | `P` 职业能力 | 证书标准主体能力 |
| 通用工具、数据分析方法、沟通协作、信息技术应用 | `G` 通用能力 | 跨岗位能力 |
| 职业道德、法律法规、服务意识、质量意识、安全规范 | `S` 社会能力 | 职业素养、规范、安全 |
| 学习提升、创新创业、持续改进、职业发展 | `D` 发展能力 | 发展性能力 |

示例 canonical JSON：

```json
{
  "ability_mapping_profile": "certificate_pgsd_mapping.v1",
  "tasks": [
    {
      "task_code": "CERT-P-3.1.1",
      "task_name": "电子商务数据采集",
      "work_contents": [
        {
          "content_code": "CERT-P-3.1.1.1",
          "content_name": "采集交易、流量、用户行为数据",
          "abilities": [
            {
              "ability_code": "P-3.1.1",
              "ability_major_category_code": "P",
              "ability_content": "能够根据分析目标采集并整理电子商务运营数据",
              "source_requirement_type": "skill",
              "source_text": "能够采集、清洗、整理电子商务数据",
              "confidence": 0.88
            }
          ],
          "knowledge_requirements": [
            {
              "knowledge_text": "掌握电子商务数据指标体系、数据采集方法",
              "knowledge_domain": "data_analysis"
            }
          ]
        }
      ]
    }
  ]
}
```

约束：

- PGSD 映射是衍生模型，不覆盖证书标准原文结构。
- `source_text`、`trace`、`confidence` 必须保留，便于人工复核。
- 没有显式 PGSD 编码时可以生成 canonical code，但必须标注 `code_generated=true`。
- 低置信映射进入 review，不自动影响官方治理结果。

## 7. 是否复用现有 PGSD 表

不建议直接把证书标准写入现有 `occupational_ability_analysis` 主表。

原因：

1. 证书标准源形态是文档，不是结构化职业能力分析表。
2. 证书标准有“证书、等级、职业功能、评价要求、权重、考核方式”等特有字段。
3. PGSD 是能力映射目标，不是证书标准的原始结构。
4. 直接写入 `occupational_ability_analysis` 会混淆“职业能力分析表”和“证书标准文档”的来源语义。

推荐“双层模型”：

```text
证书标准原生模型
  -> skill_certificate_standard / level / task / skill / knowledge

PGSD-compatible 投影模型
  -> skill_certificate_pgsd_projection / skill_certificate_ability_item
```

建议新增：

```text
skill_certificate_pgsd_projection
```

字段：

| 字段 | 说明 |
| --- | --- |
| `id` | 主键 |
| `standard_id` | FK |
| `profile_id` | FK -> `ability_analysis_profile` |
| `analysis_model` | `PGSD` |
| `task_count` | 任务数量 |
| `ability_item_count` | 能力项数量 |
| `quality_summary` | 映射质量 |
| `created_at` | 创建时间 |

以及：

```text
skill_certificate_ability_item
```

字段复用 `occupational_ability_item` 的核心语义：

```text
ability_code
ability_major_category_code
ability_major_category_name
ability_sequence
ability_content
confidence
quality_flags
trace
source_requirement_id
```

能力图谱层可以统一汇聚：

```text
occupational_ability_analysis
skill_certificate_pgsd_projection
job_demand_requirement_item
major_distribution
```

## 8. 抽取策略

### 8.1 MinerU 解析要求

PDF 走现有 Pipeline A：

```text
model_version: auto-selected by mime_type
ocr_enable: true for PDF
return_images: true
response_format_zip: true
image path: parsed/<version_id>/<artifact_id>/images/
```

normalize 后应保留：

```text
blocks[]
body_markdown
toc
heading path
page number
table markdown/html
image_uris
```

### 8.2 文档结构识别

从 `normalized_document.blocks` 识别：

```text
标题
目录
一级/二级章节
表格块
连续段落块
页码
```

重点章节：

```text
职业概况
基本要求
职业道德
基础知识
工作要求
职业功能
工作内容
技能要求
相关知识要求
权重表
评价要求
```

### 8.3 表格优先

证书标准常见表格：

```text
职业功能 | 工作内容 | 技能要求 | 相关知识要求
工作领域 | 工作任务 | 职业技能要求 | 专业知识要求
等级 | 职业功能 | 工作内容 | 技能要求 | 相关知识要求
```

处理优先级：

```text
table block -> structured rows -> task / skill / knowledge
paragraph block -> fallback semantic extraction
```

### 8.4 LLM 抽取

新增 Prompt Profile：

```text
occupation.skill_certificate.standard_extraction
```

输入只能来自 normalized_document 摘要和允许策略下的内容片段：

```json
{
  "title": "...",
  "toc": [],
  "section_blocks": [],
  "tables": [],
  "document_metadata": {},
  "governance_context": {}
}
```

输出 schema：

```json
{
  "standard": {},
  "levels": [],
  "occupations": [],
  "work_domains": [],
  "tasks": [],
  "skill_requirements": [],
  "knowledge_requirements": [],
  "assessment_requirements": [],
  "pgsd_mapping": []
}
```

必须执行：

- Pydantic schema validation
- 字段白名单
- 敏感内容脱敏
- 置信度阈值
- 规则校验
- 人工 review 分流

## 9. 治理规则设计

分类、分级、打标和准入必须使用 active `governance_rule_version` 中的内置规则，不允许在 extractor/writer 中硬编码最终治理结论。

建议扩展 `governance_rule_version.rules_content`：

```json
{
  "classifications": [
    {
      "code": "vocational_skill_certificate_standard",
      "name": "职业技能证书标准",
      "parent_type": "岗位、职业与能力数据",
      "title_keywords": [
        "职业技能等级标准",
        "国家职业技能标准",
        "1+X证书",
        "职业技能等级证书",
        "职业标准"
      ],
      "content_keywords": [
        "职业功能",
        "工作内容",
        "技能要求",
        "相关知识要求",
        "职业道德",
        "基础知识",
        "评价要求"
      ],
      "default_level": "L1",
      "applicable_knowledge_types": [
        "skill_certificate_standard",
        "occupational_ability",
        "structured_document"
      ]
    }
  ]
}
```

分级建议：

| 场景 | 等级建议 |
| --- | --- |
| 公开发布的国家职业技能标准、1+X 证书标准 | L1 |
| 内部院校对标分析、课程映射结论 | L2 |
| 含企业内部岗位评价、学生个人评价数据 | L3/L4 例外 |

标签建议：

```text
专业领域: 电子商务
能力领域: 数据分析 / 网络营销 / 运营推广
应用场景: 人才培养方案 / 专业群建设 / 课证融通
数据类型: 职业技能证书标准
证书类型: 1+X / 国家职业技能标准
```

## 10. 质量治理规则

抽取质量检查：

| 规则 | 处理 |
| --- | --- |
| 无法识别标准名称 | blocking |
| 无法识别任何工作任务或技能要求 | blocking |
| 缺少来源 trace | blocking |
| 等级名称无法规范化 | warning |
| 技能要求和知识要求混淆严重 | warning |
| PGSD 映射低置信 | review_required |
| 同一等级/任务下重复要求过多 | warning |
| LLM 输出不符合 schema | blocking |
| 出现敏感个人信息 | review_required / policy block |

`available` 条件：

```text
normalized_asset_ref 有效
governance.quality_level = pass
classification / level / tags / org_scope 完整
certificate_standard 主表写入成功
至少有 1 个 level 或 occupation
至少有 1 个 task
至少有 1 个 skill_requirement 或 knowledge_requirement
无 blocking rule
AI confidence 达到阈值
```

否则：

```text
review_required
```

## 11. API 设计建议

### 11.1 Open API

用于上游业务系统、人才培养方案工具、专业群建设工具消费：

```http
GET /open/v1/skill-certificate-standards
GET /open/v1/skill-certificate-standards/{standard_id}
GET /open/v1/skill-certificate-standards/{standard_id}/levels
GET /open/v1/skill-certificate-standards/{standard_id}/tasks
GET /open/v1/skill-certificate-standards/{standard_id}/requirements
GET /open/v1/skill-certificate-standards/{standard_id}/pgsd-abilities
```

查询参数：

| 参数 | 说明 |
| --- | --- |
| `major_name` | 专业名称 |
| `major_code` | 专业代码 |
| `occupation_name` | 职业名称 |
| `certificate_type` | `1+x` / `national_occupation_standard` |
| `level_code` | 等级 |
| `ability_category` | P/G/S/D |
| `keyword` | 任务/技能/知识要求关键词 |
| `normalized_ref_id` | 标准资产引用 |
| `page` / `pageSize` | 分页 |

Open API 必须只返回锚定 `available` asset_version 的数据。

### 11.2 Internal API

用于 console 审核、抽取结果查看、人工修正：

```http
GET /internal/v1/domain-assets/skill-certificate-standards
GET /internal/v1/domain-assets/skill-certificate-standards/{standard_id}
GET /internal/v1/domain-assets/skill-certificate-standards/{standard_id}/extraction-result
GET /internal/v1/domain-assets/skill-certificate-standards/{standard_id}/requirements
GET /internal/v1/domain-assets/skill-certificate-standards/{standard_id}/pgsd-mapping
POST /internal/v1/domain-assets/skill-certificate-standards/{standard_id}/review
```

建议使用 `domain-assets`，而不是 `record-assets`，避免误导为 Pipeline B record 资产。

## 12. Console 呈现建议

资产详情页新增领域 Tab：

```text
证书标准
```

内容：

- 标准概览
- 等级结构
- 职业/岗位方向
- 工作领域
- 工作任务
- 技能要求
- 知识要求
- PGSD 映射
- 来源证据
- 治理结果

交互：

1. 左侧章节树来自 normalized_document TOC。
2. 中间显示抽取出的任务/技能/知识结构。
3. 右侧显示来源 block/page evidence。
4. 低置信字段标红进入人工 review。
5. PGSD 映射可人工确认或调整，但所有人工覆盖必须写 audit。

不得在 console 中直接编辑 raw PDF 或 MinerU 原始输出。

## 13. Knowledge Chunk 设计

该类 PDF 仍然参与知识检索，但 chunk 需要同时支持文档语义和领域结构。

建议 chunk 类型：

```text
document_section
certificate_task
certificate_skill_requirement
certificate_knowledge_requirement
certificate_pgsd_ability
```

chunk metadata：

```json
{
  "knowledge_type_code": "skill_certificate_standard",
  "standard_id": "...",
  "level_code": "level_3",
  "occupation_name": "电子商务师",
  "task_id": "...",
  "requirement_type": "skill",
  "ability_category": "P",
  "source_block_ids": ["block-021", "block-022"],
  "page_range": [12, 13]
}
```

约束：

```text
knowledge_chunk.normalized_ref_id 仍然指向 normalized_asset_ref。
领域表不反向持有 chunk 指针。
```

## 14. 与人才培养方案/专业群建设的关系

证书标准领域模型支持：

1. 专业培养目标对标
2. 毕业要求能力点对标
3. 课程体系覆盖度分析
4. 课证融通矩阵
5. 实训项目设计
6. 专业群共享课程能力覆盖
7. 岗位-证书-课程-能力图谱

后续关系：

```text
skill_certificate_standard
  -> skill_certificate_ability_item
  -> course_outcome
  -> curriculum_module
  -> talent_training_program
  -> major_group
```

关系类型：

```text
CERT_REQUIRES_ABILITY
ABILITY_COVERED_BY_COURSE
CERT_ALIGNS_TO_MAJOR
CERT_SUPPORTS_TRAINING_PROGRAM
TASK_RELATED_TO_JOB
KNOWLEDGE_SUPPORTS_ABILITY
```

P0 先实现证书标准抽取和 PGSD 映射；课程/培养方案对标作为 P1。

## 15. 实施切片建议

### C0：设计冻结

交付：

```text
docs/pipeline_a_skill_certificate_standard_design.md
docs/task-packages/wk_skill_certificate_standard_task_package.md
```

冻结：

```text
document_profile
classification.code
domain tables
API path
review_required 条件
governance_rule_version 扩展项
```

### C1：document_profile_detect

实现：

```text
detect_skill_certificate_standard(normalized_document)
```

测试：

```text
两个 PDF 样本识别为 skill_certificate_standard
普通政策/教材 PDF 不误识别
低置信输出 skill_certificate_standard_candidate
```

### C2：证书标准抽取器

实现：

```text
certificate_standard_extractor.py
```

能力：

```text
章节识别
表格行抽取
LLM fallback
schema validation
trace 保留
```

输出 canonical JSON：

```json
{
  "standard": {},
  "levels": [],
  "occupations": [],
  "tasks": [],
  "skill_requirements": [],
  "knowledge_requirements": [],
  "pgsd_mapping": []
}
```

### C3：领域表和 writer

新增表：

```text
skill_certificate_standard
skill_certificate_level
skill_certificate_occupation
skill_certificate_work_domain
skill_certificate_work_task
skill_requirement_item
knowledge_requirement_item
skill_certificate_pgsd_projection
skill_certificate_ability_item
```

实现 writer：

```text
skill_certificate_standard_writer.write(...)
```

要求：

```text
按 normalized_ref_id 幂等删除重建
不写 raw content
保留 trace
低置信不自动 available
```

### C4：治理规则扩展

更新：

```text
governance_rules_v2.json
seed_data.py
governance_rule_version migration
```

新增：

```text
classification.code = vocational_skill_certificate_standard
knowledge_type_code = skill_certificate_standard
tag rules
quality / admission rules
```

测试：

```text
classification / level / tags 从 governance_rule_version 解析
无硬编码治理结论
```

### C5：API

新增 open/internal API。

测试：

```text
available-only 过滤
按证书类型 / 等级 / 能力类别查询
详情返回 trace
```

### C6：Console

资产详情新增证书标准 Tab：

```text
等级
工作任务
技能要求
知识要求
PGSD 映射
来源证据
```

### C7：与能力图谱/培养方案集成

输出：

```text
certificate ability graph projection
course/curriculum alignment API
major group coverage matrix
```

## 16. P0 最小范围建议

必须做：

```text
PDF 走 Pipeline A + MinerU
识别 skill_certificate_standard.v1
抽取 standard / levels / tasks / skill_requirements / knowledge_requirements
映射 P/G/S/D
落证书标准领域表
open/internal 只读 API
治理分类/分级/打标使用 governance_rule_version
```

暂不做：

```text
人工编辑器
课程体系自动对标
专业群覆盖度矩阵
复杂图谱推理
证书评价权重深度解析
多证书版本差异比对
```

## 17. Review 问题清单

需要评审确认：

1. `classification.code` 是否采用 `vocational_skill_certificate_standard`。
2. Internal API 是否新增 `domain-assets` 资源族，还是复用 `record-assets`。
3. P0 是否落 `certificate_assessment_requirement` 表，还是先保留在 JSON。
4. PGSD-compatible 投影是否独立建表，还是直接复用 `occupational_ability_*`。
5. `skill_requirement_item` 与既有 `job_demand_requirement_item` 是否需要统一抽象父层，还是保持来源域独立。
6. Knowledge chunk 是否新增 `certificate_*` chunk type，还是先统一为 `structured_record_row` / `document_section`。
7. 证书标准默认 L1/L2 的具体规则是否需要在 `governance_rule_version` 中新增专门准入项。

