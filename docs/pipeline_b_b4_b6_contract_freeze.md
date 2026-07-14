# Pipeline B B4 / B6 并行契约冻结

> 本文档是 `docs/pipeline_b_contract_freeze.md` 的**增量扩展**，专门冻结 B4（岗位需求领域表）与 B6（能力分析领域表）**并行执行所必需**的接口契约。
>
> 表 schema 本身已在 `docs/pipeline_b_contract_freeze.md §五（5.1-5.3, 5.5-5.11）` 完成草案；本文档将其**状态由"草案"提升为"frozen"**，并补齐表 schema 之外的执行契约（写入服务签名、字段映射、幂等键、quality_flags 词表、审计事件、并行隔离边界）。
>
> 评审通过后，B4 与 B6 可由不同 Agent 并行实施；本文档同时是后续 B4 / B6 task package 的源头依据。

---

## 〇、与现状的校准

| 项                                               | 现状                                                                                                                                                                                           |
| ------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 表 schema 冻结源                                 | `docs/pipeline_b_contract_freeze.md §5.1-5.3, §5.5-5.11`（草案 → 经本文档评审升级为 frozen）                                                                                                   |
| `normalized_record.payload` schema               | v2（`normalized-record.v2`），由 B3 落地；常量在 `nexus_app/pipeline/normalized_record_schema.py`                                                                                              |
| `normalized_asset_ref` 现状字段                  | `version_id` / `normalized_type` / `schema_version` / `record_count` / `governance` / `quality` / `lineage` / `metadata_summary`（见 `nexus_app/models.py:481-535`）                           |
| `ability_analysis_profile` / `ai_analysis_rules` | 表本身**不属 B4 / B6 范畴**：`ability_analysis_profile` 由 B6 内建 seed（不冻结管理 API）；`ai_analysis_rules` 由 B5 建表；B4 仅在 `job_demand_requirement_item.rules_version_id` 预留 FK 占位 |
| API 归属                                         | 见 `docs/pipeline_b_contract_freeze.md §十` + `docs/pipeline_b_api_contract_draft.md §1.1-1.7 / §2.1-2.7`（本期不再重述路径）                                                                  |

---

## 一、并行隔离边界（核心 · 防 B4 / B6 互相阻塞）

为支持 B4 / B6 并行实施，约定以下隔离原则：

| 类别             | B4 范围                                                                                                  | B6 范围                                                                                                                                                                                                                               | 共享 / 接缝                                                                                                                                                                             |
| ---------------- | -------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 领域表           | `job_demand_dataset` / `job_demand_record` / `job_demand_requirement_item`                               | `ability_analysis_profile`（seed only）/ `occupational_ability_analysis` / `occupational_work_task` / `occupational_work_content` / `occupational_ability_item` / `occupational_ability_relation` / `ability_analysis_source_dataset` | 都引用 `normalized_asset_ref.id`（单向 FK，无反向指针）                                                                                                                                 |
| 写入入口         | `nexus_app/domain_normalize/job_demand_writer.py`（新模块）                                              | `nexus_app/domain_normalize/ability_analysis_writer.py`（新模块）                                                                                                                                                                     | 共用 `nexus_app/domain_normalize/__init__.py` 公开 `dispatch_domain_normalize(normalized_ref)` 单入口                                                                                   |
| Worker 集成      | 无新阶段；B2 `profile_detect` 已落地后由 B4 在 `pipeline/stages.py` 新增 `_run_domain_normalize`         | 同左（B6 复用 B4 在 stages 的接缝；通过 `domain_profile` 分发）                                                                                                                                                                       | `run_domain_normalize(job, session)` 单一 worker stage；按 `domain_profile` switch 分发到上述 writer                                                                                    |
| 审计事件         | `JOB_DEMAND_DATASET_PERSISTED` / `JOB_DEMAND_RECORD_PERSISTED`                                           | `ABILITY_ANALYSIS_PERSISTED` / `ABILITY_ITEM_PERSISTED`                                                                                                                                                                               | 共用 `DOMAIN_NORMALIZE_COMPLETED` / `DOMAIN_NORMALIZE_FAILED`                                                                                                                           |
| Migration 文件夹 | 各自独立 revision；B4 不依赖 B6 表存在                                                                   | 各自独立 revision；B6 不依赖 B4 表存在                                                                                                                                                                                                | `ability_analysis_source_dataset` 同时引用 `occupational_ability_analysis` 与 `job_demand_dataset`：由 **B6 负责创建**，若 B4 未先 merge 则 alembic merge 时通过 down_revision 顺序解决 |
| API 资源前缀     | `/v1/record-assets/job-demand-records/*` / `/v1/record-assets/job-demand-datasets/*` / requirement-items | `/v1/record-assets/ability-analyses/*` / `*/work-tasks/*` / `*/work-contents/*` / `*/ability-items/*`                                                                                                                                 | 详见 §五                                                                                                                                                                                |

**强约束**：

- B4 / B6 不得**双向**修改对方的表、writer、API、audit enum；只能**新增**自己的迁移文件
- B4 / B6 不得共用同一个 alembic revision；并行实施时各自分支 head，最后合并通过 alembic merge 解决
- B6 的 `ability_analysis_source_dataset` 表引用 `job_demand_dataset`：B4 merge 后 B6 才能跑该表的 migration（依赖关系明示在 down_revision 中）

---

## 二、normalized_record v2 → 领域表字段映射（不可变契约）

> 字段名严格对齐 `docs/pipeline_b_contract_freeze.md §5.0.2` 中 `record_body` 的 JSON shape，与领域表列名一一对应。Writer 必须按此映射逐字段读取，不允许"语义近似"字段替换。

### 2.1 岗位需求映射（B4 writer）

**`record_body.dataset.*` → `job_demand_dataset.*`**

| `record_body.dataset.<key>` | `job_demand_dataset.<column>`            | 说明                                                                                           |
| --------------------------- | ---------------------------------------- | ---------------------------------------------------------------------------------------------- |
| `major_name`                | `major_name`                             | 缺省 NULL                                                                                      |
| `industry_name`             | `industry_name`                          | 缺省 NULL                                                                                      |
| `source_channel`            | `source_channel`                         | 必填；不在白名单时回写 `quality_summary.unknown_source_channel = <value>`，列入 `excel_upload` |
| `record_count`              | `record_count`                           | 数值；缺省 `0`                                                                                 |
| `invalid_count`             | `invalid_count`                          | 数值；缺省 `0`                                                                                 |
| `duplicate_count`           | `duplicate_count`                        | 数值；缺省 `0`                                                                                 |
| —                           | `schema_version`                         | 固定写 `record_body` payload 的 `schema_version`（来自 profile）                               |
| —                           | `quality_summary`                        | 由 writer 聚合 §四 quality_flags 词表生成（详见 §四）                                          |
| —                           | `asset_version_id` / `normalized_ref_id` | 由 writer 从 `NormalizedAssetRef` 上下文取                                                     |

**`record_body.records[].*` → `job_demand_record.*`**

| `record_body.records[].<key>` | `job_demand_record.<column>` | 说明                                                                                         |
| ----------------------------- | ---------------------------- | -------------------------------------------------------------------------------------------- |
| `source_record_key`           | `source_record_key`          | 必填；来自爬虫记录 ID / sheet+row hash                                                       |
| `job_title`                   | `job_title`                  | 必填；缺失时整条记录跳过，计入 `invalid_count`                                               |
| `employment_type`             | `employment_type`            | 不做枚举校验                                                                                 |
| `job_function_category`       | `job_function_category`      | 不做枚举校验                                                                                 |
| `job_count`                   | `job_count`                  | INT NULL                                                                                     |
| `city`                        | `city`                       | 原文写入；不解析                                                                             |
| `region`                      | `region`                     | 由 normalize 解析；失败 NULL + `quality_flags.location_unparsed = true`                      |
| `salary_min` / `salary_max`   | `salary_min` / `salary_max`  | NUMERIC NULL                                                                                 |
| `salary_text`                 | `salary_text`                | 原文                                                                                         |
| `experience_requirement`      | `experience_requirement`     | 原文                                                                                         |
| `education_requirement`       | `education_requirement`      | 原文                                                                                         |
| `company_name`                | `company_name`               | 原文                                                                                         |
| `company_address`             | `company_address`            | 原文                                                                                         |
| `enterprise_size`             | `enterprise_size`            | 原文；**禁止**任何枚举/区间归一                                                              |
| `industry_name`               | `industry_name`              | 原文                                                                                         |
| `job_skill_text`              | `job_skill_text`             | 原文                                                                                         |
| `job_description`             | `job_description`            | 原文                                                                                         |
| `responsibility_text`         | `responsibility_text`        | 原文                                                                                         |
| `requirement_text`            | `requirement_text`           | 原文                                                                                         |
| `source_url`                  | `source_url`                 | NULL 允许                                                                                    |
| `source_platform`             | `source_platform`            | NULL 允许                                                                                    |
| `source_published_at`         | `source_published_at`        | ISO8601 字符串解析为 timestamptz；解析失败 NULL + `quality_flags.published_at_unparsed=true` |
| `trace`                       | `trace`                      | 直接整体写 JSONB                                                                             |
| —                             | `record_fingerprint`         | 由 writer 按 §三 算法计算                                                                    |
| —                             | `quality_flags`              | writer 在写入过程中累积（§四 词表）                                                          |

**`job_demand_requirement_item`**：B4 仅建表 + 索引；写入由 B5 LLM 抽取阶段负责，B4 不写入任何记录。

### 2.2 能力分析映射（B6 writer）

**`record_body.analysis.*` → `occupational_ability_analysis.*`**

| `record_body.analysis.<key>` | `occupational_ability_analysis.<column>` | 说明                                                                               |
| ---------------------------- | ---------------------------------------- | ---------------------------------------------------------------------------------- |
| `major_name`                 | `major_name`                             |                                                                                    |
| `major_direction`            | `major_direction`                        |                                                                                    |
| `analysis_model`             | `analysis_model`                         | 与 `profile_id` 指向的 profile.model_code 一致；不一致则 reject                    |
| `task_count`                 | `task_count`                             | 计算值                                                                             |
| `work_content_count`         | `work_content_count`                     | 计算值                                                                             |
| `ability_item_count`         | `ability_item_count`                     | 计算值                                                                             |
| —                            | `profile_id`                             | writer 按 `payload.domain_profile` 查 `ability_analysis_profile.schema_version` 取 |
| —                            | `schema_version`                         | 取自 `payload.schema_version`                                                      |
| —                            | `source_job_demand_dataset_id`           | P0 默认 NULL；预留 P1 通过 `ability_analysis_source_dataset` 关联                  |

**`record_body.tasks[].*` → `occupational_work_task.*`**

| key                           | column                        | 说明                                     |
| ----------------------------- | ----------------------------- | ---------------------------------------- |
| `task_code`                   | `task_code`                   | 必填                                     |
| `task_name`                   | `task_name`                   | 必填                                     |
| `task_description`            | `task_description`            | 原文；保留多行 `\n` 与 `①②③`             |
| `task_description_structured` | `task_description_structured` | B6 写入时强制置 `{}`；由 B5 LLM 抽取覆盖 |
| `display_order`               | `display_order`               | INT；缺省按 record_body 顺序             |
| `trace`                       | `trace`                       | 直接整体写 JSONB                         |

**`record_body.tasks[].work_contents[].*` → `occupational_work_content.*`**

| key                   | column                | 说明                    |
| --------------------- | --------------------- | ----------------------- |
| `content_code`        | `content_code`        | 必填                    |
| `content_name`        | `content_name`        | 必填                    |
| `content_description` | `content_description` | 缺省 NULL               |
| —                     | `display_order`       | 按 record_body 顺序自增 |
| —                     | `task_id`             | writer 写入 task 后取   |

**`record_body.tasks[].work_contents[].abilities[].*` + `general_abilities.{G,S,D}[].*` → `occupational_ability_item.*`**

| key                           | column                        | 说明                                                                           |
| ----------------------------- | ----------------------------- | ------------------------------------------------------------------------------ |
| `ability_code`                | `ability_code`                | 必填；唯一 `(analysis_id, ability_code)`                                       |
| `ability_major_category_code` | `ability_major_category_code` | 'P'/'G'/'S'/'D' 等；从 `ability_analysis_profile.category_schema` 校验         |
| —                             | `ability_major_category_name` | writer 从 profile.category_schema 反查取得                                     |
| —                             | `ability_sequence`            | 由 ability_code 按 code_pattern[<category>].regex 提取段式部分（去掉大类前缀） |
| `ability_content`             | `ability_content`             | 必填                                                                           |
| `normalized_terms`            | `normalized_terms`            | 缺省 `{}`                                                                      |
| `confidence`                  | `confidence`                  | 缺省 NULL                                                                      |
| `trace`                       | `trace`                       | 直接整体写 JSONB                                                               |
| —                             | `work_content_id`             | 必填当 profile.code_pattern[<category>].requires_work_content=true；否则 NULL  |
| —                             | `task_id`                     | 必填（所有 ability 均挂在 task 下）                                            |

`occupational_ability_relation`：B6 写入 `TASK_HAS_WORK_CONTENT` + `WORK_CONTENT_REQUIRES_ABILITY`；其余白名单（`ABILITY_DERIVED_FROM_JOB_REQUIREMENT` / `ABILITY_RELATED_TO_SKILL`）由 B5 / 后续切片写入。

`ability_analysis_source_dataset`：B6 写入仅当 `payload.metadata.source_job_demand_dataset_id` 显式声明时；P0 默认不写。

---

## 三、唯一性 / 幂等键算法冻结

### 3.1 `job_demand_record.record_fingerprint`

```text
record_fingerprint = sha256_hex(
  norm(company_name) || "|" ||
  norm(job_title)    || "|" ||
  norm(city)         || "|" ||
  norm(source_record_key)
)

norm(x) = lower(strip(unicode_nfkc(x || "")))
```

- `norm("")` 保留为空字符串
- 算法实现需公开为 `nexus_app/domain_normalize/fingerprint.py::compute_job_demand_record_fingerprint(record_dict)`，B5 / B7 复用
- 哈希长度 64 字符，写入 `TEXT NOT NULL`
- 唯一约束 `uq_jdr_dataset_fingerprint (dataset_id, record_fingerprint)`：dataset 内去重；不同 dataset 允许相同 fingerprint

在源行 fingerprint 之外，B4 写入前执行公司岗位清洗：仅当 `company_name` 和
`job_title` 均非空时按其 NFKC 规范化值分组。同一组若存在可解析
`source_published_at`，保留发布时间最新的记录；若全组都没有可解析发布时间，
保留源输入顺序第一条。公司名为空的记录不参与该规则，以避免将不同未知企业的
岗位错误合并。被清洗掉的记录不写入 `job_demand_record`，并通过
`duplicate_company_job` 计入 dataset 的 `duplicate_count` 与 `quality_summary`。

### 3.2 `occupational_*` 唯一约束

- `uq_owt_analysis_task_code (analysis_id, task_code)`：同 analysis 内 task_code 不重复
- `uq_owc_analysis_content_code (analysis_id, content_code)`：同 analysis 内 content_code 不重复
- `uq_oai_analysis_code (analysis_id, ability_code)`：同 analysis 内 ability_code 不重复

冲突时 writer 行为：

- B6 走 `upsert by (analysis_id, *_code)`：相同 code 视作 record*body 的修订；覆写非 PK / 非 FK 字段；写 `audit_log` 记 `ABILITY*\*\_UPDATED`（如需）
- B4 走 `insert on conflict do nothing`：record_fingerprint 冲突视为去重，`duplicate_count++`

### 3.3 dataset-level idempotency

- `job_demand_dataset` / `occupational_ability_analysis` 主键 `(normalized_ref_id)` 必须**唯一**：同一 normalized_ref 只能写一份 dataset / analysis 记录
- writer 行为：先查 `(normalized_ref_id)`，存在则 `delete cascade → re-insert`，避免脏数据（job 重跑场景）
- delete cascade 通过 FK 的 `ondelete="CASCADE"` 实现（B4 / B6 migration 必须显式声明）

---

## 四、`quality_flags` 词表冻结（B4 / B6 共用）

writer 在写入时按下列固定 key 累积 `quality_flags` JSONB；下游 console / governance 据此分类展示。

| flag key                              | 写入方 | 含义                                                                         | 阻塞策略                          |
| ------------------------------------- | ------ | ---------------------------------------------------------------------------- | --------------------------------- |
| `location_unparsed`                   | B4     | `city` 原文存在但 `region` 解析失败                                          | 不阻塞                            |
| `published_at_unparsed`               | B4     | `source_published_at` 原文存在但 ISO 解析失败                                | 不阻塞                            |
| `placeholder_row_dropped`             | B4     | 行命中占位规则被丢弃；`invalid_count++`                                      | 不阻塞                            |
| `duplicate_company_job`               | B4     | 同 dataset 内同一非空公司名和岗位名的清洗重复；有有效发布时间取最新，否则取源顺序第一条；`duplicate_count++` | 不阻塞 |
| `duplicate_fingerprint`               | B4     | 行 fingerprint 与同 dataset 已存在记录冲突；`duplicate_count++`              | 不阻塞                            |
| `missing_required_field`              | B4     | 必填字段缺失（`job_title` 等）；`invalid_count++`                            | 不阻塞                            |
| `unknown_source_channel`              | B4     | dataset `source_channel` 不在已知集合                                        | 不阻塞                            |
| `ability_code_pattern_mismatch`       | B6     | `ability_code` 不符合 `code_pattern[<category>].regex`                       | 不阻塞；条目仍入库（用于 review） |
| `ability_category_unknown`            | B6     | `ability_major_category_code` 不在 `profile.category_schema`                 | **阻塞条目入库**（reject 该行）   |
| `work_content_missing_for_p_category` | B6     | profile 声明 `requires_work_content=true` 但 record_body 未挂 work_content   | 阻塞条目入库                      |
| `task_code_duplicate`                 | B6     | 同 analysis 内 task_code 重复                                                | 阻塞重复行（保留首条）            |
| `cross_sheet_inconsistency`           | B6     | 任务-工作内容-能力编码隐含 work_content 与子表声明不一致（决策 17 宽松模式） | 不阻塞                            |
| `body_markdown_fallback`              | B5     | LLM 渲染失败走 deterministic template（与 B4/B6 无关，仅声明 reserved）      | 不阻塞                            |

**强约束**：

- writer **不得**自创 flag key；新增需通过本文档评审追加
- `quality_flags` 累积**只增不删**；一行可同时持有多个 flag
- dataset / analysis 级 `quality_summary` 由 writer 聚合：`{<flag>: <count>, ...}`

---

## 五、写入服务接口签名冻结

### 5.1 公共入口（B4 / B6 共用）

```python
# nexus_app/domain_normalize/__init__.py
def dispatch_domain_normalize(
    session: Session,
    normalized_ref: NormalizedAssetRef,
    *,
    settings: Settings | None = None,
) -> DomainNormalizeResult: ...
```

行为：

- 读取 `normalized_ref.lineage` / 上挂的 `record_body`（通过 MinIO 取 payload）
- 按 `payload.domain_profile` switch：
  - `job_demand.v1` → `job_demand_writer.write(...)`
  - `ability_analysis.pgsd.v1` → `ability_analysis_writer.write(...)`
  - 其他 → 跳过，记 `quality_flags.domain_normalize_skipped = true`
- 返回 `DomainNormalizeResult(dataset_id?, analysis_id?, records_written, items_written, quality_summary)`
- 不抛业务异常；底层 IO / DB 异常向上抛出由 worker 转 `DOMAIN_NORMALIZE_FAILED`

### 5.2 B4 writer

```python
# nexus_app/domain_normalize/job_demand_writer.py
def write(
    session: Session,
    normalized_ref: NormalizedAssetRef,
    record_body: dict,
    *,
    settings: Settings | None = None,
) -> JobDemandWriteResult: ...

@dataclass(frozen=True)
class JobDemandWriteResult:
    dataset_id: str
    records_inserted: int
    duplicate_count: int
    invalid_count: int
    quality_summary: dict[str, int]
```

### 5.3 B6 writer

```python
# nexus_app/domain_normalize/ability_analysis_writer.py
def write(
    session: Session,
    normalized_ref: NormalizedAssetRef,
    record_body: dict,
    *,
    settings: Settings | None = None,
) -> AbilityAnalysisWriteResult: ...

@dataclass(frozen=True)
class AbilityAnalysisWriteResult:
    analysis_id: str
    profile_id: str
    tasks_written: int
    work_contents_written: int
    abilities_written: int
    abilities_rejected: int
    relations_written: int
    quality_summary: dict[str, int]
```

### 5.4 Fingerprint 公共算法

```python
# nexus_app/domain_normalize/fingerprint.py
def compute_job_demand_record_fingerprint(record: Mapping[str, Any]) -> str: ...
```

---

## 六、占位行清理规则（B4 专用）

writer 写入前对每条 `record_body.records[]` 应用以下规则，命中即丢弃 + `quality_flags.placeholder_row_dropped`：

| 规则                     | 命中条件                                                                                        |
| ------------------------ | ----------------------------------------------------------------------------------------------- |
| `placeholder_text`       | `job_title` 或 `job_description` 仅含 `……`/`...`/`—`/`-`/`无` 等占位符                          |
| `empty_row`              | 所有非 `trace` / `source_record_key` 字段均为 NULL / 空字符串                                   |
| `pure_index`             | `job_title` 仅含数字 + 标点（如 `"1"`, `"1."`, `"序号 1"`）                                     |
| `example_row`            | `job_title` 含 `示例`/`例：`/`example` 关键词（不区分大小写）                                   |
| `missing_required_field` | `job_title` 缺失但其他字段有值（命中后另写 `quality_flags.missing_required_field`，不重复算计） |

清理后剩余记录数 = `record_count - invalid_count`。

---

## 七、审计事件冻结

| event_type 常量                | 写入方 | 触发                                 | target_type / target_id                                              |
| ------------------------------ | ------ | ------------------------------------ | -------------------------------------------------------------------- |
| `DOMAIN_NORMALIZE_COMPLETED`   | 共用   | `dispatch_domain_normalize` 成功返回 | `normalized_asset_ref` / `<normalized_ref.id>`                       |
| `DOMAIN_NORMALIZE_FAILED`      | 共用   | writer 抛异常                        | `normalized_asset_ref` / `<normalized_ref.id>`                       |
| `JOB_DEMAND_DATASET_PERSISTED` | B4     | `job_demand_dataset` 落库            | `job_demand_dataset` / `<dataset_id>`                                |
| `JOB_DEMAND_RECORDS_PERSISTED` | B4     | `job_demand_record` 批量落库         | `job_demand_dataset` / `<dataset_id>`（payload 含 records_inserted） |
| `ABILITY_ANALYSIS_PERSISTED`   | B6     | `occupational_ability_analysis` 落库 | `occupational_ability_analysis` / `<analysis_id>`                    |
| `ABILITY_ITEMS_PERSISTED`      | B6     | `occupational_ability_item` 批量落库 | `occupational_ability_analysis` / `<analysis_id>`                    |
| `ABILITY_ITEMS_REJECTED`       | B6     | 阻塞性 quality_flag 拒绝条目入库     | `occupational_ability_analysis` / `<analysis_id>`                    |

所有事件落 `nexus_app/enums.py:AuditEventType`，alembic enum 同步与 B1 / B2 同模式（B4 / B6 各自迁移文件追加值）。

---

## 八、API 路径冻结（增量）

> 全局归属与资源根路径已在 `pipeline_b_contract_freeze.md §十` 与 `pipeline_b_api_contract_draft.md §1.1-1.7 / §2.1-2.7` 冻结。本节仅冻结 B4 / B6 **资源细分路径**和**操作语义**，避免并行实施时命名漂移。

### 8.1 业务侧 `/v1`（B4）

| Method | Path                                                                 | 操作                                                           |
| ------ | -------------------------------------------------------------------- | -------------------------------------------------------------- |
| GET    | `/v1/record-assets/job-demand-datasets`                              | 列表（按 normalized_ref / major / industry 过滤；分页）        |
| GET    | `/v1/record-assets/job-demand-datasets/{dataset_id}`                 | 详情 + quality_summary                                         |
| GET    | `/v1/record-assets/job-demand-datasets/{dataset_id}/records`         | 列表（按 city / industry / enterprise_size / employment_type） |
| GET    | `/v1/record-assets/job-demand-records/{record_id}`                   | 详情                                                           |
| GET    | `/v1/record-assets/job-demand-records/{record_id}/requirement-items` | 抽取项列表（由 B5 填充；P0 返回空数组）                        |

### 8.2 业务侧 `/v1`（B6）

| Method | Path                                                             | 操作                                                         |
| ------ | ---------------------------------------------------------------- | ------------------------------------------------------------ |
| GET    | `/v1/record-assets/ability-analyses`                             | 列表（按 normalized_ref / profile / major 过滤；分页）       |
| GET    | `/v1/record-assets/ability-analyses/{analysis_id}`               | 详情 + profile 内嵌                                          |
| GET    | `/v1/record-assets/ability-analyses/{analysis_id}/tasks`         | 任务树（含 work_contents 嵌套）                              |
| GET    | `/v1/record-assets/ability-analyses/{analysis_id}/ability-items` | 能力条目（按 category / task_code / work_content_code 过滤） |
| GET    | `/v1/record-assets/ability-analyses/{analysis_id}/relations`     | 关系列表（按 source_type / relation_type 过滤）              |

### 8.3 控制台侧 `nexus-console`

| Method | Path                                                           | 操作                                        |
| ------ | -------------------------------------------------------------- | ------------------------------------------- |
| GET    | `/internal/v1/record-assets/job-demand/quality-summary`        | 质量摘要 + flag 分布（管理视图）            |
| GET    | `/internal/v1/record-assets/ability-analyses/{id}/diagnostics` | 跨 sheet 一致性告警 + ability_code 校验明细 |
| GET    | `/internal/v1/ability-analysis-profiles`                       | 列表（只读，决策 2 - P0 不开放编辑）        |

### 8.4 共用约束

- 所有 list endpoint 强制分页（`page` / `page_size`，默认 20 / 上限 200）
- 错误码沿用 `docs/pipeline_b_api_contract_draft.md §3.1` 命名空间
- 写操作（删除资产 / 重跑 normalize）均在 `nexus-console`；`/v1` 严格只读
- 权限：`/v1` 沿用现有凭证认证 + org_scope 预留钩子（与 search 一致，见 `feedback_p0_search_permission_scope`）

---

## 九、Forbidden changes（B4 / B6 并行期）

继承 `pipeline_b_contract_freeze.md §十一` 并追加：

- 禁止 B4 修改 B6 表 / writer / API；反之亦然
- 禁止合并 B4 / B6 的 alembic revision 到同一文件
- 禁止 writer 写 `quality_flags` 以外的 key（新增需走本文档评审）
- 禁止在 writer 内调用 LLM（B5 任务）
- 禁止在 writer 内写 `knowledge_chunk` / 触发 RAGFlow（Pipeline B 不入 chunk）
- 禁止改 `normalized_record.payload.schema_version` 或 `domain_profile` 字段（B3 已冻结）
- 禁止 B4 写 `job_demand_requirement_item`（B5 责任）
- 禁止 B6 写 `task_description_structured` 非 `{}` 值（B5 责任）
- 禁止 `enterprise_size` 任何形式归一 / 枚举校验
- 禁止 writer 把 record_body 完整 JSONB 同步进领域表外的任何表（不复制真源）

---

## 十、Review Gate 触发

| Gate                          | 关注点                                                                            |
| ----------------------------- | --------------------------------------------------------------------------------- |
| **Data Model Gate**           | §一 隔离边界、§二 字段映射、§三 唯一约束 / cascade、§六 占位规则                  |
| **API Contract Gate**         | §八 路径、§五 writer 接口签名（dispatcher / writer / fingerprint）                |
| **Rule Engine Gate**          | §四 quality_flags 词表是否完整覆盖治理决策 7 / 8 / 14 / 17                        |
| **Version State Gate**        | §三 dataset-level upsert + cascade 不破坏 AssetVersionStatus 转移（job 重跑场景） |
| **Permission And Audit Gate** | §七 审计事件覆盖所有写入路径；§八 `/v1` 只读 + console 写操作分离                 |

---

## 十一、签字栏（待人工填写）

```
后端 owner（B4 实施）（_______________）：审阅 §一 / §二.1 / §三 / §五.2 / §六 / §七 / §八.1 → 签字 / 待修改
后端 owner（B6 实施）（_______________）：审阅 §一 / §二.2 / §三 / §五.3 / §七 / §八.2 → 签字 / 待修改
AI 工程 owner（___________）：审阅 §二.1 / §二.2 中的 LLM 接缝（rules_version_id / task_description_structured 预留） → 签字 / 待修改
业务专家（_______________）：审阅 §二 字段映射 / §四 quality_flags 词表 / §六 占位规则 → 签字 / 待修改
```

未签字前禁止启动 B4 / B6 实施。

---

## 十二、回写责任

| 评审通过后需回写             | 文档                                | 章节                                                      |
| ---------------------------- | ----------------------------------- | --------------------------------------------------------- |
| §五.1-§五.3 schema 状态升级  | `pipeline_b_contract_freeze.md`     | §五标题去掉"草案 · 不写 migration"                        |
| §五.5-§五.11 schema 状态升级 | `pipeline_b_contract_freeze.md`     | 同上                                                      |
| 并行契约入口                 | `pipeline_b_implementation_plan.md` | §五 标注"B4 / B6 并行契约 frozen，依据 b4_b6 freeze 文档" |
| API 路径细分                 | `pipeline_b_api_contract_draft.md`  | §1.1-1.7 增量补 §八.1 / §八.2 细分路径                    |
| 全局红线                     | `ARCHITECT.md`                      | 必要时补 domain_normalize 接缝说明                        |
