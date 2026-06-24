# Pipeline B API 契约草案（B0 产出 · 待评审）

- **状态**：**待 API Contract Gate + Permission And Audit Gate Review**
- **日期**：2026-06-24
- **切片**：B0 合同冻结配套草案（实施计划 §三 B0 Deliverables）
- **依据**：
  - 主冻结清单：`docs/pipeline_b_contract_freeze.md` §十
  - 决策依据：实施计划 §八 决策 9（API 暴露到 `nexus-api/v1`）
  - 现状代码：
    - 业务 API：`nexus-api/nexus_api/api/open.py`（实际前缀 `/open/v1`，与 `CLAUDE.md` "`/v1` baseline" 的实现形态）
    - 控制台后端 API：`nexus-api/nexus_api/api/internal/*.py`（前缀 `/internal/v1`）
    - 控制台前端 handler：`nexus-console/app/api/*`（Next.js route handlers）
  - 全局约束：`WORKFLOWS.md` API Implementation Constraints
- **核心约束**：
  - **不在 B0 编写任何 API 实现代码**（B0 Forbidden）
  - 业务 API 与控制台 API **资源命名、错误码、幂等策略对齐 RESTful**，但归属严格分离
  - `nexus-console` 控制台路由不绕过 `nexus-api`（业务能力必须在 `/open/v1`，不能仅在 `/internal/v1`）

---

## 〇、命名与归属规则

| 前缀                       | 归属服务                           | 调用方                                             | 鉴权方式                                 |
| -------------------------- | ---------------------------------- | -------------------------------------------------- | ---------------------------------------- |
| `/open/v1/*`               | `nexus-api`                        | 上游系统（智能问答、第三方课程平台、招聘合作方等） | API Key（`api_caller`） + 权限过滤       |
| `/internal/v1/*`           | `nexus-api`                        | `nexus-console` 控制台后端调用                     | JWT（user_account） + RBAC               |
| `nexus-console /app/api/*` | `nexus-console`（Next.js handler） | 浏览器端                                           | NextAuth session → 调用 `/internal/v1/*` |

约束：

- 同一业务能力**禁止**仅暴露在 `/internal/v1`；上游消费场景的能力必须复制（或代理）一份到 `/open/v1`
- `/open/v1` 不暴露管理类操作（写入治理结果、修改 profile、编辑规则等）
- 业务 API 响应字段必须经过 `nexus-app/permissions.py` 的 org_scope 过滤；管理 API 按 RBAC 鉴权

---

## 一、`/open/v1/*` 业务 API（上游消费）

> 全部为只读 GET（P0 范围）。错误响应统一使用 `nexus-api` 既有错误体（`responses.py` / `errors.py`）。

### 1.1 Record 资产列表

```http
GET /open/v1/record-assets
```

Query 参数：

| 参数              | 类型   | 必填                        | 说明                                                                             |
| ----------------- | ------ | --------------------------- | -------------------------------------------------------------------------------- |
| `record_type`     | enum   | 否                          | `job_demand_dataset` / `occupational_ability_analysis` / `generic_table_dataset` |
| `domain`          | string | 否                          | 如 `occupation`                                                                  |
| `domain_profile`  | string | 否                          | 如 `job_demand.v1`                                                               |
| `industry_name`   | string | 否                          | 等值匹配                                                                         |
| `city`            | string | 否                          | 等值匹配（来源原文）                                                             |
| `enterprise_size` | string | 否                          | 等值匹配（来源原文，不归一）                                                     |
| `keyword`         | string | 否                          | 在 `title` / `major_name` 等字段做包含匹配                                       |
| `page`            | int    | 否，default `1`             |                                                                                  |
| `page_size`       | int    | 否，default `20`，max `100` |                                                                                  |

响应（Pydantic 草案）：

```python
class RecordAssetListItem(BaseModel):
    asset_id: str
    asset_version_id: str
    normalized_ref_id: str
    record_type: str
    domain: str
    domain_profile: str
    title: str | None
    major_name: str | None
    industry_name: str | None
    record_count: int
    schema_version: str
    quality_summary: dict
    created_at: datetime

class RecordAssetListResponse(BaseModel):
    items: list[RecordAssetListItem]
    page: int
    page_size: int
    total: int
```

### 1.2 Record 资产详情

```http
GET /open/v1/record-assets/{normalized_ref_id}
```

响应：

```python
class RecordAssetDetail(BaseModel):
    asset_id: str
    asset_version_id: str
    normalized_ref_id: str
    record_type: str
    domain: str
    domain_profile: str
    profile: dict                # 见冻结清单 §2
    schema_version: str
    record_count: int
    quality_summary: dict
    lineage: dict
    metadata_summary: dict
    created_at: datetime
    updated_at: datetime
```

错误：

- `404` `RECORD_ASSET_NOT_FOUND`
- `403` `RECORD_ASSET_NOT_AUTHORIZED`

### 1.3 岗位需求记录列表（按 dataset）

```http
GET /open/v1/job-demand-datasets/{dataset_id}/records
```

Query 参数：

| 参数                     | 类型   | 必填 | 说明           |
| ------------------------ | ------ | ---- | -------------- |
| `city`                   | string | 否   |                |
| `industry_name`          | string | 否   |                |
| `enterprise_size`        | string | 否   | 原文等值匹配   |
| `employment_type`        | string | 否   |                |
| `education_requirement`  | string | 否   |                |
| `experience_requirement` | string | 否   |                |
| `salary_min_gte`         | number | 否   | 结构化薪资下界 |
| `salary_max_lte`         | number | 否   | 结构化薪资上界 |
| `page` / `page_size`     | int    | 否   |                |

响应：

```python
class JobDemandRecordItem(BaseModel):
    id: str
    dataset_id: str
    job_title: str
    employment_type: str | None
    job_function_category: str | None
    city: str | None
    region: str | None
    salary_min: float | None
    salary_max: float | None
    salary_text: str | None
    experience_requirement: str | None
    education_requirement: str | None
    company_name: str | None
    enterprise_size: str | None
    industry_name: str | None
    job_skill_text: str | None
    quality_flags: dict
    source_published_at: datetime | None

class JobDemandRecordListResponse(BaseModel):
    items: list[JobDemandRecordItem]
    page: int
    page_size: int
    total: int
```

### 1.4 岗位需求记录抽取项

```http
GET /open/v1/job-demand-records/{record_id}/requirement-items
```

Query 参数：

| 参数             | 类型   | 说明                                                                                            |
| ---------------- | ------ | ----------------------------------------------------------------------------------------------- |
| `item_type`      | enum   | `professional_skill` / `tool` / `certificate` / `professional_literacy` / `work_task_candidate` |
| `min_confidence` | number | 默认 0；上游可指定 ≥ 阈值过滤                                                                   |

响应：

```python
class RequirementItem(BaseModel):
    id: str
    item_type: str
    item_name: str
    normalized_name: str | None
    raw_text: str | None
    evidence_field: str | None
    confidence: float
    extractor_version: str | None
    ai_model_alias: str | None

class RequirementItemListResponse(BaseModel):
    record_id: str
    items: list[RequirementItem]
```

### 1.5 能力分析任务树

```http
GET /open/v1/occupational-ability-analyses/{analysis_id}/tasks
```

响应：

```python
class WorkContent(BaseModel):
    id: str
    content_code: str
    content_name: str
    content_description: str | None
    display_order: int

class WorkTask(BaseModel):
    id: str
    task_code: str
    task_name: str
    task_description: str | None
    task_description_structured: dict
    display_order: int
    work_contents: list[WorkContent]

class TaskTreeResponse(BaseModel):
    analysis_id: str
    analysis_model: str
    major_name: str | None
    tasks: list[WorkTask]
```

### 1.6 能力条目列表（按 analysis / task / work_content 过滤）

```http
GET /open/v1/occupational-ability-analyses/{analysis_id}/ability-items
```

Query 参数：

| 参数                          | 类型   | 说明                                            |
| ----------------------------- | ------ | ----------------------------------------------- |
| `task_id`                     | UUID   | 可选过滤                                        |
| `work_content_id`             | UUID   | 可选过滤；P/G/S/D 中 G/S/D 不传 work_content_id |
| `ability_major_category_code` | string | `P` / `G` / `S` / `D`                           |
| `page` / `page_size`          | int    |                                                 |

响应：

```python
class AbilityItem(BaseModel):
    id: str
    task_id: str
    work_content_id: str | None      # G/S/D 类为 None
    ability_code: str
    ability_major_category_code: str
    ability_major_category_name: str
    ability_sequence: str
    ability_content: str
    normalized_terms: dict
    confidence: float | None
    quality_flags: dict

class AbilityItemListResponse(BaseModel):
    items: list[AbilityItem]
    page: int
    page_size: int
    total: int
```

### 1.7 CapabilityGraphStaging 预览（只读）

```http
GET /open/v1/capability-graph-staging/{build_id}
```

响应：

```python
class StagingNode(BaseModel):
    id: str
    node_type: str
    node_key: str
    display_name: str
    canonical_name: str | None
    properties: dict
    confidence: float | None

class StagingEdge(BaseModel):
    id: str
    source_node_id: str
    target_node_id: str
    edge_type: str
    evidence: dict
    confidence: float | None

class StagingBuildPreview(BaseModel):
    build_id: str
    normalized_ref_id: str
    domain: str
    build_type: str
    status: str
    schema_version: str
    quality_summary: dict
    nodes: list[StagingNode]
    edges: list[StagingEdge]
```

约束：单次响应节点 + 边总数上限 `5000`，超出走 `404` `STAGING_BUILD_TOO_LARGE` + 提示走 list 分页接口（P1）。

---

## 二、`/internal/v1/*` 控制台后端 API（管理用）

> JWT 鉴权 + RBAC。Pydantic schema 与 `/open/v1` 共享底层 dto，但响应额外暴露管理字段（如 `quality_flags`、`trace`、内部 ID、未脱敏字段）。

### 2.1 Profile 识别结果与 candidate 列表

```http
GET /internal/v1/record-profiles/candidates
```

Query：`record_type=*_candidate` 或 confidence 范围；返回候选 record_type 的 normalized_ref 列表，用于人工 review。

### 2.2 治理结果与 review 操作

```http
GET    /internal/v1/governance-results?normalized_ref_id=...
POST   /internal/v1/governance-results/{id}/review        # 人工通过 / 拒绝
POST   /internal/v1/governance-results/{id}/recompute     # 重新跑治理校验
```

约束：

- 所有写入操作必须带 `Idempotency-Key` header
- `recompute` 触发 `GovernanceRulesRecomputeRequested` 审计事件（既有事件名）
- 写入操作落 `audit_log`

### 2.3 ability_analysis_profile 管理（仅查询）

```http
GET /internal/v1/ability-analysis-profiles
GET /internal/v1/ability-analysis-profiles/{id}
```

P0 不提供编辑接口（profile 由 Alembic seed 维护）。

### 2.4 ai_analysis_rules 查询（仅查询，决策 2）

```http
GET /internal/v1/ai-analysis-rules
GET /internal/v1/ai-analysis-rules/{id}
```

响应字段：`rule_set_code` / `version` / `scenario` / `domain` / `output_contract` / `guardrails` / `auto_admit_threshold` / `is_active` / `initialized_at`。

P0 **不提供** POST / PUT / DELETE（变更走 PR + 评审 + seed 重跑）。

### 2.5 ai_prompt_profile 查询（沿用既有 `/internal/v1/ai-prompts/*`）

> 既有路由 `nexus-api/nexus_api/api/internal/ai_prompts.py`。本计划在响应中补充 `domain` / `rules_object_type` / `rules_object_code` 三个字段（B5 配合改造）。

### 2.6 任务追溯（已存在）

复用 `/internal/v1/jobs/*` 既有接口；新增的 `job_type` 取值或 `payload.pipeline_type` 字段不破坏响应 schema。

### 2.7 跨 sheet 不一致告警查询

```http
GET /internal/v1/occupational-ability-analyses/{analysis_id}/quality-flags
```

响应：

```python
class QualityFlag(BaseModel):
    flag_key: str            # e.g. 'cross_sheet_inconsistency', 'location_unparsed'
    severity: str            # 'warning' / 'blocking'
    description: str
    detail: dict             # 不一致项的具体差异
```

P0 宽松模式下 `cross_sheet_inconsistency` 仅以 `severity=warning` 出现，**不**进入 `review_required`（决策 3）。

---

## 三、错误码与幂等约定

### 3.1 错误码命名空间

| 命名空间              | 适用                   |
| --------------------- | ---------------------- |
| `RECORD_ASSET_*`      | 业务 API record 资产   |
| `JOB_DEMAND_*`        | 岗位需求子资源         |
| `ABILITY_ANALYSIS_*`  | 能力分析子资源         |
| `STAGING_*`           | CapabilityGraphStaging |
| `AI_ANALYSIS_RULES_*` | 知识单元加工规则       |

每个错误响应符合既有 `nexus-api` 错误体：

```json
{
  "trace_id": "...",
  "error": {
    "code": "RECORD_ASSET_NOT_FOUND",
    "message": "record asset {id} not found",
    "details": {}
  }
}
```

### 3.2 幂等性

| 写入端点                                              | 幂等策略                                                                     |
| ----------------------------------------------------- | ---------------------------------------------------------------------------- |
| `POST /internal/v1/governance-results/{id}/review`    | `Idempotency-Key` header；重复请求返回首次结果 + `X-Idempotent-Replay: true` |
| `POST /internal/v1/governance-results/{id}/recompute` | 同上                                                                         |
| 任何 seed 重跑                                        | DB 层 `(rule_set_code, version)` 唯一键去重                                  |

读 GET 接口天然幂等。

### 3.3 限流（建议，B5+ 落地）

`/open/v1/*` 全部 GET 按 `api_caller` 限流；建议默认 60 req/min；超限返回 `429 RATE_LIMITED`。

---

## 四、权限模型

### 4.1 `/open/v1/*` 权限

- 鉴权：`api_caller` API Key
- 授权：基于 `api_caller.org_scope` 做行级过滤
- 字段级脱敏：L3/L4 字段在响应中默认掩码；除非 `api_caller` 拥有显式 `unmask` scope

约束（继承 `WORKFLOWS.md` Permission And Audit Gate）：

- Auth before return；不允许鉴权失败但返回 200
- 高敏感字段（如 `company_address`、`source_url`）默认掩码
- 所有命中 `/open/v1/*` 的请求落 `SEARCH_QUERY_EXECUTED` 或新增 `ASSET_VERSION_ACCESSED` 审计事件（按调用语义）

### 4.2 `/internal/v1/*` 权限

- 鉴权：`user_account` JWT
- 授权：RBAC（角色：admin / editor / reviewer / viewer，按既有角色集合）
- 操作：`review` / `recompute` 仅 admin / reviewer 可调用

### 4.3 `nexus-console /app/api/*`（Next.js handler）

- 仅做 session → JWT 翻译，不实现业务逻辑
- 透传到 `/internal/v1/*` 后返回

---

## 五、契约测试要求

> B5 / B4 / B6 / B8 实施时必交付：

1. **`/open/v1` 与 `/internal/v1` 字段映射一致性**：同一资源（如 `JobDemandRecord`）在两侧暴露的字段子集与命名必须一致（管理 API 可超集）
2. **错误码完整性**：每个端点的错误码集合必须有 pytest 用例覆盖
3. **幂等性回归**：写入端点的重复请求测试
4. **权限隔离**：跨 `api_caller` 的 record 资产不可见
5. **L3/L4 掩码**：高敏感字段在 `/open/v1` 响应中已脱敏

---

## 六、与既有 API 的兼容性

| 既有端点                                    | 影响                                                                | 处理                                                                    |
| ------------------------------------------- | ------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| `/open/v1/normalized-refs/{ref_id}/content` | record 资产命中时返回标准化快照                                     | 已支持，不改                                                            |
| `/open/v1/normalized-refs/{ref_id}/chunks`  | record 资产**不应**返回 chunks（Pipeline B 不写 `knowledge_chunk`） | 命中 record_type 时返回 `404 RECORD_HAS_NO_CHUNKS` 或空数组（评审决定） |
| `/open/v1/search`                           | 是否含 record 资产搜索？（建议 P0 仅含 document）                   | 评审决定；建议 **不** 在本期扩展                                        |
| `/internal/v1/ai-prompts/*`                 | 响应新增 `domain` / `rules_object_type` / `rules_object_code` 字段  | B5 改                                                                   |
| `/internal/v1/jobs/*`                       | `payload.pipeline_type` 可能为 `record`，前端展示标签需对应         | B9 改                                                                   |

---

## 七、不进入本期 API

- `POST /internal/v1/ai-analysis-rules`（创建规则）— P0 不支持编辑
- `PUT /internal/v1/ai-analysis-rules/{id}`（编辑规则）— 同上
- `POST /internal/v1/ability-analysis-profiles`（创建 profile）— P0 由 seed 维护
- record 资产语义搜索 / QA — P0 不进入
- staging build 创建端点 — 由 worker 自动触发，不暴露同步创建 API
- `nexus-api/v1` "promote staging → 正式图谱" — 设计中 `promoted` 状态留待 P1

---

## 八、Review 关注点

> **API Contract Gate** 必须覆盖：

1. `/open/v1/normalized-refs/{ref_id}/chunks` 对 record 资产返回什么？（建议 `404 RECORD_HAS_NO_CHUNKS`）
2. `/open/v1/record-assets` 与既有 `/open/v1/normalized-refs` 是否重复？（建议**新增** `record-assets` 资源，因业务语义对上游更明确）
3. `enterprise_size` 在 `/open/v1` 是否需要任何归一化？（决策 7：**否**，按原文等值匹配）
4. `task_description_structured` 是否暴露给上游？（建议**暴露**，但 confidence < 阈值时打 quality_flag 提示）
5. 分页是否使用 cursor 而非 offset？（按既有 `/open/v1` 接口形态决定；建议 P0 沿用 page/page_size）

> **Permission And Audit Gate** 必须覆盖：

1. `api_caller.org_scope` 对 record 资产的过滤语义是否清晰？
2. 高敏感字段集合（`company_address` / `source_url` / `source_record_key` 等）是否需要默认掩码？
3. 是否需要为 record 资产单独定义 `RECORD_ASSET_ACCESSED` 审计子类型，还是复用 `ASSET_VERSION_ACCESSED`？（建议**复用**，通过 `AssetAccessType` 区分）

---

## 九、签字栏（待人工填写）

```
后端 owner（_______________）：审阅 §一 / §二 / §三 / §六 → 签字 / 待修改
前端 owner（_______________）：审阅 §二 / §四 → 签字 / 待修改
业务专家（_______________）：审阅 §一 字段映射 → 签字 / 待修改
安全 owner（_______________）：审阅 §四 / §八 → 签字 / 待修改
```

未签字前 B4 / B5 / B6 / B8 不得开始 API 实施。
