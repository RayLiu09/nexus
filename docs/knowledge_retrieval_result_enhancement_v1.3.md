# NEXUS 知识检索与召回结果增强方案 v1.3（优化方案）

- **状态**：v1.3 优化设计（2026-07-09 首版；同日修订，见 §16）
- **日期**：2026-07-09
- **适用范围**：跨数据资产复杂检索、维度联动、证据链汇总；重点解决"跨资产桥接可落地性"
- **输入基础**：
  - `docs/knowledge_retrieval_result_enhancement_v1.0.md`（四层编排骨架）
  - `docs/knowledge_retrieval_result_enhancement_v1.1.md`（DAG + 六维度桥接方向）
  - v1.2 讨论结论（语义标签作主桥）
  - v1.3 讨论结论（tag_asset_index 详细契约 + 六层匹配 + 治理简化）
  - v1.3 修订讨论（业务标签抽取合并到现有 AI 治理阶段，见 §16）
- **文档关系**：v1.3 **不替代** v1.0 骨架，**替换** v1.1 中"标准编码强 FK 桥接"的部分设计；v1.2 未成为独立文档，其结论已并入 v1.3。

---

## 1. 定位再校准与 v1.1 短板复盘

### 1.1 v1.1 的正确部分（保留）

- 四层编排（意图 → 计划 → 并行 → 汇总）
- sub_query DAG + `shared_constraints` + `binding_map`
- 多粒度 embedding（chunk / outline_node / ability_item）
- evidence_chain 汇总模式 + 断链显式提示
- Console 三区结构 + SSE 事件流
- 合规红线（三 Prompt profile + `ai_governance_run` + `SearchQueryExecuted`）
- 六维度分类学（region / industry / occupation / major / ability / topic / time）

### 1.2 v1.1 需要替换的部分

原始 PDF/Excel 数据源中，标准编码（GB/T 2260/4754/6565、教育部专业目录、能力体系码）**原生可得率极低**：

| 桥字段     | 原生编码可得率 | 主要原因                                |
| ---------- | -------------- | --------------------------------------- |
| region     | 中低           | 通常仅"北京市"文本，罕见带码            |
| industry   | 极低           | 政策/报告几乎不写 GB/T 4754 码          |
| occupation | 极低           | 岗位表为"直播运营/数据分析师"，无职业码 |
| major      | 中高           | 教育部专业布点表通常带；教材大多不带    |
| ability    | 中             | 业务专家整理时可能带                    |
| time       | 高             | 唯一原生可得的高质量桥                  |

依赖治理 LLM 推测编码 + 人工审核回填的方案带来两个不可接受的成本：

1. **LLM 编码映射天花板**：分类学争议（"直播电商"属 `I65` 还是 `F51`）本身无客观答案。
2. **人工审核吞吐倒挂**：审"标签是否与文档匹配"（语义任务，秒级）与审"编码映射是否正确"（分类学任务，分钟级）成本差一个数量级。

**结论**：v1.1 的"标准编码强 FK 桥接"在 NEXUS 现实数据源上**不可落地**。

### 1.3 v1.3 的核心命题

> **语义标签作跨资产主桥，`tag_asset_index` 作语义倒排枢纽；结构化数据靠字段直接投影建索引，非结构化靠大纲节点与现有 AI 治理产物投影；标准编码字典退化为可选归一化辅助，永不强依赖；不新增独立的"业务标签抽取"阶段，业务标签由现有 AI 治理阶段一次产出。**

五个决定性设计选择：

1. **`tag_asset_index` 是唯一语义倒排枢纽**（多态外键覆盖结构化 record、outline_node、asset_ref）。
2. **结构化数据不做 record-level embedding**；语义能力集中在 tag_asset_index。
3. **六层匹配降级链的主战场是 L1 + L1.5 + L4**（不依赖字典与治理编码）。
4. **业务标签作为现有 AI 治理产物的一部分**：升级现有治理 Prompt 输出 schema，一次 LLM 调用同时产出 classification / level / **分类型结构化 tags** / quality_summary，不新增独立 tag 抽取 profile、不新增独立审核入口。
5. **分类型标签的类型体系归入 `config/governance_rules.json`**（新增 `tag_taxonomy` 顶层段），作为业务规则的一部分；Console 治理中心的"标签审核"页面升级为分类展示，专家标注功能内嵌其中。

---

## 2. `tag_asset_index` 详细契约（v1.3 核心）

### 2.1 为什么是语义倒排枢纽

`tag_asset_index` 把"业务标签 → 资产/大纲节点/结构化记录"的多对多关系落成扁平表。任何维度过滤（结构化 SQL 或非结构化召回）都通过它反查得到"目标 ID 集合"，避免让每个 executor 各自实现字段匹配 + 语义扩展。

对结构化 SQL 查询尤其关键：

- 假设 `job_demand_record.industry_name="互联网信息服务"`，用户查询 tag `industries=["直播电商"]`。
- 字符串上不等、不含 → 无 tag_asset_index 时死局。
- 有 tag_asset_index 时：先在索引中用 tag_embedding 找相似 tag → 得到 `target_id` 集合 → SQL `WHERE id IN (...)` 二次过滤聚合。

**语义相似度计算完全发生在 tag_asset_index 阶段，SQL 只做集合过滤和聚合**。这一分离让 SQL 部分保持简单可审计。

### 2.2 表结构

```
tag_asset_index
  id                     uuid PK
  tag_type               enum(region | industry | occupation | major | ability | topic | time)
  tag_value              text            -- 自然语言原值："北京市" / "直播电商"
  tag_value_normalized   text            -- 归一化后（见 §3.1 内建规则）
  standard_code          text nullable   -- 字典命中或专家标注时填
  tag_embedding          vector(512)     -- bge-small-zh-v1.5 或同规格
  target_type            enum(normalized_asset_ref | outline_node
                              | job_demand_record | job_demand_requirement_item
                              | major_distribution_record
                              | occupational_ability_item)
  target_id              uuid            -- 指向对应表的主键
  asset_version_id       uuid            -- 冗余，用于版本失效批量清理
  source                 enum(field_projection | outline_projection
                              | governance_tag | expert_manual | dict_alias_hit)
  confidence             float           -- 抽取/投影置信度
  extracted_at           timestamptz
  extraction_run_id      uuid nullable   -- 关联 ai_governance_run.id（source=governance_tag 时）

INDEX ix_tai_type_norm       (tag_type, tag_value_normalized)
INDEX ix_tai_type_code       (tag_type, standard_code) WHERE standard_code IS NOT NULL
INDEX ix_tai_embedding_hnsw  USING hnsw (tag_embedding vector_cosine_ops)
INDEX ix_tai_target          (target_type, target_id)
INDEX ix_tai_asset_version   (asset_version_id)
```

关键设计点：

- `target_type` + `target_id` 是**多态外键**，一张表覆盖所有跨资产维度。
- `asset_version_id` 冗余存储，用于**版本失效批量清理**（asset 换版时 tag 一起换）。
- `source` 显式标注抽取路径，用于**质量评级**和**审计追溯**。
- `extraction_run_id` 关联到 `ai_governance_run`，保证治理侧 tag 全链路可审计。

### 2.3 数据来源分层

| 来源 code                                     | 触发时机                 | 目标 target_type                                                                                                | 数据质量                            | 依赖 LLM                |
| --------------------------------------------- | ------------------------ | --------------------------------------------------------------------------------------------------------------- | ----------------------------------- | ----------------------- |
| **A. `field_projection`**：结构化字段直接投影 | Pipeline B record 写入后 | `job_demand_record` / `major_distribution_record` / `occupational_ability_item` / `job_demand_requirement_item` | **极高**（原文字段）                | **否**                  |
| **B. `outline_projection`**：大纲节点投影     | outline_node 生成/更新时 | `outline_node`                                                                                                  | 高（标题 + node_metadata.keywords） | 部分（keywords 抽取时） |
| **C. `governance_tag`**：AI 治理标签          | 治理 job 完成时          | `normalized_asset_ref`                                                                                          | 中（confidence 过滤）               | 是                      |
| **D. `expert_manual`**：专家人工标注          | Console 面板             | 任意                                                                                                            | 极高                                | 否                      |
| **E. `dict_alias_hit`**：字典 alias 命中      | A/B/C/D 任一路径命中时   | 补齐已存在行的 `standard_code`                                                                                  | N/A                                 | 否                      |

**核心洞察**：结构化数据的 tag 来源是"字段直接投影"，不依赖 AI、不依赖字典，可靠性极高。AI 治理只是补充增量，不是主要来源。

### 2.4 投影规则（v1.3 落地契约；v1.3 修订 R2 全面重写）

**指导原则**（v1.3 修订轮次 2，2026-07-10）：

1. 投影**不是"字段全放"**——只把**检索侧真正会用作跨资产维度过滤**的字段写入 `tag_asset_index`；其他保留在领域表内做本地 SQL `structured_filters`。
2. `job_demand_requirement_item.item_type` 是**固定枚举**（`professional_skill / tool / certificate / professional_literacy / work_task_candidate`）。当前**仅** `professional_skill` 值得跨资产投影（其余属于岗位本地约束，进 tag_asset_index 会引入噪声）。
3. 能力类跨资产联结（`occupational_ability_item` / `job_demand_requirement_item` / `major_profile_ability`）依赖 **text 语义**——它们各自的 `ability_code` / `taxonomy_code` / 序号仅是内部编号，**无共享词汇**，因此**不投影**为 tag（保持 local_only），跨资产联结走 L4 语义匹配（见 §3.3）。
4. 长文本字段（岗位职责、任职要求正文、能力项详细描述等）**不投影**为 tag——它们进入 chunk / outline 层，避免 tag_asset_index 主题桶被冲垮。

投影白名单初始版本 v0.1 归 `nexus_app/ai_governance/projection_config.py`（`PROJECTION_WHITELIST_V1_3` 常量），未来将迁至 `governance_rules.json.tag_taxonomy.projection_whitelist`。

**结构化侧（source=`field_projection`）**：

| 领域表                        | 投影字段 → tag_type                                                                                                | 本地 SQL structured_filters（不投影）                                                                                                                                                                         | 长文本（chunk 层承载）                                                         |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| `job_demand_record`           | `city` → region, `industry_name` → industry, `job_title` → occupation, `source_published_at` → time_range          | `employment_type`, `experience_requirement`, `education_requirement`, `salary_min/max/text`, `enterprise_size`, `job_count`, `job_function_category`, `region`（上游解析）, `company_name`, `company_address` | `job_skill_text`, `job_description`, `responsibility_text`, `requirement_text` |
| `job_demand_requirement_item` | **仅 `item_type='professional_skill'`**：`normalized_name`（回退 `item_name`）→ **ability + topic**                | `item_type`（保留供 SQL 精确过滤"筛技能项"）, `confidence`, `evidence_field`                                                                                                                                  | —                                                                              |
| `major_distribution_record`   | `province_name` → region, `region_scope` → region, `major_name` → major, `major_code` → major, `year` → time_range | `education_level`, `distribution_count`                                                                                                                                                                       | —                                                                              |
| `occupational_ability_item`   | `ability_content` → ability                                                                                        | `ability_code`, `ability_major_category_code`, `ability_major_category_name`, `ability_sequence`（**内部编号，无跨资产语义，永远 local**）                                                                    | —                                                                              |
| `major_profile_ability`       | `text` → ability                                                                                                   | `item_index`                                                                                                                                                                                                  | —                                                                              |

**跳过的 item_type**（`job_demand_requirement_item.item_type`）：`tool` / `certificate` / `professional_literacy` / `work_task_candidate`——都是**本地岗位约束**，进 tag_asset_index 会污染跨资产 ability/topic 桶。

**非结构化侧（source=`outline_projection`）**：

| 源                       | 字段/元数据 → tag_type                              | 本地 filters                                             |
| ------------------------ | --------------------------------------------------- | -------------------------------------------------------- |
| `knowledge_outline_node` | `title` → topic, `node_metadata.keywords[]` → topic | `level`, `anchor_range`, `chunk_count`, `numbering_path` |
| `task_outline_node`      | `title` → topic                                     | `task_profile`, `textbook_subtype`, `level`, `node_type` |

**治理侧（source=`governance_tag`）**：

按 **现有 AI 治理阶段产出的** `governance_result.tags`（v1.3 分类型结构化契约，见 §4.1）分类型分行写入，写入前按 `confidence` 阈值过滤（阈值定义在 `governance_rules.json.tag_taxonomy`，见 §4.4 与 §7）。

**关键**：本层数据来自**现有** AI 治理阶段一次 LLM 调用的产物（升级现有治理主 Prompt 的 output schema），不引入独立"业务标签抽取"子阶段。

### 2.5 写入与失效机制

**写入**：

- 每类 target 有对应的**投影 hook**（`domain_normalize/*_writer.py` 完成 record 写入后触发，或 SQLAlchemy after_flush event）。
- 投影 hook 只写入 `tag_value` / `tag_value_normalized` / `standard_code`（若命中字典）等字段，`tag_embedding` 由异步 job 计算。
- `tag_embedding` 缺失时匹配层降级到 L1/L1.5（不进 L4），index_manifest 记录 embedding lag。

**失效**：

- `asset_version_id` 变更时批量 DELETE 旧版本行（按 `ix_tai_asset_version` 索引）。
- 治理结果重算时按 `source=governance_tag` + `extraction_run_id` 精确清理重建。
- 专家删除标签时软删（保留审计）或硬删（配置化）。

**一致性**：

- 允许**最终一致**，检索层容忍延迟。
- `index_manifest` 扩展新 `backend_type=tag_asset_index`，记录投影 lag、embedding lag、失败重试次数。

### 2.6 容量评估

假设：

- 结构化 record 约 100 万条，平均每条 4 个 field_projection tag
- 非结构化资产约 10 万，平均每资产 5 个 outline_node + 每 outline_node 3 个 topic tag
- 治理标签约每资产 8 个

预估行数约 500 万；tag_embedding 512 维 float32 ≈ 2KB/行，主体存储约 **10GB**（含 HNSW 索引开销 ×1.5-2 倍约 15-20GB）。可接受，与 pgvector chunk 索引同数量级。

超过 1000 万行时启动独立 schema 或读副本评估（对齐 v1.0 §3.3.1.3 pgvector 容量分层）。

---

## 3. 六层匹配降级链

### 3.1 层次定义与依赖矩阵

| 层       | 名称            | 依赖                     | 命中率变量           | 状态                  |
| -------- | --------------- | ------------------------ | -------------------- | --------------------- |
| **L1**   | 精确匹配        | 无                       | tag_value 归一化质量 | **必备**              |
| **L1.5** | 内建归一化匹配  | 无（纯代码规则）         | 规则覆盖度           | **必备（v1.3 新增）** |
| **L2**   | 字典 alias 匹配 | `dim_*_alias` 表完备度   | 字典条目数           | 可选                  |
| **L3**   | 标准编码匹配    | `standard_code` 填充率   | 治理侧/专家标注覆盖  | 可选                  |
| **L4**   | 语义匹配        | `tag_embedding` 模型质量 | 模型选型、阈值       | **必备**              |
| **L5**   | Chunk 兜底      | v1.0 pgvector 索引       | v1.0 契约            | 保留                  |

**关键设计**：**L1 + L1.5 + L4 三层是主战场**，不依赖字典与治理编码，字典空时方案仍可用。

### 3.2 L1.5 内建归一化规则（不依赖字典）

规则清单（v1.3 起步版本）：

| 规则                              | 例子                                    |
| --------------------------------- | --------------------------------------- |
| Unicode NFKC 归一                 | 全角/半角、繁简                         |
| 小写化                            | `Python` → `python`                     |
| 去空白（含内部多空格压缩）        | `直 播 电 商` → `直播电商`              |
| 去常见后缀（可配置）              | `北京市` → `北京`；`零售业` → `零售`    |
| 去括号内容                        | `直播电商（含短视频带货）` → `直播电商` |
| 常用简称展开表（内建小表 ~30 条） | `京` → `北京`；`沪` → `上海`            |

**性质**：

- 纯代码规则，无 DB 依赖，可单元测试。
- 覆盖率评估（经验判断）：地区类 ≥ 90%、时间类 ≥ 95%、行业/职业/专业/能力 60-75%。
- 与字典是**互补**关系：L1.5 处理规则性差异（后缀、简称、空白），L2 处理**同义词**（"直播带货" ~ "直播电商"）——后者非规则可推导，必须字典。

### 3.3 L4 语义匹配

- HNSW 近邻查询：`ORDER BY tag_embedding <=> query_embedding LIMIT top_k WHERE score >= threshold`。
- **模型选型**：默认 `bge-small-zh-v1.5`（512 维），P0 前敲定；替换模型需批量重算 tag_embedding 并升级 `index_manifest`。
- **阈值**：默认 `semantic_threshold=0.75`，`top_k=20`；planner 可按 tag_type 覆写。
- **短标签风险**（2-4 字标签 embedding 语义不稳定）**缓解**：
  1. **`tag_type=ability` 类型强制 rerank**（v1.3 修订 R2 从 P1 提前到 P0）——因为 `occupational_ability_item` / `job_demand_requirement_item` / `major_profile_ability` 三方**内部编号无共享语义**（见 §4.3），跨资产 ability 联结**只能**走 L4，rerank 是唯一质量兜底。
  2. 其他 tag_type 的 rerank 保留在 P1（cross-encoder 或 LLM re-scoring）。
  3. 汇总层看到 `match_layer=L4` 时**折扣证据强度**（"强"降到"中"），evidence_chain 显式提示。

### 3.4 端到端可靠性判断

字典完全空 + tag_embedding 就位时，复杂场景（"北京市 直播电商 → 专业建设方案"）综合评估：

| DAG 节点       | 主要 tag                       | L1  | L1.5 | L4  | 综合可靠性 |
| -------------- | ------------------------------ | --- | ---- | --- | ---------- |
| q_policy       | industry=直播电商              | ⚠️  | ✅   | ✅  | 中高       |
| q_job region   | region=北京市                  | ✅  | ✅   | ✅  | 高         |
| q_job industry | industry=直播电商              | ⚠️  | ⚠️   | ✅  | 中         |
| q_ability      | occupation=直播运营            | ✅  | ✅   | ✅  | 高         |
| q_major        | region=北京市 + major=电子商务 | ✅  | ✅   | ✅  | 高         |
| q_textbook     | ability=...                    | ⚠️  | ⚠️   | ✅  | 中         |

**综合结论**：字典空 + tag_embedding 就位时，复杂场景端到端可行，个别节点走 L4，evidence_chain 显示"证据强度：中"，用户可读、可信、可追溯。字典是加分项而非必要项。

---

## 4. 数据契约（v1.3 定稿）

### 4.1 `governance_result.tags`（结构化契约，无编码映射）

```json
{
  "regions": [
    {
      "value": "北京市",
      "confidence": 0.95,
      "evidence_span": "北京市直播电商新政..."
    }
  ],
  "industries": [
    { "value": "直播电商", "confidence": 0.9, "evidence_span": "..." },
    { "value": "跨境电商", "confidence": 0.65, "evidence_span": "..." }
  ],
  "occupations": [
    { "value": "直播运营", "confidence": 0.85, "evidence_span": "..." }
  ],
  "majors": [],
  "abilities": [],
  "topics": [
    { "value": "数据合规", "confidence": 0.85, "evidence_span": "..." }
  ],
  "time_ranges": [{ "kind": "year_range", "start": 2024, "end": 2026 }]
}
```

关键点：

- **无 `standard_code` 字段**：治理阶段完全不做编码映射。
- **每个 tag 必须带 `evidence_span`**：从原文抽取的短语引用，用于审核依据。
- **可为空**：抽取不到就不输出，不强制"六维度必须都有"。
- **产出方式**：由**现有 AI 治理主 Prompt 一次产出**（升级现有 profile 的 output schema），与 `classification` / `level` / `quality_summary` 同一次 LLM 调用同源；**不引入独立的 `governance_tag_extract` profile**。审计走同一份 `ai_governance_run`。
- **tag 分类体系**（regions / industries / occupations / majors / abilities / topics / time_ranges）由 `config/governance_rules.json.tag_taxonomy` 声明（见 §4.4），Prompt 从规则读取作为受控输出格式。

### 4.2 `knowledge_outline_node.tags`

节点级 tag JSONB，与 §4.1 同构。数据来源：

- `outline_projection`：从 `title` / `numbering_path` / `node_metadata.keywords` 派生。
- `governance_tag`：治理侧若对节点做了 tag 抽取（P1 增强），可写入此处。

### 4.3 字典表（精简为可选归一化辅助）

```
dim_region (canonical)
  code                text PK   -- "11" / "1101"（如 GB/T 2260 命中时可填，无强约束）
  name                text      -- "北京市"
  level               enum(province | city | district)
  parent_code         text nullable

dim_region_alias
  alias               text
  canonical_name      text      -- FK to dim_region.name
  alias_type          enum(short | full | old | slang)
  confidence          float
  PRIMARY KEY(alias, canonical_name)
```

其他维度（`dim_industry` / `dim_occupation` / `dim_major` / `dim_ability`）同构。

**变化**：

- `dim_time_bucket` 由平台预置（时间是原生高质量维度）。
- `dim_region` 由平台预置省级/市级 canonical name + 少量 alias（"京"/"沪"等）。
- 其他维度**允许空表**，Console 由专家渐进维护。
- **不设强 FK**，字典只在 L2 归一化时被查询；命中即补 tag_asset_index.standard_code，未命中不阻塞。

**`dim_ability` 特殊说明（v1.3 修订 R2）**：`occupational_ability_item.ability_code` / `job_demand_requirement_item.taxonomy_code` / `major_profile_ability` 的编号都是**内部自动序列**，各表之间**不共享值域、无跨资产桥接语义**。因此：

- `dim_ability` **不承担**"跨资产 ability 归一化" 职责——它降级为纯**术语参考表**（"数据分析" ~ "数据分析能力"这类写作规范化）。
- L2（字典 alias）与 L3（`standard_code` 精确匹配）在 `tag_type=ability` 上**事实上无效**。
- ability 类型的跨资产联结**完全依赖 L4 语义匹配 + 强制 rerank**（见 §3.3）。这条约束是能力域检索质量的关键。

### 4.4 `governance_rules.json` 中的 `tag_taxonomy` 段

分类型 tag 的**类型体系**归入 `config/governance_rules.json`，作为业务规则的一部分（与 `classifications` / `levels` / `quality_scoring` 同层）：

```json
{
  "schema_version": "3.0",
  "tag_taxonomy": {
    "types": [
      { "code": "region",     "name": "地区", "canonical_source": "dim_region",     "allow_free_form": true, "expected_cardinality": "low"    },
      { "code": "industry",   "name": "行业", "canonical_source": "dim_industry",   "allow_free_form": true, "expected_cardinality": "medium" },
      { "code": "occupation", "name": "职业", "canonical_source": "dim_occupation", "allow_free_form": true, "expected_cardinality": "medium" },
      { "code": "major",      "name": "专业", "canonical_source": "dim_major",      "allow_free_form": true, "expected_cardinality": "medium" },
      { "code": "ability",    "name": "能力", "canonical_source": "dim_ability",    "allow_free_form": true, "expected_cardinality": "high"   },
      { "code": "topic",      "name": "主题", "canonical_source": null,             "allow_free_form": true, "expected_cardinality": "high"   },
      { "code": "time_range", "name": "时间", "canonical_source": "dim_time_bucket","allow_free_form": true, "expected_cardinality": "low"    }
    ],
    "auto_accept_threshold": 0.75,
    "review_threshold": 0.55
  },
  "classifications": [ ... 现有 per-classification tagging_basis 保持不变 ... ],
  "levels": [ ... ],
  "quality_scoring": [ ... ]
}
```

**说明**：

- 现有各 `classification.tagging_basis` / `geo_scope` / `timeliness` / `data_source` 段保持不变——它们描述"每类资产**应打什么值**"（细粒度业务规则）。
- 新增 `tag_taxonomy` 描述"跨资产共有的**标签类型骨架**"（粗粒度骨架），供治理 Prompt、tag_asset_index、检索侧、Console 共同引用。
- 二者是**互补关系**：`tag_taxonomy.types` 声明骨架，`classification.tagging_basis` 提供每类资产在骨架上的取值参考。
- 阈值（`auto_accept_threshold` / `review_threshold`）从代码硬编码迁移到规则文件，符合"规则文件即真源"。
- schema_version 建议从 `2.1` 升级到 `3.0`，通过 v1.0 ETag + fcntl 机制保护写入原子性。

### 4.5 移除的 v1.1 设计

- ❌ `normalized_asset_ref.dimension_refs`（复杂 JSONB）—— 合并进 tag_asset_index。
- ❌ 结构化领域表补 code 列 + FK —— 保留原字段，投影为 tag 即可。
- ❌ 治理阶段的编码映射能力。
- ❌ 编码回填异步 job。
- ❌ 独立的 `governance_tag_extract_v1_3` Prompt profile（v1.3 修订后移除，见 §16）。

---

## 5. 意图识别与检索计划层

### 5.1 `RetrievalIntent` schema（v1.3）

```json
{
  "business_domains": ["industry_policy", "job_demand", "major_distribution"],
  "retrieval_channels": ["hybrid"],
  "question_type": "planning_recommendation",
  "output_expectation": ["evidence_chain", "recommendation"],

  "cross_asset_tags": {
    "regions": [{ "value": "北京市", "confidence": 0.94 }],
    "industries": [
      { "value": "直播电商", "confidence": 0.9 },
      { "value": "跨境电商", "confidence": 0.65 }
    ],
    "occupations": [],
    "majors": [{ "value": "电子商务", "confidence": 0.9 }],
    "abilities": [],
    "topics": [],
    "time_ranges": [{ "kind": "year_range", "start": 2024, "end": 2026 }]
  },
  "unresolved_terms": ["职业院校"],

  "resource_hints": {
    "industry_policy": "outline_traversal",
    "industry_report": "outline_traversal",
    "course_textbook": "outline_traversal",
    "task_textbook": "task_traversal",
    "competency_analysis": "ability_graph_walk",
    "job_demand": "sql_aggregation",
    "major_distribution": "sql_aggregation",
    "major_profile": "hybrid"
  },

  "confidence": 0.86,
  "tag_confidence": 0.85
}
```

**变化（对比 v1.1）**：

- `cross_asset_dimensions` → `cross_asset_tags`（自然语言标签，无 code）。
- 新增 `unresolved_terms`（未识别成 tag 的关键词，走 L4/L5 兜底）。
- 新增 `tag_confidence`（tag 识别的独立置信度）。
- Prompt 注入的字典摘要**仅用于归一化**（用户说"京"→ LLM 输出"北京市"），不要求 LLM 输出编码。

### 5.2 澄清策略

- v1.0 保留：`intent.confidence < 0.78` 触发澄清。
- v1.3 新增：`tag_confidence < 0.7` 且问题含明显维度关键词（省份、专业名等）时也触发澄清。
- Console 澄清界面**双栏化**：左"资产域候选"、右"tag 约束候选"，用户可分别修正。

### 5.3 `RetrievalPlan` schema（v1.3）

```json
{
  "original_query": "基于北京市直播电商产业布局，规划某高职院校电子商务专业建设方案",
  "shared_constraints": {
    "regions": [{ "value": "北京市" }],
    "industries": [{ "value": "直播电商" }],
    "time_ranges": [{ "kind": "year_range", "start": 2024, "end": 2026 }]
  },

  "sub_queries": [
    {
      "query_id": "q_policy",
      "channel": "unstructured",
      "domain": "industry_policy",
      "purpose": "background_evidence",
      "depends_on": [],
      "unstructured_plan": {
        "index": "outline_node_embedding_pgvector",
        "tag_filters": {
          "industries": {
            "tags": "$shared.industries",
            "match_strategy": "l1|l1.5|l4",
            "semantic_threshold": 0.75
          },
          "regions": {
            "tags": "$shared.regions",
            "match_strategy": "l1|l1.5",
            "optional": true
          }
        },
        "combine": "AND",
        "top_k": 6
      },
      "output_binding": "policy_evidence"
    },
    {
      "query_id": "q_job",
      "channel": "structured",
      "domain": "job_demand",
      "purpose": "aggregation",
      "depends_on": [],
      "structured_plan": {
        "table_profile": "job_demand.v1",
        "tag_filters": {
          "regions": {
            "tags": "$shared.regions",
            "match_strategy": "l1|l1.5|l4"
          },
          "industries": {
            "tags": "$shared.industries",
            "match_strategy": "l1|l1.5|l4",
            "semantic_threshold": 0.75
          }
        },
        "combine": "AND",
        "group_by": ["job_title"],
        "metrics": [{ "field": "record_id", "function": "count" }],
        "top_n": 10
      },
      "output_binding": "top_jobs"
    },
    {
      "query_id": "q_ability",
      "channel": "structured",
      "domain": "competency_analysis",
      "depends_on": ["q_job"],
      "binding_map": {
        "occupation_tags": {
          "source": "$q_job.output.top_jobs[*].job_title",
          "as_tag_type": "occupation",
          "match_strategy": "l1|l1.5|l4",
          "semantic_threshold": 0.72,
          "limit": 10
        }
      },
      "structured_plan": {
        "table_profile": "competency_analysis.v1",
        "tag_filters": {
          "occupations": {
            "tags": "$binding.occupation_tags",
            "match_strategy": "l1|l1.5|l4"
          }
        },
        "expand": "ability_tree"
      },
      "output_binding": "required_abilities"
    },
    {
      "query_id": "q_major",
      "channel": "structured",
      "domain": "major_distribution",
      "depends_on": [],
      "structured_plan": {
        "table_profile": "major_distribution.v1",
        "tag_filters": {
          "regions": { "tags": "$shared.regions", "match_strategy": "l1|l1.5" },
          "majors": { "tags": "$shared.majors", "match_strategy": "l1|l1.5|l4" }
        },
        "combine": "AND",
        "structured_filters": { "education_level": "高职" },
        "group_by": ["major_name", "year"],
        "metrics": [{ "field": "distribution_count", "function": "sum" }]
      },
      "output_binding": "current_majors"
    },
    {
      "query_id": "q_textbook",
      "channel": "unstructured",
      "domain": "course_textbook",
      "depends_on": ["q_ability"],
      "binding_map": {
        "ability_tags": {
          "source": "$q_ability.output.required_abilities[*].name",
          "as_tag_type": "ability",
          "match_strategy": "l1|l1.5|l4",
          "semantic_threshold": 0.72
        }
      },
      "unstructured_plan": {
        "index": "outline_node_embedding_pgvector",
        "tag_filters": {
          "abilities": {
            "tags": "$binding.ability_tags",
            "match_strategy": "l1|l1.5|l4"
          }
        },
        "top_k": 8
      },
      "output_binding": "curriculum_evidence"
    }
  ],

  "merge_goal": "planning_recommendation",
  "merge_strategy": "evidence_chain",
  "max_dag_depth": 3,
  "max_sub_queries": 8
}
```

**关键升级**：

- `tag_filters` 结构包含 `match_strategy`（层级组合表达式）、`semantic_threshold`、`optional`（该 filter 未命中时不否决整个 sub_query）。
- `combine` 声明多 tag_filter 之间的集合运算（AND/OR/WEIGHTED）。
- `structured_filters` 保留传统精确字段过滤（如 `education_level="高职"`），与 `tag_filters` 并行走 `combine`。
- `binding_map` 传递业务实体名（自然语言），下游作为 tag_candidate 走匹配降级链。

### 5.4 Planner 边界

- `binding_map` 表达式路径必须 schema 校验（引用的 `query_id` 存在，字段在 `output_binding` 声明中）。
- 循环依赖检测：DAG 检测在 planner 阶段完成，出错拒绝执行。
- `max_dag_depth=3` / `max_sub_queries=8` 起步。
- 用户可在 Console 手动编辑 DAG（辅助分析区），编辑后重新校验执行。

### 5.5 `RetrievalPlan.friendly_view`（v1.3 R3 新增契约）

`RetrievalPlan` 附带 `friendly_view: FriendlyRetrievalPlanView | None` 字段，作为 Console 面向业务用户的**可读呈现契约**。由 orchestrator 生成，前端仅渲染、不派生。**不替换**原始 `sub_queries` 字段（工程/审计侧仍走原始）。完整设计与渲染细节见 `docs/retrieval_plan_console_ux_v1.md`；本节仅冻结契约骨架：

```json
{
  "friendly_view": {
    "intent_summary": {
      "natural_language": "查询北京市直播电商产业规划，涉及岗位需求、教材与专业布点",
      "business_domains_display": ["产业政策", "岗位需求", "专业布点"],
      "identified_constraints": [
        {
          "label": "地区",
          "value": "北京市",
          "confidence": 0.94,
          "source_display": "从问题中识别"
        }
      ],
      "unresolved_terms": ["职业院校"],
      "confidence": 0.86,
      "confidence_level": "high",
      "clarification_suggestions": []
    },
    "sub_query_cards": [
      {
        "query_id": "q_job",
        "display_index": "②",
        "title": "分析北京市直播电商岗位需求",
        "purpose_display": "岗位需求分析",
        "channel_display": "结构化数据",
        "domain_display": "岗位需求",
        "depends_on_display": [],
        "filter_summary": [
          {
            "label": "地区",
            "values": ["北京市"],
            "match_strategy_display": "精确匹配",
            "is_optional": false
          },
          {
            "label": "行业",
            "values": ["直播电商"],
            "match_strategy_display": "精确或语义匹配",
            "is_optional": false
          }
        ],
        "status": "completed",
        "status_display": "已完成",
        "degraded_reasons": [],
        "result_summary": {
          "hit_count": 156,
          "hit_count_display": "156 条记录",
          "duration_ms": 620,
          "duration_display": "620 ms",
          "match_layer_summary": "精确匹配 60% / 归一化 25% / 语义 15%",
          "evidence_strength": "strong",
          "evidence_strength_display": "证据强度：强",
          "warnings": ["行业维度部分走语义匹配"]
        },
        "actions_available": ["view_details", "rerun"]
      }
    ],
    "overall": {
      "total_sub_queries": 5,
      "max_depth": 3,
      "estimated_duration_ms": null,
      "combine_summary": "所有维度均需匹配（AND）"
    }
  }
}
```

**契约要点**：

- **由 orchestrator 生成**：中文映射源（`tag_type` → 中文 label、`domain` → 中文 label、`match_strategy` → 中文短语、`purpose` → 中文短语、`channel` → 中文短语）在后端集中维护，前端零派生。见 `retrieval_plan_console_ux_v1.md §4.3`。
- **依赖表达用自然语言**（v1.3 R3 Q3 决策）：`depends_on_display: ["需要先完成 ① 岗位分析"]`；不画 DAG 拓扑图。
- **binding 反哺显式标签**：`filter_summary[i].is_from_binding=true` + `binding_source_display="来自 ① 岗位分析"`——业务用户看到"来自 ①"而非 `$q_job.output.top_jobs[*].job_title`。
- **状态与 warning 中文化**：`SubQueryStatus` / `degraded_reasons` 有内置中文映射表（与 tag_filter reliability matrix §2 warning code 一一对应）。
- **增量友好**：SSE 事件用 `card_delta` 携带**变化字段**（不全量重发），前端本地维护 `Map<query_id, SubQueryCard>` 应用 delta。见 `retrieval_plan_console_ux_v1.md §5`。
- **兜底**：`friendly_view` 生成失败（例如 orchestrator 崩），前端仍可以从原始 `sub_queries` 派生降级卡片（P2 增强项）。

---

## 6. tag_filter 执行流程与执行器

### 6.1 结构化数据是否需要 vector 存储

**结论：不需要 record-level embedding。**

理由：

1. 结构化 record 的字段本质是**离散业务标签**（岗位名、行业名、城市名、专业名），语义相似度承载在 tag_asset_index 就够。
2. 给整条 record 做 embedding 需要构造"记录语义摘要"，涉及字段拼接、权重、上下文——复杂度高、无明显收益。
3. 正确抽象层次：**字段级 tag + tag_embedding**（存 tag_asset_index），不是 record-level embedding。

**唯一例外**：长文本字段（如"任职要求"长文本）。这类字段应**先切成短语抽取为 tags**，再进 tag_asset_index，不给整段做 embedding。

### 6.2 tag_filter 两阶段执行流程

```
tag_filter = {
  type: "industry",
  tags: ["直播电商"],
  match_strategy: "l1|l1.5|l4",
  semantic_threshold: 0.75,
  limit?: 100
}

Phase A：查 tag_asset_index 得 target_id 集合
  For each candidate in tag_filter.tags:
    L1  精确匹配   WHERE tag_type=T AND tag_value_normalized = normalize(candidate)
    L1.5 归一化匹配 应用内建规则再精确匹配
    L2  别名匹配   查 dim_*_alias 归一到 canonical，再精确匹配（optional）
    L3  编码匹配   candidate 命中字典且有 code → 匹配 standard_code（optional）
    L4  语义匹配   HNSW top-k(tag_embedding, threshold)
  合并结果：
    target_ids = union of all hit rows filtered by (target_type = executor.target_type)
    每行标注 match_layer 供后续证据评级

Phase B：Executor 拿 target_ids 做业务查询
  Structured executor：WHERE record.id IN target_ids  GROUP BY ... ORDER BY ...
  Outline executor    ：WHERE outline_node.id IN target_ids → 反链 chunk
  Chunk executor      ：先按 target_type=normalized_asset_ref 过滤到 ref 集合
                        再对 chunk 做 pgvector 查询（filtered ANN）
```

### 6.3 多 tag_filter 的组合

一个 sub_query 常含多个 tag_filter（region + industry + occupation）。执行策略：

```
每个 tag_filter 各自走 Phase A 得 target_ids 集合
组合方式（由 planner 的 combine 指定）：
  - AND（默认）：target_ids 求交集
  - OR：求并集
  - WEIGHTED：每个集合带权重，按加权分排序
在 SQL 执行前完成集合运算，再进入 Phase B
```

如 tag_filter 声明 `optional=true` 且 Phase A 返回空集，则该 filter 从 combine 中排除，warnings 记录降级。

### 6.4 新增/扩展的 executor

| Executor                             | 输入                                        | 输出                           | 状态                    |
| ------------------------------------ | ------------------------------------------- | ------------------------------ | ----------------------- |
| `TagAssetIndexResolver`              | tag_filters + match_strategy                | target_ids + match_layer 分布  | **v1.3 新增，公共组件** |
| `OutlineNodeRetrievalExecutor`       | 语义查询 + tag_filters                      | 大纲节点集 + 反链 chunk        | v1.1 提出，v1.3 落地    |
| `TaskOutlineRetrievalExecutor`       | tag_filters + 任务类型                      | 任务节点 + 步骤/资源/产物      | P1                      |
| `AbilityGraphExecutor`               | 起点 ability tag                            | `AbilityRelation` 多跳节点与边 | P1                      |
| `JobDemandExecutor`（扩展）          | tag_filters + structured_filters + group_by | 聚合结果                       | v1.3 P0                 |
| `MajorDistributionExecutor`（扩展）  | tag_filters + structured_filters + group_by | 聚合结果                       | v1.3 P0                 |
| `CompetencyAnalysisExecutor`（扩展） | tag_filters + expand=ability_tree           | 能力树                         | v1.3 P0                 |

### 6.5 SQL guardrails 扩展

`retrieval/sql_guardrails.py` 白名单支持：

- `record.id IN (?)`（target_ids 集合注入，参数化）
- `structured_filters` 中的字段白名单精确匹配、范围过滤、`education_level="高职"` 类枚举匹配
- **禁止**：SQL 层向量运算、JSONB 复杂表达式、LLM 生成原始 SQL、跨库 JOIN、DDL/DML

所有语义相似度计算完全发生在 tag_asset_index 阶段，SQL 只做集合过滤和聚合。

### 6.6 DAG orchestrator 执行契约

```
1. plan.sub_queries -> topological sort (respect depends_on)
2. Level 0: 并行执行所有无依赖 sub_query
3. Level k: 等 Level k-1 全部完成 -> 解析 binding_map -> 生成 tag_candidates -> 并行执行
4. 任一节点失败/超时：
   - 有下游依赖：标记下游为 blocked，写 warning
   - 无下游依赖：继续，其他分支不受影响
5. 全部完成后：把每个 sub_query 的 output_binding 汇总到 evidence set
6. 每个 sub_query 完成立即推送 SSE 事件（含 match_layer 分布）
```

- 单 sub_query 超时不阻塞其余分支；`context_pack.warnings` 显式列出降级项。
- `binding_map` 解析失败时（上游返回空、路径不存在），下游查询依然执行但去掉该维度过滤，warnings 记录降级。

---

## 7. AI 治理阶段的产出扩展（合并策略）

### 7.1 关键原则

> **v1.3 不新增独立的"业务标签抽取"子阶段。**分类型结构化 tag 是**现有** AI 治理主 Prompt 一次产出的一部分，与 `classification` / `level` / `quality_summary` / `decision_trail` 走**同一次** LLM 调用、**同一份** `governance_result`、**同一条** `ai_governance_run` 审计记录、**同一处** Console 审核入口（治理中心的"标签审核"页面）。

这一决定确保：

- 契合 CLAUDE.md：AI 治理是 `metadata-service.ai-governance`；不新增平行子服务。
- 契合"规则文件即真源"：分类体系落在 `governance_rules.json.tag_taxonomy`（见 §4.4），不散落在代码或独立 profile 中。
- 消除冗余：无重复 tag 存储、无重复 Prompt profile、无重复审计路径、无重复审核入口。
- 降本：一次 LLM 调用产出多个产物，一处业务规则维护，一处审核 UI。

### 7.2 治理主 Prompt profile 的升级

- 现有治理主 profile（示例命名 `asset_governance_analysis_v{N}`，具体 profile 名以代码库当前实际为准）**版本升级至 `v{N+1}`**（走 v1.0 已有的 profile 版本机制：新版本自动 active、旧版本归档）。
- Output schema 扩展 `tags` 字段：从"扁平字符串数组"升级为 §4.1 分类型结构化对象。
- Prompt 内容扩展：新增"按 `tag_taxonomy.types` 声明的类型分组输出业务标签，每个 tag 附 `confidence` 与 `evidence_span`；抽取不到的类型不输出"。
- Prompt 从规则文件动态读取 `tag_taxonomy.types` 与对应 `classification.tagging_basis`（每类资产的取值参考），保证受控输出。
- **不新增独立 profile**；也不新增独立 LLM 调用。

### 7.3 治理 Prompt 输出对照

**v1.1 曾提议**：

> "分析文档，输出 `industry_code`（对齐 GB/T 4754）、`occupation_code`（对齐 GB/T 6565）..."

**v1.3 修订后（合并方案）**：

> 现有治理 Prompt 之外，扩展 output schema 中的 `tags` 段——按 `tag_taxonomy.types` 声明的 7 类（region / industry / occupation / major / ability / topic / time_range）分组输出，每个标签自然语言 + `confidence` + `evidence_span`；不做编码映射；抽取不到的类型不输出。

同一次 LLM 分析活动本来就要读整个文档做业务判断，附带产出分类型 tags 是自然扩展，不显著增加 token 成本。

### 7.4 治理侧 tag 投影阈值

阈值定义在 `governance_rules.json.tag_taxonomy`（见 §4.4）：`auto_accept_threshold` / `review_threshold`。

投影 job 在治理 job 完成后触发：

```
For each tag in governance_result.tags:
  if tag.confidence >= tag_taxonomy.auto_accept_threshold:
    insert into tag_asset_index (source=governance_tag, target=normalized_asset_ref)
    异步生成 tag_embedding
  elif tag.confidence >= tag_taxonomy.review_threshold:
    stays in governance_result.tags with status=pending_review
    Console "标签审核" 页面自动列入待审队列
  else:
    drop into decision_trail 供追溯，不入索引
```

- 阈值全部由业务专家在 Console 维护 `governance_rules.json.tag_taxonomy` 时修改，符合项目"规则文件即真源"约定。
- 投影 job 与治理 job 是同一 Worker 内串接的两个 stage（`normalize → governance → tag_projection`），失败可独立重试。

---

## 8. Console 标签审核页面升级（沿用现有入口）

### 8.1 入口位置

**沿用**治理中心已有的"标签审核"页面，不新增独立入口。

- 治理中心 → 资产详情 → "标签审核"面板。
- 与 classification / level / quality_summary 的审核**同页展示**，共用同一次治理结果的审计上下文。

### 8.2 面板升级：分类型展示 + 内嵌专家标注

现有"标签审核"页面从"扁平标签列表"升级为"按 `tag_taxonomy.types` 分类展示"，并内嵌专家标注操作：

```
┌───────────────────────────────────────────────────────┐
│ 标签审核  [资产: 《XX 产业发展规划》 v3]              │
│ 治理结果： classification=industry_policy  level=L2   │
├───────────────────────────────────────────────────────┤
│ ▼ 地区                                                │
│   北京市    [AI 0.95] [接受] [编辑] [删除]           │
│ ▼ 行业                                                │
│   直播电商  [AI 0.9]  [接受] [编辑] [删除]           │
│   社交电商  [AI 0.62 待审] [接受] [拒绝] [编辑]       │
│   跨境电商  [专家] [删除]                             │
│ ▼ 职业                                                │
│   直播运营  [AI 0.85] [接受] [编辑] [删除]           │
│ ▼ 专业                                                │
│   (未识别，+ 手动新增)                                │
│ ▼ 主题                                                │
│   数据合规  [AI 0.85] [接受] [编辑] [删除]           │
│                              + 手工新增标签           │
├───────────────────────────────────────────────────────┤
│ 高级：为已有标签补充标准编码（opt-in）                │
│   地区: 北京市    → 标准码: [11 (GB/T 2260)] [保存]  │
│   行业: 直播电商  → 标准码: [未映射] [选择字典]       │
└───────────────────────────────────────────────────────┘
```

### 8.3 行为约定

- 审核动作（接受 / 拒绝 / 编辑 / 删除 / 新增）**统一写入** `governance_result.tags`（同资产同版本的产物），并写 `decision_trail` + `audit_log`。
- 接受高置信度 tag → 触发投影 job（`governance_tag → tag_asset_index`）+ 异步 `tag_embedding` 生成。
- 专家新增 tag → 落入 `governance_result.tags` 且 `source=expert_manual`；投影同上。
- 补 `standard_code` 时提供字典 auto-complete，允许留空；仅补 `tag_asset_index.standard_code` 字段，不影响 tag 本身接受/拒绝状态。
- 支持"批量补 tag"（一次给一批同类资产打统一 topic）。
- 支持"提议 alias"：专家可以给字典建议新增 alias，进入字典维护队列（P1）。

### 8.4 优先级与去重

- 同 `(tag_type, tag_value_normalized, target_type, target_id)` 只保留一条。
- 冲突时优先级：`expert_manual` > `governance_tag` > `outline_projection` > `field_projection` > `dict_alias_hit`。
- 专家标注**不覆盖**已有 AI tag（作为并存 tag），仅通过冲突去重时的优先级体现权威。

### 8.5 约束

- 不引入"审核标准化编码"的强流程；`standard_code` 是纯 opt-in 辅助信息。
- 高敏感资产的专家标注是否需要二次审批（Review Gate），P1 讨论。
- **审核入口只有一个**：治理中心的"标签审核"页面。**不新增**独立"业务标签"面板/独立"专家标注"页面。

---

## 9. evidence_chain 汇总层

### 9.1 汇总模板（复杂场景示例）

```markdown
## 一、规划背景（政策 + 产业）

**结论**：<从 policy/report outline 抽出的核心观点，2-3 条 bullet>

**主要依据**：

- 政策：《XX 规划》第三章第 2 节 —— [大纲节点] / [chunk 来源]
- 行业报告：《XX 白皮书》2025，第 5 章 —— [来源]

## 二、岗位需求分析（结构化）

**结论**：本市 <industry_name> 相关岗位近三年岗位数变化、Top 岗位分布

| 岗位     | 2024 | 2025 | 2026 | 变化率 |
| -------- | ---- | ---- | ---- | ------ |
| 直播运营 | ...  | ...  | ...  | ...    |

**来源**：job_demand_dataset X / Y（sheet / row_range）
**匹配层分布**：L1: 60%, L1.5: 25%, L4: 15%

## 三、能力对齐（岗位 → 能力）

**逻辑**：由岗位 Top-N 映射到职业能力分析中的能力项集合。

**核心能力项**（按需求岗位数加权排序）：

- [能力大类] 数字营销：直播脚本策划、短视频创作、用户运营 …
- [能力大类] 数据分析：GMV 拆解、投放 ROI 分析 …

**来源**：occupational_ability_analysis 资产 X / 能力项 id 列表

## 四、供给侧现状（专业布点）

**结论**：本省当前专业布点分布与规模

| 专业 | 层次 | 2024 | 2025 | 2026 |
| ---- | ---- | ---- | ---- | ---- |

**来源**：major_distribution 数据集 X

## 五、专业建设建议

**逻辑链**：产业需求 → 岗位缺口 → 能力要求 → 现有专业匹配度 → 建议

- 建议保留/加强：<现有专业> —— 支撑 <能力集合>
- 建议新增/调整方向：<方向> —— 缺口能力：<...>
- 课程/教材支撑：<从 course_textbook outline 命中的章节>

## 六、证据链完备性

| 环节     | 证据源     | 完备度 | 证据强度 | 说明                                |
| -------- | ---------- | ------ | -------- | ----------------------------------- |
| 政策依据 | q_policy   | ✅     | 强       | 3 篇 outline 节点命中，主要 L1/L1.5 |
| 产业趋势 | q_industry | ⚠️     | 中       | 仅命中 1 篇；建议补数据             |
| 岗位数据 | q_job      | ✅     | 强       | region L1、industry L4              |
| 能力对齐 | q_ability  | ⚠️     | 中       | 岗位→能力走 L4 语义匹配             |
| 专业布点 | q_major    | ✅     | 强       | region L1、major L1                 |
| 教材支撑 | q_textbook | ⚠️     | 中       | ability→教材走 L4 语义匹配          |

## 七、说明与警告

- 中等证据强度环节：q_ability / q_textbook（主要走语义匹配）
- 未命中：<...>
- 结论中含推理性内容，需业务专家复核。
```

### 9.2 汇总边界

- 每节结论**必须**回引至少一个 sub_query 的 `output_binding` 或 `source_refs`。
- **断链节点必须显式提示**（未命中 tag、fallback、超时降级）。
- **推理性结论**必须打 `"reasoning": true` 标记，Markdown 视觉区分。
- LLM 不得引入检索结果之外的事实。
- 汇总 Prompt 走 `ai_prompt_profile.evidence_chain_summary_v1_3`，输出走 schema 校验（至少校验 source_ref 引用完整性）。

### 9.3 `context_pack` 扩展

v1.0 §5 `context_pack` 增加：

```json
{
  "tag_resolution": {
    "resolved": {
      "regions": [
        {
          "value": "北京市",
          "match_layers": ["L1", "L1.5"],
          "target_count": 42,
          "sources_hit": ["job_demand_record", "major_distribution_record"]
        }
      ],
      "industries": [
        {
          "value": "直播电商",
          "match_layers": ["L1", "L4"],
          "target_count": 18,
          "l4_semantic_neighbors": ["社交电商", "跨境电商"]
        }
      ]
    },
    "unresolved_terms": ["职业院校"]
  },
  "dag_execution_trace": [
    {
      "level": 0,
      "sub_query_ids": ["q_policy", "q_industry", "q_job", "q_major"],
      "started_at": "...",
      "finished_at": "..."
    },
    {
      "level": 1,
      "sub_query_ids": ["q_ability"],
      "resolved_bindings": { "occupation_tags": ["直播运营", "短视频运营"] }
    },
    {
      "level": 2,
      "sub_query_ids": ["q_textbook"],
      "resolved_bindings": { "ability_tags": ["GMV 拆解", "投放 ROI 分析"] }
    }
  ],
  "evidence_chain_report": {
    "sections": [
      {
        "name": "policy_background",
        "completeness": "ok",
        "evidence_strength": "strong",
        "match_layer_distribution": { "L1": 0.6, "L1.5": 0.3, "L4": 0.1 }
      },
      {
        "name": "ability_alignment",
        "completeness": "degraded",
        "evidence_strength": "medium",
        "reason": "occupation matching uses L4 semantic"
      }
    ]
  }
}
```

---

## 10. Console 展示层增量（v1.3 R3-c：三区 → 单一对话流）

**R3-c 变更**：v1.3 R1 曾采用"对话主区 / 执行步骤区 / 辅助分析区"三区结构；R3-b 曾调整为"主对话区 + 辅助分析抽屉"二区；R3-c 最终决策为**单一对话流**——取消所有独立区/抽屉/侧栏，所有内容一律呈现在一个滚动区内按时间顺序排列；工程/审计细节按需通过卡片内嵌 `<InlineDetailsCollapse>` 展开。理由：抽屉/侧栏依然构成"再一层分区"的认知负担，业务用户希望和 ChatGPT 类对话界面一致的单栏体验；工程细节按需展开即可，无需常驻。

完整设计与渲染细节见独立文档 `docs/retrieval_plan_console_ux_v1.md`；本节仅冻结骨架契约。

### 10.1 单一对话流结构

| 层次                 | 内容                                                                                                                                              | 目标用户                                |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------- |
| **对话流（唯一区）** | 用户问题 → 意图卡（`friendly_view.intent_summary`）→ 执行步骤卡片列表（`friendly_view.sub_query_cards`）→ Markdown 汇总 → trace footer → 追加问题 | 业务用户为主；工程/审计按需 inline 展开 |

**呈现规则**（详见 `retrieval_plan_console_ux_v1.md §6`）：

- **意图卡**：展示 `natural_language`（一句话陈述）+ `identified_constraints`（约束 chip）+ `unresolved_terms`（灰色标签）+ `confidence_level` 徽章；卡片底部提供"展开详情"折叠区（inline）→ 显示原始 intent JSON。
- **执行步骤卡片列表**：每 sub_query 一张卡；标题 + 数据来源（`domain_display`）+ 过滤条件（`filter_summary`，中文自然语言）+ 依赖描述（`depends_on_display`，如"需要先完成 ② 岗位分析"）+ 状态徽章 + 完成后附结果摘要（命中数、耗时、`match_layer_summary` 中文百分比、`evidence_strength_display`、warnings）；卡片底部提供"展开详情"折叠区（inline）→ 显示该 sub_query 的 source_refs、匹配层分布小图、warnings 详情、原始 sub_query JSON。
- **依赖表达**（v1.3 R3 Q3 决策）：用自然语言"需要先完成 ② 岗位分析"表达，**不画 DAG 图**；binding 反哺用"来自 ② 岗位分析"标签替代 `$q_job.output.top_jobs[*].job_title`。
- **匹配层去 code**：`L1 60% / L1.5 25% / L4 15%` 展示为 `精确匹配 60% / 归一化 25% / 语义 15%`。
- **Markdown 汇总**：evidence_chain 分节；每节顶部展示"证据强度徽章"（强/中/弱）；悬停结论高亮对应 source_refs。
- **Trace footer**：Markdown 汇总下方一个 8-10px 灰色小 footer 展示 `trace_id`；工程/审计需要时可复制，业务用户可忽略。

**关键 UX 原则**（R3-c）：

- **零抽屉、零侧栏、零 modal**——所有工程/审计细节走卡片自身的 `<InlineDetailsCollapse>` 内嵌折叠区；展开时在卡片自身高度内完成，不推动下方卡片布局跳动。
- 追加问题在同一对话流内延续；前一轮的意图卡/步骤卡默认折叠为一行摘要（可点击展开）。

### 10.2 SSE 事件类型契约

后端 `orchestrator.emit_events()` 按检索流生命周期推送，每事件带 `event_seq`（严格递增）以支持断连重连增量拉取。前端订阅 `EventSource`，断连自动 fallback 到轮询 `RetrievalContextPack`。

```json
{"event_seq": 1, "event": "intent_started"}
{"event_seq": 2, "event": "intent_recognized",
 "friendly_view": {"intent_summary": {...}}}
{"event_seq": 3, "event": "plan_started"}
{"event_seq": 4, "event": "plan_generated",
 "friendly_view": {"intent_summary": {...},
                   "sub_query_cards": [...全量, 均 pending...],
                   "overall": {...}}}
{"event_seq": 5, "event": "sub_query_updated",
 "query_id": "q_policy",
 "card_delta": {"status": "running"}}
{"event_seq": 6, "event": "sub_query_updated",
 "query_id": "q_policy",
 "card_delta": {"status": "completed", "result_summary": {...}}}
{"event_seq": 7, "event": "sub_query_updated",
 "query_id": "q_ability",
 "card_delta": {"status": "degraded",
                "degraded_reasons": ["optional_filter_skipped"]}}
{"event_seq": 8, "event": "summary_ready",
 "markdown": "...", "source_refs": [...]}
{"event_seq": 9, "event": "done"}
```

**契约要点**：

- **增量友好**：`card_delta` 只带**变化字段**；前端本地维护 `Map<query_id, SubQueryCard>` 应用 delta，不重发全量。
- **可重连**：后端保留最近 300 秒事件缓存；断连重连时前端携 `Last-Event-ID: <event_seq>` 补发。
- **超缓存窗口 → 轮询兜底**：前端切换到定期轮询 `RetrievalContextPack`，用户无感切换。
- **兜底渲染**：`friendly_view` 生成失败时前端从原始 `sub_queries` 派生简化卡片（P2 增强项）。

---

## 11. 合规与审计（对齐 CLAUDE.md 红线）

v1.0 §10 权限阶段暂不启用，但审计红线仍必须遵守。v1.3 P0 **必须**关闭以下差距：

1. **三次检索 LLM 调用全部走 `ai_prompt_profile`**：
   - `intent_recognition_v1_3`
   - `retrieval_plan_generator_v1_3`
   - `evidence_chain_summary_v1_3`
   - 版本变更走 v1.0 已有的 profile 版本机制（新增即 active，旧版本归档）。
2. **每次 LLM 调用写 `ai_governance_run`**：`input_hash`、`output_schema_valid`、`adoption_status`；注入的字典摘要计入 `evidence_refs`。
3. **业务 tag 抽取沿用现有 AI 治理主 profile**（版本升级至 `v{N+1}`，见 §7.2），**不新增独立 profile**；治理产物（含分类型 tags）与该次治理调用共享同一条 `ai_governance_run` 记录；tag_asset_index 行的 `extraction_run_id` 关联至该记录。
4. **`SearchQueryExecuted` 审计事件字段扩容**：
   - 保留 v1.0：`query_hash`、`hit_normalized_refs`、`hit_chunk_ids`、`source_locators`、`caller`、`trace_id`。
   - 新增：`hit_tag_asset_index_ids`、`hit_outline_node_ids`、`match_layer_distribution`、`dag_depth`、`degraded_sub_queries`。
5. 日志不得记录用户问题原文、LLM 答案全文、Prompt 内部信息（v1.0 已有约束继续沿用）。

---

## 12. 分阶段落地路线

### 12.1 v1.3-P0（最小可靠闭环）

**目标**：跨资产复杂场景**不依赖字典和 AI 编码回填**的情况下可跑通。

范围：

1. **数据层**：
   - `governance_rules.json` schema 升级至 `3.0`：新增顶层 `tag_taxonomy` 段（§4.4）；保留现有 classifications / levels / quality_scoring。
   - `governance_result.tags` schema 升级为 §4.1 分类型结构化契约。
   - 现有 AI 治理主 `ai_prompt_profile` 版本升级（§7.2），output schema 扩展 tags；**不新增**独立的 tag 抽取 profile。
   - **老数据一次性迁移 job**：把老 `governance_result.tags`（扁平字符串数组）尝试归类到 `tag_taxonomy.types`（能匹配到 canonical 的入对应类型，无法归类的暂入 `topics`），迁移日志入 `audit_log`；未归类项进入 Console"标签审核"待审队列。
   - `knowledge_outline_node.tags` JSONB 列增列。
   - **不改动**结构化领域表（保留原字段）。
2. **索引层**：
   - `tag_asset_index` 表上线（含 `tag_embedding` HNSW）。
   - **投影 hook 上线**：Pipeline B writer 完成后触发字段投影；outline_node 生成时触发；消费 `nexus_app/ai_governance/projection_config.py::PROJECTION_WHITELIST_V1_3`（§2.4 表格所示白名单）。
   - 治理 tag 投影 job（`governance_tag → tag_asset_index`）。
   - `outline_node_embedding_pgvector`（承接 v1.1 P0）。
3. **匹配层**：
   - L1 + L1.5（内建归一化规则）+ L4（tag_embedding HNSW）**三层 mandatory**。
   - L2/L3 保留 stub，字典空时自动跳过。
   - `TagAssetIndexResolver` 公共组件。
   - **`tag_type=ability` 强制 rerank**（§3.3）——因为三方 ability 表内部编号无共享词汇，跨资产 ability 联结只能走 L4，rerank 是唯一质量兜底。
4. **编排层**：
   - `RetrievalIntent.cross_asset_tags` 自然语言 tag 契约。
   - `RetrievalPlan.tag_filters + match_strategy + combine + structured_filters`。
   - DAG orchestrator + tag_signature binding_map。
5. **执行层**：
   - Structured executor 支持"Phase A 查 index + Phase B SQL IN"两阶段。
   - Unstructured executor 支持多粒度索引选择 + tag 预过滤。
   - `sql_guardrails.py` 白名单支持 `IN (?)` 集合注入。
6. **合规**：v1.3 §11 全部落地；`SearchQueryExecuted` 扩容。

验收：

- 字典完全空 + 治理 tag 覆盖率 ≥ 50% 时，复杂场景（"北京市 直播电商 → 电子商务专业建设建议"）端到端可跑通 evidence_chain。
- match_layer 分布可观测（L1 / L1.5 / L4 各占比）。
- 结构化 executor 语义匹配可用（`industry=直播电商` 能命中 `industry_name=互联网信息服务` 的相关 record）。
- 三次检索 LLM 调用有 `ai_governance_run` 记录，Prompt profile 可审计。

### 12.2 v1.3-P1（体验与精度）

范围：

1. **Console 治理中心"标签审核"页面升级**（§8）：分类型展示、内嵌专家标注、内嵌 opt-in 编码补充。**不新建独立入口**。
2. **evidence_chain 完整落地**：证据强度评级 + 推理性结论标签。
3. **DAG 可视化 + tag 命中路径可视化**（§10.3）。
4. **SSE 事件流**（§10.5）。
5. **通用 rerank adapter**：cross-encoder 或 LLM re-scoring 用于其他 tag_type 的 L4 结果精修。（`tag_type=ability` 的 rerank 已在 P0，见 §3.3 / §12.1）
6. **`TaskOutlineRetrievalExecutor` / `AbilityGraphExecutor`** 上线（承接 v1.1 P1）。
7. **`ability_item_embedding_pgvector`** 上线。

### 12.3 v1.3-P2（字典完善与自愈）

范围：

1. **字典 alias 表 Console 维护 UI**（`dim_*_alias`）。
2. **未命中 tag 高频榜** 驱动字典扩展；专家可基于此建议新增 alias。
3. **投影 lag 监控**（`index_manifest` 扩展新 backend）。
4. **golden set** 与匹配层命中率评测（意图识别、tag 识别 F1、DAG 合理性、evidence_chain 完备率、SQL 正确率）。
5. **pgvector 容量/并发/filtered ANN 评测**（承接 v1.0 §11 阶段四）。

### 12.4 v1.4（权限/治理过滤，承接 v1.0 §11 阶段五）

- 大纲/tag/结构化字段的权限过滤在 `tag_asset_index` 层预置 `access_scope`。
- L3/L4 masking 覆盖到 tag、outline_node、chunk、结构化 record。
- filtered ANN 召回率评测。

---

## 13. v1.1 契约变更清单（v1.3 需要覆盖回写）

| v1.1 位置                       | v1.3 变更                                                                                                                                                                                                                                                                                                     |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| §3.1 六维度字典表               | 精简为 canonical + alias；不设强 FK；`dim_time_bucket` / `dim_region` 由平台预置，其他允许空                                                                                                                                                                                                                  |
| §3.2 桥字段回填                 | 移除 `normalized_asset_ref.dimension_refs` 复杂 JSONB；结构化领域表**不新增** code 列                                                                                                                                                                                                                         |
| §3.3 索引策略                   | 保留 `outline_node_embedding_pgvector`；新增 `tag_asset_index`（v1.3 §2）                                                                                                                                                                                                                                     |
| §4.1 多粒度 embedding           | 保留                                                                                                                                                                                                                                                                                                          |
| §4.2 反查索引 `tag_asset_index` | 升级为 v1.3 §2 多态倒排枢纽（含 `tag_embedding` + 多态 target）                                                                                                                                                                                                                                               |
| §5 意图识别                     | `cross_asset_dimensions` → `cross_asset_tags`；不要求 LLM 输出 code                                                                                                                                                                                                                                           |
| §6 检索计划                     | `filters` → `tag_filters`（含 `match_strategy` 层级组合）+ `structured_filters` 并存；`binding_map` 传自然语言                                                                                                                                                                                                |
| §7 执行层                       | 新增 `TagAssetIndexResolver` 公共组件；executor 采用 Phase A + Phase B 两阶段；SQL guardrails 只支持 `IN` 集合注入                                                                                                                                                                                            |
| §8 evidence_chain               | 汇总模板增加"匹配层分布 / 证据强度"评级                                                                                                                                                                                                                                                                       |
| §9 Console                      | 增加"tag 约束卡片 / tag 命中路径 / 证据强度徽章 / SSE 扩展事件"                                                                                                                                                                                                                                               |
| §10 合规                        | 三个检索 profile 命名统一为 `*_v1_3`；**业务 tag 抽取沿用现有 AI 治理主 profile**（版本升级 v{N+1}），不新增独立 profile                                                                                                                                                                                      |
| §11 分阶段                      | 落地路线以 v1.3 §12 为准                                                                                                                                                                                                                                                                                      |
| §2.4 投影规则                   | v1.3 修订 R2 全面重写：从"字段全放"改为"仅投影跨资产检索维度"；`item_type='professional_skill'` 白名单；能力表用 `ability_content` / `text`；内部编号列（`ability_code` 等）永远 local_only；长文本字段进 chunk；初始白名单常量位于 `nexus_app/ai_governance/projection_config.py::PROJECTION_WHITELIST_V1_3` |
| §3.3 L4 语义                    | v1.3 修订 R2：`tag_type=ability` 强制 rerank 从 P1 前置到 P0，因为三方 ability 编号无跨资产语义，语义匹配是唯一路径                                                                                                                                                                                           |
| §4.3 字典表                     | v1.3 修订 R2：`dim_ability` 降级为纯"术语参考表"，明确 L2/L3 在 ability 类型上事实无效                                                                                                                                                                                                                        |
| §7.2 tagging prompt v2          | v1.3 修订 R2：加入"主体范围 vs 举例范围"区分要求（regions / industries / occupations / majors 四类）；`evidence_span` 需佐证主体身份；宁少勿滥                                                                                                                                                                |
| §2.4 投影规则（region_scope）   | v1.3 修订 R3：`major_distribution_record.region_scope` 存储的是"国家/省/市 范围粒度"操作性标签，无跨资产语义；从 `field_projections` 移出，归入 `local_only_filters`；`province_name` 是唯一权威 region 值                                                                                                    |
| §5.5 friendly_view              | v1.3 修订 R3（新增契约）：`RetrievalPlan.friendly_view` 骨架冻结；orchestrator 生成中文卡片契约（意图卡 + sub_query_cards + overall），前端零派生；`depends_on_display` 用自然语言表达，不画 DAG 图；完整设计见 `docs/retrieval_plan_console_ux_v1.md`                                                        |
| §10 Console 展示层              | v1.3 修订 R3-c：Console 从三区改为**单一对话流**（取消 R3-b 的辅助分析抽屉方案）；执行步骤内嵌为对话流时间线卡片；工程/审计细节按需通过卡片 `<InlineDetailsCollapse>` 展开；`match_layer` code 全部中文化                                                                                                     |
| §16.7 tag_filter 稳定性         | v1.3 修订 R3：新增 `docs/tag_filter_reliability_matrix_v1.md` 作为 M-B 前置设计——12 步链路现状 + 每步失败模式与兜底 + 12 条跨步不变量 + 12 个 P0 PR 清单 + 5 sprint 落地节奏；关键不变量 I-1 归一化函数唯一真源 / I-2 tag_type code 单一真源                                                                  |

---

## 14. 待确认问题

1. **`tag_embedding` 模型选型**（`bge-small-zh-v1.5` vs `m3e-small`）与维度（512 vs 768）—— P0 前敲定。
2. **投影 hook 实现方式**：SQLAlchemy after_flush event、writer 内嵌调用、还是独立 job worker 消费？P0 前决定。
3. **`tag_taxonomy.auto_accept_threshold` / `review_threshold`** 初始值（默认 0.75 / 0.55）是否按资产类别（classification）进一步差异化？还是全局固定？
4. **L4 语义 top_k 与 threshold 默认值**（top_k=20, threshold=0.75 起步）是否按 tag_type 差异化？
5. **专家人工标注是否需要 Review Gate**（高敏感资产二次审批）？
6. **`tag_asset_index` 失效清理策略**：asset_version_id 变更时同步删除 vs 异步清理，是否需要"版本切换事务"约定？
7. **combine 策略**默认 AND，是否需要 planner 按 `question_type` 自动选择（例如 comparison 用 OR）？
8. **DAG 最大深度默认 3、最大 sub_query 数默认 8**，是否需要按 caller 差异化？
9. **rerank 层的引入时机**：P1 是否需要引入商用 rerank API（cross-encoder），还是先用 LLM re-scoring 兜底？
10. **`dim_region` / `dim_time_bucket` 预置数据源**：是否由平台仓库直接维护（Alembic seed）还是独立数据初始化包？
11. **`governance_rules.json` schema 升级至 `3.0`**：新增 `tag_taxonomy` 段是否作为一次独立的 schema bump 上线（走已有 ETag + fcntl 保护），还是与老 tags 迁移 job 打包为同一次上线？
12. **现有 AI 治理主 profile 的确切名称与当前版本号**：需在 P0 前确认（`nexus-app` 侧代码库检查 `ai_prompt_profile` 表记录），并明确 `v{N+1}` 版本的兼容读写策略。
13. **老数据（扁平字符串 tags）迁移策略**：**已定（v1.3 修订 R2）**——不做翻译式迁移，改走 `recompute_tagging_only` 窄口径重跑（详见 §16.4）。
14. **v1.3 修订 R2 落地节奏**：`projection_config.py` 常量已就位（v0.1），迁移到 `governance_rules.json.tag_taxonomy.projection_whitelist` 是否等 M-B 投影 hook 实施时一并做，还是提前独立上线？
15. **`item_type` 白名单演进策略**：v1.3 修订 R2 仅 `professional_skill` 投影；未来若 `professional_literacy`（素养）也希望作为 topic 参与检索，是否引入"conditional_projections 增补"审议流程？
16. **主体范围识别效果监控**：Prompt 靠 LLM 自判主体/举例；上线后需要抽样评测（人工标注 ≥ 30 条各 classification）估算误判率，是否作为 A4 golden set 的必测项？
17. **rerank 提前实施位置**：`tag_type=ability` 强制 rerank 已从 P1 移到 P0；具体 rerank 服务是走 LiteLLM re-scoring（低成本、通用）还是引入独立 cross-encoder（高质量、需部署）？P0 前敲定。

---

## 15. v1.3 结论

v1.3 是**方案落地性的质变**，通过五个决定性设计选择让复杂跨资产检索可靠可落地：

1. **`tag_asset_index` 是语义倒排枢纽**（多态外键覆盖结构化 record、outline_node、asset_ref），把语义能力集中在一处。
2. **结构化数据不做 record-level embedding**，字段直接投影为 tag，SQL 只做集合过滤和聚合，简单可审计。
3. **六层匹配降级链的主战场是 L1 + L1.5 + L4**，不依赖字典与治理编码，字典空时方案仍可用。
4. **业务标签抽取合并到现有 AI 治理阶段一次产出**，不新增独立 Prompt profile、独立审计路径或独立审核入口；标签分类体系归入 `governance_rules.json.tag_taxonomy`，作为业务规则的一部分。
5. **治理阶段不做编码映射**；Console 治理中心的"标签审核"页面升级为分类型展示 + 内嵌专家标注，opt-in 补充标准编码。人工审核负担从"分类学"回归"业务判断"。

v1.3 **保留 v1.0 全部编排骨架、v1.1 全部 DAG 与 evidence_chain 思路、v1.0 §10 全部合规红线**，仅在桥接机制上做质变。工程改动集中在：新增 `tag_asset_index` 与投影 hook、升级现有治理主 Prompt profile 一次产出分类型 tags、意图/计划 schema 微调、结构化 executor 两阶段执行流程、三个检索 `ai_prompt_profile` 上线、Console 治理中心标签审核页面升级。落地风险显著低于 v1.1。

方案对字典完备度与治理侧 AI 精度的敏感性大幅降低，字典可增量扩展、alias 可回补、专家标注可渐进积累——**系统随时间自我完善**，而不是上线时一次性完美。

---

## 16. v1.3 修订说明（2026-07-09）

### 16.1 修订触发

v1.3 首版（同日早些时候）在 §7 提议独立 `governance_tag_extract_v1_3` Prompt profile 与独立"业务标签"专家标注面板（§8）。审阅时发现与 NEXUS 现有 AI 治理阶段（`metadata-service.ai-governance`）产生功能重叠与架构冗余：

- 治理阶段本身已产出 `governance_result.tags`（原扁平字符串数组）与 `classification` / `level` / `quality_summary`。
- Console 治理中心已有"标签审核"页面。
- 独立 Prompt profile 会导致：两次 LLM 调用（成本↑）、两处 tag 存储（真源分裂）、两个 profile 维护（审计路径分裂）、两个审核入口（用户体验割裂）。
- 违反 CLAUDE.md 两条约定：AI 治理不应有平行子服务；业务规则应在 `governance_rules.json` 中定义。

### 16.2 修订要点

| 位置                   | 修订前                                    | 修订后                                                                                                                                                                                                                                                    |
| ---------------------- | ----------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| §1.3 核心命题          | 4 项，第 4 项"治理阶段只抽 tag"           | 5 项，新增第 4 项"业务标签由现有治理阶段一次产出"、第 5 项"分类体系归入 `governance_rules.json.tag_taxonomy`"                                                                                                                                             |
| §2.3 数据来源分层 C 行 | 简单描述"治理 job 完成时"                 | 明确"由现有治理主 Prompt 一次产出"                                                                                                                                                                                                                        |
| §4.1 tag 契约关键点    | "Prompt 走 `governance_tag_extract_v1_3`" | "由现有 AI 治理主 Prompt 一次产出（升级 output schema），同一次 LLM 调用产 classification / level / tags / quality_summary"                                                                                                                               |
| §4.4（新增）           | —                                         | 定义 `governance_rules.json.tag_taxonomy` 顶层段结构                                                                                                                                                                                                      |
| §4.5 移除的 v1.1 设计  | —                                         | 追加"独立的 `governance_tag_extract_v1_3` Prompt profile"                                                                                                                                                                                                 |
| §7 治理阶段简化        | 独立 profile + 独立调用                   | 现有治理主 profile 版本升级 `v{N+1}`，output schema 扩展 tags；不新增独立 profile                                                                                                                                                                         |
| §7.4 阈值              | 代码硬编码                                | 迁移至 `governance_rules.json.tag_taxonomy`                                                                                                                                                                                                               |
| §8 Console 面板        | 独立"业务标签"面板                        | 沿用治理中心"标签审核"页面，分类型展示 + 内嵌专家标注                                                                                                                                                                                                     |
| §11 合规第 3 点        | 独立 profile 审计                         | 沿用治理主 profile 的 `ai_governance_run` 记录                                                                                                                                                                                                            |
| §12.1 P0 数据层        | 新增独立 profile                          | 升级 `governance_rules.json` 至 3.0、升级 `governance_prompt_template` task_type='tagging' 至 template_version=2、用 `recompute.recompute_tagging_only` 重跑老 result（不做翻译式迁移）                                                                   |
| §16.4 老数据迁移策略   | 翻译式迁移 + `legacy_dimension_map` 归类  | 放弃翻译式迁移；`tag_taxonomy` 移除 `legacy_dimension_map` 字段；改走 `recompute.enumerate_tagging_recompute_targets` + `plan_tagging_recompute` 窄口径重跑（仅 tagging task_type，classification/level/quality/knowledge_type 不动，chunk/index 零级联） |
| §12.2 P1 Console       | "专家标注面板"                            | "治理中心标签审核页面升级"，明确不新建独立入口                                                                                                                                                                                                            |
| §13 变更清单 §10       | 独立 profile                              | 沿用治理主 profile 版本升级                                                                                                                                                                                                                               |
| §14 待确认问题         | 10 条                                     | 追加第 11-13 条：schema bump 时机、治理 profile 名称版本、老数据迁移策略                                                                                                                                                                                  |
| §15 结论               | 4 项决定性选择                            | 5 项决定性选择                                                                                                                                                                                                                                            |

### 16.3 未变更的核心内容

- `tag_asset_index` 表结构、投影规则、失效机制（§2）
- 六层匹配降级链（§3）
- 结构化数据不做 record-level embedding（§6.1）
- tag_filter 两阶段执行（§6.2）
- DAG 编排、意图/计划 schema、evidence_chain 汇总（§5、§9）
- 三个检索 LLM `ai_prompt_profile`（intent / plan / summary）、`SearchQueryExecuted` 审计（§11）
- 分阶段落地路线的整体骨架（§12）

### 16.4 老数据迁移策略（v1.3 修订）

**方案变更**：v1.3 首版曾提出"扁平 tags → 分类型 tags 的翻译式迁移"（依赖 `legacy_dimension_map` 归类）。审阅后判定该方案存在三个根本问题：老 `governance_result.tags` 已打平为 `list[str]` 维度信息丢失；`professional_domain` 值归 industry 还是 major 存在语义歧义仍需人工判断；将一次性迁移映射写入长期契约 `tag_taxonomy` 造成职责耦合。**修订后放弃翻译式迁移**，改走"重跑治理但只跑 tagging task_type"路径。

**实证依据**：全库 grep 确认 `governance_result.tags` **未被** 任何下游知识加工阶段（`knowledge/`、`index/`、chunk emission、index_manifest）消费；`tags` 目前仅作治理产物储存，供 v1.3 检索侧的 `tag_asset_index` 投影使用。因此重跑 tagging 不会级联到 chunk / index / 状态机变更。

**执行路径**（`nexus_app.governance.recompute`）：

1. **枚举**：`enumerate_tagging_recompute_targets(current_schema_version="3.0")` 找出 `rules_schema_version != "3.0"` 的 GovernanceResult。开发阶段 `include_available=True`；生产 `include_available=False`（保留"published content 需 operator 审批"约定）。
2. **计划**：`plan_tagging_recompute(...)` 返回 dry-run 报告（review_required / available / other 数量分布），零副作用（不 flip 状态、不写审计）。
3. **执行**（A3 完成 tagging profile 升级后接线）：对每个 target 只调用 `governance_prompt_template` 中 `task_type='tagging'` 的最新 template_version（升级后为 v2 输出分类型结构），生成新 `ai_governance_run`（task_type=tagging），仅更新对应 `governance_result.tags` 与 `rules_schema_version` / `rules_version_id`；**不动** classification / level / index_admission / quality_summary / status。
4. **投影**：新 tags 写入 `governance_result` 后自动触发 `governance_tag → tag_asset_index` 投影 hook（Milestone B 交付）。
5. **审计**：每次 tagging 重跑写一条 `ai_governance_run` + 一条 `SearchQueryExecuted` 无关的独立审计事件（复用现有 audit 通道）。

**低置信度 tag**：仍按 `governance_rules.json.tag_taxonomy.review_threshold` 进队；Console 治理中心"标签审核"页面消费待审队列（§8）。**未识别**的旧 tag 值（新 profile 输出为空）**不做兜底归类**；对应 asset 在 tag_asset_index 中该类型无 governance_tag 来源，但 field_projection / outline_projection / L5 chunk 兜底仍保证检索不断链。

### 16.5 迁移风险与缓解

- **风险**：tagging profile v2 upgrade 后，output schema 校验大面积失败。
- **缓解**：v2 上线前跑 100 条样本回归（覆盖每个 classification）；期间保留 v1 作为 fallback profile；单次调用 schema 校验失败时 result.tags **不更新**（保留老值）并写 warnings。
- **风险**：审核队列积压。
- **缓解**：待审队列**不阻塞**检索（低置信度 tag 仍参与 tag_asset_index，evidence_chain 显式提示"未评审"）；分批调度重跑，节奏可按 classification / creator 维度控制。
- **风险**：`AVAILABLE` 状态 asset 在开发阶段重跑后，若 tagging 输出与老 tags 语义大变，用户展示层可能困惑。
- **缓解**：开发阶段默认 `include_available=True`；生产阶段翻转为 `False`，需 operator 显式触发。
- **风险**：某些老 asset 的 `ai_run_id` 为空（历史遗留），无法从 ai_output 反查原始输入。
- **缓解**：不影响新方案（新 tagging 重跑直接以 `normalized_document/record` 为输入，不依赖老 ai_output）。

### 16.6 v1.3 修订 R2（2026-07-10）：投影白名单 + 主体范围

**触发**：项目落地过程中业务方 review 发现 v1.3 §2.4 投影规则与 §7.2 tagging prompt v2 存在四类漏洞：

1. `job_demand_requirement_item.item_type` 是**固定枚举**，非每种都值得跨资产投影（v1.3 R1 假设是自由文本，误把关键词当分类特征）。
2. 三方 ability 表（`occupational_ability_item` / `job_demand_requirement_item` / `major_profile_ability`）内部编号（`ability_code` / `taxonomy_code` / 序号）**无跨资产语义**——v1.3 R1 曾按"code 桥接"处理，实际必须走 text 语义匹配。
3. 结构化 record 投影时**未区分"检索侧过滤维度" vs "本地字段"**，导致 tag_asset_index 主题桶会被 `required_education` / `salary_range` 等本地字段冲垮。
4. 文档中的 `regions` 有两种角色（主体 vs 举例），tagging prompt v2 R1 版本未做区分——会导致大量误召回（用户查"浙江直播电商"命中一份仅举例浙江的山东报告）。

**R2 变更要点**：

| 位置                   | 变更                                                                                                                                                                                                                                                                                                 |
| ---------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| §2.4 投影规则          | 全面重写：白名单驱动、item_type 仅 `professional_skill` 投影为 ability+topic、三方 ability 表内部编号列 local_only、长文本进 chunk；初始白名单 v0.1 落 `nexus_app/ai_governance/projection_config.py::PROJECTION_WHITELIST_V1_3`，未来迁至 `governance_rules.json.tag_taxonomy.projection_whitelist` |
| §3.3 L4 语义           | `tag_type=ability` 强制 rerank 从 P1 前置到 P0（三方 ability 无跨资产共享词汇，L4 是唯一路径）                                                                                                                                                                                                       |
| §4.3 字典表            | `dim_ability` 降级为"术语参考表"；明确 L2/L3 在 ability 上事实无效                                                                                                                                                                                                                                   |
| §7.2 tagging prompt v2 | 加入"主体范围 vs 举例范围"区分要求；`evidence_span` 需佐证主体身份；宁少勿滥；`change_summary` 同步更新                                                                                                                                                                                              |
| §12.1 P0 数据层        | 投影 hook 消费 `PROJECTION_WHITELIST_V1_3`；ability 强制 rerank 纳入 P0 匹配层                                                                                                                                                                                                                       |
| §12.2 P1               | 通用 rerank adapter 保留 P1；ability rerank 已移 P0                                                                                                                                                                                                                                                  |
| §14 待确认             | 新增 3 条（R2 落地节奏、item_type 白名单演进、主体范围识别监控、rerank 服务选型）                                                                                                                                                                                                                    |

**代码交付**（本轮已完成，未上线）：

- `nexus_app/ai_governance/projection_config.py`：`PROJECTION_WHITELIST_V1_3` v0.1 常量 + 读取 helper
- `nexus_app/ai_governance/default_prompts.py::_TAGGING_PROMPT_V2`：加入主体 vs 举例指令
- `V1_3_PROMPT_UPGRADES["tagging"]["change_summary"]`：同步更新
- 测试：`tests/ai_governance/test_projection_config.py`（18 项静态守卫）+ `tests/ai_governance/test_tagging_prompt_v2.py` 新增 2 项守卫

**Alembic 影响**：本轮**未新增迁移**——`_TAGGING_PROMPT_V2` 是常量层修改，走已存在的 0069 迁移（0069 seed 时会自动携带 R2 版本内容）。若 0069 已 apply 到 CI DB，需要一个后续迁移（0070）把 prompt_template 更新到 R2 版本；若尚未 apply，直接跑 0069 即可。

**风险与缓解**：

- **风险**：LLM 判断主体 vs 举例的准确率不确定，可能过度过滤导致真主体也漏输出。
- **缓解**：Prompt 明确"宁少勿滥"，可 evidence_chain 层显式提示"主体范围识别置信度低"；A4 golden set 中人工标注 30+ 条主体/举例对照用例作为精度基线。
- **风险**：`projection_config.py` 与 `governance_rules.json` 未来合并时可能引入 schema 二次冲突。
- **缓解**：常量结构与规划的 JSON 段结构一一对应；迁移时通过一个转换脚本自动同步，不需要手工重写。

### 16.7 v1.3 修订 R3（2026-07-10）：region_scope 快修 + tag_filter 稳定性 + friendly_view 单一对话流

**R3 迭代记录**：R3 分三个子轮次收敛（同一天迭代）：R3-a（region_scope 快修 + tag_filter reliability matrix）→ R3-b（friendly_view 契约 + 二区结构初版）→ R3-c（业务反馈"别分割那么多区"→ 改为**单一对话流**，取消辅助分析抽屉）。本节以最终 R3-c 状态为准。

**触发**：项目落地过程中三个方向的深化：

1. `major_distribution_record.region_scope` 实际存储的是"国家 / 省 / 市"范围粒度（操作性桶值），不是真实地理值，v1.3 R2 把它作为 `region` tag 投影会污染跨资产 region 桶。
2. tag_filter 全链路 12 步中 9 步完全未实施；小步实施前必须一次性铺开衔接点、失败模式、跨步不变量与 P0 补丁清单，避免反复反悔。
3. Console 需要向业务用户呈现友好可读的执行计划（原始 JSON 不可读）；R1 的三区结构分割过细，业务用户注意力被切碎。

**R3 变更要点**：

| 位置          | 变更                                                                                                                                                                                                   |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| §2.4 投影规则 | `major_distribution_record.region_scope` 移出 `field_projections`，归入 `local_only_filters`；注释明确"存储粒度桶值，无跨资产语义"                                                                     |
| §5.5（新增）  | `RetrievalPlan.friendly_view` 契约冻结：`FriendlyRetrievalPlanView` schema 骨架（`intent_summary` / `sub_query_cards` / `overall`）；orchestrator 生成中文卡片，前端零派生                             |
| §10 Console   | 三区 → **单一对话流**（R3-c 最终决策：取消辅助分析抽屉，工程细节按需通过卡片 `<InlineDetailsCollapse>` 内嵌折叠展开）；执行步骤内嵌为对话流时间线卡片；SSE `card_delta` 增量更新；断连 fallback 到轮询 |
| §13 变更清单  | 追加 R3 5 行（region_scope 快修 / friendly_view / Console 单一对话流 / tag_filter 稳定性 / §16.7 说明段）                                                                                              |
| §14 待确认    | 无新增（R3 决策 Q1/Q2/Q3 已定；tag_filter 未决项归入 `tag_filter_reliability_matrix_v1.md §8`）                                                                                                        |

**代码交付**（本轮已完成）：

- `nexus_app/ai_governance/projection_config.py`：`major_distribution_record` 投影规则修正（region_scope 移到 local_only_filters）
- `tests/ai_governance/test_projection_config.py`：新增 `test_region_scope_stays_local_not_projected` 守卫

**文档交付**（本轮已完成）：

- `docs/tag_filter_reliability_matrix_v1.md`（约 500 行）：tag_filter 全链路 12 步稳定性设计，12 条跨步不变量、12 个 P0 PR 清单、5 sprint 落地节奏
- `docs/retrieval_plan_console_ux_v1.md`（约 360 行）：Console **单一对话流**结构（R3-c 最终）、`FriendlyRetrievalPlanView` 完整 schema、SSE 事件契约、卡片渲染示意、卡片内嵌 `<InlineDetailsCollapse>` 折叠详情设计、前端组件设计（`<ConversationStream>` + `<IntentSummaryCard>` + `<SubQueryCard>` + `<InlineDetailsCollapse>`）、M-C 三阶段落地节奏

**Alembic 影响**：**无**——本轮只改代码常量 + 文档，无 DB schema 变更。

**风险与缓解**：

- **风险**：`friendly_view` 中文映射规则（tag_type / domain / match_strategy / purpose / channel）分散在 orchestrator 与 domain_registry 之间，容易漂移。
- **缓解**：约定所有中文映射源在 M-B 落地时**集中到** `retrieval/display_labels.py` 单一模块；单测强制"每个 tag_taxonomy code 都有中文 label"、"每个 QueryProfile 都有 display_name"。
- **风险**：SSE 断连场景多，前端 fallback 到轮询后 UI 一致性可能出错。
- **缓解**：`SubQueryCard` 是幂等结构，轮询拉全量后应用等同 delta；单测覆盖"三条 delta 与一次全量拉取产生相同最终状态"。
- **风险**：tag_filter reliability matrix 中的"12 条不变量"若在实施时被绕过，全链路可信性受损。
- **缓解**：每条不变量在 PR-1~PR-12 里都要显式声明遵守（PR 描述模板加"影响的不变量清单"字段）；关键 I-1（归一化函数唯一真源）、I-2（tag_type code 单一真源）在 M-B 首批 PR 中落 assertions + 单测护栏。
