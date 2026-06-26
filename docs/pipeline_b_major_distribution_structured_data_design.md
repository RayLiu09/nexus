# Pipeline B 专业布点表结构化数据资产治理设计方案

- **状态**：待人工 Review，暂不实施
- **日期**：2026-06-26
- **样本文件**：
  - `docs/samples/2.（专业布点数）专业布点数.xlsx`
  - `docs/samples/电子商务专业布点数量.xlsx`
- **适用对象**：专业数据类型下的专业布点数、专业布点数量、院校/区域/层次/年份维度的专业开设数量统计表
- **不适用对象**：专业教学标准、人才培养方案、专业简介等文档型资产；岗位需求表；职业能力分析表；RAGFlow 语义 chunk
- **核心结论**：专业布点表属于 Pipeline B `record` 资产。必须走 `ingest_validate -> assetize -> structured_parse -> profile_detect -> domain_normalize -> normalized_record -> normalized_asset_ref -> AI governance -> rules -> available/review_required`，不调 MinerU，不产出 `parse_artifact`，不以 `knowledge_chunk` 为治理中心。

## 一、设计定位

专业布点表是专业数据类型下的结构化统计资产，核心价值是按年份、地域、专业、专业代码、学历层次进行查询、统计、对比和趋势分析。

这类资产的目标不是：

```text
PDF/Office 版面解析
MinerU OCR
段落切块
RAG chunk preview
workbook 单元格定位跳转
```

而是：

```text
结构化表解析
专业布点 profile 识别
字段标准化与别名适配
统计口径校验
记录级质量治理
领域读模型落库
结构化检索、过滤和聚合
AI 治理与规则治理从 normalized_record 发起
```

因此，专业布点表应在现有 Pipeline B 体系内新增一个专业数据领域 profile，而不是复用岗位需求或职业能力分析 profile，也不能绕过资产台账、版本、标准化引用、治理结果和审计链路。

### 1.1 与现有 Pipeline B 合同的关系

`docs/pipeline_b_contract_freeze.md` 当前冻结的 `record_type` 仅覆盖：

- `job_demand_dataset`
- `job_demand_dataset_candidate`
- `occupational_ability_analysis`
- `occupational_ability_analysis_candidate`
- `generic_table_dataset`

专业布点表需要新增 `record_type` 与 `domain_profile`，属于合同扩展，必须先经过 Review Gate，不能直接把样本特征硬编码进已冻结实现。

建议新增：

| 字段 | 新值 | 含义 |
| --- | --- | --- |
| `record_type` | `major_distribution_dataset` | 专业布点数据集 |
| `record_type` | `major_distribution_dataset_candidate` | 专业布点候选，表头或统计口径不完整，需人工 review |
| `domain` | `major` | 专业数据域 |
| `domain_profile` | `major_distribution.v1` | 专业布点表 v1 profile |
| `classification.code` | `major_distribution` | AI 治理业务分类，现有治理 seed 已存在中文映射“专业布点数” |

约束：

- 新增 `record_type` 前，需更新 `profile_detect.schemas.RecordType` 白名单、API contract、console label 和相关测试。
- `record_type` 是技术路径决策；`governance_result.classification = major_distribution` 是业务治理结果。二者不能互相替代。
- 低置信识别必须走 `major_distribution_dataset_candidate` 或 `generic_table_dataset`，并进入 `review_required`。

## 二、样本结构分析

### 2.1 样本 A：跨专业明细模板

文件：`docs/samples/2.（专业布点数）专业布点数.xlsx`

Workbook：

```text
Sheet1: 4 rows x 7 cols
Sheet2: empty
Sheet3: empty
```

`Sheet1` 表头：

```text
序号 | 专业名称 | 专业代码 | 层次 | 省份 | 布点数 | 年份
```

有效样例行：

```text
1 | 网络营销与直播电商 | 530704 | 高职 | 北京市 | 4 | 2026年
2 | 跨境电子商务       | 530702 | 高职 | 北京市 | 3 | 2026年
```

特殊行：

```text
row4: "……" 占位行
```

业务含义：

- 一个数据集包含多个专业。
- 每条记录粒度为 `(year, province, education_level, major_code)`。
- `序号` 是纯行号列，不进入领域字段。
- `……` 是样本占位行，不进入正式领域记录，但应进入质量摘要中的 placeholder 统计。

### 2.2 样本 B：单专业省份分布模板

文件：`docs/samples/电子商务专业布点数量.xlsx`

Workbook：

```text
Sheet1: 34 rows x 5 cols
```

表头：

```text
年份 | 省份 | 专业名称 | 专业代码 | 专业布点数量（个）
```

有效样例：

```text
2026年 | 全部             | 电子商务 | 530701 | 1568
2026年 | 北京市           | 电子商务 | 530701 | 19
2026年 | 浙江省           | 电子商务 | 530701 | 67
...
2026年 | 新疆生产建设兵团 | 电子商务 | 530701 | 8
```

业务含义：

- 一个数据集主要描述单一专业。
- `省份 = 全部` 是来源表提供的汇总行，不是普通省份，也不进入领域记录。
- 其余行是省级或区域级明细。
- 每条正式记录粒度为 `(year, province, major_code)`；样本缺少 `层次` 字段时，只有数据源元数据、文件名或上下文存在明确层次证据才补齐，并记录 evidence；无明确证据时保持空值，禁止猜测。
- 全国/合计口径应由明细记录动态计算得到，不保存为一条领域记录。

### 2.3 两类模板的统一口径

两份样本字段顺序和列名不同，但语义可统一为：

| 规范字段 | 样本 A 来源 | 样本 B 来源 | 说明 |
| --- | --- | --- | --- |
| `year` | `年份` | `年份` | 标准化为整数，如 `2026`；保留原文到 `year_text` |
| `province_name` | `省份` | `省份` | 保留行政区原文 |
| `region_scope` | `省份` 派生 | `省份` 派生 | `province` / `unknown`；汇总行不入记录；`新疆生产建设兵团` 按 `province` 存储 |
| `major_name` | `专业名称` | `专业名称` | 必填 |
| `major_code` | `专业代码` | `专业代码` | 6 位数字字符串，禁止丢前导零 |
| `education_level` | `层次` | 缺省 | 如 `高职`；缺失时可由明确证据补齐，否则为空 |
| `distribution_count` | `布点数` | `专业布点数量（个）` | 非负整数 |
| `source_row_no` | `序号` | 无 | 来源表自带序号，仅用于审计回溯和错误提示，不参与业务唯一性和统计 |

## 三、Pipeline B 流程设计

### 3.1 作业路由

Excel 上传或 NAS 扫描时，按既有 Pipeline B 路由规则创建 Job：

```json
{
  "pipeline_type": "record"
}
```

约束：

- `pipeline_type` 在 Job 创建侧写入，Worker 只读取 payload，不运行时推断。
- XLSX/CSV/JSON 结构化文件进入 Pipeline B；不调 MinerU。
- `assetize` 与 `normalize` 保持独立：`assetize` 创建 `asset` / `asset_version`，`normalize` 生成 `normalized_record` / `normalized_asset_ref`。

完整流程：

```text
raw Excel
  -> raw_object
  -> ingest_validate
  -> Job(payload.pipeline_type="record")
  -> assetize
  -> structured_parse
  -> profile_detect(major_distribution)
  -> domain_normalize(major_distribution.v1)
  -> normalized_record
  -> normalized_asset_ref(normalized_type="record")
  -> AI governance
  -> governance rules
  -> available / review_required
```

### 3.2 structured_parse 要求

复用现有 Pipeline B `structured_parse` 约束：

| 要求 | 专业布点表处理 |
| --- | --- |
| sheet 顺序与命名 | 原样保留，不重命名 |
| 空 sheet | 保留到 parse summary；不参与领域记录 |
| 表头行 | 允许第一行表头；未来可通过 profile 配置支持多行表头 |
| 序号列 | `序号` / `No.` / `#` 识别为行号列，不进入领域字段 |
| 占位行 | `……`、全空行、仅序号/占位符行不在 parse 阶段过滤，由 domain_normalize 统计并过滤 |
| 数字字段 | 先保留原值，domain_normalize 再转 `distribution_count` |
| trace | 每个字段记录 `{sheet, row, column}`，用于审计和质量定位，不作为前端定位能力 |

### 3.3 profile_detect 新增 detector

新增 detector：`detect_major_distribution(workbook)`。

识别证据：

| 证据 | 示例 |
| --- | --- |
| 文件名 | `专业布点数`、`专业布点数量`、`电子商务专业布点数量` |
| header signatures | `专业名称`、`专业代码`、`省份`、`布点数`、`专业布点数量（个）`、`年份`、`层次` |
| row patterns | `专业代码` 为 6 位数字；`年份` 含 `2026年`；`布点数` 为非负整数 |
| summary marker | `省份 = 全部`；仅作为汇总行识别证据，不进入领域记录 |
| source metadata | 数据源业务标签为专业数据 / D3 / 专业布点 |

header 别名必须配置化，禁止在 detector 中硬编码单一列名。建议别名集合：

| 规范字段 | header 别名 |
| --- | --- |
| `year` | `年份` / `年度` / `统计年份` / `year` |
| `province_name` | `省份` / `省市` / `地区` / `地域` / `行政区` / `province` / `region` |
| `major_name` | `专业名称` / `专业` / `专业名` / `major_name` |
| `major_code` | `专业代码` / `专业编码` / `专业目录代码` / `major_code` |
| `education_level` | `层次` / `学历层次` / `办学层次` / `education_level` |
| `distribution_count` | `布点数` / `布点数量` / `专业布点数量（个）` / `专业布点数量` / `开设数量` / `院校数` |
| `source_row_no` | `序号` / `No.` / `#` |

建议输出：

```json
{
  "record_type": "major_distribution_dataset",
  "domain": "major",
  "domain_profile": "major_distribution.v1",
  "detector_version": "record-profile-detector.v2",
  "confidence": 0.95,
  "evidence": {
    "matched_headers": ["年份", "省份", "专业名称", "专业代码", "专业布点数量（个）"],
    "sheet_names": ["Sheet1"],
    "sample_row_count": 33,
    "matched_row_patterns": ["major_code_6_digits", "year_with_suffix", "non_negative_count"],
    "has_total_row": true,
    "major_name": "电子商务",
    "major_code": "530701"
  }
}
```

字段语义补充：

- 来源表里的 `省份 = 全部` / `全国` / `合计` 属于汇总数据。此类数据可以由明细记录计算得到，因此 `domain_normalize` 应识别并忽略，不写入 `major_distribution_record`，也不设计 `is_total_row` 字段。
- `source_row_no` 表示来源表内自带的序号列，如样本 A 的 `序号 = 1 / 2`。它不是业务字段，不参与去重、聚合、排序语义和治理分类判断；系统排序与追溯应使用 `trace.sheet + trace.row`。保留该字段只是为了人工 review 时能对照原表看到“第几条样本记录”，以及在质量问题中提示来源序号。

低置信处理：

| 情况 | 输出 |
| --- | --- |
| 命中 `专业名称` / `专业代码`，但缺少布点数量列 | `major_distribution_dataset_candidate` |
| 命中布点数量和地区，但专业代码缺失 | `major_distribution_dataset_candidate` |
| 只有普通表格结构，无专业布点证据 | `generic_table_dataset` |
| 与岗位需求或能力分析 detector 同时高置信 | `review_required`，记录 `profile_conflict` |

### 3.4 与 AI governance classification 的边界

`profile_detect` 与 `governance_result.classification` 必须分离：

| 维度 | `profile_detect` | AI governance / rules |
| --- | --- | --- |
| 时机 | `structured_parse` 后、`domain_normalize` 前 | `normalized_record` 生成后 |
| 目的 | 选择 `major_distribution.v1` normalizer 与领域表 | 分类、定级、标签、质量评分、admission |
| 输入 | sheet/header/row pattern | 标准化后的 `normalized_record` |
| 输出 | `record_type` / `domain_profile` / confidence / evidence | `classification=major_distribution`、level、tags、quality、state decision |

推荐交叉校验：

- `profile.record_type = major_distribution_dataset` 时，治理分类应为 `major_distribution`。
- 若治理分类不是 `major_distribution`，加入质量标记 `profile_classification_mismatch`，进入 `review_required`。

## 四、标准化输出设计

### 4.1 `normalized_record.payload`

`normalized_record` 使用 `normalized-record.v2` 风格 payload，新增 `major_distribution.v1` record body。

```json
{
  "schema_version": "normalized-record.v2",
  "record_type": "major_distribution_dataset",
  "domain_profile": "major_distribution.v1",
  "title": "电子商务专业布点数量",
  "language": "zh-CN",
  "source_type": "record",
  "content_type": "table_sheet",
  "profile": {
    "record_type": "major_distribution_dataset",
    "domain": "major",
    "domain_profile": "major_distribution.v1",
    "confidence": 0.95,
    "detector_version": "record-profile-detector.v2",
    "evidence": {}
  },
  "record_body": {
    "dataset": {
      "dataset_name": "电子商务专业布点数量",
      "source_channel": "excel_upload",
      "major_scope": "single_major",
      "major_name": "电子商务",
      "major_code": "530701",
      "education_level": null,
      "year_min": 2026,
      "year_max": 2026,
      "record_count": 32,
      "ignored_summary_count": 1,
      "invalid_count": 0,
      "placeholder_count": 0,
      "duplicate_count": 0
    },
    "records": [
      {
        "source_record_key": "Sheet1#row3",
        "year": 2026,
        "year_text": "2026年",
        "province_name": "北京市",
        "region_scope": "province",
        "major_name": "电子商务",
        "major_code": "530701",
        "education_level": null,
        "distribution_count": 19,
        "source_row_no": null,
        "quality_flags": [],
        "trace": {
          "sheet": "Sheet1",
          "row": 3,
          "columns": {
            "year": "A",
            "province_name": "B",
            "major_name": "C",
            "major_code": "D",
            "distribution_count": "E"
          }
        }
      }
    ]
  },
  "body_markdown": null,
  "body_markdown_meta": null,
  "governance": {},
  "quality": {
    "quality_level": "pending",
    "record_count": 32,
    "required_field_missing_count": 0,
    "invalid_count": 0,
    "placeholder_count": 0,
    "ignored_summary_count": 1,
    "duplicate_count": 0,
    "anomaly_items": []
  },
  "lineage": {
    "raw_object_id": "...",
    "parser": "structured_parse.xlsx",
    "normalizer": "major_distribution_normalizer.v1",
    "source_sheets": ["Sheet1"],
    "field_inference": {
      "education_level": {
        "filled": false,
        "source": null,
        "evidence": null
      }
    }
  }
}
```

### 4.2 `normalized_asset_ref`

专业布点表的 `normalized_asset_ref` 必须满足 v3.0 M22 字段要求：

| 字段 | 建议值 |
| --- | --- |
| `normalized_type` | `record` |
| `schema_version` | `normalized-record.v2` |
| `content_type` | `table_sheet` |
| `source_type` | 从 `raw_object` / data source 复制 |
| `title` | 文件名去扩展名，或 dataset_name |
| `language` | `zh-CN` |
| `record_count` | 有效领域记录数，不含占位行 |
| `block_count` | `0` |
| `governance` | classification / level / tags / org_scope / version_status snapshot |
| `quality` | record 质量摘要、异常项、manual review 状态 |
| `lineage` | raw_object_id、parser_version、normalizer_version、source_sheets、checksum |
| `metadata_summary.profile` | profile_detect 输出摘要 |
| `metadata_summary.business` | major_name、major_code、year_min/year_max、province_count、total_count |

禁止：

- 禁止把治理输入指向 raw Excel 或 `ParsedWorkbook`。
- 禁止让 `governance_result` 指向 `asset_version`。
- 禁止在 `asset_version` 上写 `normalized_ref_id` 反向指针。

## 五、领域读模型设计

专业布点表不应长期只存在 `normalized_record.payload.record_body`。建议新增领域读模型，支持上游结构化查询、过滤和聚合。

### 5.1 `major_distribution_dataset`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string(36) PK | 数据集 ID |
| `normalized_ref_id` | string(36) FK | 指向 `normalized_asset_ref.id`，单向 |
| `asset_version_id` | string(36) FK | 版本锚点，便于查询 |
| `dataset_name` | text | 数据集名称 |
| `source_channel` | text | `excel_upload` / `nas` / `database` / `crawler` |
| `major_scope` | text | `single_major` / `multi_major` / `unknown` |
| `major_name` | text null | 单专业数据集时填值，多专业可空 |
| `major_code` | text null | 单专业数据集时填值，多专业可空 |
| `education_level` | text null | 数据集级统一层次；混合层次为空 |
| `year_min` | int null | 最小年份 |
| `year_max` | int null | 最大年份 |
| `province_count` | int | 明细地域数 |
| `record_count` | int | 有效记录数 |
| `ignored_summary_count` | int | 被识别并忽略的来源汇总行数 |
| `invalid_count` | int | 无效记录数 |
| `placeholder_count` | int | 占位行数 |
| `duplicate_count` | int | 重复业务键数量 |
| `quality_flags` | jsonb | 数据集级异常 |
| `created_at` / `updated_at` | timestamptz | 审计时间 |

建议索引：

- `ix_pdd_normalized_ref_id`
- `ix_pdd_asset_version_id`
- `ix_pdd_major_code`
- `ix_pdd_year_range (year_min, year_max)`

### 5.2 `major_distribution_record`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string(36) PK | 记录 ID |
| `dataset_id` | string(36) FK | 指向 `major_distribution_dataset.id` |
| `normalized_ref_id` | string(36) FK | 指向 `normalized_asset_ref.id`，便于权限过滤 |
| `source_record_key` | text | 如 `Sheet1#row2` |
| `source_row_no` | text null | 来源表自带序号；审计/人工 review 辅助字段，不参与业务唯一键 |
| `year` | int not null | 统计年份 |
| `year_text` | text null | 原始年份 |
| `province_name` | text not null | 地域原文 |
| `region_scope` | text not null | `province` / `unknown`；`新疆生产建设兵团` 按 `province` 存储 |
| `major_name` | text not null | 专业名称 |
| `major_code` | text not null | 专业代码 |
| `education_level` | text null | 层次 |
| `distribution_count` | int not null | 布点数量 |
| `quality_flags` | jsonb | 行级质量标记 |
| `trace` | jsonb | sheet/row/column 回溯 |
| `created_at` / `updated_at` | timestamptz | 审计时间 |

建议约束：

```text
CHECK distribution_count >= 0
CHECK year BETWEEN 1900 AND 2100
UNIQUE(dataset_id, year, province_name, major_code, coalesce(education_level, ''))
```

建议索引：

- `ix_pdr_dataset_id`
- `ix_pdr_normalized_ref_id`
- `ix_pdr_major_code`
- `ix_pdr_major_name`
- `ix_pdr_year`
- `ix_pdr_province`
- `ix_pdr_region_scope`
- `ix_pdr_education_level`

### 5.3 为什么需要领域表

专业布点的典型消费问题是结构化查询：

```text
电子商务专业 2026 年各省布点数量是多少？
北京市高职电子商务类相关专业布点数有哪些？
某专业代码全国布点总数是多少？（由省级/区域明细动态聚合）
同一专业跨年份布点变化趋势如何？
```

这些问题不适合依赖 RAG chunk 召回。领域表能直接支撑过滤、排序、聚合和图表，且权限、治理、审计仍通过 `normalized_ref_id` 与资产底座关联。

## 六、domain_normalize 规则

### 6.1 字段标准化

| 字段 | 规则 |
| --- | --- |
| `year` | 从 `2026年` / `2026` 提取四位年份；无法提取则行级 `year_invalid` |
| `major_code` | 转字符串；去 `.0`；保留前导零；必须匹配 `^\d{6}$`，否则 `major_code_invalid` |
| `distribution_count` | 转非负整数；小数、负数、非数字标记 `distribution_count_invalid` |
| `province_name` | 去首尾空格；`全部` / `全国` / `合计` 识别为汇总行并忽略，不写领域记录 |
| `education_level` | 优先保留原文字段；缺失时仅允许从数据源元数据、文件名或同批上下文中的明确层次证据补齐，并记录 `lineage.field_inference.education_level`；无明确证据时保持 `null`；可配置别名归一，如 `高职专科` -> `高职`，但不强制枚举 |
| `source_row_no` | 仅作为 trace，不参与业务唯一键 |

### 6.2 行过滤与质量标记

| 行类型 | 处理 |
| --- | --- |
| 全空行 | 不写领域记录，计入 parse summary |
| 仅 `……` / `...` / `—` | 不写领域记录，`placeholder_count + 1` |
| 缺少专业名称或专业代码 | 不写正式记录，计入 `invalid_count`；如果比例超阈值则 review |
| 缺少年份或布点数量 | 不写正式记录，计入 `invalid_count`；如果比例超阈值则 review |
| 重复业务键 | 保留第一条，后续标记 `duplicate_business_key` 或进入 review，具体策略由当前生效的 `governance_rule_version` 决定 |

### 6.3 数据集级派生

`domain_normalize` 应派生：

- `major_scope`
  - 只有一个 `major_code`：`single_major`
  - 多个 `major_code`：`multi_major`
  - 无法判断：`unknown`
- `year_min` / `year_max`
- `province_count`：distinct `province_name`
- `ignored_summary_count`
- `placeholder_count`
- `duplicate_count`

## 七、治理方案

### 7.1 治理输入

治理输入必须是：

```text
normalized_record
  via normalized_asset_ref
```

禁止：

- raw Excel
- `ParsedWorkbook`
- raw JSON dump
- 领域表单独绕过 `normalized_asset_ref`

### 7.2 规则来源边界

专业布点资产的分类、分级、打标、质量评分、review 触发和 admission 判断，统一使用当前生效的 `governance_rule_version` 中 `major_distribution` 对应的内置规则。Pipeline B 的 `profile_detect` 和 `domain_normalize` 只负责技术路径识别、字段标准化、结构化质量事实生成，不拥有独立的业务治理规则真源。

明确边界：

| 规则类型 | 规则来源 | 说明 |
| --- | --- | --- |
| 分类 | `governance_rule_version.classifications[major_distribution]` | AI suggestion 必须被该分类规则校验后才能采纳 |
| 分级 | `governance_rule_version.levels` + `major_distribution` 默认/约束 | 默认 L1/L2；L3/L4 只能由规则证据、来源配置或人工审批触发 |
| 打标 | `governance_rule_version.tag_dimensions` 与分类内置打标依据 | 专业领域、学历层次、地域范围、时效性、数据来源等标签从规则版本读取 |
| 质量评分 | `governance_rule_version.quality_scoring` 与分类内置质量项 | 完整性、准确性、一致性、可用性等维度使用规则版本快照 |
| review/admission | `governance_rule_version` 阈值与阻断规则 | 决定 `available` / `review_required`，并写入 decision_trail |

`major_distribution.v1` 可以定义字段映射、表头别名、结构化 normalizer 和质量事实名称，但不能覆盖 `governance_rule_version` 的分类/分级/打标/admission 结果。治理结果必须记录 `rules_schema_version` 和 `rules_content_hash`，以证明使用的是对应规则版本快照。

### 7.3 AI governance 建议输出

AI governance 仅给出建议，不能绕过规则直接成为正式治理结果。

建议输出：

```json
{
  "classification": {
    "code": "major_distribution",
    "name": "专业布点数",
    "confidence": 0.95,
    "evidence": [
      "表头包含专业名称、专业代码、省份、年份、布点数量",
      "记录为专业按地域统计的布点数量"
    ]
  },
  "level": {
    "code": "L1",
    "confidence": 0.9,
    "reason": "样本为公开统计口径数据，不含个人隐私或院校私有明细"
  },
  "tags": {
    "专业领域": ["电子商务"],
    "学历层次": ["高职"],
    "地域范围": ["全国", "省级"],
    "时效性": ["2026"],
    "数据来源": ["Excel导入"]
  },
  "quality_score": {
    "score": 90,
    "dimensions": {
      "completeness": 92,
      "accuracy": 88,
      "consistency": 90,
      "usability": 90
    }
  },
  "review_reasons": []
}
```

### 7.4 规则治理

专业布点治理规则应落在当前生效的 `governance_rule_version` 内置规则中，表达式必须受限，不允许任意代码执行。`domain_normalize` 输出的字段缺失率、格式错误率、忽略汇总行数量、重复业务键等只能作为规则输入事实，不能自行决定正式分类、分级、标签或最终状态。

建议质量维度：

| 维度 | 检查项 | 失败处理 |
| --- | --- | --- |
| 完整性 | 必填字段：`year`、`province_name`、`major_name`、`major_code`、`distribution_count` | 超阈值 `review_required` |
| 格式准确性 | `major_code` 为 6 位数字；`distribution_count >= 0`；`year` 合法 | 格式错误行进入 invalid；错误率超阈值 review |
| 重复性 | 同一业务键不得重复 | 重复率超阈值 review |
| 口径明确性 | 层次字段缺失且无明确证据可补齐 | 质量扣分；是否 review 可配置 |
| profile 一致性 | `profile.record_type` 与 `classification=major_distribution` 一致 | 不一致必须 review |

### 7.5 状态机决策

`available` 条件：

- 已生成有效 `normalized_asset_ref(normalized_type=record)`。
- `governance.quality_level = pass`。
- 依据当前生效 `governance_rule_version`，`classification = major_distribution`。
- 依据当前生效 `governance_rule_version`，level、tags、org_scope 已填充且满足分类约束。
- 当前生效 `governance_rule_version` 无 blocking rule 命中。
- AI confidence 达到当前生效 `governance_rule_version` 的自动采纳阈值。
- 该资产没有另一个冲突的 available 版本。

进入 `review_required` 的条件：

- `major_distribution_dataset_candidate` 或 `generic_table_dataset`。
- profile 与 governance classification 不一致。
- 必填字段缺失率、格式错误率、重复率超过阈值。
- `major_code` 与 `major_name` 在同一数据集内出现明显冲突。
- 检测到 L3/L4 敏感内容或来源被配置为高敏例外。
- org_scope 无法确定。
- 人工规则明确要求 review。

默认分级：

- 专业布点统计默认 L1/L2。
- 不因“专业数据”自动升为 L3/L4。
- 只有包含院校私有明细、未公开招生计划、内部战略布局等高敏例外证据时，才触发 L3/L4 审批、脱敏和授权。

### 7.6 审计事件

必须继承 Pipeline B 共同审计事件：

- `INGEST_BATCH_SUBMITTED`
- `RAW_OBJECT_PERSISTED`
- `INGEST_VALIDATE_COMPLETED`
- `VERSION_STATUS_CHANGED`
- `PIPELINE_FAILED`

建议扩展或复用 record 侧事件：

| 事件 | 触发 |
| --- | --- |
| `RecordProfileDetected` | profile_detect 完成，写入 record_type/domain_profile/confidence/evidence |
| `RecordProfileReviewRequired` | detector 低置信、candidate 或冲突 |
| `DomainNormalizeCompleted` | major_distribution normalizer 写入 normalized_record 和领域表 |
| `GovernanceResultGenerated` | AI/rule 治理结果生成 |
| `VersionStatusChanged` | `processing -> available/review_required/failed` |

审计注意：

- 不记录大段原始 Excel 内容。
- 不记录 L3/L4 明文。
- 记录 trace_id、raw_object_id、normalized_ref_id、asset_version_id。
- 治理审计和 `governance_result.decision_trail` 必须记录 `governance_rule_version.id`、`rules_schema_version`、`rules_content_hash`。

## 八、API 与前端呈现建议

### 8.1 业务 API

专业布点是上游可消费的结构化数据，业务 API 应归属 `nexus-api`，而不是只做 console 内部接口。

建议只读 API：

```http
GET /open/v1/major-distribution-datasets
GET /open/v1/major-distribution-datasets/{dataset_id}
GET /open/v1/major-distribution-datasets/{dataset_id}/records
GET /open/v1/major-distribution-records
```

查询参数建议：

| 参数 | 说明 |
| --- | --- |
| `year` | 年份 |
| `major_code` | 专业代码 |
| `major_name` | 专业名称等值或模糊 |
| `province_name` | 省份/地区 |
| `education_level` | 层次 |
| `region_scope` | `province` / `unknown` |
| `min_count` / `max_count` | 布点数量范围 |
| `page` / `page_size` | 分页 |

所有 API 返回前必须执行权限过滤和 level/org_scope 检查。

### 8.2 Console 呈现

资产详情页 record 资产视图建议：

- 数据集概览：年份范围、专业数、地域数、有效记录数、无效/占位/重复数量。
- 表格视图：年份、省份、专业名称、专业代码、层次、布点数、质量标记。
- 统计视图：按省份柱状图、按专业对比、由明细动态聚合的全国汇总值。
- 治理视图：classification、level、tags、quality_score、review reasons、decision trail。

不要显示成知识块列表，也不要提供 Excel 单元格高亮跳转作为 P0 能力。

## 九、实施切片建议

该设计是合同扩展，建议新开 Pipeline B 专项切片，不直接塞入已完成的 B4/B6。

### PD0 合同冻结

冻结：

- 新增 `record_type` / `domain_profile`
- `ProfileEvidence` 扩展字段
- `record_body.major_distribution.v1`
- 领域表 schema
- API 草案
- `governance_rule_version` 中 `major_distribution` 内置分类/分级/打标/质量/admission 规则引用方式
- domain_normalize 质量事实与质量标记词表

Review Gate：

- Data Model Gate
- API Contract Gate
- Rule Engine Gate
- AI Governance Gate
- Version State Gate

### PD1 profile_detect 与 record_body 投影

范围：

- 新增 `detect_major_distribution`
- 新增 header alias 配置
- `record_body_adapter` 投影为 `major_distribution.v1`
- 单元测试覆盖两个样本

验收：

- 样本 A 高置信识别为 `major_distribution_dataset`。
- 样本 B 高置信识别为 `major_distribution_dataset`。
- 缺少布点数字段的变体降级为 candidate。

### PD2 domain_normalize 与领域表

范围：

- 新增 `major_distribution_dataset` / `major_distribution_record`
- 写入服务与幂等 upsert
- 质量标记、汇总行忽略统计
- migration 与测试

验收：

- 样本 A 写入 2 条有效记录，`placeholder_count = 1`。
- 样本 B 写入 32 条有效记录，`ignored_summary_count = 1`。
- `province_name = 全部` 被识别为来源汇总行并忽略，不写入 `major_distribution_record`。

### PD3 治理与 API/console

范围：

- AI governance prior 与规则校验
- `major_distribution` 质量评分
- open/internal API
- Console record 资产专业布点视图

验收：

- 高质量样本自动进入 `available`。
- API 按年份/专业/省份过滤正确。
- 审计链路完整。

## 十、样本验收用例

| 用例 | 输入 | 期望 |
| --- | --- | --- |
| PD-E2E-001 | `2.（专业布点数）专业布点数.xlsx` | Pipeline B；不调 MinerU；生成 `major_distribution_dataset`；有效记录 2；占位 1 |
| PD-E2E-002 | `电子商务专业布点数量.xlsx` | Pipeline B；有效记录 32；`省份=全部` 汇总行忽略；`ignored_summary_count = 1` |
| PD-E2E-003 | 删除 `专业代码` 列 | candidate；`review_required`；reason 包含 `required_field_missing` |
| PD-E2E-004 | `布点数 = -1` | 行级 `distribution_count_invalid`；质量扣分或 review |
| PD-E2E-005 | 来源表存在 `全部` / `全国` / `合计` 汇总行 | 不写入领域记录；`ignored_summary_count` 增加；汇总值由明细动态计算 |
| PD-E2E-006 | 同一业务键重复两行 | `duplicate_business_key`；重复率超阈值 review |
| PD-E2E-007 | profile 为专业布点但治理分类为岗位需求 | `profile_classification_mismatch`；`review_required` |

## 十一、开放问题

1. 专业代码是否需要接入教育部专业目录作为权威校验源？P0 可只做 6 位格式校验，目录校验作为后续增强。
