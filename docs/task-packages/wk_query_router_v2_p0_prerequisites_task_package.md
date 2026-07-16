# Task Package: Query Router v2.0 P0 Prerequisites

## Source Context

- `docs/knowledge_retrieval_router_v2.0_design.md` **§10 阶段 A + §1.9 第九轮范围裁剪 + §1.11 第十一轮闭合 + §1.12 第十二轮 A1f 方案反转 + §1.13 第十三轮 A1f 实施澄清 + §1.14 第十四轮 A1b 收窄仅 major + §1.15 第十五轮 5 场景业务视角重映射（scenario 语义按业务分类 / A1b 加 industry_distribution 聚合 / scenario_3 双路 A2）**（v2.0 定稿）
- `CLAUDE.md`：Prompt 维护在 NEXUS、AI 输出非持久化不入治理红线、LiteLLM 承担模型编排、权限 P0 = 凭证认证 + org_scope noop
- `ARCHITECT.md`：orchestration 层扩展点；不引入 RAGFlow / RabbitMQ / Celery / Redis 为 P0 依赖
- `SPEC.md`：`/open/v1/search`、`/open/v1/qa` 保持现有行为；扩展审计事件仅通过 `audit_log.summary` 自由 JSON 字段

## 第十一轮评审反馈闭合摘要（v2.0 定稿）

本任务包已按设计文档 §1.11 九项决策 + 四项配套修复重写。要点：

1. **A1f `build_type` 枚举取 db 实际小写值**（第十二轮再次收敛为 `[teaching_standard, ability_analysis]`，见下）
2. **A5 是新实现**（v1 无同义 query 生成能力）：LiteLLM 生成 3-5 条同义 query + 独立召回 + `chunk_id` 简单 dedup；**不引入多路 rerank 融合**
3. **取消 A5 A/B 评测**（Gate 1 第 7 条改为单元测试覆盖）
4. **A0 DoD 加"LLM 未返回 tool_call → 降级 unknown 兜底"路径**
5. **场景 2 走 `search_chunks_by_semantic(kb=industry_research_kb)`**，A3 工具注册表补齐 scenario_2 / scenario_3 分组
6. **`config/query_router_tools.json` 无控制台编辑需求**，不引入 ETag / fcntl 保护
7. **A1e / A1f 性能基线不纳入 P0**（上线后观察）
8. **`industry_research_kb` 混装（政策/产业报告/行业报告）确认**，不新增二次过滤维度
9. **A6 依赖 A7**（`caller_type` 字段值由 A7 提供）；A8 补 audit 端到端回归 + `caller_type` 老端点回填 + tool_call 缺失兜底 smoke
10. **A4 chart_id 生成规则** `{tool_call_id}:{chart_index}`，占位替换在 **Composer 流完成后统一执行**
11. **§3.3 双入口鉴权勘误**：`/internal/v1/query` 走 JWT session（`nexus-api/nexus_api/dependencies/user.py` 已实现），非"内部信任"

## 第十二轮追加决策（A1f 方案反转）

**A1f 从方案 A（反查）反转为方案 B（build.major_name 冗余列）**：

1. **Schema 变更**：`capability_graph_staging_build` 加 `major_name: String(256) | None` + 索引；需 alembic 迁移
2. **build 生产者写入路径修改**：对 `build_type ∈ {teaching_standard, ability_analysis}` 从 `normalized_asset_ref.title` 解析 major_name 写入；job_demand / combined 类留空
3. **数据回填脚本**：迁移时对已存在的 teaching_standard / ability_analysis build 一次性回填
4. **端点简化**：一次单表 `SELECT ... WHERE major_name ILIKE :major AND build_type = :build_type AND status = 'GENERATED'`
5. **`build_type` 枚举收敛为 `[teaching_standard, ability_analysis]`**（去掉 job_demand——该类不涉及 major 冗余；加 ability_analysis 支持职业能力分析表检索场景）
6. **业务范围锁定**：只有专业教学标准、专业简介、职业能力分析表三类数据资产涉及 major 业务维度；专业简介无 build 不受本轮影响

**工程量**：A1f 从 S~M 上调为 **M**（含 alembic 迁移 + build 生产者写入路径修改 + 数据回填 + 端点实现）。

## 第十三轮追加决策（A1f 实施澄清 — 基于平台真实数据）

**基于代码复核 NEXUS 平台专业教学标准 / 专业简介真实数据，对第十二轮方案 B 做实施路径澄清**：

1. **复用平台已有 identity 抽取器，禁止重新实现**：
   - `nexus_app.teaching_standard.extractor._major_identity(title, blocks)` → `(major_code, major_name)`
   - `nexus_app.major_profile.extractor._extract_identity(title, text)` + `_iter_labeled_identities(text)` → `(major_code, major_name)`
   - build 生产者按 build_type 分派调用

2. **既有 major_name 语义漂移问题需修复**：`test_teaching_standard_graph.py:33` 显示既有实现会输出 `"电子商务专业教学标准"`（把资产类型后缀吸进去了）——**新增归一化函数** `capability_graph.major_normalizer.normalize_major_name()` 剥离资产类型后缀

3. **同时冗余 major_code + major_name 双列**：既有抽取器天然产出 `(major_code, major_name)`，同步落 build 两列，端点支持双通路查询
   - `major_code`：4-6 位数字精确匹配（stable，无歧义）
   - `major_name`：substring 模糊匹配（user-friendly，允许别名）
   - 端点参数 at-least-one-required

4. **归一化规则**：
   - **剥离**尾部资产类型词（"专业教学标准" / "职业教育专业教学标准" / "专业简介" / "职业能力分析表" 等，从 `governance_rules_v2.json:769-825 / 1071-1088 / 1651-1656` 别名列表整理，按长度降序匹配）
   - **剥离**"类"后缀（"电子商务类" → "电子商务" 与"电子商务"统一归一化；父子关系区分交由 `major_code` 位数承担——4 位=类、6 位=具体专业；检索 `major_name ILIKE '%X%'` 自动覆盖父子）；**保留"大类"复合词**（"财经商贸大类" 不剥离）
   - **保留**括号内规范化补充（"电子商务（跨境方向）"不切）

5. **P0 单元测试样本内联在任务包里**（无需业务 owner 额外提供）：源自 `test_teaching_standard_graph.py` / `test_major_profile.py` / `governance_rules_v2.json` 的 10 组真实样本，详见 A1f 章节交付物 ③

6. **端点 SQL 与响应契约调整**：
   - Query params：`{major_name?, major_code?, build_type}`，`major_name/major_code` at-least-one-required
   - `build_meta` trace 字段增加 `major_code`

**工程量**：A1f 保持 M（复用现有抽取器抵消归一化 + 双列冗余的额外成本）。

## 第十五轮追加决策（5 场景业务视角重映射 + A1b industry_distribution 聚合 + scenario_3 双路 A2）

**基于用户业务视角复核，5 类检索场景语义按数据资产 + 输出形式重映射**（编号 `scenario_1..5` 字面量保持稳定，避免 audit 值域冲击）：

| 编号         | v2.0.1 业务语义                                              | 覆盖资产                           |
| ------------ | ------------------------------------------------------------ | ---------------------------------- |
| `scenario_1` | **讯息类**（chunks + summary）                               | 产业政策 / 产业报告 / 行业报告     |
| `scenario_2` | **结构化数据**（按 major / job_title）                       | 岗位需求 / 职业能力分析 / 专业布点 |
| `scenario_3` | **专业教学标准**（双路 A2：图谱 + 培养目标/职业面向 chunks） | 专业教学标准                       |
| `scenario_4` | **教材类**（含实训，按 kb 区分）                             | 电子商务基础 / 核心课程 / 实训教材 |
| `scenario_5` | **Agentic RAG**（多步骤模板）                                | 跨资产                             |

**三项决策落地**：

1. **A2 场景 3 双路**（问题 A 解决）：`teaching_standard/extractor.py` 只输出岗位知识图谱表格，缺培养目标/职业面向；场景 3 走 `query_capability_graph_by_major(build_type=teaching_standard)` + `search_chunks_by_semantic(kb=course_standard_authoring_process, outline_node="培养目标"|"职业面向")` 双路并行 → Composer 三段汇总；零新增结构化字段/迁移

2. **B1 A1b industry_distribution 聚合**（问题 B 解决）：A1b 端点在 `fields` 参数含 `industry_distribution` 时后端做 `GROUP BY industry_name COUNT ORDER DESC LIMIT 5` 聚合；响应 `{records, aggregations: {industry_distribution}}`；覆盖用户场景 2 "岗位行业分布图 Top-5" 需求

3. **C3 场景编号语义重映射**：编号保留数字 `scenario_1..5`（audit 稳定），但每编号业务语义按用户新分类重定义；意图分类器 Prompt 在阶段 B B1/B2 重写；工具注册表 §4.2.1 按新分组重排

**工程量变化**：

- A1b：M（含 industry_distribution 聚合）；上限收敛到 6-7 人天
- A3：M 不变（重分组不增工作量，仅调整 JSON 分组）
- 意图分类器 Prompt 重写在 B1/B2 阶段完成，不冲击阶段 A

## 第十四轮追加决策（A1b 参数收窄到仅 major）

**基于对场景 5 `step_demand` 实际使用模式的复核，A1b 进一步收窄为仅 major 一维业务过滤**：

1. **Query params 精简**：
   - 保留：`major`(substring, 走 dataset join) + `normalized_ref_id`(optional trace) + 分页/排序
   - **删除**：`job_title`(substring)、`salary_min`/`salary_max`、`experience_requirement`、`education_requirement`、`region`、`source_published_at` 范围等**所有细粒度过滤**
2. **理由**：
   - 场景 5 `step_demand` 的核心需求是"按专业拉取岗位需求汇总"，细粒度过滤未验证
   - 端点契约越窄越稳定，一旦加入难以下线
   - 细粒度筛选由 Composer 追问引导即可
3. **§4.2.1 工具 schema 同步精简**：`internal.query_job_demand` 只保留 `major` (required) + `normalized_ref_id` (optional) + `fields`
4. **§5.1 YAML 同步**：`step_demand` inputs 只留 `major` + `fields`；删除 `year_range` / `region`
5. **Gate 1 第 3 条改**：从"major + job_title 两维"改为"仅 major 一维"
6. **单元测试范围缩小**：从"跨 3 dataset × 2 维过滤组合"简化为"跨 3 dataset × major 命中"

**工程量**：A1b 从 M 保持 M（下限偏向 5 人天，因参数变少）。

## Goal

完成 v2.0 检索方案 §10 阶段 A 全部前置项，跑通 **Gate 1**，让阶段 B（Layer 1-3 编排层）可以直接开工。所有前置项**互相独立、可并行**（A3 与 A8 依赖前置完成后收口）。

## Scope

以下 11 项工程任务为 P0 前置最小可用切片：

- **A0** — LiteLLM function calling / tool use 支持
- **A1b** — 新增跨 dataset job-demand-records 端点（**仅 major** substring 过滤；第十四轮 §1.14 收窄）
- **A1e** — ability-analyses `major_name` substring 支持
- **A1f** — capability-graph by-major 一跳端点（**方案 B** + 第十三轮 §1.13 实施澄清：复用现有 identity 抽取器 + 新增归一化函数 + **major_name + major_code 双列冗余** + alembic + 回填 + 端点双通路 at-least-one-required）
- **A2** — outline subtree 查询 API
- **A3** — `config/query_router_tools.json` 工具注册表
- **A4** — 图 API → chart JSON 薄适配器 + `[[CHART:...]]` 占位替换机制
- **A5** — `search_chunks_by_semantic` 加 `expand_queries` 参数
- **A6** — 审计事件字段扩展
- **A7** — api_caller / console 身份区分（**最小可用**，见 §1.9 决策 #4）
- **A8** — 老端点 + 新端点回归测试集补齐

## Out Of Scope

- 阶段 B（Layer 1 意图分类器、Layer 2 dispatcher、Layer 3 Composer、`/open/v1/query` / `/internal/v1/query` 主入口）
- 阶段 C（场景 5 人才培养方案模板执行器）
- `/open/v1/query` / `/internal/v1/query` 主入口 API
- Prompt 模板（`retrieval.intent_v2` / `retrieval.param_extract_v2` / `retrieval.compose_v2` / `retrieval.plan.talent_cultivation`）
- v1 组件重构（`retrieval/intent.py`、`retrieval/planner.py`）
- 前端 chart fence 渲染 + generated 段落样式（阶段 B B8）

## Explicitly Deleted (第九轮 §1.9 决策)

- ~~A1a~~ job-demand datasets 过滤补齐（dataset 是容器不含 job 数据，过滤无价值）
- ~~A1c~~ 已合并入 A1b
- ~~A1d~~ 产业政策薄封装（理由见设计文档 §1.10 勘误）：产业政策是 **document-type 资产**（`primary_knowledge_type = industry_research_kb`，见 `config/governance_rules_v2.json:134`），走 chunks 通路即可；场景 5 `step_policy` 使用 `internal.search_chunks_by_semantic(kb="industry_research_kb", top_k=8, expand_queries=true)` 拿相关 chunks 后由 Composer 汇总；**不需要专用结构化 API**
- A1b 内的 salary/experience/education/region/published_at 细粒度过滤（延后 P1，靠对话追问引导）

## Forbidden Changes

- 不修改 `/open/v1/search` / `/open/v1/qa` 端点的响应 schema（保持向后兼容，仅老端点使用方是内部开发内测）
- 不引入 BM25 / tsvector / OpenSearch / Elasticsearch（P0 遗留）
- ~~不新建 `capability_graph_staging_build.major_name` 冗余列（A1f 走反查方案 A）~~ **第十二轮 §1.12 反转**：改走方案 B，新建 `major_name` 冗余列 + alembic 迁移 + 回填脚本 + build 写入路径修改
- 不新增 audit 事件类型（仅扩展 `summary` JSON 字段）
- 不新增 P0 依赖：RabbitMQ / Celery / Redis / RAGFlow
- 不改变 P0 权限模型（凭证认证 + org_scope noop）；A7 差异化权限留 P1

---

## Track / Owner 划分建议

| Track                    | 责任范围               | 建议人数             |
| ------------------------ | ---------------------- | -------------------- |
| Track 1 — LLM/AI         | A0                     | 1（含 LiteLLM 熟手） |
| Track 2 — 结构化领域 API | A1b / A1e / A1f        | 1-2                  |
| Track 3 — 平台底座       | A2 / A4 / A5 / A6 / A7 | 1-2                  |
| Track 4 — 集成收口       | A3 / A8                | 1（依赖前三 Track）  |

## 任务细节

### A0 — LiteLLM function calling 支持

- **文件**：`nexus-app/nexus_app/ai_governance/litellm_client.py`
- **交付物**：
  - `LiteLLMClientProtocol.call()` 扩展 `tools: list[dict] | None`、`tool_choice: str | dict | None` 参数
  - `RealLiteLLMClient.call()` 透传上述参数到 OpenAI 兼容 chat completions API
  - `LiteLLMClientProtocol` 新增 `call_with_tools()` 便捷方法（或直接扩展 call），返回结构含 `tool_calls: list[ToolCall]`（`ToolCall` 至少包含 `id / name / arguments`）
  - Pydantic schema 校验 tool schema（输入约束）与 tool_call 结果（输出约束）
  - **降级路径接口预留**：Protocol 里同时保留 `response_format=json_object` 通路（用于 JSON output + 手动 parse 降级方案，阶段 B B4 可切换）
- **DoD**：
  - 单元测试覆盖以下**5 类**场景：
    1. 单 tool 调用成功
    2. 多 tool 并行调用成功
    3. tool_call 参数 Pydantic 校验失败 → 1 次重试 → 再失败 → **返回明确信号供 dispatcher 降级 unknown 兜底**（第十一轮决策 #4）
    4. **模型未返回任何 tool_call**（含 `finish_reason=stop` 且 `tool_calls` 为空 / null）→ **返回明确信号供 dispatcher 降级 unknown 兜底**（不做二次 LLM 重试）
    5. LiteLLM 侧超时 / rate limit / server error → 走现有 `LiteLLMCallError` 重试逻辑
  - Fake LLM client 覆盖 CI 场景（不依赖真实 LiteLLM 部署），能在测试里模拟"返回空 tool_calls"与"tool_call arguments 非法 JSON"两种边界
  - **契约文档**：在 docstring 或 CHANGELOG 中写明"tool_call 缺失 / 校验连续失败 → 由调用方（B4 dispatcher）负责降级 unknown 兜底，本层不做业务降级"
- **依赖**：无
- **估工**：**L**（10-14 人天）
- **风险**：LiteLLM 版本或后端模型 tools API 兼容性；**降级方案**：`response_format=json_object` + 手动 parse 替代 tool use，阶段 B B4 里加 fallback dispatcher（本次 A0 已预留 Protocol 接口）

### A1b — 跨 dataset job-demand-records 端点（第十四轮 §1.14 收窄仅 major + **第十五轮 §1.15 B1 加聚合响应**）

- **文件**：`nexus-api/nexus_api/api/internal/record_assets.py`
- **交付物**：
  - 新增 `GET /record-assets/job-demand-records` 端点
  - Query params（**第十四轮 §1.14 收窄到仅一个业务过滤维度**）：
    - `major`(substring, required) — **走 `job_demand_dataset.major_name` join**（第十一轮闭合项）；**不使用 `industry_name` 兜底**（专业"跨境电商" ≠ 行业"电商"）
    - `normalized_ref_id`（optional trace）
    - `fields`（optional, array of string；**第十五轮 §1.15 B1**）—— 请求字段白名单，含 `industry_distribution` 时后端做聚合响应
    - 分页 / 排序（默认按 `created_at desc`）
  - Response：`{records: [...], aggregations: {industry_distribution: [{industry_name, count}] | null}}`
    - `records`：与 `_serialize_job_demand_record` 一致；每条**必带 `normalized_ref_id` + `dataset_id`**（trace）
    - `aggregations.industry_distribution`：请求参数含 `industry_distribution` 时后端 SQL 做 `GROUP BY industry_name COUNT ORDER DESC LIMIT 5`；请求不含时字段为 `null`
- **DoD**：
  - substring 过滤走 `ILIKE` 或等价大小写不敏感匹配
  - 单元测试：
    1. 跨 3 dataset records 混合查询，验证 **major 过滤命中**；分页正确；排序稳定
    2. **`fields=industry_distribution` 聚合正确性**（第十五轮 §1.15 B1）：mock 5+ 个 industry 分布 → 验证 Top-5 截断 + 按 count 降序；空数据边界（0 records）返回 `industry_distribution: []`；未请求聚合时字段为 `null`
  - **反例测试**：确认查询"跨境电商"专业不会误命中 industry_name="电商" 但 dataset.major_name != "跨境电商" 的记录
  - **未支持参数验证**：客户端传 `job_title` / `salary_min` / `region` / `experience_requirement` / `education_requirement` / `source_published_at` 等参数时，端点或忽略并 warn（更宽容）或返回 400（更严格）——由 owner 定；不能悄悄按未记录语义处理
- **依赖**：无
- **估工**：**M**（6-7 人天；加 industry_distribution 聚合后偏中上限）
- **不做**（第十四轮 §1.14 全部下沉 P1）：
  - `job_title` (substring) 过滤
  - `salary_min` / `salary_max` 范围
  - `experience_requirement` / `education_requirement`
  - `region` / `source_published_at` 范围
  - `industry_name` 兜底（第十一轮闭合项延续）
  - 除 `industry_distribution` 外的其他聚合维度（如 `salary_distribution` / `region_distribution`；未来按需求增补）
  - 上述细粒度筛选需求交由 Composer 追问引导或未来 P1 增补

### A1e — ability-analyses major_name substring 支持

- **文件**：`nexus-api/nexus_api/api/internal/record_assets.py:1032-1080`
- **交付物**：`GET /record-assets/ability-analyses` 的 `major_name` query 参数从 exact 改为 substring（`ILIKE`）
- **DoD**：
  - 单元测试：验证 substring 命中；旧 exact 用法不 break（因为 substring 是 exact 的超集，"跨境电商" 仍能命中 "跨境电商"）
- **依赖**：无
- **估工**：**S**（3 人天）
- **不做**（第十一轮决策 #8）：性能基线测量与 GIN trigram 索引前置。P0 上线后观察，若慢查询出现再触发升级

### A1f — capability-graph by-major 一跳端点（**方案 B** + 第十三轮 §1.13 实施澄清）

**背景**：

- 第八轮曾采纳方案 A（反查 build → dataset → major），**第十二轮反转为方案 B**（build 冗余列）
- **第十三轮实施澄清**（基于对 NEXUS 平台专业教学标准 / 专业简介真实数据代码复核）：
  1. **平台已有两处 identity 抽取器可复用**，无需新建
  2. 现有 major_name 存在语义漂移（含资产类型后缀"专业教学标准"），需**新增归一化函数**剥离
  3. **同时冗余 major_code + major_name 双列**（既有抽取器天然产出两者；major_code 精确匹配 + major_name substring 双通路）
  4. 真实 title 样本已在测试代码里，**不需要业务 owner 额外提供**

- **文件**：
  - `nexus-app/nexus_app/models.py`（`CapabilityGraphStagingBuild` 加 `major_name` + `major_code` + 复合索引）
  - `nexus-app/alembic/versions/<new>_add_build_major_columns.py`（迁移 + 数据回填）
  - `nexus-app/nexus_app/capability_graph/major_normalizer.py`（**新建**：`normalize_major_name` 归一化函数）
  - `nexus-app/nexus_app/capability_graph/builders.py`（既有，修改：接入 identity 抽取器 + normalizer + 写入两列）
  - `nexus-api/nexus_api/api/internal/capability_graph_staging.py`（新增端点）

- **复用的既有能力**（**禁止**重复实现）：
  - `nexus_app.teaching_standard.extractor._major_identity(title, blocks)` → `(major_code, major_name)`（教学标准侧）
  - `nexus_app.major_profile.extractor._extract_identity(title, text)` + `_iter_labeled_identities(text)` → `(major_code, major_name)`（专业简介 / 一般文档侧）
  - Build 生产者调用抽取器的分派规则：`teaching_standard` build → `_major_identity`；`ability_analysis` build → `_extract_identity`

- **交付物**：

  **① Schema 变更（alembic 迁移）**
  - `capability_graph_staging_build` 加列：
    - `major_name: String(256) | None`（可空，job_demand / combined 类留空）
    - `major_code: String(16) | None`（4-6 位数字字符串）
  - 加复合索引：`Index("ix_cgsb_major_type", "major_name", "build_type")` + `Index("ix_cgsb_major_code", "major_code")`
  - 迁移脚本 upgrade / downgrade 均实现

  **② 归一化函数 `normalize_major_name`**（`major_normalizer.py` 新建，仅剥后缀，其他复用现有抽取器）
  - 输入：既有抽取器输出的 `major_name`（如"电子商务专业教学标准"、"电子商务类"、"电子商务"）
  - 输出：`normalized: str | None`
  - **剥离规则**（按顺序，从 `config/governance_rules_v2.json:769-825 / 1071-1088 / 1651-1656` 的别名列表整理，按长度降序匹配）：
    1. **剥离资产类型后缀**（先做，按长度降序）：
       - `"职业教育专业教学标准" / "中等职业教育专业教学标准" / "高等职业教育专科专业教学标准" / "专业教学标准" / "教学标准"`
       - `"院校专业简介" / "专业简介"`
       - `"职业能力分析表" / "能力分析表"`
    2. **剥离"类"后缀**（后做）：结尾单个"类"字剥离（"电子商务类" → "电子商务"）；**保留"大类"复合词**（"财经商贸大类" 保留，因"大类"是复合词）
       - 实现建议：`re.sub(r"(?<!大)类$", "", name)` 或用白名单
       - 目的：`"电子商务类"` 与 `"电子商务"` 统一归一化到 `"电子商务"`；父子关系区分交给 `major_code` 位数（4 位=类、6 位=具体专业）承担
  - **保留括号内规范化补充**（`"电子商务（跨境方向）"` 不切）
  - 空字符串或纯空白 → 返回 `None`

  **③ 内联 title 样本清单**（P0 单元测试基准，无需业务 owner 补齐；样本源自 `test_teaching_standard_graph.py` / `test_major_profile.py` / `governance_rules_v2.json`）

  | #   | 原始 title                                                            | 期望 `(major_code, normalize(major_name))`                            | 来源                                     |
  | --- | --------------------------------------------------------------------- | --------------------------------------------------------------------- | ---------------------------------------- |
  | 1   | `"5307 电子商务专业教学标准"`                                         | `("5307", "电子商务")`                                                | `test_teaching_standard_graph.py:24`     |
  | 2   | `"电子商务专业教学标准"`（identity 从 block "电子商务（530701）" 抽） | `("530701", "电子商务")`                                              | `test_teaching_standard_graph.py:62/106` |
  | 3   | `"电子商务（530701）专业教学标准"`                                    | `("530701", "电子商务")`                                              | `test_teaching_standard_graph.py:75`     |
  | 4   | `"（高职电子商务类专业简介）5307 电子商务类"`                         | `("5307", "电子商务")` **（类后缀已剥离）**                           | `test_major_profile.py:68/112`           |
  | 5   | `"电子商务专业教学标准"`（无 block identity）                         | `(None, "电子商务")` 或 `(None, None)` if 只走 title 且识别不出 code  | 派生                                     |
  | 6   | `"跨境电商专业教学标准"`                                              | `(None, "跨境电商")`                                                  | 业务典型样本                             |
  | 7   | `"跨境电子商务专业教学标准"`                                          | `(None, "跨境电子商务")`                                              | 业务典型样本                             |
  | 8   | `"财经商贸大类教学标准"`                                              | `(None, "财经商贸大类")` **（"大类"保留，非单字"类"后缀）**           | `governance_rules_v2.json:786`           |
  | 9   | 空字符串 / 空白                                                       | `(None, None)`                                                        | 边界                                     |
  | 10  | `"电子商务（跨境方向）专业教学标准（2024 修订）"`                     | `("(无 code)", "电子商务（跨境方向）")` 或按抽取器行为定              | 边界                                     |
  | 11  | `"电子商务类"`（既有抽取器直接输出）                                  | `(None, "电子商务")` **（新增：验证类后缀剥离，与样本 #4 同归一化）** | 归一化专项验证                           |

  **归一化不变量**：样本 #4 与样本 #11 归一化结果必须相同（均为 `"电子商务"`），保证检索 `major_name ILIKE '%电子商务%'` 能同时命中原本 title 含"电子商务"与"电子商务类"的 build。

  **④ build 生产者写入路径修改**（`capability_graph/builders.py` 或对应生成入口）
  - 对 `build_type ∈ {teaching_standard, ability_analysis}` 的 build，在构造时：
    1. 拿 `normalized_asset_ref.title` + 关联 blocks（若可访问）
    2. 分派调用相应抽取器：teaching_standard → `_major_identity`；ability_analysis → `_extract_identity`
    3. 抽取结果 `major_name` 走 `normalize_major_name()` 归一化
    4. 写入 `build.major_code` + `build.major_name` 两列
  - 对 `build_type ∈ {job_demand, combined}` 的 build 不写两列（留 NULL）
  - **CI 断言**：新落库的 teaching_standard / ability_analysis build 若两列均为空必须有对应的 warn 日志（防止抽取器静默失败）

  **⑤ 数据回填脚本**（迁移的一部分）
  - 对已存在的 `build_type ∈ {teaching_standard, ability_analysis}` + `status = GENERATED` 的 build 一次性回填
  - 通过 join `normalized_asset_ref` 拿 title → 调抽取器 + normalizer → 写回两列
  - Idempotent：重跑不重复处理已有两列的行
  - 解析失败条目：留 NULL + 记入 `migration_backfill_errors` 表（或迁移日志），由 DBA 复检

  **⑥ 端点实现**
  - 新增 `GET /capability-graph-staging/by-major?major_name=X&major_code=Y&build_type=Z`
  - Query params：
    - `major_name`（optional, substring, 走 `build.major_name ILIKE`）
    - `major_code`（optional, exact, 4-6 位数字, 走 `build.major_code =`）
    - **at-least-one-required**（校验层保证两者至少给一个）
    - `build_type`（必填，enum `[teaching_standard, ability_analysis]`）
  - 后端 SQL（两者都给时 code 优先，OR 语义）：
    ```sql
    SELECT * FROM capability_graph_staging_build
    WHERE (
        (:major_code IS NOT NULL AND major_code = :major_code) OR
        (:major_name IS NOT NULL AND major_name ILIKE :major_name_substr)
      )
      AND build_type = :build_type
      AND status = 'GENERATED'
    ORDER BY created_at DESC
    LIMIT 1
    ```
  - 拿到 build 后按 build_id 一次性 join nodes / edges 表返回 `{build_meta, nodes: [...], edges: [...]}`
  - `build_meta` 必带 `build_id` / `normalized_ref_id` / `major_name` / `major_code` / `build_type` / `created_at`（trace 字段）
  - **不做多 build 聚合**：若匹配多个 build，取 `created_at desc` 最新一份

- **DoD**：
  - **归一化函数单元测试**：覆盖上述 **11 个内联 title 样本**（含类后缀剥离专项样本 #11；不需要业务 owner 额外提供）；**断言归一化不变量**：样本 #4 与样本 #11 归一化结果一致（均为 `"电子商务"`）
  - **检索联通性测试**：写入两个 build——一个 title 含"电子商务"（归一化为"电子商务"）+ 一个 title 含"电子商务类"（归一化也为"电子商务"），发起 `major_name=电子商务` substring 查询应能同时命中；用 `major_code` 精确区分（4 位=类、6 位=具体专业）
  - **迁移测试**：向前迁移（加两列）+ 数据回填 + 向后迁移（删两列）在测试环境全部成功
  - **回填正确性**：抽样若干 teaching_standard / ability_analysis build 验证 major_name / major_code 与 title 语义一致；解析失败条目落 `migration_backfill_errors`
  - **写入路径测试**：新触发一次 build 生成 → 两列正确写入；解析失败时留空且有 warn 日志
  - **端点单元测试**：
    - `major_name` substring 命中
    - `major_code` 精确命中
    - 两者都给：走 OR 语义
    - 两者都不给：返回 422 明确报错（at-least-one-required）
    - 无匹配 → 返回 404 或空
    - 多 build 情况取最新一份
    - `build_type=job_demand` 或大写值（如 `TEACHING_STANDARD`）返回 422 明确报错
  - **Smoke test**：
    - `major_code=530701` + `build_type=teaching_standard` → 拿电子商务教学标准图
    - `major_name=电子商务` + `build_type=ability_analysis` → 拿电子商务职业能力分析表图

- **依赖**：既有抽取器（无需新建）；build 生产者代码（nexus-app 内）联动
- **估工**：**M**（8-10 人天，含 alembic 迁移 + normalizer + 写入路径接入 + 数据回填 + 端点）
- **不做**：
  - `build_type=job_demand` 走本端点（岗位需求走 `internal.query_job_demand` / `get_job_demand_role_graph`）
  - **重新实现 identity 抽取**（复用 `_major_identity` / `_extract_identity`）
  - 反查性能基线（第十一轮决策 #8）
  - LLM 兜底解析（若解析失败率高再评估）
  - ~~剥离"类"后缀（业务决策：保留）~~ **业务决策更新**：**剥离**"类"后缀（除"大类"复合词），父子关系交由 `major_code` 位数承担 + substring 匹配自然覆盖

### A2 — outline subtree 查询 API

- **文件**：`nexus-api/nexus_api/api/internal/knowledge_outline.py`
- **交付物**：
  - 新增 `GET /internal/v1/knowledge-outline-nodes/{node_id}/subtree` 端点
  - 递归展开当前 node 的所有子孙节点（限深度默认 5，可 query 覆盖）
  - Response：树形结构 `{node, children: [{node, children: [...]}, ...]}`
  - 可选 query：`include_chunks: bool`（默认 false，为 true 时每 node 附带其 chunks 列表）
- **DoD**：
  - 单元测试：单层子树、多层子树、限深截断、循环引用防护（若模型允许）
  - 404：node_id 不存在时返回明确错误
- **依赖**：无
- **估工**：**S**（3 人天）

### A3 — 工具注册表 `config/query_router_tools.json`（**第十五轮 §1.15 按业务视角重分组**）

- **文件**：`config/query_router_tools.json`（新建）+ `nexus-app/nexus_app/retrieval/tools_registry.py`（新建加载器）
- **交付物**：
  - JSON 文件按 `scenario_1` … `scenario_5` **全部 5 组分组**（**按第十五轮 §1.15 业务视角重排**）：

    | scenario     | 业务含义         | 工具清单                                                                                                                                                                                                                       |
    | ------------ | ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
    | `scenario_1` | 讯息类           | `internal.search_chunks_by_semantic (kb=industry_research_kb, const)`                                                                                                                                                          |
    | `scenario_2` | 结构化数据       | `internal.query_job_demand` + `internal.get_job_demand_role_graph` + `internal.query_ability_analysis` + `internal.query_capability_graph_by_major (build_type=ability_analysis, const)` + `internal.query_major_distribution` |
    | `scenario_3` | 专业教学标准双路 | `internal.query_capability_graph_by_major (build_type=teaching_standard, const)` **+** `internal.search_chunks_by_semantic (kb=course_standard_authoring_process, const; outline_node enum=[培养目标, 职业面向])`              |
    | `scenario_4` | 教材类           | `internal.search_chunks_by_semantic (kb enum=[course_textbook, practical_training_kb])` + `internal.get_evidence_graph_by_ref` + `internal.get_outline_subtree`                                                                |
    | `scenario_5` | Agentic RAG      | 无独立 tool（`$comment` 标注，由模板文件 `config/plans/talent_cultivation_plan.yaml` whitelist 引用其他 scenario 的 tools）                                                                                                    |

  - 每个 tool 完整包含 `name` / `description` / `parameters`（标准 JSON Schema）；`build_type` / `kb` 在特定 scenario 下用 `const` 收窄
  - `query_capability_graph_by_major` **同一 tool 名在 scenario_2 与 scenario_3 各出现一次**（`build_type` 不同 const），Layer 2 dispatcher 按 scenario 分派
  - 命名对齐真实 API：`internal.search_chunks_by_semantic` / `internal.query_job_demand`(→ A1b, 含 `fields=industry_distribution` 聚合) / `internal.query_ability_analysis` / `internal.query_capability_graph_by_major`(→ A1f) / `internal.query_major_distribution` / `internal.get_evidence_graph_by_ref` / `internal.get_outline_subtree`(→ A2) / `internal.get_job_demand_role_graph`
  - **不含 `internal.search_industry_policy`**（A1d 已删除，见设计文档 §1.10）
  - 参数遵循 §2.5.0 跨资产原则：**业务维度为主必填、trace 字段仅可选**
  - Python 加载器：解析 JSON、Pydantic 校验、按意图查询工具集
  - **第十一轮决策 #6**：不引入 ETag / fcntl / 编辑审计（无控制台编辑需求，由后端工程师随代码 PR 维护）
- **DoD**：
  - Pydantic 校验：每工具的 parameters 必须是合法 JSON Schema；required 字段必须在 properties 中；`const` 值域正确
  - **A0/A3 联调**（第十一轮闭合项）：用 A0 fake LLM client 逐个 tool 试跑一次 tool_choice 决策，验证 schema 完全兼容
  - **跨 scenario 分派测试**（第十五轮 §1.15 补）：验证 `query_capability_graph_by_major` 在 scenario_2 / scenario_3 分别拿到不同 const 值的 build_type schema；scenario_3 双路（图谱 + chunks）能同时被 Layer 2 dispatcher 选中执行
  - 单元测试：按意图查子集、按 name 精确取工具、schema 合规检查
  - 静态 lint：JSON 格式化
- **依赖**：**A0（联调）**, A1b, A1e, A1f, A2
- **估工**：**M**（5-7 人天；重分组不增工作量，仅调整 JSON 分组）

### A4 — 图 API → chart JSON 薄适配器

- **文件**：`nexus-app/nexus_app/retrieval/chart_adapter.py`（新建）
- **交付物**：
  - 输入：internal graph API 响应（`KnowledgeGraphNode/Edge/Fact` 或 `CapabilityGraphStagingNode/Edge`）
  - 输出：`chart:echarts` fence JSON schema：
    ```json
    {"type": "graph", "nodes": [{"id","name","category"}], "edges": [{"source","target","relation"}], "meta": {"title","source_ref"}}
    ```
  - **chart_id 生成规则**（第十一轮闭合项）：`{tool_call_id}:{chart_index}`
    - `tool_call_id` 来自 A0 LiteLLM `tool_calls[].id`
    - `chart_index` 是单次 tool 调用返回多张图时的 0-based 序号（多数场景为 `0`）
    - 后端在 chart 表暂存 `request_id → chart_id → chart_json`（进程内 map，请求结束销毁）
  - `[[CHART:{chart_id}]]` **占位替换工具函数**（Composer 流完全结束后统一执行一次替换，**不做增量替换**——避免流的中间态出现半截 fence）
  - **边界处理**：
    - Composer 输出含**未登记 chart_id** → 忽略该占位保留原文本 + 记录 `audit.summary.chart_hallucination_ids`
    - Composer 输出 chart_id 数量少于后端登记 → 记录 `audit.summary.chart_unused_ids`
- **DoD**：
  - Pydantic 校验输出 schema 合法
  - 单元测试：知识图谱 → chart、能力图谱 → chart、空节点边缘情况、字段映射（node.category = node_type 归一化）
  - **单元测试补**：chart_id 生成幂等性（同 tool_call_id + chart_index → 同 chart_id）；hallucination / unused id 审计字段落地正确
- **依赖**：A0（chart_id 依赖 tool_calls[].id 生成契约）
- **估工**：**S**（3 人天）

### A5 — search_chunks_by_semantic 加 expand_queries 参数（**新实现**）

**第十一轮决策 #2 / #3 关键勘误**：v1 无同义 query 生成能力，A5 是**新增实现**（不是复用）；且**不引入多路 rerank 融合**（现有 `rerank.py` 的 `apply_weighted_rerank` 服务结构化 plan，不适配本场景），改用简单 dedup。

- **文件**：`nexus-app/nexus_app/index/pgvector_search.py`（或对应服务层）+ 新增 `nexus-app/nexus_app/retrieval/query_expansion.py`
- **交付物**：
  - 新增 `expand_queries: bool = False` 参数
  - 为 True 时执行：
    1. 调用 LiteLLM 生成 **3-5 条同义 / 近义 query**（Prompt 走 `ai_prompt_profile`，scenario = `retrieval.query_expansion_v2`；单次调用，不缓存）
    2. 原 query + 扩展 query 独立走 pgvector 召回，各拿 `top_k` 条
    3. 按 `chunk_id` **简单 dedup**（同一 chunk 出现多次取最高分）
    4. 返回 top_k 条按分数降序
  - 结果 metadata 中标注 `matched_queries: [str]`（原 + 扩展）供审计与调试
  - **降级**：query expansion LLM 调用失败 → 仅用原 query 召回（不阻断）；`expand_queries` 字段回传 `false_due_to_error` 供审计
- **DoD**（**取消 A/B 评测，第十一轮决策 #7**）：
  - 单元测试：
    1. `expand_queries=False` 时行为与旧版一致（回归保护）
    2. `expand_queries=True` 时正确生成 3-5 条 query
    3. 多路召回结果按 `chunk_id` dedup，同一 chunk 保留最高分且 `matched_queries` 含原 + 扩展 query
    4. LLM 调用失败降级：仅原 query 结果 + `expand_queries=false_due_to_error`
  - **不做**：A/B 评测脚本、标注 query 数据集
- **依赖**：B1（`retrieval.query_expansion_v2` prompt profile 需在 B1 一同新增，可与 A5 并行沟通模板契约）
- **估工**：**S**（3 人天）

### A6 — 审计事件字段扩展

- **文件**：`nexus-app/nexus_app/audit.py`（`write_audit()` 相关）
- **交付物**：
  - `SearchQueryExecuted` / `QAAnswerGenerated` 的 `summary` JSON 增加字段（无需 schema 迁移，因 summary 已是自由 JSON）：
    - `route`: `"internal_query" | "open_query" | "search" | "qa"`
    - `caller_type`: `"console_session" | "api_caller"`（**值来源于 A7 身份识别**，第十一轮闭合项）
    - `intent`: `"scenario_1" … "unknown" | null`
    - `intent_confidence`: `float | null`
    - `invoked_tools`: `list[str]`
    - `generated_ratio`: `float | null`
    - `template_id`: `str | null`
    - `query_route`: `"v2"`（预留字段）
    - `missing_optional_params`: `list[str]`
    - **`dispatch_fallback`**: `"no_tool_call" | "param_validation_failed" | null`（第十一轮决策 #4 补：dispatcher 降级 unknown 兜底的原因）
    - **`chart_hallucination_ids`**: `list[str]`（Composer 输出未登记 chart_id，第十一轮 §7.3 补）
    - **`chart_unused_ids`**: `list[str]`（后端登记但 Composer 未引用的 chart_id）
    - **`matched_queries`**: `list[str] | null`（A5 同义 query 扩展的匹配记录）
    - **`expand_queries_status`**: `"true" | "false" | "false_due_to_error" | null`（A5 降级审计）
  - 定义 TypedDict / Pydantic 便捷 wrapper（可选，用于代码可读性）
- **DoD**：
  - 单元测试：新字段能写入、能查询、缺失字段不 break 旧记录
  - 现有 audit 事件全量回归通过
  - **端到端联调**：A7 完成后，调 console 与 api_caller 两个入口跑一次 `/open/v1/search`（老端点），验证 `caller_type` 字段正确落数据
- **依赖**：**A7**（`caller_type` 字段值由 A7 身份识别写入；第十一轮闭合项）
- **估工**：**S**（3 人天）

### A7 — api_caller / console 身份区分（最小可用）

**第十一轮闭合项**：console 侧 **JWT session 已在 `nexus-api/nexus_api/dependencies/user.py` 实现**（非"内部信任"）；A7 直接接入即可，不需新建认证。

- **文件**：`nexus-api/nexus_api/dependencies/user.py`（已存在，读取即可）、`nexus-api/nexus_api/auth.py`（`require_api_caller`）、`nexus-api/nexus_api/permissions.py`、audit 写入路径
- **交付物**：
  - Console 侧：接入现有 `dependencies/user.py` JWT session 认证 dependency，落 `caller_type = "console_session"` 到 request state
  - api_caller 侧（`require_api_caller` 已存在）：**仅打 `caller_type = "api_caller"` 标签，权限逻辑与 console 一致**
  - Audit 事件写入时读 `caller_type` 落 A6 定义的字段
  - **同步在老端点 `/open/v1/search` / `/open/v1/qa` 回填 `caller_type=api_caller`**（第十一轮闭合项，避免 A6/A7 完成后老事件仍缺 caller_type）
  - `permissions.py` 保持 P0 noop 不变，**为 P1 差异化预留 caller_type 分支点**
- **DoD**：
  - 单元测试：两种 caller 分别调用同一 endpoint，audit 记录中 `caller_type` 正确
  - Smoke test：两种入口都能通过；权限过滤结果一致
  - **老端点回填验证**：调 `/open/v1/search` → 检查 `SearchQueryExecuted.summary.caller_type == "api_caller"`
- **依赖**：**无**（A6 反过来依赖 A7 提供 caller_type 值；先做 A7 或两者预留字段 + 联调时同步落数据）
- **估工**：**S~M**（4 人天）
- **不做**：api_caller 差异化权限过滤（P1）

### A8 — 回归测试集补齐

- **文件**：`nexus-api/tests/api/internal/` + `nexus-api/tests/api/open/`
- **交付物**：
  - 老 `/open/v1/search` + `/open/v1/qa` 全量回归（含 outline_node 过滤 / kb 参数 / top_k 边界 / caller unauthorized 等）
  - **job-demand records major 过滤回归**（A1b 端点：**仅 major** substring 跨 dataset、分页、排序；第十四轮 §1.14 收窄）+ **major 走 dataset join 反例验证**（不误命中 industry_name）+ **`fields=industry_distribution` 聚合 Top-5 正确性回归**（第十五轮 §1.15 B1）+ 未支持参数（`job_title` / `salary_*` / `region` 等）拒绝或忽略验证
  - ability-analyses substring 回归（A1e）
  - capability-graph by-major 一跳端到端 smoke test（A1f：**`build_type=teaching_standard` 拿教学标准图、`build_type=job_demand` 拿岗位需求图**——小写枚举校验）
  - outline subtree API smoke test（A2）
  - **跨资产原则合规性检查脚本**：遍历 `config/query_router_tools.json`，验证每工具的 `parameters.required` 中**无 trace 字段**（`dataset_id` / `normalized_ref_id` / `build_id`）；每工具的 response 示例必带 trace 字段；**scenario_1-5 全部 5 组分组齐全**
  - **审计事件字段端到端回归**（第十一轮闭合项）：
    - 老端点 `caller_type` 回填验证（console → `console_session`、api_caller → `api_caller`）
    - A6 全部新字段可写入 / 可查询（`dispatch_fallback` / `chart_hallucination_ids` / `chart_unused_ids` / `matched_queries` / `expand_queries_status` 等）
  - **tool_call 缺失降级到 unknown 兜底 smoke test**（第十一轮决策 #4）：Mock LLM 返回空 `tool_calls` → dispatcher 走 unknown 兜底 → 审计 `dispatch_fallback=no_tool_call`
- **DoD**：
  - CI 全绿
  - **不做**：`expand_queries` A/B 评测（第十一轮决策 #7 已取消）
- **依赖**：A1b, A1e, A1f, A5, A6, A7
- **估工**：**M**（5-7 人天）

---

## 依赖示意（第十一轮定稿）

```
A0 (LiteLLM tools, tool_call 缺失→unknown 兜底) ─▶ A3(联调), A4(chart_id), B4
A1b (job-demand records, 仅 major, dataset join) ─┐
A1e (ability-analyses substring)       ├─▶ A3 ─▶ B3, B4, C3
A1f (capability-graph by-major 方案B, ┘
      alembic 双列(major_name+major_code) +
      复用 _major_identity/_extract_identity + normalize_major_name +
      回填 + 端点双通路 at-least-one-required,
      build_type ∈ {teaching_standard, ability_analysis})
A2 (outline subtree) ─────────────▶ A3
A4 (chart adapter + chart_id + 流式替换) ─▶ B5
A5 (同义 query 生成 + dedup, 新实现) ─▶ B4
A7 (caller_type + JWT 接入 + 老端点回填) ─▶ A6 (audit fields) ─▶ A8
A7 ────────────────────────────────────────────▶ B6, B7
B1(query_expansion_v2 prompt) ─▶ A5
```

**关键变化**（vs 第九轮）：

- A5 从"复用 v1"改为"新实现"，工程量估工不变（S）但复杂度上升
- A6 依赖 A7（而非 A7 依赖 A6）：`caller_type` 值由 A7 身份识别提供
- A3 增加 A0 联调 DoD
- A4 增加 A0 依赖（chart_id 生成依赖 tool_calls[].id）

## 时间线（2 sprint，共 ~3 周）

**Sprint 1（Week 1-2）**

- Track 1：A0 启动并推进（关键路径，L 工作量跨 sprint）
- Track 2：A1e ▓▓▓ → A1f ▓▓▓▓ 完成；A1b 启动
- Track 3：A2 ▓▓▓、A4 ▓▓▓、A5 ▓▓▓、A6 ▓▓▓ 完成；A7 启动

**Sprint 2（Week 3-4）**

- Track 1：A0 收口 + 强化单测
- Track 2：A1b 完成
- Track 3：A7 完成
- Track 4：A3 ▓▓▓▓ → A8 ▓▓▓▓▓
- **Week 4 末：Gate 1 评审**

## Gate 1 验收标准（Review Gate，第十一轮定稿 12 条）

按 `WORKFLOWS.md`，Gate 1 通过需以下**全部**满足：

1. ✅ LiteLLM function calling 单元测试通过（tool 选择、参数抽取、多 tool 并行、参数校验失败）
2. ✅ **LLM 未返回 tool_call → 降级 unknown 兜底 smoke test 通过**（第十一轮决策 #4，Mock LLM 空 `tool_calls` → dispatcher 走 unknown → 审计 `dispatch_fallback=no_tool_call`）
3. ✅ **job-demand records major 过滤回归**通过（**仅 major** substring 跨 dataset；第十四轮 §1.14 收窄）+ major 走 dataset join 反例验证（不误命中 industry_name）+ **`fields=industry_distribution` 聚合 Top-5 回归通过**（第十五轮 §1.15 B1：3+ industry 分布 + 截断 + 空分布边界）+ 未支持参数（`job_title` / `salary_*` / `region` / `experience` / `education` / `published_at` 等）拒绝或忽略验证
4. ✅ ability-analyses `major_name` substring 回归通过
5. ✅ **capability-graph by-major 一跳端点端到端验证**通过（**方案 B** + 第十三轮 §1.13 实施澄清）：
   - alembic 迁移加 `major_name` + `major_code` **双列** + 数据回填成功
   - build 写入路径 CI 断言通过（新 build 落库时两列非空或有 warn 日志）
   - **归一化函数 `normalize_major_name` 单元测试通过**（11 组内联真实 title 样本；剥离资产类型后缀 + 剥离"类"后缀（保留"大类"）；**样本 #4 "电子商务类" 与样本 #11 归一化结果均为 "电子商务"** — 归一化不变量断言）
   - **检索联通性测试通过**：混合写入"电子商务"专业与"电子商务类"父类两个 build，`major_name=电子商务` substring 查询同时命中；`major_code=5307`(4 位类) vs `major_code=530701`(6 位具体专业) 精确区分
   - 按 `major_name`(substring) 或 `major_code`(exact, 4-6 位数字) + `build_type ∈ {teaching_standard, ability_analysis}` **双通路 at-least-one-required** 一跳拿单 build 完整图，**不合并多 build**
   - 两个 major 参数都不给 → 返回 422（at-least-one-required）
   - `build_type=job_demand` 或大写值明确返回 422
6. ✅ outline subtree API smoke test 通过
7. ✅ **同义 query 生成组件单元测试通过**（生成 3-5 条、chunk_id dedup 正确、`expand_queries=false` 回归、LLM 失败降级） — **取消 A/B 评测**（第十一轮决策 #7）
8. ✅ 老 `/open/v1/search` / `/open/v1/qa` 全量回归通过
9. ✅ **跨资产原则合规性检查**通过（工具注册表无 trace 字段作为必填、响应必带 trace、scenario_1-5 全部 5 组分组齐全）
10. ✅ **审计事件字段端到端回归通过**（第十一轮闭合项）：
    - 老端点 `caller_type` 回填正确
    - A6 全部新字段（`dispatch_fallback` / `chart_hallucination_ids` / `chart_unused_ids` / `matched_queries` / `expand_queries_status` 等）可写入 / 可查询
11. ✅ **Console / api_caller 双身份识别 smoke test 通过**（console 走 JWT session 接入 `dependencies/user.py`、api_caller 走 X-API-Key、audit `caller_type` 分别正确落地）
12. ✅ **A0/A3 联调通过**：用 A0 fake LLM client 试跑 A3 工具注册表中每个 tool 的 tool_choice，验证 schema 完全兼容
13. ✅ **scenario_3 双路 smoke test 通过**（第十五轮 §1.15 A2）：意图命中 scenario_3 时**并行**调用 `internal.query_capability_graph_by_major(build_type=teaching_standard)` + `internal.search_chunks_by_semantic(kb=course_standard_authoring_process, outline_node="培养目标"|"职业面向")`；Composer 拿到两路结果时按"培养目标 / 职业面向 / 岗位知识图谱"三段结构化输出；outline_node 未命中时退化为纯语义 top-K 且响应标注 warn
14. ✅ **工具注册表 §4.2.1 按第十五轮 §1.15 新分组重排验证**：`config/query_router_tools.json` 分组符合业务视角映射（scenario_1 讯息类 / scenario_2 结构化 / scenario_3 教学标准双路 / scenario_4 教材类 / scenario_5 模板占位）；`query_capability_graph_by_major` 在 scenario_2 (`ability_analysis`) 与 scenario_3 (`teaching_standard`) 各出现一次且 `const` 值域正确；跨 scenario 分派测试通过

Gate 1 通过后立即启动阶段 B（`docs/task-packages/wk_query_router_v2_p0_stage_b_task_package.md`，待撰写）。

## 风险与降级（第十一轮定稿）

| 风险                                 | 触发条件                                                                    | 降级方案                                                                                                                 |
| ------------------------------------ | --------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| A0 LiteLLM function calling 实现风险 | LiteLLM 版本 / 外部模型 tools API 兼容性                                    | **`response_format=json_object` + 手动 parse** 替代 tool use；A0 已预留 Protocol 接口，阶段 B B4 加 fallback dispatcher  |
| A0 `tool_call` 缺失 / 校验连续失败   | LLM 幻觉、prompt 未收敛                                                     | dispatcher **降级 unknown 跨类型纯向量兜底**，审计 `dispatch_fallback` 落原因（第十一轮决策 #4）                         |
| A5 同义 query 生成 LLM 失败          | LiteLLM 超时 / rate limit                                                   | 仅用原 query 召回（不阻断），`expand_queries_status=false_due_to_error` 供审计                                           |
| A0/A3 schema 兼容性                  | tools JSON Schema 与 LiteLLM 后端子集不匹配                                 | A3 DoD 内联调阶段用 A0 fake client 逐 tool 试跑，早发现早修（新增闭合项）                                                |
| A1b 跨 dataset join 性能             | 记录量大时 major substring 走 join 慢                                       | 观察项；**P0 不做基线**（第十一轮决策 #8）。真出现问题再考虑物化视图 / 冗余列                                            |
| **A1f title → major 解析失败率高**   | title 命名不规范（如"电商专业教学标准（2024 修订版本 v2）"）解析器返回 None | 留 NULL + warn 日志；A1f 端点查询该 build 时返回 404；由数据管理员人工补录；未来考虑 LLM 兜底解析                        |
| **A1f alembic 迁移 / 回填失败**      | 存量 build 关联 normalized_asset_ref 缺失、或解析器异常                     | 迁移脚本 idempotent + 失败条目记入 `migration_backfill_errors` 表由 DBA 复检；不阻断迁移                                 |
| **A1f build 生产者写入路径遗漏**     | 未覆盖所有 build 生成入口（如批处理 vs 流处理不同代码路径）                 | CI 断言 teaching_standard / ability_analysis build 落库时 major_name 非空或有 warn 日志；集成测试覆盖所有 build 生成入口 |
| A6 / A7 依赖闭环风险                 | 先做 A6 后做 A7 → `caller_type` 字段空值                                    | **顺序化**：先做 A7 打身份标签 → 再联调 A6；或两者并行开发但集成前对齐字段契约                                           |
| chart_id 幻觉 / 未引用               | Composer 未按 prompt 使用后端提供 chart_id                                  | 后端替换阶段忽略幻觉占位 + 审计 `chart_hallucination_ids`；不阻断响应                                                    |
| A7 双入口身份识别设计争议            | permissions.py 架构分歧                                                     | 按第九轮 §1.9 决策 #4 走**最小可用**（打标签、不改 permission 逻辑），P1 再统一                                          |
| 前置任务并行冲突                     | 多人改同一文件（如 `record_assets.py`）                                     | 按端点前缀拆 owner；PR 顺序化                                                                                            |
| Track 4 收口延迟                     | A3 / A8 需等前置完成，若前置滑坡则收口被压                                  | Sprint 1 末做前置项完成度中检；如滑坡则考虑砍 A5（`expand_queries`）放到阶段 B                                           |

## 变更同步

任务包完成后，同步更新：

- `docs/knowledge_retrieval_router_v2.0_design.md` §10 阶段 A 表格状态标记
- 若过程中发现契约缺口，在 §一 追加"第十轮讨论"章节，再修订正文对应小节
