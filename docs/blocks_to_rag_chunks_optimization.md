# Blocks → RAG 语义块 转换层 — 待优化设计

- **状态**：待决策（pending）
- **日期**：2026-06-22
- **样本资产**：`4abe6b71-9b07-488d-a04f-863fee14ebe7`（《2025 直播电商行业发展白皮书》）
- **关联文档**：
  - `ARCHITECT.md`（Chunk Locator Contract、Knowledge Pipeline 独立性）
  - `CLAUDE.md`（normalize / knowledge / index 边界）
  - `docs/document_normalize_defects.md` §11/§12/§13（索引修复历史与 v2.1 规则）
- **关联代码**：
  - `nexus-app/nexus_app/pipeline/mineru_converter.py`（blocks 产出）
  - `nexus-app/nexus_app/knowledge/services.py::run_knowledge_pipeline`（chunks 产出）
  - `nexus-app/nexus_app/knowledge/chunking_strategies/`（已有 8 种切块策略）
  - `nexus-app/nexus_app/models.py::KnowledgeChunk`、`NormalizedAssetRef`

---

## 一、问题陈述

`normalized_ref.blocks` 是**忠实于版面结构**的 PDF 解析中间产物：

- 一行小标题 = 一块；一段正文 = 一块；一张图 = 一块；一张大表 = 一块；一个数据来源标注 = 一块。
- 携带 `bbox` / `page` / `md_char_range` / `per_page_bboxes` 等定位元信息，**对源文档可定位 citation 极其合适**。

但 **RAG 语义块（chunk）的自然边界是「一个事实 / 一个论点 / 一个原子条目」**，与版面边界**并非一一对应**。对样本资产 4abe6b71（255 blocks）的逐类检查显示 4 类系统性错配（详见 `docs/document_normalize_defects.md` §14 verbatim 分析）：

| 错配                          |                                                      涉及块 | 实质                                    |
| ----------------------------- | ----------------------------------------------------------: | --------------------------------------- |
| 不该成 chunk 的成了 chunk     |                  59 heading + 16 短附属段 ≈ **75 块 / 29%** | 索引污染、召回噪声                      |
| 该按子单元切的没切            |                                      6 大 table 块 ≈ 3 万字 | 检索粒度失配（47 行政策被压成 1 chunk） |
| 该作 metadata 的没作 metadata | 全 heading、数据来源、章节路径、文档级标题/作者/日期/关键词 | 召回时上下文丢失                        |
| 该聚合的没聚合                |                  跨段同主题论证、（一）（二）（三）并列结构 | 召回完整度低                            |

**结论**：直接把 blocks 作为 RAG 索引单元（当前 `passthrough_to_ragflow` 模式实际就是这样）会把上述错配照单全收。需要**在 blocks → knowledge_chunks 之间增加一层 RAG 语义重组转换**。

---

## 二、设计原则：什么是「好的 RAG 语义块」

| 维度     | 定义                                                           |
| -------- | -------------------------------------------------------------- |
| 自包含   | 单独读这个 chunk 不查邻居就能看懂在讲什么                      |
| 单一主题 | 1 chunk = 1 事实 / 1 论点 / 1 条目                             |
| 携带定位 | 知道自己在文档里的位置（heading_path、page、source block_ids） |
| 可被问到 | embedding 后能被 1-2 个自然语言问题精确召回                    |
| 边界自然 | 切分顺着内容的语义/结构自然边界，不机械等分                    |

**大小是观察结果，不是设计目标**。50 字的法律条款和 1200 字的完整论证都可以是好 chunk。

---

## 三、优化方案

### 三.1 引入「语义重组层」：blocks → semantic chunks 的转换

#### 三.1.1 转换层落点

放在现有 `nexus_app.knowledge.services.run_knowledge_pipeline` 内（已存在的 KT-感知切块入口），扩展为 5 个语义化重组算子：

```
blocks (版面单元)
   ├── (a) extract_document_metadata  ← 抽取文档级 metadata（见 §三.3）
   ├── (b) drop_navigational          ← heading 独立块、目录残留 → 不作 chunk 候选
   ├── (c) attach_attribution         ← "数据来源:" / 署名小段 → 附入上一图表
   ├── (d) decompose_atomic           ← 大 table / 长列表 → 行级 / 项级
   ├── (e) merge_continuation         ← 跨页跨段同主题论证 → 聚合 chunk
   └── (f) enrich_context             ← 每个 chunk 注入 heading_path + page + caption
                                        作为 in-vector context（embedding 前缀）
                                        与 out-of-band metadata（chunk.chunk_metadata）
                                        两种形式
```

#### 三.1.2 5 个算子的具体规则（最小可行版本）

| 算子                              | 输入                                               | 输出                                                                                                   | 触发规则                                                                                                       |
| --------------------------------- | -------------------------------------------------- | ------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------- |
| **(a) extract_document_metadata** | 文档前 N 个 blocks（heading + paragraph 序列）     | 抽取后写入 `normalized_ref.document_metadata`（见 §三.3）；这些 block 标记为 metadata-only，不作 chunk | 第一个 h1 heading 之后到第一个章节级 h2 之间的内容                                                             |
| **(b) drop_navigational**         | heading 块、目录残留块（§12 TOC 抽取已处理一部分） | 不入 chunk 候选；heading 文本仅作为后续 chunk 的 heading_path metadata                                 | `block_type == "heading"` 且独立成块                                                                           |
| **(c) attach_attribution**        | 短附属段                                           | 合并到上一个 chart/image/table 的 chunk 内容尾部                                                       | `len(content) < 50` 且匹配模式：`^数据来源[:：]` / `^图\s*\d+-\d+` / `^表\s*\d+-\d+` / `^注\d+` / `^来源[:：]` |
| **(d) decompose_atomic**          | 大 table 块                                        | N 行 = N 个 chunks（每个携带 caption + 列头作 in-vector context）+ 1 个表概览 chunk                    | `block_type == "table"` 且 markdown rows ≥ 3                                                                   |
| **(e) merge_continuation**        | 连续同主题 paragraph                               | 合并为 1 个 semantic chunk                                                                             | 同 page 或相邻 page + 同 heading 父节点 + 上段无终止符或下段以连续词起始（"其次"/"再次"/"同时" 等）            |
| **(f) enrich_context**            | 任一 chunk 候选                                    | 注入 metadata + 可选 embedding 前缀                                                                    | 通用                                                                                                           |

#### 三.1.3 转换后 chunk 实例（vs 当前）

样本「表 3-1 政策一览表」（47 行）：

| 状态                | chunk 数量          | chunk 形态                                                                                                                                                                                        |
| ------------------- | ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 当前（passthrough） | 1                   | 7082 字符整表，embedding 信号被稀释                                                                                                                                                               |
| 重组后              | 48 = 47 行 + 1 概览 | 每行："表 3-1 直播电商相关政策一览表 → 第三章第一节 → 2021.04 国家网信办等七部门《网络直播营销管理办法（试行）》：直播营销平台应建立..."；概览："2020.11–2025.12 期间共 47 条直播电商相关政策..." |

样本「图 1-2 市场规模」（chart 块）：

| 状态   | chunk 形态                                                                                                                                    |
| ------ | --------------------------------------------------------------------------------------------------------------------------------------------- |
| 当前   | "**图1-2 2022-2025 我国直播电商市场规模及增速** > X 年份... > 数据..."                                                                        |
| 重组后 | "**第一章 第二节 一、行业规模 → 图 1-2 2022-2025 我国直播电商市场规模及增速** > X 年份... > 数据... > 数据来源：欧特欧咨询（数据来源段合并）" |

#### 三.1.4 转换层与 KT 切块策略的关系

- `KnowledgeTypeConfig.chunking_strategy` 现有 8 种（`semantic` / `qa_extract` / `process_step_extract` / `indicator_decompose` / `case_decompose` / `graph_extract` / `tag_decompose` / `passthrough`）。
- 转换层算子 (b)–(f) 是**所有 KT 共享的前置步骤**；算子 (a) 同样所有 KT 共享。
- KT 自己的 chunking_strategy **只决定** chunk 内容的最终编排方式（如 graph_extract 把表行变图三元组、qa_extract 把段拆 Q/A 对），不再负责"哪些 block 该独立成 chunk"这种 layout-vs-semantic 的决策。

---

### 三.2 chunks 表生长治理

#### 三.2.1 增长测算

按转换后规则，**每个 normalized_ref 产出 chunks 的量级**估算（以白皮书类长文档为例）：

| 来源                                           |                  每文档典型量 |
| ---------------------------------------------- | ----------------------------: |
| paragraph chunks（含合并）                     |                        80–150 |
| table → 行级 chunks                            | 100–500（取决于表数量与行数） |
| chart / image chunks                           |                         10–30 |
| 子单元 chunks（process step / Q&A / 指标项等） |              0–100（KT 而定） |
| **单文档合计**                                 |            **150–800 chunks** |

P0 验收的"D1-D4 试点域 × 数千份资产"规模：**预估 chunks 表条数 = 50 万 – 800 万**，5 年规模可达 千万–亿级。

#### 三.2.2 单表压力点

PostgreSQL 单表过亿后的典型压力：

- 索引膨胀（特别是 `(normalized_ref_id, knowledge_type_code)` 复合索引）
- VACUUM/REINDEX 窗口拉长
- 全表扫描成本（含审计/统计类查询）
- 写入并发（多 worker 同时插入热点）

#### 三.2.3 三阶段治理方案

> 按"先实现工作正确，再实现规模高效"的原则分阶段，不一上来就上分区。

**阶段 1（≤ 100 万 chunks）—— 不分区，加索引 + 控制热点**

- 维持现有 `knowledge_chunk` 单表。
- 现有索引：`(normalized_ref_id, knowledge_type_code)`、`(knowledge_type_code, created_at)`、`(ragflow_doc_id)` 够用。
- 新增 partial index：`WHERE embedding_status='pending'` 加速 worker scan。
- 写入侧：worker 按 ref 串行（同 ref 的 chunks 一次性批量插入），避免行锁争用。

**阶段 2（100 万 – 1000 万 chunks）—— PostgreSQL 声明式分区**

- 改 `knowledge_chunk` 为 `PARTITION BY HASH (normalized_ref_id)` 或 `PARTITION BY LIST (knowledge_type_code)`：
  - **按 ref hash 分**（推荐）：同一 ref 的 chunks 在同一分区，配合 `(ref_id, kt_code)` 索引召回单 ref 全部 chunks 时只走一个分区；新增 ref 写入均匀分散到 N 个分区，避免热点。建议 16 或 32 分区。
  - **按 KT 分**：检索按 KT 路由（每个 KT 一张物理表），但表数量等于 KT 数（16+），且 KT 之间 chunk 数极不均衡（textbook_kb 可能 10x industry_research_kb）。**不推荐**。
- 迁移：`pg_partman` 或手写迁移脚本 + 短窗口 `DETACH/CREATE TABLE LIKE/REATTACH`。
- 触发条件：监控 `pg_stat_user_tables` 上 `knowledge_chunk` 的 `n_live_tup` 超过 100 万，或单次 EXPLAIN ANALYZE 超过 200ms。

**阶段 3（> 1000 万 chunks）—— 冷热分离**

- 热表：仍是阶段 2 的分区表，存最近 N 个月新增 / 高频访问的 chunks。
- 冷表：单独表 `knowledge_chunk_archive`，按月归档；只支持精确 id 查询。
- 归档触发：
  - `asset_version.status = archived` 的 ref 对应 chunks 整批迁冷；
  - 长尾访问（最近 90 天 0 命中）迁冷。
- RAGFlow 端：归档不删 RAGFlow 文档，仅本地 metadata 移表。

#### 三.2.4 同步配套

- `KnowledgeChunk` 新增列（一次迁移）：
  - `parent_ref_id`（冗余 `normalized_ref.version_id` 的 asset_id，便于按 asset 范围查询不 join）—— 阶段 2 之前可选。
  - `archived_at: TIMESTAMPTZ NULL`（阶段 3 准备字段）。
- `IndexManifest` 不动（每 ref × kt 仅 1 行，量级 KB 不到百万）。

---

### 三.3 文档级 metadata 单独存放（不混入 chunk metadata）

#### 三.3.1 现状

文档级信息（标题、副标题、作者/编制单位、出版日期、关键词、摘要、版本号、ISBN/文件号、章节大纲）**目前都散落在前几个 block 里**：

- `block-p00-001`：标题 `# 2025 直播电商行业发展白皮书`
- `block-p00-002`：编制单位 `市场监管总局发展研究中心`
- `block-p00-003`：编制单位 `中国社会科学院财经战略研究院课题组`
- `block-p00-004`：日期 `2026 年 1 月`
- `block-p06-021`：关键词 `关键词：直播电商；规范化；政策；监管；协同治理。`

如果作为 RAG chunk 候选：单独召回它们答不了任何业务问题；不召回又把"这本白皮书是什么"的最重要描述完全丢失。

#### 三.3.2 设计

**抽取到 `normalized_asset_ref` 上一个新结构化字段**（不是 `metadata_summary` 那个杂物口袋）：

```python
# nexus_app/models.py 新增
class NormalizedAssetRef(...):
    ...
    document_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True,
        comment="Document-level metadata extracted from blocks (title, authors, "
                "publish_date, keywords, abstract, outline, doc_number, version). "
                "Used as 'every chunk's parent context' and for asset-detail "
                "rendering, NOT replicated into per-chunk metadata."
    )
```

字段 schema（最小集）：

```json
{
  "title": "2025 直播电商行业发展白皮书",
  "subtitle": null,
  "authors": ["市场监管总局发展研究中心", "中国社会科学院财经战略研究院课题组"],
  "publish_date": "2026-01",
  "publisher": null,
  "doc_number": null,
  "version": null,
  "language": "zh-CN",
  "keywords": ["直播电商", "规范化", "政策", "监管", "协同治理"],
  "abstract": "本白皮书系统梳理了直播电商行业从快速扩张到规范发展的演进路径...",
  "outline": [
    {"level": 1, "title": "第一章 直播电商行业发展历程及现状", "page": 9},
    {"level": 2, "title": "第一节 直播电商的定义", "page": 9},
    ...
  ],
  "source_block_ids": ["block-p00-001", "block-p00-002", ...]
}
```

#### 三.3.3 抽取规则（v1，规则驱动）

| 字段         | 抽取信号                                                                    |
| ------------ | --------------------------------------------------------------------------- |
| title        | 第一个 `block_type=heading` 且 `level=1`（或 `^#\s+` md 前缀）              |
| authors      | title 之后、第一个 h2 之前的短 paragraph 块（< 60 字符）                    |
| publish_date | 匹配 `^\d{4}\s*年\s*\d{1,2}\s*月` 或 ISO 日期                               |
| keywords     | 匹配 `^关键词[：:]` 起始的段 → split by `；;`                               |
| abstract     | "## 导论" / "## 摘要" / "## 前言" 第一个 h2 之后的连续 paragraph 块（合并） |
| outline      | 已有的 `payload.toc`（§12 落地）+ TOC 抽取增强                              |
| doc_number   | 匹配 `^[A-Z]{2,}/?\s*\d+[-\.\d]*`                                           |

抽取后，对应 block 的 `chunk_metadata` 标 `role=document_metadata`，转换层据此**不**再把它产为独立 chunk。

#### 三.3.4 消费侧

- **RAG 召回时**：每个 chunk 注入 in-vector 前缀（缩写形式，不重复全文）：
  ```
  [doc: 2025 直播电商行业发展白皮书 | 作者: 市场监管总局发展研究中心等 | 章节: 第三章 第一节 → 表 3-1] 2021.04 国家网信办...
  ```
  - 优点：embedding 自带"我来自哪本书的哪一节"语义；用户 query 含"白皮书"时可命中。
  - 反对意见：会让 embedding 维度受 prefix 影响。**折中**：只把 `章节路径 + caption` 放 in-vector，作者/日期等放 out-of-band metadata（RAGFlow chunk_metadata 字段）。
- **资产详情 UI**：直接读 `document_metadata` 渲染顶部 description / abstract，不再从 blocks 第一段拼。
- **AI 治理**：`AIGovernanceInputBuilder` 把 `document_metadata` 作为 prompt context，比当前依赖 `body_markdown[:N]` 更精准。

#### 三.3.5 与 chunk_metadata 的边界

| 信息                                            | 存放位置                            | 原因                            |
| ----------------------------------------------- | ----------------------------------- | ------------------------------- |
| 标题、作者、日期、关键词、摘要、大纲            | `normalized_ref.document_metadata`  | 文档级、跨所有 chunk 共享、量小 |
| heading_path（"第三章/第一节/二、地方规范..."） | `chunk.chunk_metadata.heading_path` | chunk 级局部坐标                |
| page / bbox / source_block_ids                  | `chunk.chunk_metadata.locator`      | chunk 级源定位                  |
| caption（图表标题）                             | `chunk.chunk_metadata.caption`      | chunk 级                        |
| KT code、co_emission_origin、chunking_strategy  | `chunk` 表已有列                    | 物化字段                        |

**核心原则**：**chunk 级 metadata 只保留 chunk-specific 信息，文档级共享信息上抬到 ref。** chunks 表千万级时，每条多 200 字节的文档级冗余 = 数 GB 浪费 + 召回时一致性维护噩梦。

---

## 四、落地切片

### 切片 1 — `document_metadata` 字段 + 抽取（最小可行）

- 单一 migration：`ALTER TABLE normalized_asset_ref ADD COLUMN document_metadata JSON`
- 新模块 `nexus_app/normalize/document_metadata_extractor.py`：从 blocks 抽取 metadata，写入 ref。
- normalize 阶段（`stages.run_normalize_document`）增加最后一步：调用 extractor。
- 不破坏现有 chunk 行为；UI/治理可选地开始消费 ref.document_metadata。

### 切片 2 — 语义重组转换层骨架

- 新模块 `nexus_app/knowledge/semantic_repack.py` 实现 5 个算子：
  - `extract_document_metadata`（与 #1 共享）
  - `drop_navigational`、`attach_attribution`、`merge_continuation`、`enrich_context` 先实现；
  - `decompose_atomic` 单独切片做（涉及 markdown table 解析）。
- `run_knowledge_pipeline` 流程改为：blocks → semantic_repack → KT chunking_strategy → chunks。
- 已有 KT 的 chunking_strategy 大部分可保持不变，只是输入由"原始 blocks"变"语义重组后的 chunks 候选"。

### 切片 3 — 大 table 行级原子化

- `decompose_atomic` 算子专项实现：markdown table 解析 → 每行一个 chunk，附 caption + 列头 in-vector 前缀。
- 增加表级概览 chunk（"本表共 N 行，时间跨度..."），由小型 LLM 调用生成。
- 路由：industry_research_kb / structured_record_table 默认启用；其他 KT 按需。

### 切片 4 — chunks 表治理阶段 1（加 partial index + 控制热点）

- partial index `WHERE embedding_status='pending'`。
- worker 写入侧：按 ref 批量 insert（已有，确认即可）。
- 上线监控：`pg_stat_user_tables.n_live_tup` for `knowledge_chunk`，触发阶段 2 的告警阈值 = 100 万。

### 切片 5 — chunks 表治理阶段 2（分区表）—— 仅在阈值触发后

- 迁移到 `PARTITION BY HASH (normalized_ref_id)`，32 分区。
- 准备灰度方案：新写入路由到分区表，旧表只读直至全部归档。

### 切片 6 — 冷热分离 —— 仅在 > 1000 万 触发

- 增 `knowledge_chunk_archive`；归档 worker 每日扫 archived ref + 90 天 0 命中 chunk。

---

## 五、与现有边界的对齐

| 既有契约                                                | 影响                                                                     | 处理                                                 |
| ------------------------------------------------------- | ------------------------------------------------------------------------ | ---------------------------------------------------- |
| `ARCHITECT.md` Chunk Locator Contract                   | chunk.locator 仍指源 blocks 的 bbox/page；source_block_ids 仍是 N→1 关系 | 不破坏，反而更精准（每 chunk 来源 block 列表更紧凑） |
| `CLAUDE.md` Knowledge Pipeline 独立于 Asset Pipeline    | semantic_repack 在 Knowledge Pipeline 内                                 | 不破坏                                               |
| `feedback_md_char_range_out_of_band`                    | semantic_repack 是从 blocks 派生 chunks，不修改 `body_markdown`          | 不破坏                                               |
| `governance_result.decision_trail` 内嵌 quality_summary | document_metadata 是文档侧描述，与治理结果正交                           | 互不干扰                                             |
| `KnowledgeChunk` 已有 `chunk_metadata` JSON             | chunk 级 metadata 仍走该字段；文档级抬到 ref.document_metadata           | 边界明确                                             |

---

## 六、待决策项

| #   | 决策点                                                                                                                                               | 选项                                 |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------ |
| 1   | semantic_repack 算子 (a)(b)(c)(e)(f) 是否一次性全做，还是按切片节奏                                                                                  | 建议切片                             |
| 2   | (d) decompose_atomic 是否对所有 KT 默认开启，还是 structured_record_table / industry_research_kb 等少数 KT                                           | 建议按 KT                            |
| 3   | in-vector context prefix（heading_path）使用哪种格式：紧凑 (`第三章/第一节/二`) vs 完整 (`第三章 直播电商监管 / 第一节 国家政策 / 二、地方规范...`） | 推荐紧凑+尾节全名                    |
| 4   | 文档元信息抽取规则是否需要 LLM 兜底（v1 纯规则，v2 加 LLM）                                                                                          | v1 纯规则，accumulate 失败样本后再加 |
| 5   | chunks 表治理阶段 2 触发阈值是否提到 50 万更早分区                                                                                                   | 100 万阈值 OK                        |
| 6   | 冷热分离时 RAGFlow 端文档是否同步归档                                                                                                                | 不归档，仅 Nexus 侧迁冷              |
| 7   | 是否额外保留 `block_role` 字段（document_metadata / heading / body / attribution / chart / table_row / aggregate）方便后续重组演进                   | 推荐加，开销极小                     |

---

## 七、不在本方案范围

- chunk embedding 召回质量评测（属 RAG 评测体系，单独立项）。
- RAGFlow 端 chunk_method 演进（属 RAGFlow 升级，由部署侧推动）。
- 跨文档实体关系（人物/机构/事件）抽取 —— 属图谱 KT 范围。
- 向量库选型 / 替换 RAGFlow（属架构层）。

---

## 历史

- 2026-06-22 §14：基于样本资产 4abe6b71 的 blocks 抽样分析，识别 4 类 layout-vs-semantic 错配；提出转换层 + 表分区 + 文档级 metadata 三件套，登记待决策。
