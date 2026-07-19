# NEXUS 数据资产平台检索召回方案 v2.0

> **状态**：**v2.0 定稿（十一轮评审通过，进入阶段 A 执行）**
> **版本关系**：v2.0 **由现有四层检索框架演进而来**，不并存双轨、无版本切换开关
> **适用范围**：P0 阶段 9 类固定资产（产业政策、产业报告、行业报告、岗位需求数据、职业能力分析表、专业教学标准、专业布点数据、专业简介、电子商务类基础与核心课程教材）
> **契约红线**：不违反根 `CLAUDE.md`、`ARCHITECT.md` 关于 Prompt 维护在 NEXUS、AI 输出非持久化不入治理红线、LiteLLM 承担模型编排、权限 P0=凭证认证 等条款

---

## 目录

- 一、方案评审讨论记录（十五轮）
- 二、方案背景与目标（含前置条件与能力矩阵）
- 三、总体架构（含 v1 组件对齐表 + 内外双入口）
- 四、分层设计
- 五、场景 5 专项：人才培养方案模板
- 六、Unknown 兜底路径
- 七、图谱 → chart 承载协议
- 八、治理与审计
- 九、v1 → v2 演进改造路径
- 十、P0 工程清单与依赖
- 十一、非 P0 事项（延后）
- 十二、后续文档变更点

---

## 一、方案评审讨论记录（十五轮）

> 本节保留 v2.0 方案成型过程中的关键讨论，作为设计动机与取舍依据。后续对本方案的任何修订，应先回读本节，避免绕开已经拒绝或已经确认的选项。

### 1.1 第一轮 —— 三层客服式 RAG 方案提出与可行性初评

**提出方**：业务/架构

**核心命题**：NEXUS 资产类型有限（9 类）、Internal 接口已具备结构化检索能力，检索方案适合按"客服 RAG"三层建设：

1. **Layer 1** — 基于固定 5 类场景做意图识别
2. **Layer 2** — 用 LLM 函数调用能力把用户问题转成 Internal 接口调用，参数由 LLM 动态抽取
3. **Layer 3** — 检索结果由 LLM 汇总为结构化富文本输出

**5 类场景**（业务定义）：

1. **精确知识块检索**（课程教材类，如"介绍下短视频拍摄"）→ chunks 语义召回 + evidence graph 关联
2. **综合性检索**（如"2025 年跨境电商行业发展趋势"）→ 行业报告 summary
3. **实训任务类检索**（如"如何进行市场数据采集"）→ 实训类教材章节
4. **图谱类数据检索**（如"新媒体运营岗位职责与知识要求"）→ 专业教学标准中的岗位知识图谱
5. **复杂检索类型**（如"为浙江经贸学院规划 2026 年跨境电商人才培养方案"）→ 跨资产多步骤检索 + LLM 汇总；检索无结果时允许 LLM 生成

**可行性初评结论（评审方）**：技术方向可行。5 项关键风险：场景 5 开放式规划风险、"无结果 LLM 生成"冲撞治理红线、意图边界模糊、Internal 缺 summary 能力、三层串行延迟高。

### 1.2 第二轮 —— 六点调整与工程约束反馈

**提出方**：业务/架构，对第一轮建议做六点调整。

1. **Layer 3 输出格式**：改为 **Markdown**；图谱内容以 **charts 图** 呈现
2. **Generated 内容治理**：一次性返回用户、**不沉淀数据**，不入治理红线
3. **意图未识别时**：走 **BM25 + chunk 向量的混合检索** 作为兜底
4. **Summary 无法离线化**：每次汇总的关注点可能不同，必须实时算
5. **场景 5**：**保留动态规划**，不接受"固定 pipeline"退化
6. **v1 与 v2 切换**：新增 `SWITCH_TO_V2_QUERY_ROUTE=false` 配置开关（**本轮暂定，第四轮已废弃**）

**评审方反馈要点**：chart 数据必须后端拼装（禁 LLM 造节点）；BM25 需先补基建；summary 走 top-K chunks 而非全文；场景 5 用"模板 + 动态填充"折中；开关粒度支持 per-caller。

### 1.3 第三轮 —— 收敛决策

| 议题                                  | 决定                         |
| ------------------------------------- | ---------------------------- |
| Generated 段落加 MD 统一标记          | **接受**                     |
| BM25 / tsvector 基建                  | **P0 遗留不处理**            |
| Summary 走 top-K chunks + 短 TTL 缓存 | **接受**                     |
| 场景 5 P0 只做"人才培养方案"模板      | **接受**                     |
| v2 开关（全局 env + per-caller flag） | **接受**（**第四轮已废弃**） |
| Unknown 兜底：跨类型纯向量 top-K      | **接受**                     |

### 1.4 第四轮 —— 合并演进决策（取消双轨与开关）

**核心洞察**：现有四层框架里的"问题转化"本质上是**场景 1 内部的召回强化子步骤**，不是与 v2.0 平行的另一种检索哲学。四层组件与 v2.0 三层结构存在大面积重叠，双轨并置代价不划算。

**关键前提确认**：`/open/v1/search` 和 `/open/v1/qa` **无外部消费方，仍处于开发内测阶段**，schema 兼容前提天然成立。

**最终决定**：**取消 v1/v2 双轨与开关，走"由 v1 四层合并演进为 v2 三层"的单轨方案**。

### 1.5 第五轮 —— 契约细化与前置条件锁定

**提出方**：业务/架构，对细节做 8 项细化。

| #   | 决策                                                                                                  | 落点章节      |
| --- | ----------------------------------------------------------------------------------------------------- | ------------- |
| 1   | 检索接口分两类：对内 `/internal/v1/query`（console）、对外 `/open/v1/query`（api_caller）             | §3.3、§9、§10 |
| 2   | Layer 1 参数抽取**基于对应场景的工具函数参数并集**，不再固定字段                                      | §4.1          |
| 3   | Layer 1 输出**单一意图**（取最可能），删除 `top_k_alternatives`                                       | §4.1          |
| 4   | 工具注册表每工具须含 `name` + `description` + `parameters`（JSON schema），Layer 2 允许命中一到多工具 | §4.2.1        |
| 5   | Chart 适配器：**底层图 API 已是 nodes+edges 结构，只需薄适配层**（工作量 S，非最初判断的 M）          | §7、§10       |
| 6   | DAG 模板路径改为 `config/plans/talent_cultivation_plan.yaml`                                          | §5.1、§12     |
| 7   | 缺参处理：**非必填缺失忽略**（放宽范围）；仅必填缺失才前端追问                                        | §5.2          |
| 8   | 新增前置条件与能力矩阵章节                                                                            | §2.5          |

**评审方追加发现**（调研自 nexus-app / nexus-api 源代码）：

- **阻塞项 1**：`LiteLLMClientProtocol`（`nexus-app/nexus_app/ai_governance/litellm_client.py:50-59`）**完全未支持 function calling / tool use**，是 Layer 2 dispatcher 的硬前置。工作量 L
- **阻塞项 2**（第六轮已修正为过度悲观）：结构化领域 API 状态见 §1.6 勘误
- **阻塞项 3**：`knowledge_outline_node.subtree` 查询 API 缺失，是场景 3 实训检索的硬前置。工作量 S
- **可复用**：`RetrievalSummaryService`（`nexus-app/nexus_app/retrieval/summary.py`）已具备 LLM 汇总能力，场景 2 可直接嫁接
- **零成本**：`audit_log.summary` 字段（`nexus-app/nexus_app/audit.py:91-116`）已是自由 JSON，扩展字段无需迁移

### 1.6 第六轮 —— 前置调研勘误 + 过滤能力要求

**提出方**：业务/架构，指出第五轮结论中"3 套结构化 API 缺失"的判断可能有误。

**评审方复核**（重新精读 `nexus-api/nexus_api/api/internal/`）：**判断确有错**。之前的漏检源于**命名不对齐**（业务口径 vs 代码口径）：

| 业务口径                              | 代码/端点口径（真实前缀）                                                                         | 端点完整度                                                                                                   |
| ------------------------------------- | ------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| 岗位需求数据（position_demand）       | `/record-assets/job-demand-*`                                                                     | ✅ **完整**：datasets/records/**role-graph**（岗位角色图谱）/requirement-items（`record_assets.py:307-601`） |
| 职业能力分析表（capability_analysis） | `/record-assets/ability-analyses/*`                                                               | ✅ **完整**：analyses/tasks/ability-items（`record_assets.py:1032-1200`）                                    |
| 专业布点数据（major_distribution）    | `/record-assets/major-distribution-*`                                                             | ✅ **完整**（`record_assets.py:603-940`）                                                                    |
| 专业教学标准 → 岗位知识图谱           | `/capability-graph-staging/*`（builds/nodes/edges）                                               | ✅ **完整**——教学标准解析后**投影到 capability_graph_staging**（`capability_graph_staging.py:32-155`）       |
| 知识图谱（教材类）                    | `/knowledge-graphs/*` + `/normalized-refs/{ref_id}/knowledge-graph`                               | ✅ 完整（`evidence_graph.py:35-358`）                                                                        |
| 知识大纲（教材）                      | `/normalized-refs/{ref_id}/knowledge-outline` + `/knowledge-outline-nodes/{id}/chunks`+`/preview` | ✅ **基本完整，缺 subtree 递归展开**（`knowledge_outline.py:43-158`）                                        |
| 任务大纲（实训）                      | `/normalized-refs/{ref_id}/task-outline` + `/task-outline/nodes/{id}`                             | ✅ 完整（`task_outline.py:22-138`）                                                                          |
| 产业政策                              | 仅在 asset 类型枚举（`internal/assets.py:30`），无专用查询端点                                    | ⚠️ 走通用 asset 查询；按 `subject` + `year_range` 需**薄封装**（S）                                          |

**追加决策（第六轮 #1）**：**专业布点和岗位需求数据属于纯结构化数据，查询接口必须提供常规参数的过滤能力**。评审方按此复核每个端点的现有过滤参数：

| 端点                                                      | 已有过滤参数                                                                                                                           | 缺口                                                                                                                                                  | 补齐工作量 |
| --------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- |
| `/record-assets/major-distribution-datasets`              | normalized_ref_id / major_code / major_name(substring) / education_level / year                                                        | 完备                                                                                                                                                  | —          |
| `/record-assets/major-distribution-records` (跨 dataset)  | normalized_ref_id / year / major_code / major_name(substring) / province_name / education_level / region_scope / min_count / max_count | 完备                                                                                                                                                  | —          |
| `/record-assets/major-distribution-datasets/{id}/records` | 同上（去 normalized_ref_id）                                                                                                           | 完备                                                                                                                                                  | —          |
| `/record-assets/job-demand-datasets`                      | normalized_ref_id / major(exact) / industry(exact)                                                                                     | 缺 `year`、`major` substring                                                                                                                          | S          |
| `/record-assets/job-demand-datasets/{id}/records`         | city / industry(exact) / enterprise_size / employment_type                                                                             | 缺 `job_title` (substring) / `salary_min` / `salary_max` / `experience_requirement` / `education_requirement` / `region` / `source_published_at` 范围 | **M**      |
| **跨 dataset 的 job-demand-records 列表端点**             | ❌ 不存在（当前必须先选 dataset）                                                                                                      | 新增 `/record-assets/job-demand-records` 支持全量过滤                                                                                                 | **M**      |

**修正后的前置工程量净变化**：

| 项                                    | 修正前判断      | 修正后                                                                                     |
| ------------------------------------- | --------------- | ------------------------------------------------------------------------------------------ |
| 3 套结构化 API 新增                   | 3 × M           | **0**（已具备）                                                                            |
| 教学标准专用 API                      | M               | **0**（走 capability-graph-staging）                                                       |
| 产业政策查询                          | M               | **S**（薄封装）                                                                            |
| **job-demand 过滤补齐**（新增前置项） | —               | **S + M**（datasets 过滤加 year/substring + records 端点扩过滤 + 新增跨 dataset 记录列表） |
| outline subtree                       | S               | S（不变）                                                                                  |
| LiteLLM function calling              | L               | L（不变）                                                                                  |
| **总前置工程量**                      | **~1.5 sprint** | **约 0.6-0.8 sprint**（主要仍是 LiteLLM tools 的 L + job-demand 过滤补齐）                 |

**决策**：

1. 按新的能力矩阵重写 §2.5 表格
2. 阶段 A 从"5 套 M 项"缩减为"1 个 L（LiteLLM）+ 2 个 M（job-demand 过滤 + 跨 dataset records 端点）+ 3 个 S（industry_policy 薄封装、outline subtree、chart 适配器）"
3. Layer 2 工具注册表命名按真实 API 对齐（job_demand / ability_analysis / capability_graph_by_major 等）
4. 场景 5 模板 tool 名同步对齐
5. Review Gate 1 增加"job-demand 全量过滤参数回归"一项

### 1.7 第七轮 —— 跨资产检索原则与聚合端点补齐

**提出方**：业务/架构

**核心原则**：

> `dataset_id` / `normalized_ref_id` / `build_id` **是数据处理层的 trace 字段**，用于审计与追溯；**检索入口必须以业务维度（major / subject / year / region / job_title 等）为主，允许跨资产聚合，trace 字段仅作输出携带（供 Composer 生成 source citation）**。

**评审方按此原则复核所有领域端点跨资产能力**：

| 领域                                 | 跨资产状态                                                                                 | 备注                                                                                  |
| ------------------------------------ | ------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------- |
| chunks 语义检索                      | ✅ 已跨 ref（pgvector）                                                                    | 主入口天然按语义，无 trace 依赖                                                       |
| major-distribution records           | ✅ 已跨（全维过滤完备）                                                                    | —                                                                                     |
| ability-analyses                     | ⚠️ 跨 ref 有，`major_name` **只 exact**，需 substring                                      | 新增 A1e                                                                              |
| job-demand records                   | ❌ 只 dataset-scoped                                                                       | 已列 A1c                                                                              |
| capability-graph-staging builds      | ⚠️ 跨 ref 有，但 **build 表无 `major` 字段**                                               | 无法直接按专业过滤                                                                    |
| capability-graph-staging nodes/edges | ❌ 只 build-scoped，必须两跳（且 build 表无 major 字段）                                   | 新增 A1f **by-major 一跳端点**（不做跨 build 聚合，见 §1.8）                          |
| knowledge-graphs nodes               | ⚠️ build-scoped，但 evidence graph 走 `/normalized-refs/{ref_id}/knowledge-graph` 反查够用 | 无需补                                                                                |
| knowledge-outline / task-outline     | ❌ ref-scoped                                                                              | 场景 3 靠 pgvector chunks + `heading_path` 间接满足，**跨 ref outline 端点延后到 P1** |

**追加决策**：

1. **§2.5 前置增加"跨资产检索原则"小节**，写进能力矩阵之前作为工具设计准则
2. **新增前置项 A1e**：`/record-assets/ability-analyses` 加 `major_name` substring 支持（S）
3. **新增前置项 A1f**（第八轮已修正为 by-major 一跳）：新增 `GET /capability-graph-staging/by-major?major=X&build_type=Y`，一跳返回单一 build 的 `{build_meta, nodes, edges}`；**不做多 build 聚合**（详见 §1.8）
4. **outline 跨 ref 端点确认延后到 P1**：场景 3 用 pgvector chunks + `heading_path` 元数据间接满足
5. **§4.2.1 关键约束新增一条**：工具输入以业务维度为主；trace 字段（`dataset_id` / `normalized_ref_id` / `build_id`）只作可选精确定位参数，且必须在响应中携带回来供 Composer 引用
6. **§5.1 `internal.query_capability_graph_by_major` tool 依赖 A1f**——不做 A1f 则该 tool 无法单跳完成检索

**净增前置工程量**：+1 S（A1e）+1 M（A1f）= **约 1 周**，仍在 §1.6 修正后的 ~0.6-0.8 sprint 范围内可吸收。

### 1.8 第八轮 —— capability-graph 检索维度勘误（去聚合、按 major 一跳）

**提出方**：业务/架构

**核心澄清**：第七轮 A1f 的表述"跨 build 聚合"是**错误方向**。**capability-graph 不需要跨 build 聚合**（一个 major 对应一份 build，业务上不合并多 build 的图），但**检索入口必须以 `major` / `major_code` 为主，不能以 `build_id` 为主**。

**修正后的语义**：

- 一个 `major` → 定位**单一 build**（通常取最新 `GENERATED` 状态） → 返回该 build 的 nodes+edges
- **不做多 build 结果合并**（避免语义冲突：不同 build 可能有不同来源/版本，合并会引入不可解释的噪声）
- Trace 字段（`build_id` / `normalized_ref_id`）在响应中携带回来，供 Composer 引用

**评审方复核实现路径**：

`capability_graph_staging_build` 表当前**没有 `major` 字段**（major 在 dataset 层），所以 by-major 检索有两个可行实现：

| 方案   | 描述                                                                                                                                                            | 工程量                                 |
| ------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------- |
| 方案 A | 新增语义端点 `GET /capability-graph-staging/by-major?major=X&build_type=Y`，后端做 build → dataset 反查 major，一跳返回单 build 的 `{build_meta, nodes, edges}` | **S~M**（无 schema 变更）              |
| 方案 B | 在 `capability_graph_staging_build` 加冗余 `major_name` / `major_code` 字段（写入时同步）+ `/builds` 加 major filter + `/by-major` 端点                         | **M**（含 alembic 迁移与写入路径修改） |

**决策**：**采用方案 A**（无 schema 变更，一跳返回）。future 若发现 build 列表按 major 检索也常用，再升级到方案 B。

> ⚠️ **本决策已被第十二轮反转为方案 B**（见 §1.12）：反查路径实现代价高、查询链路复杂、审计困难；且 major 可以从 `normalized_asset_ref.title` 稳定解析，冗余成本可控。**A1f 最终按方案 B 实现**。以下"追加决策"中的 A1f 工程量估算与相关表述已过期，以 §1.12 为准。

**追加决策**：

1. A1f 命名改为"capability-graph by-major 单跳端点"（去掉"聚合"字样）
2. ~~A1f 工程量从 M 修正为 **S~M**（按方案 A 估算）~~ → 第十二轮：方案 B 工程量 **M**
3. §2.5 B 表 nodes/edges 行的"缺口"描述改为"仅 build-scoped，需按 major 一跳定位"
4. §4.2.1 tool `internal.query_capability_graph_by_major` description 去掉"聚合"、明确"按 major 定位单 build 并返回其完整图"
5. §10 Gate 1 相应改为"capability-graph by-major 端到端验证（按 major + build_type 一跳拿单 build 完整图）"

### 1.9 第九轮 —— 前置任务范围裁剪（进入执行前的最小可用切片）

**提出方**：业务/架构

**核心动因**：进入前置任务执行前对 §10 阶段 A 做最后一次范围裁剪，剔除对 P0 检索链路非必需的项，压缩到最小可用切片。

**四项裁剪决策**：

1. **删除 A1a（job-demand datasets 过滤补齐）**
   - **理由**：`job-demand-dataset` 是容器（一个 normalized_ref 对应一个 dataset），**本身不含 job 数据**；对 dataset 层加 year / major / job_title 过滤在检索场景没有价值——真正被检索的是记录
   - **影响**：无检索链路影响

2. **A1b 合并 A1c 并聚焦到最小 2 维过滤** _（第十四轮 §1.14 进一步收窄为**仅 major**，job_title 也删除；本条历史决策以第十四轮为准）_
   - **A1b 新范围**：`GET /record-assets/job-demand-records` 跨 dataset 端点，支持 **`major`(substring，走 dataset join) + ~~`job_title`(substring)~~**（第十四轮删除）+ optional `normalized_ref_id`
   - **删除**：`salary_min` / `salary_max` / `experience_requirement` / `education_requirement` / `region` / `source_published_at` 范围等细粒度过滤
   - **理由**：P0 场景 5 岗位需求维度以 `major` + `job_title` 为主，细粒度过滤需求未验证；先保证跨 dataset 可用性
   - **影响**：LLM 想按薪资/学历/地域细筛时靠追问引导；不阻塞主链路
   - **A1c 删除**（并入 A1b）

3. **删除 A1d（产业政策薄封装）**
   - **理由**：无对应模型；场景 5 `step_policy` 允许命中率低，走 `on_empty: mark_generated_placeholder` + Composer ⚠️ 引用块
   - **影响**：场景 5 输出的"政策"部分常态由模型推断生成、明确打标；用户可据此再手动查资料

4. **A7 降级为最小可用**
   - **console 侧完整**：识别 console session + audit `caller_type` 落地
   - **api_caller 侧仅预留**：打 `caller_type=api_caller` 标签，权限逻辑与 console 一致，**不做差异化**
   - **理由**：P0 权限模型 = 凭证认证 + org_scope noop，双端口的差异化过滤未验证需求；先保证 open 入口能识别身份，差异化留 P1
   - **影响**：B6 (`POST /open/v1/query`) 变最小可用；对外契约不变

**范围裁剪后的前置总量**：

- 净删除：A1a（S~M）+ A1c（合并入 A1b）+ A1d（S）+ A7 半个 M ≈ **−10-13 人天**
- 新总量：**约 40-50 人天**，工期 **~2-3 周（1-1.5 sprint）**

**同步落点**：

- §10 阶段 A 表格重写（A1a/A1c/A1d 删除、A1b 重写、A7 降级）
- §10 依赖示意图更新
- §10 Gate 1 验收标准去掉 industry_policy smoke test；job-demand 回归改为核心 2 维过滤回归
- **生成前置任务包**：`docs/task-packages/wk_query_router_v2_p0_prerequisites_task_package.md`（按本决策 owner / deliverables / DoD 展开）

### 1.10 第十轮 —— step_policy 检索方式勘误（走 chunks 语义 + summary，不是 placeholder）

**提出方**：业务/架构

**核心澄清**：第九轮 §1.9 决策 #3 关于删除 A1d 的**理由描述有误**。产业政策是 **document-type 资产**（`primary_knowledge_type = industry_research_kb`，见 `config/governance_rules_v2.json:134`），走**知识管道 chunks 化 + pgvector 语义检索**通路；场景 5 `step_policy` 的正确实现是：

1. 用 `internal.search_chunks_by_semantic(query="{major_name} 相关行业政策", kb="industry_research_kb", top_k=5)` 拿到相关政策 chunks
2. Layer 3 Composer 对这些 chunks 做主题聚合 + summary（不是 `mark_generated_placeholder`）
3. **不是"命中率低走 placeholder"，而是"和其他 document-type 资产一样走 chunks 通路"**

**决策不变**：**A1d 仍然删除**（不需要结构化的 `internal.search_industry_policy` 端点，因为政策不是结构化资产）；但删除**理由**改为"政策是 document-type 资产，走 chunks 通路即可，无需专用结构化端点"。

**同步下游 3 处修正**：

1. **§1.9 决策 #3 理由重述**：从"允许命中率低走 placeholder"改为"document-type 资产走 chunks 语义 + summary，无需结构化端点"
2. **§5.1 talent_cultivation_plan.yaml `step_policy` tool** 从 `internal.search_industry_policy`（已删）改为 `internal.search_chunks_by_semantic`，参数 `kb="industry_research_kb"` + `top_k=5` + `expand_queries=true`
3. **§10 阶段 C C3 描述**：删除 "step_policy 走 mark_generated_placeholder" 字样；改为"step_policy 走 `internal.search_chunks_by_semantic` (kb=industry_research_kb)"
4. **§10 关键路径说明**：删除 "A1d / industry_policy 已删除" 段落里"常态走 mark_generated_placeholder"字样，改为"走 chunks 通路，不需要专用结构化 API"
5. **任务包**：A1d 删除理由同步修正；模板样例同步

**引申观察**（架构原则确认）：

- **Document-type 资产**（产业政策、产业报告、行业报告、专业简介、教材）→ 走 chunks + pgvector 语义检索 + Composer summary
- **结构化资产**（岗位需求、能力分析、专业布点、教学标准图谱）→ 走 structured internal API + LLM function call
- 这个二分法与 v2.0 §2.5 A/B 表分层一致；`step_policy` 归 document-type 分支

**同样适用于**：场景 2 综合性检索（"2025 年跨境电商行业发展趋势"）用 `internal.search_chunks_by_semantic(kb="industry_research_kb", top_k=8)` + Composer 汇总，已在 §4.2.5 Summary 场景描述中正确体现，无需修正。

### 1.11 第十一轮 —— 前置任务包评审反馈闭合（v2.0 定稿）

**提出方**：业务/架构，基于前置任务包（`docs/task-packages/wk_query_router_v2_p0_prerequisites_task_package.md`）与设计文档漏洞评审结论，做**发布定稿前的最后一次收敛**。

**九项决策**：

1. **A1f `build_type` 枚举值勘误** — 实际数据库中 `capability_graph_staging_build.build_type` 允许 `teaching_standard` / `job_demand` / `ability_analysis` / `combined`（小写字符串，非全大写枚举）。**A1f 与工具注册表示例中的枚举值全部改为小写**（~~`teaching_standard` / `job_demand`~~ → **第十二轮 §1.12 再次收敛为 `[teaching_standard, ability_analysis]`**，去掉 job_demand 因该类不涉及 major 冗余），与 db 契约对齐

2. **A5 同义 query 生成需新实现** — 前置调研宣称"v1 已具备多同义问题转换"，代码复核证实**该能力在 `retrieval/` 与 `index/` 目录下均无实现**。A5 定位改为**新增同义 query 生成组件**（不复用不存在的 v1 组件），实现方式：
   - 由 LiteLLM 生成 3-5 条同义/近义 query
   - 各条 query 独立 pgvector 召回
   - 结果按 `chunk_id` **去重合并**（简单 dedup，取最高分）
   - `expand_queries=false` 时行为与旧版完全一致
   - **不引入多路 rerank 融合**（第 3 条）

3. **多路 rerank 融合暂不必须** — 第九轮任务包 A5 提到"用 `retrieval/rerank.py` 的 `weighted_combine` 融合去重"实际 `rerank.py` 只有面向结构化 plan 的 `apply_weighted_rerank` / `apply_unstructured_weighted_rerank`，不适配多同义 query chunk 融合。**P0 暂不引入 rerank 融合，简单 dedup 已够用**；rerank 融合下沉 §11 非 P0

4. **A0 tool_call 缺失 → 降级 unknown 兜底** — Dispatcher 收到 LLM 未返回任何 tool call、或 tool_call 参数 Pydantic 校验连续失败 2 次时，**统一降级到 unknown 跨类型纯向量兜底路径**（§六），不做二次 LLM 重试。A0 单元测试 DoD 需覆盖此路径

5. **场景 2 走 chunks 语义 + summary（确认）** — 工具注册表补齐 `scenario_2` 分组，仅引用 `internal.search_chunks_by_semantic`（`kb=industry_research_kb`），Composer 用 `RetrievalSummaryService` 做汇总。**不新增专用 report 检索工具**

6. **`config/query_router_tools.json` 无控制台编辑需求** — 该文件由后端工程师随代码 PR 维护，**不引入 ETag / fcntl / 编辑审计等控制台编辑保护**（与 `governance_rules.json` 的治理模式区分）；仅保留 Pydantic 校验 + JSON 静态 lint

7. **A5 A/B 评测取消** — Gate 1 不再要求"expand_queries 对场景 1 召回率的 A/B 评测归档"。**同义 query 生成的正确性以单元测试覆盖**（生成条数、去重逻辑、`expand_queries=false` 回归）即可

8. **A1f / A1e 性能基线不纳入 P0** — 反查性能、`major_name` substring 索引升级留作运维层面观察项；**P0 阶段不做基线测量与 GIN trigram 索引前置**。若上线后出现慢查询再触发升级

9. **`industry_research_kb` 混装（产业政策 / 产业报告 / 行业报告）确认** — 三类资产共用同一 `primary_knowledge_type` 是既定架构，检索粒度控制交由 Composer summary + query semantics 承担，**不新增 report_type / subject metadata 二次过滤维度**（未来若召回噪声成为投诉集中项再评估）

**未在本轮闭合但仍保留的漏洞修复项**（作为文档定稿附带修订）：

- **A0 ↔ A3 联调 DoD**：A3 DoD 增加"用 A0 fake client 试跑一遍 tool schema"（避免 schema 到集成期才发现不兼容）
- **A6 ↔ A7 依赖闭环**：A6 依赖图明确写 A6 → A7（audit 事件 `caller_type` 字段值由 A7 填入）；A8 补 audit 事件字段端到端回归
- **老端点 `caller_type` 回填**：A7 完成后 `/open/v1/search` / `/open/v1/qa` 也开始记录 `caller_type=api_caller`；A8 回归覆盖此点
- **A4 chart_id 生成规则 + 流式替换时序**：§7 新增说明——chart_id 由后端在 tool 结果序列化时生成（`{tool_call_id}:{chart_index}` 形式）；`[[CHART:xxx]]` 占位替换在 **Composer 流完全结束后统一替换**，不做增量替换
- **§3.3 双入口鉴权表述勘误**：`/internal/v1/query` 走 **JWT session**（`nexus-api/nexus_api/dependencies/user.py` 已实现），非"内部信任"
- **工具注册表补齐 scenario_2 / scenario_3 分组**：与设计文档 §4.1 五类场景一一对应

**同步落点**：

- §2.5 A 表：query 转换（多同义问题）状态从 ✅ 改为 ❌，工程量 S
- §3.3 表：`/internal/v1/query` 鉴权表述改为"JWT session"
- §4.2.1：build_type 枚举小写化、补 scenario_2 / scenario_3 分组
- §4.2.2：dispatcher 流程补 tool_call 缺失降级路径
- §5.1：`step_standard` 的 `build_type: teaching_standard` 小写化
- §7：新增 chart_id 生成规则 + 流式替换时序说明
- §10：A0/A1f/A5/A6/A8 DoD 与依赖图更新；Gate 1 去掉 A/B 评测、加 audit 端到端回归、加 tool_call 缺失兜底 smoke test
- §11：rerank 多路融合 + A/B 评测下沉

### 1.12 第十二轮 —— A1f 方案反转：方案 A → 方案 B（build.major_name 冗余）

**提出方**：业务/架构，在阶段 A 尚未开工前对第八轮"采用方案 A（build → dataset 反查 major）"的最终反转。

**核心动因**：

1. **反查链路复杂度**：方案 A 需在 A1f 端点内做 `build → normalized_asset_ref → dataset → major_name` 多跳 join，实现代码分支多（不同 build_type 反查不同 dataset 表）；测试与审计困难
2. **major 数据来源已稳定**：`normalized_asset_ref.title` 里的专业名可以**在 build 生成时一次性解析并冗余**到 `capability_graph_staging_build.major_name`，写入路径简单可控
3. **业务维度收敛**：**只有专业教学标准、专业简介、职业能力分析表三类数据资产**涉及 major 业务维度；其中**产生 capability_graph_staging_build 的仅两类**（专业教学标准、职业能力分析表），major 冗余列写入路径明确
4. **`build_type=job_demand` 类 build 不涉及 major 冗余**：岗位需求数据的 major 已经在 `job_demand_dataset.major_name`，`internal.query_job_demand`（A1b 跨 dataset records 端点）直接按 major 过滤，**不需要走 A1f**；场景 4 岗位角色图走 `internal.get_job_demand_role_graph(dataset_id)`，也不需要 A1f

**方案 B 具体实现（反转后）**：

- **Schema 变更**（alembic 迁移）：`capability_graph_staging_build` 加 `major_name: String(256) | None` 列 + `Index("ix_cgsb_major_name", "major_name")`
- **写入路径变更**：build 生成流程（`nexus-app` 内 build 生产者）在构造 build 时：
  - 对 `build_type ∈ {teaching_standard, ability_analysis}`：从 `normalized_asset_ref.title` 解析 major_name 并写入 build.major_name
  - 对 `build_type ∈ {job_demand, combined}`：major_name 留空（这两类 build 不通过 A1f 检索）
  - 解析规则：优先取 title 中"XX 专业教学标准"或"XX 职业能力分析表"的"XX"部分；解析失败时留空并记录 warn 日志（不阻断 build 生成）
- **A1f 端点简化为单表查询**：
  ```sql
  SELECT * FROM capability_graph_staging_build
  WHERE major_name ILIKE :major
    AND build_type = :build_type
    AND status = 'GENERATED'
  ORDER BY created_at DESC LIMIT 1
  ```
- **A1f `build_type` 枚举收敛**：从 `[teaching_standard, job_demand]` 改为 **`[teaching_standard, ability_analysis]`**（去掉 job_demand，加上 ability_analysis 支持职业能力分析表检索场景）
- **数据回填**：alembic 迁移执行时对已存在的 `teaching_standard` / `ability_analysis` 类 build 做一次性回填（通过关联 `normalized_asset_ref.title` 解析）

**三类涉及 major 的数据资产 vs build 产生情况**：

| 数据资产       | primary_knowledge_type            | 产生 capability_graph_staging_build？ | major 从哪里来                          |
| -------------- | --------------------------------- | ------------------------------------- | --------------------------------------- |
| 专业教学标准   | course_standard_authoring_process | ✅ `build_type=teaching_standard`     | 本轮：build.major_name（从 title 解析） |
| 职业能力分析表 | competency_graph                  | ✅ `build_type=ability_analysis`      | 本轮：build.major_name（从 title 解析） |
| 专业简介       | （document-type，走 chunks 通路） | ❌ 无 build                           | chunks metadata + heading_path 承载     |

**同步落点**：

- **§1.8**：加"决策已被第十二轮反转为方案 B"警示（已完成）
- **§2.5 B 表**：`/capability-graph-staging/builds` 行标注新增 major_name 冗余列；nodes/edges 行的"缺口"改为"仅 build-scoped，需按 major 一跳定位（通过 build.major_name 直接过滤）"
- **§4.2.1 tool schema**：`internal.query_capability_graph_by_major` 的 `build_type` enum 改为 `[teaching_standard, ability_analysis]`；description 增加"覆盖专业教学标准与职业能力分析表两类资产"
- **§5.1 YAML**：`step_standard.build_type: teaching_standard` 保持不变
- **§10 A1f**：完全重写——schema 迁移 + 写入路径 + 查询简化 + 数据回填 + 工程量 **M**（含 alembic 迁移）
- **§10 依赖示意图**：A1f 增加"依赖 build 生产者写入路径修改"提示；build 表变更需产品数据管道联动测试
- **§10 Gate 1 第 5 条**：`build_type ∈ {teaching_standard, ability_analysis}`（去掉 job_demand）+ "回填数据正确性验证"
- **任务包 A1f / Gate 1 / 风险表**：同步

**新增风险**（同步 §10 风险表）：

| 风险                 | 触发条件                                                                     | 降级                                                                                                      |
| -------------------- | ---------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| title 解析规则鲁棒性 | 部分资产 title 无标准命名（如"电商专业教学标准（2024 修订版）"）导致解析失败 | 留空 major_name + warn 日志；A1f 查询该 build 时返回 404；由数据管理员人工补录（未来考虑用 LLM 兜底解析） |
| 数据回填失败         | 迁移时对存量 build 回填失败                                                  | 迁移脚本 idempotent；失败条目记入 `migration_backfill_errors` 表由 DBA 复检                               |
| build 生产者路径遗漏 | 写入路径修改未覆盖所有 build 生成入口                                        | 通过 CI 断言 `teaching_standard`/`ability_analysis` build 落库时 major_name 必非空（除解析失败白名单外）  |

### 1.13 第十三轮 —— A1f 复用平台已有 identity 抽取器 + 双列冗余 + major_name 归一化

**提出方**：业务/架构，在阶段 A 开工前基于对 NEXUS 平台专业教学标准与专业简介真实数据的核对做实施路径澄清。

**核心发现**（代码复核）：

1. **平台已有两处成熟的 identity 抽取器，无需新建**：
   - `nexus-app/nexus_app/teaching_standard/extractor.py:207` `_major_identity(title, blocks)` → `(major_code, major_name)`
     - 优先匹配"名称在前括号数字在后"：`电子商务（530701）` → `("530701", "电子商务")`
     - 兜底匹配"数字在前名称在后"：`5307 电子商务类` → `("5307", "电子商务类")`
   - `nexus-app/nexus_app/major_profile/extractor.py:195` `_extract_identity(title, text)` + `_iter_labeled_identities()` → `(major_code, major_name)`
     - 优先匹配结构化标签：`专业代码 X 专业名称 Y`
     - 兜底同上正则策略；用 `_clean_name` 做基础清洗

2. **既有 major_name 存在语义漂移**（bug 或历史遗留）：
   - `test_teaching_standard_graph.py:33` 断言 `major_name == "电子商务专业教学标准"`——从 title `"5307 电子商务专业教学标准"` 用正则贪婪匹配把资产类型后缀"专业教学标准"也吸进去了
   - **A1f 端点需要的 major_name 是"电子商务"这样的纯专业名**，不是带类型后缀的字符串
   - **必须在写入 `build.major_name` 前做归一化**：剥离"专业教学标准" / "专业简介" / "职业能力分析表" / "类"等资产类型 / 分类后缀词

3. **major_code 是天然的稳定业务键**（既有抽取器自然产出）：
   - 4 位 = 专业类（如 `5307 电子商务类`）
   - 6 位 = 具体专业（如 `530701 电子商务`）
   - **A1f 应同时冗余 `major_code` 与 `major_name` 双列**，端点支持两条通路：
     - `major_code` **精确匹配**（stable，无歧义）
     - `major_name` **substring 模糊匹配**（user-friendly，允许别名如"跨境电商" / "跨境电子商务"）

4. **真实 title 样本**（从 `test_teaching_standard_graph.py` + `test_major_profile.py` + `governance_rules_v2.json` 汇总）：

   **专业教学标准（build_type=teaching_standard）**：
   - `"5307 电子商务专业教学标准"`（编号 + 名称 + 类型后缀）
   - `"电子商务专业教学标准"`（无编号，identity 从 block 正文抽）
   - `"电子商务（530701）专业教学标准"`（名称 + 括号编号 + 类型后缀）
   - `"电子商务专业教学标准"`（identity 从 block "电子商务（530701）" 抽出）

   **专业简介（build_type= 无 build，document-type 走 chunks 通路）**：
   - `"（高职电子商务类专业简介）5307 电子商务类"`（前缀括号带教育层级+类型标签 + 后缀编号）
   - `"专业简介"`（governance_rules_v2 别名）
   - `"院校专业简介"`、`"电子商务类专业简介"`、`"财经商贸大类教学标准"`

   **职业能力分析表（build_type=ability_analysis，样本待业务补齐）**：
   - 目前仓库中尚无直接测试样本；解析规则可复用 `_major_identity` 通用正则

5. **方案 B 实现路径最终确定**：

   | 步骤                 | 变更                                                                                                | 复用 or 新建                                      |
   | -------------------- | --------------------------------------------------------------------------------------------------- | ------------------------------------------------- |
   | 1. Schema 变更       | `capability_graph_staging_build` 加 `major_name: String(256)                                        | None`+`major_code: String(16)                     | None` + 复合索引 | 新建（alembic 迁移） |
   | 2. identity 抽取     | 调 `teaching_standard.extractor._major_identity()` 或 `major_profile.extractor._extract_identity()` | **复用**（两者按 build_type 分派）                |
   | 3. major_name 归一化 | 新增 `capability_graph.major_normalizer.normalize_major_name(raw_name) -> str`                      | **新增小工具**（剥离资产类型后缀 / 保留纯专业名） |
   | 4. build 生产者写入  | 对 teaching_standard / ability_analysis 类 build 调用步骤 2 + 3 + 写入两列                          | 修改既有 build 生产者路径                         |
   | 5. 数据回填          | 迁移时对已存在 build 一次性回填两列                                                                 | 新建脚本                                          |
   | 6. A1f 端点          | 直接查 `WHERE (major_code = :code OR major_name ILIKE :major_substr)`                               | 新建                                              |

6. **归一化函数职责**（`normalize_major_name`）：
   - **剥离后缀词**：`"专业教学标准" | "专业简介" | "职业能力分析表" | "教学标准"` 等（从 `governance_rules_v2.json:769-825` / `1071-1088` 别名列表整理）
   - **剥离"类"后缀**（业务决策更新）：`"电子商务类"` → `"电子商务"` 与 `"电子商务"` 统一归一化到同一 major_name。理由：
     - 统一后 build.major_name 表达纯专业名，语义干净
     - 父子关系区分靠 `major_code` 位数（4 位 = 类，6 位 = 具体专业）承担，业务维度不丢
     - 检索端点 `major_name` 用 substring `ILIKE '%X%'` 模糊匹配，用户查 `"电子商务"` 天然命中所有归一后为 `"电子商务"` 的 build（含原本"电子商务类"）
     - 剥离规则：结尾单个"类"字（如"电子商务类" → "电子商务"）；避免误剥离固有专业名（如"财经商贸大类" → 保留，因为"大类"是复合词非单字"类"后缀；用正则 `re.sub(r"(?<!大)类$", "", name)` 或专门白名单处理）
   - **保留括号内规范化补充**：`"电子商务（跨境方向）"` → 保留（不切）
   - **单元测试样本**：至少覆盖上述所有真实 title 样本

7. **端点参数调整**：
   - Query params 从 `major` 一个字段拆为 `major_name`（substring）+ `major_code`（精确）两个 **at-least-one-required**
   - Response `build_meta` 增加 `major_code` trace 字段

**同步落点**：

- §2.5 B 表：`/capability-graph-staging/builds` 行由"加 major_name 冗余列"改为"加 major_name + major_code 双列"
- §4.2.1 tool schema `internal.query_capability_graph_by_major` 参数：`major` → `{major_name?, major_code?}`（at-least-one-required）
- §10 A1f：交付物调整为"复用现有抽取器 + 归一化小工具 + 双列冗余"；工程量 M 不变（复用抵消归一化 + 双列冗余的额外成本）
- **任务包 A1f**：同步；title 样本清单直接内联（不再需要业务 owner 额外提供）

### 1.14 第十四轮 —— A1b 端点参数进一步收窄到仅 major（去掉 job_title 等所有细粒度过滤）

**提出方**：业务/架构，在阶段 A 开工前对 A1b（跨 dataset job-demand-records 端点）参数做最终收窄。

**决策**：**A1b 只保留 `major`(substring, 走 dataset join) + `normalized_ref_id`(optional trace)**，删除包括 `job_title` 在内的**全部细粒度过滤维度**。

**具体删除清单**：

| 参数                        | 第九轮 §1.9 决策 #2 状态 | 第十四轮 §1.14 状态             |
| --------------------------- | ------------------------ | ------------------------------- |
| `major`                     | ✅ 保留                  | ✅ **保留（唯一业务过滤维度）** |
| `job_title` (substring)     | ✅ 保留                  | ❌ **删除**                     |
| `salary_min` / `salary_max` | ❌ 已删                  | ❌ 保持删除                     |
| `experience_requirement`    | ❌ 已删                  | ❌ 保持删除                     |
| `education_requirement`     | ❌ 已删                  | ❌ 保持删除                     |
| `region`                    | ❌ 已删                  | ❌ 保持删除                     |
| `source_published_at` 范围  | ❌ 已删                  | ❌ 保持删除                     |
| `normalized_ref_id` (trace) | ✅ 保留                  | ✅ 保持（trace 字段）           |

**理由**：

1. **需求未验证**：P0 阶段场景 5 `step_demand` 的实际使用模式是"按专业拉取岗位需求汇总"，`job_title` 精细化过滤在业务侧未提出明确用例
2. **LLM 追问兜底充分**：若确实需要按岗位标题 / 薪资 / 地域细筛，Composer 可以在拿到 major-scoped 记录后按需追问用户或自行筛选
3. **端点契约稳定**：细粒度过滤一旦上线难以下线；P0 保守起见先只做刚需，未来按投诉集中项增量补齐
4. **降低测试成本**：过滤参数越少，测试组合空间越小，A8 回归工作量线性下降

**影响链条**：

- **§2.5 B 表**：跨 dataset records 行"缺口"列——从"新增跨 dataset 端点支持 major + job_title"改为"新增跨 dataset 端点仅支持 major"
- **§4.2.1 tool schema `internal.query_job_demand`**：参数 schema **大幅精简**——只保留 `major` (required) + `normalized_ref_id` (optional trace) + `fields` (返回字段白名单)；**删除** `year_range` / `region` / `industry` / `job_title` / `enterprise_size` / `employment_type` / `salary_min` / `salary_max` / `experience_requirement` / `education_requirement`
- **§5.1 talent_cultivation_plan.yaml `step_demand` inputs**：删除 `year_range` / `region` 输入项，仅保留 `major` + `fields`
- **§10 A1b 行**：描述从"major(substring) + job_title(substring) + normalized_ref_id"改为"仅 major(substring) + normalized_ref_id"
- **§10 Gate 1 第 3 条**：从"major substring + job_title substring 跨 dataset"改为"仅 major substring 跨 dataset"
- **§10 关键路径说明**：A1b 描述改为"仅 major 一维过滤"
- **任务包 A1b**：Query params / DoD / Scope 摘要 / 依赖图 / Gate 1 同步；单元测试从"3 dataset × major/job_title 命中"简化为"3 dataset × major 命中"

**同步落点**：

- §1.9 决策 #2 加勘误注脚（已完成）
- §2.5 B 表：跨 dataset records 缺口列更新
- §4.2.1 tool schema：`internal.query_job_demand` 参数精简
- §5.1 YAML：`step_demand` inputs 精简
- §10 A1b + Gate 1 + 关键路径 + 依赖图
- 任务包 A1b + Gate 1 + Scope + 依赖图

**不变**：

- A1b 仍是跨 dataset 端点（不是 dataset-scoped）——**跨资产原则未变**
- major 走 `job_demand_dataset.major_name` join，不用 industry_name 兜底（第十一轮闭合项未变）
- `normalized_ref_id` 作为可选 trace 精确定位参数保留

### 1.15 第十五轮 —— 5 场景业务视角对齐 + 场景 3 双路 + 场景 2 岗位行业分布 Top-5

**提出方**：业务/架构，在阶段 A 开工前基于对**用户场景表述**与**平台真实数据能力**的复核，把 5 类检索场景从"按检索行为分类"转为"按资产类型 + 输出形式分类"，并补齐两个能力缺口。

**核心动因**：

原 v2.0 §1.1 五场景按检索行为分类（精确知识块 / 综合性 / 实训任务 / 图谱 / 复杂），与业务方按数据资产分类的表述有落差；且检查中发现两处能力缺口：**专业教学标准培养目标/职业面向字段缺失** + **岗位行业分布 Top-5 聚合响应未落实**。

**决策**：

#### 1. 场景编号 scenario_1 - scenario_5 语义重映射（C3 方案）

编号保留（避免 audit `intent` 字段值域重构 / 审计 schema 冲击），但**每编号的业务语义按用户新分类重定义**：

| 编号       | v2.0 原语义            | **v2.0.1 新语义**             | 覆盖资产                                                  | 输出形式                                                                              |
| ---------- | ---------------------- | ----------------------------- | --------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| scenario_1 | 精确知识块检索（教材） | **讯息类检索**                | 产业政策 / 产业报告 / 行业报告                            | 语义 chunks + Composer summary                                                        |
| scenario_2 | 综合性检索（summary）  | **结构化数据检索**            | 岗位需求 / 职业能力分析 / 专业布点                        | 按 major / job_title 拿：**岗位行业分布 Top-5**、岗位角色图、专业能力图谱、专业布点表 |
| scenario_3 | 实训任务类检索         | **专业教学标准综合检索**      | 专业教学标准                                              | **双路**：岗位知识图谱 + 培养目标 / 职业面向 chunks                                   |
| scenario_4 | 图谱类数据检索         | **教材类检索**                | 电子商务基础 / 核心课程教材（含实训教材，按 kb 参数区分） | 语义 chunks + 章节大纲 + 证据图                                                       |
| scenario_5 | 复杂检索类型           | **Agentic RAG（多步骤模板）** | 跨资产                                                    | 人才培养方案模板执行器                                                                |

**为什么保留数字编号而非改名**：

- audit_log.summary 已经在写 `intent=scenario_1..5` 字符串字面量，改名会破坏历史审计的可查询性
- 意图分类器 Prompt 里 enum 值仍是 `scenario_1..5`，只是判定条件描述变
- 每处引用带业务副标题（如 `scenario_2 (结构化数据检索)`），可读性不损

#### 2. 场景 3 走**双路**（问题 A 的 A2 方案）

**背景**：`nexus_app/teaching_standard/extractor.py:85-90` 的输出**只有** `major_code / major_name / rows`（表格行——岗位领域/工作任务/技能知识要求），**没有 `training_goal` / `occupation_oriented`**。而用户场景 3 要求"培养目标 + 职业面向 + 岗位知识图谱"三件套。

**方案 A2（决策）**：

- **图谱通路**：`internal.query_capability_graph_by_major(major, build_type=teaching_standard)` → 拿岗位知识图谱（既有 A1f）
- **文本通路**：`internal.search_chunks_by_semantic(kb="course_standard_authoring_process", outline_node="培养目标|职业面向", top_k=5)` → 拿培养目标 / 职业面向段落
- **Composer 汇总**：并行拿两路结果后，模板结构化输出"培养目标 / 职业面向 / 岗位知识图谱"三段

**优点**：零新增结构化字段 / 迁移；工具复用；仅意图分类器 Prompt + 工具注册表 scenario_3 分组 + Composer prompt 调整

**限制**：`outline_node="培养目标"` / `"职业面向"` 需要教学标准 chunks 化时 `heading_path` 已带这两个章节标题（通常成立，教学标准正式发布文档结构固定）；如未成立则退化为纯语义 top-K

#### 3. 场景 2 岗位行业分布 Top-5 聚合响应（问题 B 的 B1 方案）

**背景**：`internal.query_job_demand` 的 `fields=industry_distribution` 参数已在 tool schema 里存在（§4.2.1），但 A1b 交付物未规定后端聚合行为，Composer 自行 GROUP BY 效率与准确性无保证。

**方案 B1（决策）**：

- A1b 端点检测请求参数 `fields=industry_distribution` 或类似字段时，后端做：
  ```sql
  SELECT industry_name, COUNT(*) AS count
  FROM job_demand_record jdr JOIN job_demand_dataset jdd ON jdr.dataset_id = jdd.id
  WHERE jdd.major_name ILIKE :major
  GROUP BY industry_name
  ORDER BY count DESC
  LIMIT 5
  ```
- 响应结构：`{records: [...], aggregations: {industry_distribution: [{industry_name, count}, ...] | null}}`
  - 参数不含 `industry_distribution` 时 `aggregations.industry_distribution = null`
- A1b DoD 补：聚合正确性 unit test（3 个 industry 分布 + Top-5 截断 + 空分布边界）

#### 4. 工具注册表 §4.2.1 按新场景语义重分组

**跨 scenario 迁移清单**：

| 工具                                                                        | v2.0 原分组 | **v2.0.1 新分组**                                                         |
| --------------------------------------------------------------------------- | ----------- | ------------------------------------------------------------------------- |
| `internal.search_chunks_by_semantic (kb=industry_research_kb)`              | scenario_2  | **scenario_1 (讯息类)**                                                   |
| `internal.query_job_demand`                                                 | scenario_5  | **scenario_2 (结构化)**                                                   |
| `internal.query_ability_analysis`                                           | scenario_5  | **scenario_2 (结构化)**                                                   |
| `internal.query_major_distribution`                                         | scenario_5  | **scenario_2 (结构化)**                                                   |
| `internal.get_job_demand_role_graph`                                        | scenario_4  | **scenario_2 (结构化)**（岗位角色图属结构化输出）                         |
| `internal.query_capability_graph_by_major (build_type=ability_analysis)`    | scenario_4  | **scenario_2 (结构化)**                                                   |
| `internal.query_capability_graph_by_major (build_type=teaching_standard)`   | scenario_4  | **scenario_3 (专业教学标准，双路之一)**                                   |
| `internal.search_chunks_by_semantic (kb=course_standard_authoring_process)` | 未列        | **scenario_3 (专业教学标准，双路之一)**（新增）                           |
| `internal.search_chunks_by_semantic (kb=course_textbook)`                   | scenario_1  | **scenario_4 (教材类)**                                                   |
| `internal.search_chunks_by_semantic (kb=practical_training_kb)`             | scenario_3  | **scenario_4 (教材类)**（实训并入教材，按 kb 区分）                       |
| `internal.get_evidence_graph_by_ref`                                        | scenario_1  | **scenario_4 (教材类，章节知识图谱)**                                     |
| `internal.get_outline_subtree`                                              | 未列        | **scenario_4 (教材类)**                                                   |
| （scenario_5 模板工具集）                                                   | scenario_5  | **scenario_5 (Agentic RAG)**（模板 whitelist 引用其他 scenario 的 tools） |

#### 5. 实训场景归入 scenario_4 内部（按 kb 参数区分）

用户新分类里"教材类"未显式提到实训教材，但业务上实训教材仍需检索。方案：**scenario_4 内部按 `kb` 参数区分**普通教材 (`course_textbook`) vs 实训教材 (`practical_training_kb` 或类似 code）；意图分类器不再单独区分实训 vs 普通教材，交由参数抽取器处理。

#### 6. 意图分类器 Prompt 需重写

Layer 1 意图分类器（§4.1.1）的判定条件必须按新语义重写。**判定关键词参考**：

| scenario      | 判定关键词（示例）                                               |
| ------------- | ---------------------------------------------------------------- |
| 1 讯息类      | 政策 / 报告 / 行业趋势 / 发展方向 / 综述                         |
| 2 结构化      | 岗位需求 / 招聘 / 薪资分布 / 专业布点 / 能力分析 / 就业方向      |
| 3 教学标准    | 教学标准 / 培养目标 / 职业面向 / 专业岗位知识图谱 / 专业核心课程 |
| 4 教材        | 课程 / 教材 / 章节 / 实训 / 知识点 / 概念                        |
| 5 Agentic RAG | 培养方案 / 规划 / 综合方案 / 多步骤                              |

#### 7. 同步落点

- **§1.1 五类场景**：加副标题按新业务语义描述
- **§4.1.1 意图分类器**：判定条件按新语义重写；输出 enum 值域不变
- **§4.2 边界处理**：场景 1 vs 3、场景 2 vs 5 等新的边界描述
- **§4.2.1 工具注册表**：完整按上述分组重排；scenario_3 引入 `internal.search_chunks_by_semantic(kb=course_standard_authoring_process)` 作为双路之一
- **§4.2.5 Summary 场景（原 scenario_2 内部特化）**：并入 scenario_1
- **§5.1 talent_cultivation_plan.yaml**：模板 `step_standard` 保持不变；新增 `step_talent_context`（可选）走 scenario_3 双路（如需）
- **§10 A1b DoD**：加 industry_distribution 聚合响应
- **§10 Gate 1**：第 3 条加 industry_distribution 聚合验收；新增第 13 条"scenario_3 双路 smoke test"
- **§10 Gate 2**：意图分类离线评测样本按新语义标注（5 × 20）
- **任务包 A1b / A3 / Scope / Gate 1**：同步

**工程量变化**：

- 无新增前置任务（A1-A8 结构不变）
- A1b 工程量 M 上限收敛到 6-7 人天（加聚合逻辑）
- A3 工程量 M 不变（重分组不增加工作量，仅调整 JSON 分组）
- 意图分类器 Prompt 重写在阶段 B B1/B2 完成，不冲击阶段 A

**不变项**：

- 编号 `scenario_1..5` 字符串字面量不变（audit 值域稳定）
- 5 类数据资产范围不变（9 类中的 5 类被显式覆盖）
- P0 工具接口（`internal.*`）签名不变，只是分组归属变
- 模板执行器（scenario_5）架构不变

---

## 二、方案背景与目标（含前置条件与能力矩阵）

### 2.1 现状

- NEXUS P0 已实现四层检索框架（intent / planner / rerank / pgvector 执行器），但**未接入 `/open/v1/*` 或 `/internal/v1/*` 对外链路**：`intent.py`、`planner.py` 目前是内部埋点，对外仍是 pgvector 单路
- Prompt / 权限 / 审计 / Index 契约已就位（见 `ARCHITECT.md`、`SPEC.md`）
- **缺口**：面向业务的"提问 → 富文本答复"闭环缺乏统一编排层，用户每次要自己拼多个 API

### 2.2 P0 资产范围（9 类）

**非结构化 + 结构化混合**：

- 产业政策 / 产业报告 / 行业报告（非结构化文档 + summary 视图）
- 岗位需求数据 / 职业能力分析表 / 专业布点数据（结构化领域模型表 + 岗位/专业能力图谱）
- 专业教学标准（结构化教学标准 + 岗位知识图谱）
- 专业简介（半结构化）
- 电子商务类基础/核心课程教材（chunks + outline + evidence graph）

### 2.3 5 类检索场景（业务定义，v2.0 全部承接；**第十五轮 §1.15 语义重映射**）

**§1.1 是第一轮原始表述（按检索行为分类）**，v2.0 定稿实际以 **§1.15 第十五轮的业务视角分类**为准。两者编号 `scenario_1..5` 一致，语义按下表映射：

| 编号         | v2.0.1 业务视角语义（P0 实际实现基线）     | 覆盖数据资产                       | 主输出形式                                               |
| ------------ | ------------------------------------------ | ---------------------------------- | -------------------------------------------------------- |
| `scenario_1` | **讯息类检索**                             | 产业政策 / 产业报告 / 行业报告     | 语义 chunks + Composer summary                           |
| `scenario_2` | **结构化数据检索**（按 major / job_title） | 岗位需求 / 职业能力分析 / 专业布点 | 岗位行业分布 Top-5、岗位角色图、专业能力图谱、专业布点表 |
| `scenario_3` | **专业教学标准综合检索**（双路）           | 专业教学标准                       | 岗位知识图谱 + 培养目标 / 职业面向 chunks                |
| `scenario_4` | **教材类检索**（含实训，按 kb 参数区分）   | 电子商务基础 / 核心课程 / 实训教材 | 语义 chunks + 章节大纲 + 证据图                          |
| `scenario_5` | **Agentic RAG**（多步骤模板执行器）        | 跨资产                             | 人才培养方案模板                                         |

详见 §1.15。

### 2.4 目标

- 提供**统一的自然语言检索入口**，对内对外分别一个
- 保持**平台契约红线**（Prompt 版本化、审计、权限、非持久化 generated 无需治理）
- **合并现有四层框架为单轨 v2.0**，减少长期维护成本

### 2.5 方案实施前置条件与能力矩阵

> 本节基于对 `nexus-app` / `nexus-api` 源代码的实际调研，列出 v2.0 落地依赖的**已有能力**和**必须先补齐的缺失能力**。缺失项按阻塞程度分级：**阻塞**（不做则对应场景无法上线）/ **协同**（不做则该场景降级但可上线）/ **优化**（不做不影响功能）。

> **本表已按 §1.6 / §1.7 勘误全量修正**。之前判断"3 套结构化 API 缺失"源于命名不对齐（业务口径 vs 代码口径），实际均已具备；新增"结构化数据过滤能力评估"细项与"跨资产聚合端点评估"细项。

#### 2.5.0 跨资产检索原则（P0 工具设计准则）

> **`dataset_id` / `normalized_ref_id` / `build_id` 是数据处理层的 trace 字段**，用于审计与追溯；**检索入口必须以业务维度（major / subject / year / region / job_title 等）为主，允许跨资产聚合，trace 字段仅作输出携带**（供 Composer 生成 source citation）。

**推论**：

- 所有 Layer 2 工具的输入 schema **以业务维度为必填/主字段**，trace 字段最多作为**可选的精确定位参数**（例如"我明确要看某一份"时使用）
- 所有 Layer 2 工具的输出 schema **必须携带 trace 字段**（`normalized_ref_id` / `dataset_id` / `build_id` 等），供 Composer 生成脚注引用
- 领域 API 若只暴露 trace-scoped 端点（如 `/datasets/{id}/records` 无跨 dataset 版本、或 `/builds/{id}/nodes` 无按业务维度聚合版本），**必须在阶段 A 补齐聚合端点**，否则该业务场景无法单跳完成

**A. 平台底座能力**

| 能力                                | 状态                      | 证据                                                                                                                                                                          | 阻塞等级              | 工程量    |
| ----------------------------------- | ------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------- | --------- |
| 知识图谱 nodes+edges 结构           | ✅ 已具备                 | `KnowledgeGraphNode/Edge/Fact` @ `models.py:2203-2310`；`evidence_graph.py:35-358` 端点齐全                                                                                   | —                     | —         |
| 知识图谱 → chart JSON 适配层        | ⚠️ 缺失（薄适配）         | 需在图 API 返回后加序列化层输出 `chart:echarts` fence 所需 schema                                                                                                             | 阻塞场景 4            | **S**     |
| 报告 summary 能力                   | ✅ 部分具备               | `RetrievalSummaryService` @ `retrieval/summary.py`、`internal/knowledge_retrieval.py:46-79` 已支持 LLM 汇总；缺按报告维度的二次聚合                                           | 协同场景 2            | S（复用） |
| outline subtree 查询 API            | ⚠️ 部分具备               | `KnowledgeOutlineNode.parent_id` 树结构存在（`models.py:1046-1098`）；`knowledge_outline.py:99-158` 有 chunks/preview，**缺按 node_id 查子树**                                | 阻塞场景 3            | **S**     |
| audit_log 字段扩展                  | ✅ 零成本                 | `audit.py:91-116` `summary` 已是自由 JSON dict                                                                                                                                | —                     | —         |
| LiteLLM function calling / tool use | ❌ 完全缺失               | `LiteLLMClientProtocol` @ `ai_governance/litellm_client.py:50-59` 未支持 tools/tool_choice；`RealLiteLLMClient.call()` @ line 78-99 亦未传 tools                              | **阻塞场景 1-5 全部** | **L**     |
| api_caller vs console 身份区分      | ⚠️ 部分具备               | `main.py:10-12` 已双路由；`permissions.py:22-63` 逻辑相同（P0 noop）；未显式打身份标                                                                                          | 阻塞 §3.3 双入口      | **M**     |
| query 转换（多同义问题）            | ❌ 需实现（第十一轮勘误） | 代码复核确认 `retrieval/` 与 `index/` 均无同义 query 生成实现；A5 定位为**新增能力**，由 LiteLLM 生成 3-5 条同义 query + 独立召回 + 简单 dedup（不引入 rerank 融合）          | 阻塞场景 1、5 精度    | **S**     |
| weighted rerank（结构化 plan）      | ✅ 已具备                 | `retrieval/rerank.py` 中 `apply_weighted_rerank` / `apply_unstructured_weighted_rerank`，服务结构化 plan `combine=WEIGHTED` 场景；**不适配多同义 query 融合**（第十一轮勘误） | —                     | —         |
| 多路 chunk 融合 rerank              | ⚠️ 暂不必须               | 第十一轮决策：P0 期同义 query 召回走简单 dedup 即可；rerank 多路融合下沉 §11 非 P0                                                                                            | —                     | —         |

**B. 结构化领域 API（已具备端点，重点核对过滤能力）**

| 业务资产                             | 端点前缀                                                                                                                          | 现有过滤参数                                                                                                                           | 缺口                                                                                                                                                                                                                                                                                                                                                                                              | 补齐工作量                                 |
| ------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------ |
| 岗位需求数据（datasets）             | `/record-assets/job-demand-datasets` @ `record_assets.py:307-350`                                                                 | normalized_ref_id / major(exact) / industry(exact)                                                                                     | year、major substring                                                                                                                                                                                                                                                                                                                                                                             | **S**                                      |
| 岗位需求数据（dataset 内 records）   | `/record-assets/job-demand-datasets/{id}/records` @ `record_assets.py:369-427`                                                    | city / industry(exact) / enterprise_size / employment_type                                                                             | job_title(substring) / salary_min/max / experience_requirement / education_requirement / region / source_published_at 范围                                                                                                                                                                                                                                                                        | **M**                                      |
| 岗位需求数据（跨 dataset records）   | **端点不存在**                                                                                                                    | —                                                                                                                                      | 新增 `/record-assets/job-demand-records` **仅支持 `major`(substring, 走 dataset join) + `normalized_ref_id` (trace)**（第十四轮 §1.14 收窄：删除 job_title 及所有细粒度过滤）                                                                                                                                                                                                                     | **M**                                      |
| 岗位角色图谱                         | `/record-assets/job-demand-datasets/{id}/role-graph` @ `record_assets.py:429-553`                                                 | job_title                                                                                                                              | 完备                                                                                                                                                                                                                                                                                                                                                                                              | —                                          |
| 职业能力分析表                       | `/record-assets/ability-analyses/*` @ `record_assets.py:1032-1200`（含 tasks / ability-items）                                    | `normalized_ref_id`(opt) / `profile_id` / `major_name`(**exact**)                                                                      | **`major_name` 只支持 exact match，需 substring**（阻塞按专业模糊检索）                                                                                                                                                                                                                                                                                                                           | **S**                                      |
| 专业布点数据（datasets）             | `/record-assets/major-distribution-datasets` @ `record_assets.py:603-651`                                                         | normalized_ref_id / major_code / major_name(substring) / education_level / year                                                        | 完备                                                                                                                                                                                                                                                                                                                                                                                              | —                                          |
| 专业布点数据（跨 dataset records）   | `/record-assets/major-distribution-records` @ `record_assets.py:746-810`                                                          | normalized_ref_id / year / major_code / major_name(substring) / province_name / education_level / region_scope / min_count / max_count | 完备                                                                                                                                                                                                                                                                                                                                                                                              | —                                          |
| 专业能力/教学标准图谱（builds）      | `/capability-graph-staging/builds` @ `capability_graph_staging.py:32-70`                                                          | `normalized_ref_id`(opt) / `build_type` / `status`                                                                                     | build 表**无 `major` 字段** → **第十二轮 §1.12 方案 B + 第十三轮 §1.13 实施澄清**：加 `major_name` + `major_code` **双列** 冗余（alembic 迁移 + build 写入路径**复用**现有 `teaching_standard.extractor._major_identity` / `major_profile.extractor._extract_identity` 抽取器 + 新增 `normalize_major_name` 归一化剥离资产类型后缀），仅 `teaching_standard` / `ability_analysis` 两类 build 写入 | **M**（含 alembic 迁移与数据回填，见 A1f） |
| 专业能力/教学标准图谱（nodes/edges） | `/capability-graph-staging/builds/{id}/nodes` / `/edges` @ `capability_graph_staging.py:82-155`                                   | build_id / node_type / edge_type                                                                                                       | **仅 build-scoped，需按 major 一跳定位**（通过 build.major_name 直接过滤，见第十二轮 §1.12）；不做多 build 聚合                                                                                                                                                                                                                                                                                   | **M**（并入 A1f）                          |
| 知识大纲（教材）                     | `/normalized-refs/{ref_id}/knowledge-outline` + `/knowledge-outline-nodes/{id}/chunks`+`/preview` @ `knowledge_outline.py:43-158` | 见端点定义                                                                                                                             | 缺子树递归展开（同 A 表 outline subtree 项）                                                                                                                                                                                                                                                                                                                                                      | S                                          |
| 任务大纲（实训）                     | `/normalized-refs/{ref_id}/task-outline` + `/task-outline/nodes/{id}` @ `task_outline.py:22-138`                                  | 见端点定义                                                                                                                             | 完备                                                                                                                                                                                                                                                                                                                                                                                              | —                                          |
| 产业政策                             | 仅在 asset 类型枚举（`internal/assets.py:30`）                                                                                    | —                                                                                                                                      | 新增 `/internal/v1/industry-policies` 支持 subject / year_range 过滤（薄封装走通用 asset）                                                                                                                                                                                                                                                                                                        | **S**                                      |

**前置总结（第七轮修正后）**：

- **必须在阶段 A 完成的阻塞项**：LiteLLM function calling（L）、job-demand 过滤补齐 + 跨 dataset records 端点（S + M + M）、**ability-analyses `major_name` substring（S）**、**capability-graph by-major 一跳端点（S~M，见 §1.8）**、产业政策薄封装（S）、outline subtree（S）、chart 适配层（S）、api_caller/console 身份区分（M）
- **P0 总额外工程量**：**约 0.7-0.9 sprint 前置**（相比第六轮修正后额外增加 A1e S + A1f M ≈ 1 周）

**关键结论**：

1. LiteLLM function calling **仍是全场景阻塞项**，必须最先启动；降级方案：JSON output + 手动 parse 替代 tool use
2. job-demand 过滤补齐是**结构化数据可用性**的关键前置：场景 5 人才培养方案需要按 major + year_range + region 拉取岗位数据，当前 dataset 级只有 major/industry exact match、record 级缺 year、且不支持跨 dataset 汇总
3. major-distribution 过滤能力**已完备**，直接可用；ability-analyses 需补 major substring
4. capability-graph-staging 的 nodes/edges 目前**仅 build-scoped**，场景 4"按专业查图谱"需两跳；**必须新增 by-major 一跳端点**（A1f），一个 major → 一份 build → 一次返回该 build 完整图（**不做多 build 聚合**）；**第十二轮 §1.12 决策改走方案 B**——加 `build.major_name` 冗余列，值从 `normalized_asset_ref.title` 解析；`build_type` 枚举收敛为 `[teaching_standard, ability_analysis]`（去掉 job_demand，因该类不涉及 major）
5. outline 跨 ref 语义查询**延后到 P1**，场景 3 用 pgvector chunks + `heading_path` 元数据间接满足

---

## 三、总体架构（含 v1 组件对齐表 + 内外双入口）

### 3.1 三层结构

```
                     ┌────────────────────────────────────────┐
User Query ─▶ Layer1 │ Intent Classifier + Parameter Extractor │
                     │ - 分类器：5 类 + unknown（单一意图）      │
                     │ - 抽取器：基于命中意图的工具参数并集      │
                     │ - via ai_prompt_profile (versioned)     │
                     └───────────────┬────────────────────────┘
                                     │
              ┌──────────────────────┼──────────────────────┐
              ▼                      ▼                      ▼
      场景 1-4 单/多跳          场景 5                  unknown
      (function call)      (人才培养方案模板)      (跨类型纯向量 top-K)
      内部工具（含 desc + params schema）
      每意图可命中 1..N 个工具
              │                      │                      │
              └──────────────────────┼──────────────────────┘
                                     ▼
                     ┌────────────────────────────────────────┐
                     │ Layer3  MD Composer (streaming)         │
                     │ - retrieved / generated / chart 混合     │
                     └────────────────────────────────────────┘
```

### 3.2 与现有四层框架的关系（合并演进）

| 现有四层组件                                | v2.0 位置                                   | 处置动作                                                         |
| ------------------------------------------- | ------------------------------------------- | ---------------------------------------------------------------- |
| `retrieval/intent.py`                       | Layer 1 意图分类器                          | 重构 schema 为 5 类场景，复用 LLM 调用骨架                       |
| `retrieval/planner.py`                      | Layer 2 场景 5 模板执行器 + 单跳 dispatcher | 从"自由 DAG"约束为"模板 + 白名单工具"                            |
| **query 转换（多同义问题）**                | Layer 2 场景 1 内部                         | 下沉为 `internal.search_chunks_by_semantic(expand_queries=true)` |
| `retrieval/rerank.py`                       | Layer 2 结果排序                            | 完全复用                                                         |
| `pgvector_search` / `pgvector_qa`           | Layer 2 内部工具                            | 完全复用                                                         |
| `apply_permission_filter`                   | 全链路复用                                  | 无改动                                                           |
| `index_manifest` / pgvector 表              | 全链路复用                                  | 无改动                                                           |
| `SearchQueryExecuted` / `QAAnswerGenerated` | 扩字段复用                                  | 见 §八                                                           |

### 3.3 对外/对内 API 变化

**v2.0 明确区分两类主入口**（对应第五轮决策 #1）：

| 入口                 | 消费方                                   | 路径                                                                          | 鉴权                                                                  | 权限模型                                     |
| -------------------- | ---------------------------------------- | ----------------------------------------------------------------------------- | --------------------------------------------------------------------- | -------------------------------------------- |
| **对内主入口**       | nexus-console（管理台）                  | `POST /internal/v1/query`                                                     | **JWT session**（`nexus-api/nexus_api/dependencies/user.py`，已实现） | 完整访问                                     |
| **对外主入口**       | api_caller（业务方 API 集成）            | `POST /open/v1/query`                                                         | X-API-Key（`require_api_caller`）                                     | `apply_permission_filter` + `available` 过滤 |
| **低阶 API（保留）** | 内部工具调用 + 少数需要 chunk 列表的场景 | `GET /open/v1/search`、`GET /open/v1/qa`、`GET /internal/v1/search`（若增）等 | 沿用现有                                                              | 沿用现有                                     |

**双入口共用同一套 Layer 1-3 编排代码**，仅在入口层做：

- **身份识别**：区分 caller 类型（console session vs api_caller），打进 audit `caller_type` 字段
- **权限过滤强度**：对外入口强制 `apply_permission_filter` + `available` 过滤；对内可放宽（P0 阶段仍保持一致过滤，为未来 console 端"管理员穿透查询"预留扩展点）
- **审计事件的 `route` 字段**：`internal_query` / `open_query`

**为什么分两个入口而不是一个入口 + 参数**：

- 契约边界清晰，符合 `CLAUDE.md` 中 "nexus-console 控制面 API 不可作为业务 API 暴露" 的红线
- 未来 console 可能加"跨 org 全量视图""审计模式检索"等对外禁止的能力，路径分开更安全
- 审计与限流规则可以分开策略

---

## 四、分层设计

### 4.1 Layer 1 —— 意图识别 + 参数抽取

**目标**：将用户 query 分类到 5 类场景 + `unknown`（**单一意图**），并抽取该意图对应工具集所需的参数。

**拆成两个组件**（同一 LLM session 内两阶段调用，或分两次调用）：

#### 4.1.1 Intent Classifier

**输入**：`query`、`caller`、可选 `session_hint`

**输出**：

```json
{
  "intent": "scenario_1" | "scenario_2" | "scenario_3" | "scenario_4" | "scenario_5" | "unknown",
  "confidence": 0.0-1.0
}
```

**要点**：

- 只输出**单一意图**（对应第五轮决策 #3），不再有 `top_k_alternatives`
- Prompt 走 `ai_prompt_profile`，scenario = `retrieval.intent_v2`
- 复用 v1 `retrieval/intent.py` 的 LLM 调用骨架，只重写 prompt 与输出 schema
- Confidence < 阈值（如 0.6）时强制降级 `unknown`
- 输出结构由后端 Pydantic 校验，非法结构走 `unknown`
- **enum 值 `scenario_1..5` 字面量稳定**（保护 audit `intent` 值域），但**判定条件按 §1.15 业务视角**（详见下方判定关键词）

**判定条件**（第十五轮 §1.15 业务视角重映射）：

| enum         | 业务含义                                               | 判定关键词（示例，Prompt 里完整列出）                                                  |
| ------------ | ------------------------------------------------------ | -------------------------------------------------------------------------------------- |
| `scenario_1` | **讯息类**（产业政策 / 产业报告 / 行业报告）           | "政策"、"报告"、"行业趋势"、"发展方向"、"综述"、"XX 年趋势"                            |
| `scenario_2` | **结构化数据**（岗位需求 / 职业能力分析 / 专业布点）   | "岗位需求"、"招聘量"、"薪资分布"、"专业布点"、"能力分析"、"就业方向"、"岗位分布 Top-5" |
| `scenario_3` | **专业教学标准**（培养目标 + 职业面向 + 岗位知识图谱） | "教学标准"、"培养目标"、"职业面向"、"专业岗位知识图谱"、"专业核心课程"                 |
| `scenario_4` | **教材类**（含实训教材，按 kb 参数区分）               | "课程"、"教材"、"章节"、"知识点"、"实训任务"、"如何"、"介绍下 XX 概念"                 |
| `scenario_5` | **Agentic RAG**（多步骤模板）                          | "培养方案"、"规划"、"综合方案"、"跨年度"、"多步骤"、"为 XX 学院设计..."                |
| `unknown`    | 无匹配 / 低置信                                        | —                                                                                      |

**边界处理**：

- **场景 1 vs 4**：讯息类看资产（产业/行业类关键词）；教材类看粒度（章节/知识点/如何做）
- **场景 2 vs 3**：结构化数据要"岗位/招聘/薪资/布点"数值类；教学标准要"培养目标/职业面向/教学标准"文档类
- **场景 3 vs 5**：教学标准是单资产综合检索；Agentic RAG 是跨资产多步骤（含培养方案模板）
- **模糊边界**：由 Prompt 显式指导优先选择召回范围更大的场景（4 > 3、5 > 2），配合 confidence 阈值控制精度

#### 4.1.2 Parameter Extractor（新，对应第五轮决策 #2）

**输入**：`query`、`intent`（Layer 1.1 输出）、**该意图对应工具集的参数并集 schema**

**输出**：

```json
{
  "extracted_params": {
    // 字段与该意图工具集的 required + optional 参数并集一致
    // 例如 scenario_5 (talent_cultivation) 会抽 major_name/organization/target_year
    // scenario_1 会抽 subject / kb_hint / outline_node_hint 等
  },
  "missing_required": ["<field_name>", ...]  // 命中意图的必填参数中未被抽到的
}
```

**要点**：

- **抽取 schema 由 Layer 2 工具注册表动态生成**（对每工具的 `parameters` 求并集）——这是与 v1 最本质的区别
- 若 `missing_required` 非空且属于场景 5 模板必填 → 由前端追问；否则忽略该字段（**由 Layer 2 决定放宽范围**，对应第五轮决策 #7）
- 允许 LLM 返回 null 表示"query 中未提及"，不允许臆造
- Prompt 走 `ai_prompt_profile`，scenario = `retrieval.param_extract_v2`

**为什么分两阶段而不是一次 LLM 调用**：

- 参数 schema 依赖分类结果，不知道意图就不知道要抽哪些字段
- 两阶段职责单一、prompt 短、可缓存意图分类结果、可独立评测
- 延迟代价：单次多约 300ms；可接受（Layer 2 内部并行会补偿回来）

### 4.2 Layer 2 —— 检索执行

按意图路由到不同执行器。

#### 4.2.1 工具注册表（对应第五轮决策 #4）

**配置文件**：`config/query_router_tools.json`

**每工具必须包含完整的 function-calling 元信息**（**第十五轮 §1.15 分组重排**，按业务视角）：

```json
{
  "scenario_1": {
    "description": "讯息类检索（产业政策 / 产业报告 / 行业报告；走 document-type chunks 通路 + Composer summary；第十五轮 §1.15 重映射自原 scenario_2 综合性场景）",
    "tools": [
      {
        "name": "internal.search_chunks_by_semantic",
        "description": "在 industry_research_kb 下按语义召回 top-K chunks，供 Composer 做趋势 / 政策 / 报告主题汇总",
        "parameters": {
          "type": "object",
          "properties": {
            "query": {
              "type": "string",
              "description": "检索问题（含关键词 + 时间限定）"
            },
            "kb": {
              "type": "string",
              "const": "industry_research_kb",
              "description": "固定 industry_research_kb（含产业政策 / 产业报告 / 行业报告，见 governance_rules_v2.json:134/276/419）"
            },
            "top_k": {
              "type": "integer",
              "minimum": 1,
              "maximum": 50,
              "default": 8
            },
            "expand_queries": {
              "type": "boolean",
              "description": "启用同义 query 扩展提升召回，默认 true"
            }
          },
          "required": ["query"]
        }
      }
    ]
  },
  "scenario_2": {
    "description": "结构化数据检索（岗位需求 / 职业能力分析 / 专业布点，按 major / job_title 拿：岗位行业分布 Top-5、岗位角色图、专业能力图谱、专业布点表；第十五轮 §1.15 重映射自原 scenario_5 内的结构化 tools + scenario_4 的 job_demand_role_graph）",
    "tools": [
      {
        "name": "internal.query_job_demand",
        "description": "跨 dataset 检索岗位需求记录（第十四轮 §1.14 收窄：仅支持 major 一维业务过滤 + normalized_ref_id trace）；**当 fields 含 `industry_distribution` 时后端返回 Top-5 行业分布聚合**（第十五轮 §1.15 B1 决策）",
        "parameters": {
          "type": "object",
          "properties": {
            "major": {
              "type": "string",
              "description": "专业名（substring，走 job_demand_dataset.major_name join；不使用 industry_name 兜底——第十一轮闭合项）"
            },
            "normalized_ref_id": {
              "type": "string",
              "description": "可选精确定位（trace 字段），用于用户明确指某一份数据集时"
            },
            "fields": {
              "type": "array",
              "items": { "type": "string" },
              "description": "返回字段白名单，如 `[count, industry_distribution, tasks, capability_requirements]`；含 `industry_distribution` 时后端做 GROUP BY industry_name COUNT ORDER DESC LIMIT 5 聚合，响应附 `aggregations.industry_distribution: [{industry_name, count}]`"
            }
          },
          "required": ["major"]
        }
      },
      {
        "name": "internal.get_job_demand_role_graph",
        "description": "按 dataset_id 获取岗位角色子图（岗位 → 职责 → 能力）；第十五轮 §1.15：从 scenario_4 迁入本组，作为岗位角色图输出",
        "parameters": {
          "type": "object",
          "properties": {
            "dataset_id": { "type": "string" },
            "job_title": {
              "type": "string",
              "description": "限定某一岗位标题（可选）"
            }
          },
          "required": ["dataset_id"]
        }
      },
      {
        "name": "internal.query_ability_analysis",
        "description": "按专业检索职业能力分析表（含 tasks / ability-items）",
        "parameters": {
          "type": "object",
          "properties": {
            "major": { "type": "string" },
            "include": {
              "type": "array",
              "items": { "type": "string", "enum": ["tasks", "ability_items"] }
            }
          },
          "required": ["major"]
        }
      },
      {
        "name": "internal.query_capability_graph_by_major",
        "description": "按 major 定位职业能力分析图谱（`build_type=ability_analysis` 分支；第十五轮 §1.15：teaching_standard 分支迁到 scenario_3）；见 §1.13 双列冗余",
        "parameters": {
          "type": "object",
          "properties": {
            "major_name": {
              "type": "string",
              "description": "专业名称 substring（走 build.major_name ILIKE）"
            },
            "major_code": {
              "type": "string",
              "pattern": "^\\d{4,6}$",
              "description": "专业代码精确匹配（4/6 位）"
            },
            "build_type": {
              "type": "string",
              "const": "ability_analysis",
              "description": "在本 scenario 下固定 ability_analysis（教学标准图谱走 scenario_3）"
            },
            "node_type": { "type": "string" }
          },
          "required": ["build_type"],
          "anyOf": [
            { "required": ["major_name"] },
            { "required": ["major_code"] }
          ]
        }
      },
      {
        "name": "internal.query_major_distribution",
        "description": "检索专业布点数据",
        "parameters": {
          "type": "object",
          "properties": {
            "major_code": { "type": "string" },
            "major_name": { "type": "string" },
            "year": { "type": "integer" },
            "province_name": { "type": "string" },
            "education_level": { "type": "string" },
            "region_scope": { "type": "string" },
            "min_count": { "type": "integer" },
            "max_count": { "type": "integer" }
          }
        }
      }
    ]
  },
  "scenario_3": {
    "description": "专业教学标准综合检索（培养目标 + 职业面向 + 岗位知识图谱；第十五轮 §1.15 A2 双路方案）；意图分类器命中本 scenario 时**必须同时命中两个工具**，Composer 汇总为三段结构化输出",
    "tools": [
      {
        "name": "internal.query_capability_graph_by_major",
        "description": "拿专业教学标准的岗位知识图谱（`build_type=teaching_standard` 分支；第十二轮 §1.12 方案 B + 第十三轮 §1.13 双列冗余）",
        "parameters": {
          "type": "object",
          "properties": {
            "major_name": {
              "type": "string",
              "description": "专业名称 substring（走 build.major_name ILIKE）"
            },
            "major_code": {
              "type": "string",
              "pattern": "^\\d{4,6}$",
              "description": "专业代码精确匹配"
            },
            "build_type": {
              "type": "string",
              "const": "teaching_standard",
              "description": "在本 scenario 下固定 teaching_standard"
            }
          },
          "required": ["build_type"],
          "anyOf": [
            { "required": ["major_name"] },
            { "required": ["major_code"] }
          ]
        }
      },
      {
        "name": "internal.search_chunks_by_semantic",
        "description": "在 course_standard_authoring_process kb 下按 outline_node 定位培养目标 / 职业面向段落（第十五轮 §1.15 A2 决策：补齐 teaching_standard 抽取器缺失的两个结构化字段）",
        "parameters": {
          "type": "object",
          "properties": {
            "query": {
              "type": "string",
              "description": "语义查询（如 `{major} 培养目标` / `{major} 职业面向`）"
            },
            "kb": {
              "type": "string",
              "const": "course_standard_authoring_process",
              "description": "固定 course_standard_authoring_process kb"
            },
            "outline_node": {
              "type": "string",
              "enum": ["培养目标", "职业面向"],
              "description": "限定 outline 节点（教学标准正式发布文档结构固定，heading_path 携带这两个章节标题）；无匹配则退化为纯语义 top-K"
            },
            "top_k": { "type": "integer", "default": 5 }
          },
          "required": ["query"]
        }
      }
    ]
  },
  "scenario_4": {
    "description": "教材类检索（电子商务基础 / 核心课程教材 + 实训教材；第十五轮 §1.15 重映射自原 scenario_1 精确知识块 + scenario_3 实训任务，按 kb 参数区分普通教材 vs 实训教材）",
    "tools": [
      {
        "name": "internal.search_chunks_by_semantic",
        "description": "在教材类 kb 下按语义召回 top-K chunks；kb 支持 `course_textbook`（普通教材）或 `practical_training_kb`（实训教材），由参数抽取器根据 query 判定；chunk metadata 携带 heading_path 供定位章节",
        "parameters": {
          "type": "object",
          "properties": {
            "query": { "type": "string" },
            "kb": {
              "type": "string",
              "enum": ["course_textbook", "practical_training_kb"],
              "description": "教材类知识类型 code；实训场景走 practical_training_kb"
            },
            "top_k": {
              "type": "integer",
              "minimum": 1,
              "maximum": 100,
              "default": 10
            },
            "similarity_threshold": {
              "type": "number",
              "minimum": 0,
              "maximum": 1,
              "default": 0.7
            },
            "outline_node": {
              "type": "string",
              "description": "限定 outline 节点子树 ID（可选）"
            },
            "expand_queries": {
              "type": "boolean",
              "description": "同义 query 扩展，默认 true"
            }
          },
          "required": ["query"]
        }
      },
      {
        "name": "internal.get_evidence_graph_by_ref",
        "description": "获取给定 normalized_ref 的证据图（章节内关联事实图）；用于教材类章节知识图谱输出",
        "parameters": {
          "type": "object",
          "properties": {
            "normalized_ref_id": { "type": "string" }
          },
          "required": ["normalized_ref_id"]
        }
      },
      {
        "name": "internal.get_outline_subtree",
        "description": "递归展开教材 outline 子树（第十五轮 §1.15：教材类章节层次结构输出，见 A2 子树端点）",
        "parameters": {
          "type": "object",
          "properties": {
            "node_id": { "type": "string" },
            "include_chunks": { "type": "boolean", "default": false }
          },
          "required": ["node_id"]
        }
      }
    ]
  },
  "scenario_5": {
    "description": "Agentic RAG（多步骤模板执行器，见 §五 人才培养方案）；模板 whitelist 引用其他 scenario 的 tools（如 step_policy 走 scenario_1 的 search_chunks_by_semantic、step_demand 走 scenario_2 的 query_job_demand、step_standard 走 scenario_3 的 query_capability_graph_by_major）",
    "tools": [
      {
        "$comment": "本 scenario 无独立 tool，通过模板文件 `config/plans/talent_cultivation_plan.yaml` 引用其他 scenario 的 tools（whitelist 约束）"
      }
    ]
  }
}
```

> **命名对齐**：本示例已按 §1.6 勘误修正，工具名与真实 API 端点对齐——`job_demand` 而非 `position_demand`、`ability_analysis` 而非 `capability_analysis`、`capability_graph_by_major`（走 capability-graph-staging）而非 `teaching_standard_capability_graph`。参数字段按 §2.5.B 表列出的**真实过滤能力**列全。

**关键约束**：

- **`parameters` 必须是标准 JSON Schema**，Layer 1 参数抽取器直接消费
- **Layer 2 允许 LLM 命中一到多个工具**（例如场景 1 通常同时命中 `search_chunks_by_semantic` + `get_evidence_graph_by_ref`），并行执行
- 工具 `description` 供 LLM 决策使用；命名以 `internal.<domain>_<verb>` 规范
- **跨资产检索原则（第七轮 §1.7 + §2.5.0 决策）**：
  - 工具**输入参数以业务维度为主**（`major` / `subject` / `year` / `region` / `job_title` / `industry` 等）；`dataset_id` / `normalized_ref_id` / `build_id` 等 trace 字段**只允许作为可选精确定位参数**，不能作为主检索维度
  - 工具**响应必须携带 trace 字段**（每个结果项带 `normalized_ref_id` / `dataset_id` / `build_id` 等），供 Composer 生成 Markdown 脚注引用（对应 §4.3 输出规范）
  - 若底层领域 API 只暴露 trace-scoped 端点（如 `/datasets/{id}/records`），Layer 2 工具**不能直接透传**，必须由后端提供跨资产聚合端点（阶段 A 已列入 A1c / A1f 等）

#### 4.2.2 场景 1-4：Function Call Dispatcher

**执行流程**：

1. 从工具注册表取当前意图的工具子集
2. 传给 LiteLLM function calling（**依赖前置项：LiteLLM tool use 支持**，见 §2.5）
3. LLM 返回 0..N 个 tool call + 参数（参数已由 Layer 1 预抽取，LLM 主要做 tool 选择与参数微调）
4. **LLM 未返回任何 tool call**（第十一轮决策 #4）→ **直接降级 `unknown` 走 §六 跨类型纯向量兜底**，不做二次 LLM 重试
5. **Pydantic 校验 tool_call 参数**：单次失败 → 允许 1 次重试 → 再失败 → 降级 `unknown` 走兜底
6. **并行执行**多个 tool call
7. 结果按 `chunk_id` 去重合并（多同义 query 场景，见 §4.2.6）；**P0 不引入多路 rerank 融合**（第十一轮决策 #3）
8. 返回结构化结果给 Layer 3

**审计要求**：无论走正常路径还是降级路径，`invoked_tools` / `intent` / `intent_confidence` 字段均需正确落到 `SearchQueryExecuted` / `QAAnswerGenerated` 事件的 `summary` JSON 中（§八）。tool_call 缺失或校验失败触发的降级需在 `summary.dispatch_fallback` 字段记录原因（`no_tool_call` / `param_validation_failed`）。

#### 4.2.3 场景 5：人才培养方案模板执行器

见 §五 专项。复用 v1 planner 的步骤编排能力。

#### 4.2.4 Unknown：跨类型纯向量 top-K

见 §六 专项。

#### 4.2.5 Summary 场景（**scenario_1 讯息类默认能力**，第十五轮 §1.15 重映射）

按第三轮决定：Layer 2 用工具在讯息类资产（产业政策 / 产业报告 / 行业报告，共用 `kb=industry_research_kb`）中检索 top-K chunks → Composer 只汇总这 top-K chunks → (query_hash, ref_ids) 短 TTL 缓存（15 分钟，进程内 TTL cache，不引入 Redis）。**复用现有 `RetrievalSummaryService`**（§2.5 已确认可用）。

> 第十五轮 §1.15 重映射前：本节标题为"属于场景 2 内部特化"（原 scenario_2 = 综合性检索）；现 scenario_2 已改为结构化数据检索，Summary 能力归 scenario_1 (讯息类) 默认路径。

#### 4.2.6 同义 query 生成与结果合并（`expand_queries=true`）

第十一轮决策 #2 / #3 明确：v1 无同义 query 生成能力，需**新实现**；且 P0 不引入多路 rerank 融合。

**执行流程**（当工具调用 `expand_queries=true` 时）：

1. 用 LiteLLM 生成 **3-5 条同义 / 近义 query**（Prompt 走 `ai_prompt_profile`，scenario = `retrieval.query_expansion_v2`；单次 LLM 调用，不缓存）
2. 原 query + 扩展 query 一起独立走 pgvector 召回，各拿 `top_k` 条
3. 结果按 `chunk_id` **简单 dedup**：同一 chunk 出现多次时**取最高相似度分**，metadata 记录 `matched_queries: [str]`（原 + 扩展）
4. 最终返回 top_k 条（按分数降序），Composer 引用时可读到 `matched_queries` 做上下文融合

**为什么不引入 rerank 融合**：现有 `rerank.py` 是面向结构化 plan (`combine=WEIGHTED`) 设计，与多同义 query 场景不契合；简单 dedup 在 P0 场景下召回率提升已够用。**未来若召回噪声成为投诉集中项**，再评估引入 cross-encoder rerank（§11 非 P0）。

**降级**：query expansion LLM 调用失败 → 仅用原 query 召回，不阻断请求；`expand_queries` 字段回传 `false_due_to_error` 供审计。

### 4.3 Layer 3 —— MD Composer

**输入**：Layer 2 执行结果 + 原始 query + 意图

**输出**：Markdown 字符串（流式）

**Prompt 走 `ai_prompt_profile`**，scenario = `retrieval.compose_v2`

**输出规范**：

- 主体为标准 Markdown
- **Generated 段落**：`> ⚠️ 以下为模型推断内容，未匹配到平台资产`
- **图谱数据**：Composer prompt 里以 `[[CHART:{chart_id}]]` 占位，Composer 生成后由后端字符串替换为 fenced code block
- **来源引用**：Markdown 脚注（`[^ref1]`）指向 `normalized_ref_id` + `chunk_id` + `locator`
- **流式**：SSE 或 chunked response

**Composer 硬约束**（写进 prompt）：

1. 关键结构化字段（岗位数、政策编号、教学标准编号）**禁止 generated**，未命中就写"暂无数据"
2. 图表数据**只使用后端提供的占位**，不自造节点/数值
3. 数字/日期若来源于 generated 段，必须紧邻位置补 ⚠️ 引用块

---

## 五、场景 5 专项：人才培养方案模板

**P0 唯一模板**：`talent_cultivation_plan`

### 5.1 模板骨架（对应第五轮决策 #6，路径改为 `config/plans/`）

**文件位置**：`config/plans/talent_cultivation_plan.yaml`

```yaml
template_id: talent_cultivation_plan
name: 人才培养方案
triggers:
  - "人才培养方案"
  - "培养方案规划"
required_params:
  - major_name # 必填：例如 "跨境电商"
optional_params:
  - organization # 非必填：缺失则查该专业通用规划
  - target_year # 非必填：缺失则取当前年 + 1
steps:
  - id: step_policy
    description: 语义检索 {major_name} 相关的产业政策/行业报告 chunks
    tool: internal.search_chunks_by_semantic
    inputs:
      query: "{major_name} 相关行业政策、产业规划、发展方向"
      kb: industry_research_kb # 产业政策/产业报告/行业报告共享同一 kb（governance_rules_v2.json:134）
      top_k: 8
      expand_queries: true # 同义 query 扩展提升召回
    on_empty: mark_generated_placeholder # 极端场景（无匹配政策 chunk）走标注，正常路径由 Composer 汇总
  - id: step_demand
    description: 检索 {major_name} 岗位需求数据（跨 dataset；第十四轮 §1.14：仅 major 一维过滤）
    tool: internal.query_job_demand
    inputs:
      major: "{major_name}"
      fields: [count, industry_distribution, tasks, capability_requirements]
      # year_range / region 已删除（第十四轮 §1.14）：细粒度过滤由 Composer 追问引导
    on_empty: mark_generated_placeholder
  - id: step_standard
    description: 检索 {major_name} 专业教学标准中投影的岗位能力图谱
    tool: internal.query_capability_graph_by_major
    inputs:
      major: "{major_name}"
      build_type: teaching_standard # 小写，与 db `capability_graph_staging_build.build_type` 对齐（第十一轮决策 #1）
    on_empty: mark_generated_placeholder
  - id: step_compose
    description: 汇总为培养方案
    executor: layer3_composer
    inputs:
      sources: [step_policy, step_demand, step_standard]
      output_template: talent_cultivation_plan_md
```

### 5.2 执行细节（对应第五轮决策 #7）

- **参数抽取**：由 Layer 1.2 从 query 抽 `major_name / organization / target_year`
- **缺参处理策略**：
  - **必填缺失**（如 `major_name`）→ **前端追问**"请说明目标专业"
  - **非必填缺失**（如 `organization`、`target_year`）→ **忽略并放宽范围**（如 target_year 缺失就取当前年 ±2 的窗口、organization 缺失就查通用数据）→ 在 Composer 里显式说明"未指定 XX，结果为通用范围"
- **步骤并行**：step_policy / step_demand / step_standard **可以并行**，全部完成再进 step_compose；由 v1 planner 的依赖管理机制驱动
- **每步空结果处理**：不阻断，标记 `has_source=false`，Composer 用 generated 段落 + ⚠️ 补齐
- **verification 节点**：step_compose 前，检查三步至少 2 步命中真实数据；否则输出层显式说明"检索命中不足，本方案主要由模型推断生成"

### 5.3 不做的事

- 不做动态无模板 planner（P1）
- 不做其他规划模板（课程改革方案、招生方案等）（P1）

---

## 六、Unknown 兜底路径

**决定**（第三轮）：复用 `/open/v1/search` 的纯向量 top-K，**不限 `kb` 参数跨知识类型召回**。

**流程**：

1. Layer 1 输出 `intent=unknown`（或 Layer 2 参数校验失败降级到这里）
2. **跳过 Layer 2 的 function calling**，直接调用 pgvector search
3. `top_k` 默认 20，`similarity_threshold` 默认 0.3（比意图明确时略宽松）
4. Layer 3 拿到跨类型 chunks 做 MD 汇总
5. Composer prompt 里额外提示："这是兜底检索，结果可能不精准，请提示用户细化问题"

**已知代价**（第三轮明示接受）：长尾关键词召回差（无 BM25）、跨类型排序仅靠向量相似度、不做 query 改写。

**未来升级路径（非 P0）**：加 `tsvector`+RRF 后，本条兜底改为 hybrid retrieval，其他不变。

---

## 七、图谱 → chart 承载协议

### 7.1 Fence 规范

````
​```chart:echarts
{
  "type": "graph",
  "nodes": [{"id": "n1", "name": "新媒体运营", "category": "position"}, ...],
  "edges": [{"source": "n1", "target": "n2", "relation": "requires_skill"}, ...],
  "meta": {"title": "新媒体运营岗位能力图谱", "source_ref": "ref-xxx"}
}
​```
````

- **Fence 语言标签**：`chart:echarts`（P0 唯一支持）；`chart:mermaid` 已列入 §十一 遗留项，触发条件与实现路径见该节
- **JSON schema**：由后端约定并 Pydantic 校验
- **前端**：识别 `chart:echarts` fence → 走 ECharts renderer；未识别的 fence 走普通 code block 展示（`chart:mermaid` 之外的自定义 chart 标签，前端保留 pre 兜底以便审计发现）

### 7.2 后端适配器（对应第五轮决策 #5）

**能力现状（引用 §2.5 调研结论）**：

- ✅ 底层图 API 已具备完整的 nodes+edges 数据模型（`KnowledgeGraphNode/Edge/Fact` @ `nexus-app/nexus_app/models.py:2203-2310`，`CapabilityGraph` 亦然）
- ✅ Internal 端点已存在（`internal/evidence_graph.py:35-100`）
- ⚠️ **缺一层薄适配**：把内部结构序列化为 §7.1 的 chart JSON（字段重命名、meta 拼装、node category 归类）

**工作量**：**S**（仅序列化 + 字段映射，不涉及数据模型改造）

**位置**：Layer 2 内，图 API 调用后立刻做转换

**硬约束**：

- **Chart 数据 100% 由后端拼装**，禁止 LLM 现场造节点或数值
- Composer prompt 见 chart 数据时以 `[[CHART:{chart_id}]]` 占位，Composer 生成完成后由后端字符串替换为 fenced block

### 7.3 chart_id 生成规则与占位替换时序（第十一轮补齐）

**chart_id 生成**：

- 后端在 Layer 2 完成 tool 调用、chart 适配器把图 API 响应序列化为 chart JSON 时**立刻分配** chart_id
- 格式：`{tool_call_id}:{chart_index}`
  - `tool_call_id`：LiteLLM function calling 返回的 tool_call.id（保证单次请求内唯一）
  - `chart_index`：单次 tool 调用返回多张图时的 0-based 序号（多数场景为 `0`）
- Composer prompt 传入的上下文里，chart 数据被替换为 `[[CHART:{chart_id}]]` 占位；chart JSON 由后端在 chart 表暂存（`request_id → chart_id → chart_json` map，仅进程内，请求结束销毁）

**占位替换时序**：

- Composer 采用流式输出（SSE），但 chart 占位**不做增量替换**——避免流的中间态出现半截 fence 导致前端解析失败
- **约定**：Composer 流完全结束后，后端在**发送 SSE `event: done`（或 chunked response 结束）之前**统一执行一次 `[[CHART:xxx]] → \`\`\`chart:echarts\n<json>\n\`\`\`` 字符串替换，替换后一次性把最终 Markdown 拼接段作为最后一条 SSE event 下发
- 若前端需要在流中提前显示 chart（非 P0 需求）：另发 `event: chart` 携带 `chart_id + chart_json`，前端见到占位时用本地表替换；P0 阶段不做

**边界**：

- Composer 输出中出现**未在后端 chart 表登记的 chart_id** → 视为 LLM 幻觉，替换阶段忽略该占位（保留原文本 `[[CHART:xxx]]` 以便审计发现）；同时 `SearchQueryExecuted.summary.chart_hallucination_ids` 记录
- Composer 输出中 chart_id **少于**后端 chart 表登记数量 → 记录 `summary.chart_unused_ids`，不阻断响应

### 7.4 前端约束

- ECharts 版本、graph 布局默认值（force / circular）由前端约定并写死
- 图节点 hover 显示 `source_ref` 可跳转至资产详情

---

## 八、治理与审计

### 8.1 治理红线（复述）

- Generated 段落**不落库、不入 `governance_result` / `knowledge_chunk`**，因此**不触发 AI 输出治理链路**
- 但 **UI 层必须显示** ⚠️ 引用块标记（第三轮明确）

### 8.2 审计事件（复用现有、扩展字段）

**不新增事件类型**（§2.5 确认 `audit_log.summary` 已是自由 JSON，扩展零成本）。`SearchQueryExecuted` 与 `QAAnswerGenerated` 是 NEXUS 现有审计事件，v2.0 链路继续复用。

**新增字段**（两个事件共同扩展）：

| 字段                      | 类型           | 说明                                            |
| ------------------------- | -------------- | ----------------------------------------------- |
| `route`                   | string         | `internal_query` / `open_query`（对应双入口）   |
| `caller_type`             | string         | `console_session` / `api_caller`                |
| `intent`                  | string         | `scenario_1` … `unknown`                        |
| `intent_confidence`       | float          | Layer 1 输出                                    |
| `invoked_tools`           | string[]       | Layer 2 实际调用的 internal 工具列表            |
| `generated_ratio`         | float          | Composer 输出中 generated 段落字符占比          |
| `template_id`             | string \| null | 场景 5 使用的模板 ID                            |
| `query_route`             | string         | 固定 `"v2"`；用于未来若再有版本变更时的标识锚点 |
| `missing_optional_params` | string[]       | 抽取时被忽略的非必填参数                        |

**审计原则不变**：Query 走 hash（`query_hash`），不落明文；日志不含 L3/L4 明文内容；写入失败不阻断响应（但记 metric 告警）。

### 8.3 L3/L4 内容处理

- Layer 2 检索阶段：`_filter_hits_to_available()` + `apply_permission_filter` 已过滤
- Layer 3 汇总阶段：若命中 chunk 属于 L3/L4 资产（未来扩展），**Composer 必须走 LiteLLM 私有模型 alias**；P0 暂无 L3/L4 资产，此路径预留

---

## 九、v1 → v2 演进改造路径

### 9.1 改造原则

- **底座零改动**：`index_manifest` / pgvector 表 / `apply_permission_filter` / audit_log 表结构不动
- **v1 组件原地重构**：intent、planner 重构后不改文件路径
- **老端点保留**：`/open/v1/search`、`/open/v1/qa` 保持行为不变，作为 Layer 2 内部工具入口
- **新增双主入口**：`POST /internal/v1/query`（console）+ `POST /open/v1/query`（api_caller），共用同一套 Layer 1-3 编排代码

### 9.2 三阶段推进

**阶段 A：前置能力就绪 + 底层工具与协议**（无对外行为变化）

- **A0**（阻塞）：LiteLLM function calling 支持（`LiteLLMClientProtocol` 扩展）
- **A1**（阻塞，第六轮修正后）：job-demand 过滤参数补齐（datasets 加 year/major substring；dataset-内 records 加 job_title/salary/experience/education/region/published_at 范围）
- **A1b**（阻塞）：新增跨 dataset 端点 `/record-assets/job-demand-records`
- **A1c**（阻塞）：产业政策查询薄封装 `/internal/v1/industry-policies`（走通用 asset 端点 + subject/year_range 过滤）
- **A2**：outline subtree 查询 API
- **A3**：`config/query_router_tools.json` 工具注册表（含 description + parameters schema，命名对齐真实 API）
- **A4**：chart 适配器 + `[[CHART:...]]` 占位替换机制
- **A5**：`search_chunks_by_semantic` 加 `expand_queries` 参数
- **A6**：审计事件字段扩展（新增字段先接入、留空值）
- **A7**：api_caller / console 身份区分（`caller_type` 识别）
- **Review Gate 1**：老 `/open/v1/search` / `/open/v1/qa` 全量回归通过；LiteLLM function calling 单元测试；**job-demand 全量过滤参数回归**

**阶段 B：Layer 1 + Layer 2 单跳（场景 1-4 + unknown）+ 双入口**

- **B1**：`ai_prompt_profile` 新增 3 个模板：`retrieval.intent_v2` / `retrieval.param_extract_v2` / `retrieval.compose_v2`
- **B2**：重构 `retrieval/intent.py` 为单一意图分类器
- **B3**：新增 Parameter Extractor（基于工具集参数并集 schema 抽取）
- **B4**：Layer 2 dispatcher：多工具 function call + 参数校验 + 并行执行 + v1 rerank 集成
- **B5**：Layer 3 MD Composer + generated 引用块规范 + 流式输出
- **B6**：新增 `POST /open/v1/query` 端点
- **B7**：新增 `POST /internal/v1/query` 端点（共用 B4/B5 编排层）
- **B8**：前端 chart fence 渲染 + generated 段落样式 + 脚注跳转 + 流式接收
- **Review Gate 2**：意图分类离线评测（5×20 样本）+ 端到端 5 场景 smoke test + 内外入口权限差异回归

**阶段 C：场景 5 模板执行器**

- **C1**：`ai_prompt_profile` 新增 `retrieval.plan.talent_cultivation` 模板
- **C2**：`config/plans/talent_cultivation_plan.yaml` 模板文件
- **C3**：重构 `retrieval/planner.py` 为模板执行器（白名单工具 + 依赖并行 + verification 节点）
- **C4**：人才培养方案端到端接入 `/open/v1/query` 与 `/internal/v1/query`（含 step 空数据 fallback）
- **Review Gate 3**：场景 5 端到端跑通 + step 空数据 fallback 验证 + verification 节点告警链路验证

### 9.3 回滚策略

**因取消了开关，回滚以代码级 revert 为主**：

- 阶段 A 出问题 → revert 到改造前的 `retrieval/`、`open.py`；对外无感知
- 阶段 B 出问题 → 关闭 `/open/v1/query` 与 `/internal/v1/query` 端点，继续用老 `/open/v1/search`、`/open/v1/qa`
- 阶段 C 出问题 → 主入口中把 `scenario_5` 强制降级 `unknown`

**关键前提**：老 `/open/v1/search`、`/open/v1/qa` 端点在整个演进过程中**必须保持可用**。

---

## 十、P0 工程清单与依赖

### 阶段 A：前置能力 + 底层就绪

| #   | 工程项                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 | 依赖                                 | 负责层                | 估工                  |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------ | --------------------- | --------------------- |
| A0  | **LiteLLM function calling 支持**（`LiteLLMClientProtocol` + `RealLiteLLMClient` 扩展 `tools` / `tool_choice` 参数）；**DoD 补第十一轮决策 #4**：单元测试覆盖"LLM 未返回 tool_call → 直接降级 unknown 兜底"（不做二次 LLM 重试）+ tool_call 参数校验失败 2 次后同样降级 unknown；fake LLM client 覆盖 CI                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | —                                    | nexus-app             | **L**                 |
| A1b | **新增 `GET /record-assets/job-demand-records` 跨 dataset 端点**（第九轮聚焦 + 第十四轮 §1.14 再收窄 + **第十五轮 §1.15 B1 加聚合响应**）：**仅**支持 `major`(substring, 走 `job_demand_dataset.major_name` join；不使用 `industry_name` 兜底) + optional `normalized_ref_id`(trace)；分页、排序；**不做** `job_title` / `salary` / `experience` / `education` / `region` / `published_at` 范围等所有细粒度过滤；**新增 `fields` 参数支持 `industry_distribution` 聚合**：请求参数 `fields` 数组含 `industry_distribution` 时后端做 `GROUP BY industry_name COUNT ORDER DESC LIMIT 5` 聚合，响应包 `{records: [...], aggregations: {industry_distribution: [{industry_name, count}]                                                                                                                                                                                                                                                                                                                                                                                                                                    | null}}`                              | —                     | nexus-app + nexus-api | **M** |
| A1e | **ability-analyses `major_name` substring 支持**：`/record-assets/ability-analyses` 将 `major_name` 从 exact 改为 substring match；**第十一轮决策 #8**：P0 不做性能基线与 GIN trigram 索引前置，上线后观察                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | —                                    | nexus-app + nexus-api | **S**                 |
| A1f | **capability-graph by-major 一跳端点**（第十二轮 §1.12 方案 B + 第十三轮 §1.13 实施澄清）：① **Alembic 迁移**：`capability_graph_staging_build` 加 `major_name: String(256) \| None` + `major_code: String(16) \| None` + 复合索引 `ix_cgsb_major_type`；② **build 写入路径**：**复用**现有 `teaching_standard.extractor._major_identity()` / `major_profile.extractor._extract_identity()` 抽取器 + **新增** `capability_graph.major_normalizer.normalize_major_name()` 剥离资产类型后缀（"专业教学标准" / "专业简介" / "职业能力分析表" 等），对 `build_type ∈ {teaching_standard, ability_analysis}` 同步写入两列；③ **数据回填脚本**：迁移时对已存在的两类 build 一次性回填 major_name + major_code；④ **端点实现**：`GET /capability-graph-staging/by-major?major_name=X&major_code=Y&build_type=Z`，`major_name/major_code` at-least-one-required，查询 `WHERE (major_code = :code OR major_name ILIKE :major_substr) AND build_type = :build_type AND status = 'GENERATED' ORDER BY created_at DESC LIMIT 1`；⑤ `build_type` 枚举 = `[teaching_standard, ability_analysis]`；⑥ 不做多 build 聚合 / 查询性能基线 | build 生产者代码（nexus-app 内）联动 | nexus-app + nexus-api | **M**                 |
| A2  | outline subtree 查询 API（`GET /internal/v1/knowledge-outline-nodes/{node_id}/subtree`）                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | —                                    | nexus-api             | S                     |
| A3  | `config/query_router_tools.json`（含每工具 name/description/parameters JSON schema，命名对齐真实 API，遵循 §2.5.0 跨资产原则；**含 scenario_1 - scenario_5 全部 5 组分组**，其中 scenario_2 / scenario_3 引用 `internal.search_chunks_by_semantic`；不含 industry_policy 工具）；**第十一轮决策 #6**：无控制台编辑需求，不引入 ETag / fcntl / 编辑审计；**DoD 补 A0/A3 联调**：用 A0 fake client 试跑 tool_choice 一次，验证 schema 兼容                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               | A0(联调), A1b, A1e, A1f, A2          | nexus-app             | M                     |
| A4  | 图 API → chart JSON 薄适配器 + `[[CHART:...]]` 占位替换；**DoD 补第十一轮**：chart_id 生成规则 (`{tool_call_id}:{chart_index}`) + 流式替换时序（Composer 流完成后统一替换，见 §7.3）                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   | 内部图 API（已具备）                 | nexus-app             | **S**                 |
| A5  | **新增同义 query 生成组件**（**第十一轮决策 #2 / #3 重写**）：由 LiteLLM 生成 3-5 条同义 query → 原 + 扩展 query 独立召回 → 按 `chunk_id` 简单 dedup（取最高分）；`expand_queries=false` 时行为与旧版一致；**不引入多路 rerank 融合**；DoD 只覆盖单元测试（生成条数 / dedup 正确性 / 回归）——**取消 A/B 评测**（第十一轮决策 #7）                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      | B1(query_expansion prompt profile)   | nexus-app             | S                     |
| A6  | 审计事件字段扩展（`route` / `caller_type` / `intent` / `intent_confidence` / `invoked_tools` / `generated_ratio` / `template_id` / `query_route` / `missing_optional_params` / `dispatch_fallback` / `chart_hallucination_ids` / `chart_unused_ids`）；**依赖 A7**：`caller_type` 字段值由 A7 提供的身份识别写入                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       | A7                                   | nexus-app             | S                     |
| A7  | api_caller / console 身份区分**最小可用**（第九轮 §1.9 决策 #4）：console 侧接入现有 JWT session（`dependencies/user.py`）+ audit `caller_type=console_session`；api_caller 侧仅打 `caller_type=api_caller` 标签、权限逻辑与 console 一致，差异化留 P1；**同步在老端点 `/open/v1/search` / `/open/v1/qa` 回填 `caller_type=api_caller`**（第十一轮闭合项）                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             | —                                    | nexus-api             | **S~M**               |
| A8  | 老 `/open/v1/search` / `/open/v1/qa` 回归测试集补齐 + **job-demand records 核心 2 维过滤回归**（major substring + job_title substring）+ ability-analyses substring 回归 + **capability-graph by-major 一跳端点 smoke test（build_type 小写枚举）** + **audit 事件字段端到端回归**（老端点 `caller_type` 回填 + A6 全部新字段占位可写入可查询）+ **tool_call 缺失降级到 unknown 兜底 smoke test**（第十一轮闭合项）                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    | A1b, A1e, A1f, A5, A6, A7            | nexus-api             | M                     |

> **第九轮范围裁剪说明**（§1.9）：A1a / A1c / A1d 已删除；A1b 合并原 A1c 意图、聚焦到最小 2 维过滤；A7 降级最小可用。
> **第十一轮补丁**（§1.11）：A0/A1b/A1e/A1f/A3/A4/A5/A6/A7/A8 DoD 与依赖行内更新；A5 从"复用 v1"改为"新实现";取消 A/B 评测；A6 显式依赖 A7；A8 补 audit 端到端回归 + tool_call 兜底 smoke。总工程量约 40-50 人天。

### 阶段 B：Layer 1 + Layer 2 单跳 + Layer 3 + 双入口

| #   | 工程项                                                                                                           | 依赖               | 负责层                | 估工 |
| --- | ---------------------------------------------------------------------------------------------------------------- | ------------------ | --------------------- | ---- |
| B1  | `ai_prompt_profile` 新增 3 个模板：`retrieval.intent_v2` / `retrieval.param_extract_v2` / `retrieval.compose_v2` | —                  | nexus-app             | S    |
| B2  | `retrieval/intent.py` 重构为单一意图分类器（复用 LLM 骨架，重写 prompt + schema）                                | B1                 | nexus-app             | M    |
| B3  | Parameter Extractor（读取工具注册表求参数并集，生成 JSON schema 后调 LLM）                                       | A3, B1             | nexus-app             | M    |
| B4  | Layer 2 dispatcher：多工具 function call + Pydantic 校验 + 并行执行 + v1 rerank 集成                             | A0, A3, A5, B2, B3 | nexus-app             | L    |
| B5  | Layer 3 MD Composer + generated 引用块规范 + 流式输出 + 脚注生成                                                 | A4, B1             | nexus-app + nexus-api | M    |
| B6  | 新增 `POST /open/v1/query` 入口，`require_api_caller` + `apply_permission_filter`                                | A7, B4, B5         | nexus-api             | M    |
| B7  | 新增 `POST /internal/v1/query` 入口（共用 Layer 1-3 编排层）                                                     | A7, B4, B5         | nexus-api             | S    |
| B8  | 前端 chart fence 渲染 + generated 段落样式 + 脚注跳转 + 流式接收                                                 | A4, B5             | nexus-console         | M    |

### 阶段 C：场景 5 模板执行器

| #   | 工程项                                                                                                                                                                              | 依赖                      | 负责层                | 估工 |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------- | --------------------- | ---- |
| C1  | `ai_prompt_profile` 新增 `retrieval.plan.talent_cultivation` 模板                                                                                                                   | —                         | nexus-app             | S    |
| C2  | `config/plans/talent_cultivation_plan.yaml` 模板文件                                                                                                                                | A3                        | nexus-app             | S    |
| C3  | `retrieval/planner.py` 重构为模板执行器（工具白名单需覆盖 A1b/A1e/A1f 与图/大纲 API；**step_policy 走 `internal.search_chunks_by_semantic(kb="industry_research_kb")`**，见 §1.10） | A1b, A1e, A1f, A2, A5, B4 | nexus-app             | L    |
| C4  | 人才培养方案端到端接入两个主入口                                                                                                                                                    | C1, C2, C3, B6, B7        | nexus-app + nexus-api | M    |

### 依赖示意（关键路径）

```
A0 (LiteLLM tools) ─────────────────────────────────────────▶ A3(联调), B4
A1b (job-demand 跨 dataset records, 仅 major) ────────┐
A1e (ability-analyses substring)                       ├─▶ A3 ─▶ B3, B4, C3
A1f (capability-graph by-major 方案B, alembic 双列 + 复用现有 identity 抽取器 + 归一化 + 回填 + 端点) ┘
A2 (outline subtree) ─────────────────────────▶ A3
A4 (chart adapter, chart_id 生成 + 流式替换) ─▶ B5 ──▶ B8
A5 (同义 query 生成 + dedup, 新实现) ──────▶ B4
A7 (caller_type 最小可用) ─▶ A6 (audit fields, 依赖 A7 填 caller_type) ─▶ A8
A7 ────────────────────────────────────────▶ B6, B7

B1(query_expansion prompt) ─▶ A5
B1, B2 ──▶ B3 ──▶ B4 ──▶ B5 ──▶ B6, B7 ──▶ 阶段 B 上线
C1, C2, C3 ──▶ C4 ──▶ 阶段 C 上线
```

**关键路径**：

- **A0（LiteLLM function calling）是全场景阻塞项**，必须最先启动；若落地风险高需并行准备"JSON output + 手动 parse"降级方案；A0 DoD 已含"LLM 未返回 tool_call → 降级 unknown 兜底"路径（第十一轮决策 #4）
- **A1b（job-demand 跨 dataset records 端点，仅 major 一维过滤——第十四轮 §1.14）是场景 5 step_demand 的硬前置**；major 过滤走 `job_demand_dataset.major_name` join，不引入 industry_name 兜底；`job_title` / `salary` / `region` 等细粒度过滤下沉 P1，由 Composer 追问引导
- **A1f（capability-graph by-major 一跳端点，第十二轮 §1.12 方案 B + 第十三轮 §1.13 实施澄清）是场景 4 单跳的硬前置**：alembic 迁移加 `major_name` + `major_code` **双列** + **复用现有 `_major_identity` / `_extract_identity` 抽取器** + 新增 `normalize_major_name` 剥离资产类型后缀 + 数据回填 + 端点实现；`build_type` 枚举 = `[teaching_standard, ability_analysis]`；查询参数 `major_name`(substring) + `major_code`(exact) 双通路 at-least-one-required；不做多 build 聚合；工程量 M
- **A5（同义 query 生成）是新实现**（第十一轮决策 #2 勘误）：v1 无该能力；实现方式为 LiteLLM 生成 3-5 条同义 query + 独立召回 + chunk_id 简单 dedup；**不引入多路 rerank 融合**（下沉 §11）
- **A6 依赖 A7**：`caller_type` 字段值由 A7 身份识别提供，两者顺序化推进（先 A7 再 A6 或 A6 预留字段 + A7 落数据一并 QA）
- 以上 A1x 项与 A0 / A2 / A4 相互独立，**可全部并行推进**
- **A1d / industry_policy 已删除**（理由见 §1.10 勘误）：产业政策是 document-type 资产，`step_policy` 走 `internal.search_chunks_by_semantic(kb="industry_research_kb")` 拿到相关 chunks 后由 Composer 汇总，**不需要专用结构化 API**

### Review Gate（按 `WORKFLOWS.md`）

- **Gate 1（阶段 A 完成后，第十一轮定稿）**：
  1. LiteLLM function calling 单元测试通过（tool 选择、参数抽取、多 tool 并行、参数校验失败）
  2. **LLM 未返回 tool_call → 降级 unknown 兜底 smoke test 通过**（第十一轮决策 #4）
  3. **job-demand records major 过滤回归**（第十四轮 §1.14 + **第十五轮 §1.15 B1**）：仅 major substring 跨 dataset；major 走 dataset join 反例验证（不误命中 industry_name）；**`fields=industry_distribution` 聚合响应 Top-5 正确**（3+ industry 分布 + 截断 + 空分布边界单测）；未支持参数拒绝或忽略验证
  4. ability-analyses `major_name` substring 回归通过
  5. **capability-graph by-major 一跳端点端到端验证**通过（方案 B + 第十三轮 §1.13 实施澄清）：
     - alembic 迁移加 `major_name` + `major_code` 双列成功；数据回填对存量 teaching_standard / ability_analysis build 生效（有值或解析失败留空 + warn 日志）
     - build 写入路径 CI 断言通过（新 build 落库时两列非空或有 warn 日志）
     - **归一化正确性单元测试通过**：真实 title 样本（"5307 电子商务专业教学标准" / "电子商务（530701）专业教学标准" / "（高职电子商务类专业简介）5307 电子商务类" 等）解析后 major_name 剥离资产类型后缀（"电子商务" 而非 "电子商务专业教学标准"）
     - 按 `major_name`(substring) 或 `major_code`(exact, 4-6 位数字) + `build_type ∈ {teaching_standard, ability_analysis}` 双通路 at-least-one-required 一跳拿单 build 完整图，**不合并多 build**
     - `build_type=job_demand` 或大写值明确返回 422
  6. outline subtree API smoke test 通过
  7. **同义 query 生成组件单元测试通过**（生成 3-5 条、chunk_id dedup 正确、`expand_queries=false` 回归）——**取消 A/B 评测**（第十一轮决策 #7）
  8. 老 `/open/v1/search` / `/open/v1/qa` 全量回归通过
  9. **跨资产原则合规性检查**通过（工具输入无 trace 字段作为必填、响应必带 trace；`config/query_router_tools.json` schema lint 通过）
  10. **审计事件字段端到端回归**通过（老端点 `caller_type=api_caller` 已回填 + A6 新字段全部可写入可查询 + `dispatch_fallback` / `chart_hallucination_ids` 等边界字段验证）
  11. **console/api_caller 双身份识别 smoke test 通过**（console 走 JWT session、api_caller 走 X-API-Key、audit `caller_type` 分别正确落地）
  12. **A0/A3 联调**：用 A0 fake client 试跑 A3 工具注册表中每个 tool 的 tool_choice，验证 schema 完全兼容
  13. **scenario_3 双路 smoke test 通过**（第十五轮 §1.15 A2）：意图命中 scenario_3 时**并行**调用 `internal.query_capability_graph_by_major(build_type=teaching_standard)` + `internal.search_chunks_by_semantic(kb=course_standard_authoring_process, outline_node="培养目标"|"职业面向")`；Composer 拿到两路结果时按"培养目标 / 职业面向 / 岗位知识图谱"三段结构化输出；outline_node 未命中时退化为纯语义 top-K 且响应标注 warn
  14. **工具注册表 §4.2.1 按第十五轮 §1.15 新分组重排验证**：`config/query_router_tools.json` 分组符合业务视角映射（scenario_1 讯息类 / scenario_2 结构化 / scenario_3 教学标准双路 / scenario_4 教材类 / scenario_5 模板占位）；工具跨 scenario 迁移清单核对
- **Gate 2（阶段 B 完成后）**：意图分类 5×20 样本离线评测（准确率、confidence 分布；**样本按第十五轮 §1.15 业务视角标注**）+ 端到端 5 场景 smoke test（含 scenario_3 双路 + scenario_2 industry_distribution 聚合）+ 内外双入口权限差异回归 + 审计事件字段完整性
- **Gate 3（阶段 C 完成后）**：场景 5 端到端跑通 + 缺参分级处理（必填追问 vs 非必填放宽）验证 + verification 节点告警链路

---

## 十一、非 P0 事项（延后）

| 事项                                                    | 触发条件                                                                                      | 备注                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| ------------------------------------------------------- | --------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| BM25 / tsvector 混合检索                                | 长尾召回投诉集中或搜索满意度低于阈值                                                          | 优先 `tsvector`+RRF                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| Cross-encoder rerank                                    | top-K 精度成为瓶颈                                                                            | LiteLLM alias 接 BGE-reranker                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| **多同义 query 结果 rerank 融合**（非 dedup）           | 同义 query 召回噪声成为投诉集中项                                                             | 第十一轮决策 #3 下沉：P0 用简单 dedup；未来评估用 rerank 融合替换                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| **检索召回率 A/B 评测框架**                             | 需要量化对比检索策略变更效果                                                                  | 第十一轮决策 #7 下沉：P0 用单元测试保证正确性；评测框架待建                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| **`industry_research_kb` 内 report_type 二次过滤**      | 场景 2 / step_policy 召回噪声集中                                                             | 第十一轮决策 #9 下沉：P0 三类资产（政策 / 产业报告 / 行业报告）共 kb；未来若语义混杂可按 metadata 加过滤                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| 场景 5 其他模板（课程改革方案、招生方案、产教融合方案） | 业务提出且频次 > N/周                                                                         | 每模板独立评估                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| **`chart:mermaid` fence 扩展**                          | 场景 5 正式实现且需要输出流程图 / 时序图 / 学期甘特；或用户高频要求"画个流程图"这类顺序性语义 | P0 仅支持 `chart:echarts`（graph 结构）；Mermaid 承载文本 DSL 更适合流程 / 时序 / 状态机。落地需：后端新增 `mermaid_adapter.py`（平级于 `chart_adapter.py`，输出 DSL 文本 + 注册 `ChartRegistry`；chart_id 与 §7.3 替换时序完全复用），Composer prompt 增加 `chart:mermaid` fence 说明并按 payload 类型选 fence 语言；前端引入 `mermaid@11+`（~200KB gzip），`QueryRouterAnswer.CodeRenderer` 加 `chart:mermaid` 分支 → 新建 `MermaidFence.tsx` 调用 `mermaid.render()`。**当前分派入口已具备可扩展性**：`CodeRenderer` 按 `language-*` className 字符串分派，无需重构。硬约束沿用 §7.2：Mermaid DSL 也必须由后端拼装，禁止 LLM 现场造节点 |
| 动态无模板 planner                                      | 上述模板覆盖率不足                                                                            | 严控步数、白名单                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| Query 改写 / HyDE / multi-query                         | 意图分类边界问题变多                                                                          | 需与意图分类器联合调优                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| L3/L4 私有模型链路                                      | 首次出现 L3/L4 资产                                                                           | 走 LiteLLM 私有 alias                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| Redis / 分布式结果缓存                                  | 单机 TTL cache 命中率不足                                                                     | 触发条件遵循 ARCHITECT.md 扩展规则                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| 废弃 `/open/v1/search` / `/open/v1/qa` 端点             | 确认无任何调用方且 v2 稳定运行 3 个月                                                         | 也可能长期保留作为低阶 API                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| Console 管理员穿透查询模式                              | Console 提出跨 org 全视图需求                                                                 | 在 `/internal/v1/query` 上加 `admin_scope` 参数                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |

---

## 十二、后续文档变更点

本方案落地时，同步更新：

| 文档                                           | 变更                                                                                                                                                                                                                                                                                                                                                                                                           |
| ---------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `SPEC.md`                                      | 检索/QA 章节新增 "Query Router v2（P0 默认路径）" 小节，说明 `POST /internal/v1/query` 与 `POST /open/v1/query` 为主入口，`/open/v1/search` / `/open/v1/qa` 降级为低阶 API；说明审计事件扩展字段                                                                                                                                                                                                               |
| `ARCHITECT.md`                                 | 在 orchestration 层登记新组件（Intent Classifier / Parameter Extractor / Tools Registry / Template Executor / Chart Adapter）；说明由现有四层框架合并演进而来；登记 LiteLLM function calling 支持为 P0 增强                                                                                                                                                                                                    |
| `docs/task-packages/`                          | 新增 `wk_query_router_v2_p0_task_package.md`，按 §十 的三阶段分 owner、deliverables、Review Gate                                                                                                                                                                                                                                                                                                               |
| `config/`                                      | 新增 `query_router_tools.json`（工具注册表，含 scenario_1-5 全部 5 组分组；**无 ETag/fcntl 编辑保护**，由后端工程师随代码 PR 维护，第十一轮决策 #6）；新增 **`config/plans/talent_cultivation_plan.yaml`**（DAG 模板，`step_standard.build_type` 用小写 `teaching_standard`）；`ai_prompt_profile` 添加 5 个新模板（intent_v2 / param_extract_v2 / compose_v2 / query_expansion_v2 / plan.talent_cultivation） |
| `retrieval/intent.py` / `retrieval/planner.py` | 原地重构，保留文件路径                                                                                                                                                                                                                                                                                                                                                                                         |
| `ai_governance/litellm_client.py`              | 扩展 `LiteLLMClientProtocol` 与 `RealLiteLLMClient` 支持 `tools` / `tool_choice`                                                                                                                                                                                                                                                                                                                               |

---

**文档终稿说明**：本文档为 v2.0 定稿，已合并五轮 review 讨论结论；后续实现中如发现契约缺口，先在 §一 追加"第六轮讨论"章节记录变更依据，再修订正文对应小节，保持"讨论记录 → 决定 → 实现"的追溯链完整。
