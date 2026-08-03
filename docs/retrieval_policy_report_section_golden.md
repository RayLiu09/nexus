# 政策/报告 Section Context Golden Query 验证集

## 目的

本验证集用于评估 runtime `DerivedDocumentSectionBuilder` 对政策、行业报告、白皮书类资产的召回质量提升。验证重点不是替代 chunk，而是在 `industry_research_kb` 的向量命中结果之上，检查派生 `document_section_context` 是否能把命中 chunk 扩展为业务可读的章节上下文，并在 `/internal/v1/query` 与 `/open/v1/query` 中返回有边界、可溯源的 section context。

当前阶段不落库，不新增 `document_section` 表，也不写 `knowledge_chunk.document_section_id`。所有 section 均由运行时读取 `knowledge_chunk.locator.heading_path`、`chunk_index`、`source_block_ids` 和 `locator` 派生。

## 验收口径

- `first_stage_hit`: 原始 pgvector 命中至少包含一个目标资产 chunk。
- `section_context_returned`: `section_contexts[]` 或 tool result `answer_contexts[]` 中出现 `kind=document_section_context`。
- `expected_section_hit`: 返回的 `title` 或 `heading_path` 命中期望章节主题。
- `bounded`: 单个 context 不超过实现上限，且 `truncated`、`total_chunk_count`、`total_char_count` 能说明截断情况。
- `traceable`: context 与其中每个 chunk 都保留 `normalized_ref_id`、`chunk_id`、`locator`、`source_block_ids`。
- `quality_flags_visible`: 对缺 heading、低 heading 覆盖、截断等问题显式返回 `quality_flags`，不能伪装成完整 section。

建议通过线标准：

- 5 份资产每份至少 3 条 query。
- `section_context_returned` 覆盖率 >= 80%。
- `expected_section_hit` 覆盖率 >= 70%。
- 不能出现跨报告资产混合到同一个 `document_section_context`。
- 不能出现没有 `locator`/`source_block_ids` 的 context 被标记为完整。

## Golden Queries

### 1. 北京市人才发展报告.pdf

资产特征：chunk 量大，heading 覆盖完整，适合作为长报告 section expansion 压力样本。

| query_id | 查询 | 期望章节主题 | 重点检查 |
| --- | --- | --- | --- |
| policy_report_001 | 北京市人才发展报告中关于产业人才的主要结论是什么 | 产业人才、人才结构、重点产业 | 能否从单点命中扩展到完整章节 |
| policy_report_002 | 北京市人才发展报告如何描述高层次人才引进 | 高层次人才、人才引进 | title/path 与正文共同排序 |
| policy_report_003 | 北京市人才发展报告对人才发展环境有哪些判断 | 人才发展环境、政策环境 | 多 chunk section 是否按文档顺序返回 |

### 2. 2022年中国电子商务报告.pdf

资产特征：chunk 多，表格行较多，适合验证表格行归入最近 section。

| query_id | 查询 | 期望章节主题 | 重点检查 |
| --- | --- | --- | --- |
| policy_report_004 | 2022年中国电子商务报告中跨境电商部分讲了什么 | 跨境电商 | 表格/统计行保留在跨境电商章节内 |
| policy_report_005 | 2022年中国电子商务报告如何描述农村电商发展 | 农村电商 | 不把相邻章节混入同一 context |
| policy_report_006 | 2022年中国电子商务报告对网络零售规模有哪些数据 | 网络零售、交易规模 | 统计 chunk 的 locator/source_block_ids 完整 |

### 3. 2025直播电商行业发展白皮书.pdf

资产特征：白皮书结构清晰，表格行明显，适合验证监管、趋势、平台角色等主题召回。

| query_id | 查询 | 期望章节主题 | 重点检查 |
| --- | --- | --- | --- |
| policy_report_007 | 直播电商行业监管政策演进有哪些阶段 | 监管政策、政策演进 | section title relevance 是否优先于单个高分正文 chunk |
| policy_report_008 | 2025直播电商白皮书如何判断直播电商发展趋势 | 发展趋势、行业趋势 | 返回 context 是否 bounded |
| policy_report_009 | 直播电商平台在行业生态中的角色是什么 | 平台、生态、产业链 | 多支持 hit 排名是否提升目标 section |

### 4. （跨境电商行业报告）2025上半年跨境电商行业报告.pdf

资产特征：行业阶段性报告，适合验证半年趋势、供应链、平台出海等主题。

| query_id | 查询 | 期望章节主题 | 重点检查 |
| --- | --- | --- | --- |
| policy_report_010 | 2025上半年跨境电商行业的主要趋势是什么 | 行业趋势、发展趋势 | section context 是否覆盖趋势小节 |
| policy_report_011 | 2025上半年跨境电商报告如何描述海外仓 | 海外仓、物流履约 | 子章节 heading_path 是否保留 |
| policy_report_012 | 2025上半年跨境电商报告对平台出海有哪些判断 | 平台出海、市场拓展 | 命中 chunk 是否被扩展为完整业务段落 |

### 5. （电子商务产业报告）中国电子商务报告（2024）.pdf

资产特征：新版电商报告，适合与 2022 报告形成同主题跨年份对照。

| query_id | 查询 | 期望章节主题 | 重点检查 |
| --- | --- | --- | --- |
| policy_report_013 | 中国电子商务报告2024对电子商务发展趋势有哪些判断 | 发展趋势 | 不同年份报告不应混入同一个 context |
| policy_report_014 | 中国电子商务报告2024如何描述跨境电商发展 | 跨境电商 | 与 2022 报告同主题 query 的 section 区分 |
| policy_report_015 | 中国电子商务报告2024中关于数字化转型有哪些内容 | 数字化、转型、产业升级 | heading_path title relevance 是否有效 |

## 记录模板

真实数据验证时，每条 query 建议记录以下字段：

| 字段 | 含义 |
| --- | --- |
| query_id | 上表 query id |
| query | 查询原文 |
| route | `internal_query` 或 `open_query` |
| top_hit_chunk_ids | pgvector 原始 top hit chunk id |
| returned_section_ids | 返回的 `document_section_context.section_id` |
| returned_titles | 返回 section title |
| returned_heading_paths | 返回 section heading_path |
| quality_flags | section quality_flags 汇总 |
| expected_section_hit | `pass` / `fail` |
| traceable | `pass` / `fail` |
| notes | 人工观察 |

## 下一步

1. 用当前实现跑上述 15 条 query，形成第一版人工评估结果。
2. 对失败 query 标注原因：向量首召未命中、heading_path 缺失、section 分段过粗、title/path 排序不足、chunk 本身低信息。
3. 若主要失败来自 heading_path 质量，优先修复 normalize/chunk 质量；若主要失败来自排序，再调 section ranking。
4. 当 `section_context_returned` 与 `expected_section_hit` 稳定达标后，再进入 Data Model Gate，评估是否持久化 `document_section`。
