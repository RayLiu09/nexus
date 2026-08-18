# /job-demand-records/aggregate 接口方案

> 目标：为「岗位需求」维度统计（岗位需求 TOP、学历分布、经验分布、薪资分布）提供**服务端聚合**能力，
> 替代当前「拉全量 records 后客户端自行聚合」的做法，同时明确「能力雷达 / 技能词云」的归属边界。

## 1. 现状与缺口

| 能力 | 现有接口 | 缺口 |
|------|----------|------|
| 岗位需求明细列表 | `GET /open/v1/record-assets/job-demand-records`（`open_record_assets.py:572`） | 6 个 ILIKE 过滤，**无聚合** |
| 专业分布聚合（参考范式） | `GET /open/v1/record-assets/major-distribution-records/aggregate`（`open_record_assets.py:673`） | 仅覆盖 `major_distribution_record`，非岗位需求 |
| 行业分布 Top-K（内部） | `/internal/v1/record-assets/job-demand-records?fields=industry_distribution`（`internal/record_assets.py:589`） | 内部接口、仅行业一维、Top-10 硬编码 |
| 检索执行器聚合 | `AGGREGATION_PROFILES`（`retrieval/executors/job_demand.py:41`） | 内部结构化检索通道，非开放 API |

结论：开放 API 缺少一个**面向岗位需求记录、支持多维度分组 + 多度量**的聚合端点。本方案补齐该缺口。

## 2. 接口定义

```
GET /open/v1/record-assets/job-demand-records/aggregate
```

- 认证：沿用 router 级 `require_api_caller`（与 `/open/v1/record-assets/*` 一致）。
- 语义：Pipeline B 记录为领域事实，**不** join `asset_version`、**不**要求 `available` 版本（与
  `list_job_demand_records` 的 docstring 一致）。
- 响应：`schemas.ListResponse[dict]`，`items` 为聚合行，顶层 `aggregations` 承载派生分布（薪资直方图、技能词云）。

### 2.1 查询参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `group_by` | `list[str]` | 否 | 分组维度，见 §3 白名单。缺省 `["job_title"]` |
| `metric` | `str` | 否 | 度量，见 §3 白名单。缺省 `record_count` |
| `order` | `str` | 否 | `desc`（缺省）/ `asc`，作用于度量列 |
| `limit` | `int` | 否 | Top-K 截断（仅聚合行数，非分页）；缺省 20，上限 200 |
| `job_title` / `company_name` / `city` / `education` / `industry` / `experience` | `str` | 否 | ILIKE 过滤，复用 `_contains`（`open_record_assets.py:568`） |
| `employment_type` / `enterprise_size` | `str` | 否 | 等值过滤（对齐内部 dataset 内记录的过滤方式） |
| `page` / `page_size` | `int` | 否 | 分页，复用 `pagination_params`（`page_size ≤ 200`） |

> `limit` 与 `page/page_size` 语义区分：`limit` 是「聚合分组条数上限」（如 TOP-20），
> `page/page_size` 是「聚合结果集的分页」。P0 两者保留其一即可，建议**优先用 `limit`**，
> 分页参数保留以兼容 `ListResponse` 信封。

### 2.2 请求示例

```
GET /open/v1/record-assets/job-demand-records/aggregate
    ?group_by=education_requirement&metric=record_count

GET /open/v1/record-assets/job-demand-records/aggregate
    ?group_by=job_title&metric=job_count&order=desc&limit=10&industry=电子商务

GET /open/v1/record-assets/job-demand-records/aggregate
    ?group_by=city&metric=avg_salary_min&experience=1-3年
```

## 3. 分组维度 / 度量白名单

### 3.1 分组维度（`group_by`）

映射到 `JobDemandRecord`（`models.py:1457`）的分类/文本列，与 `RECORD_COLUMNS`（`job_demand.py:577`）对齐：

```python
_JOB_DEMAND_GROUP_COLUMNS = {
    "job_title": models.JobDemandRecord.job_title,
    "company_name": models.JobDemandRecord.company_name,
    "city": models.JobDemandRecord.city,
    "region": models.JobDemandRecord.region,
    "education_requirement": models.JobDemandRecord.education_requirement,
    "experience_requirement": models.JobDemandRecord.experience_requirement,
    "industry_name": models.JobDemandRecord.industry_name,
    "employment_type": models.JobDemandRecord.employment_type,
    "enterprise_size": models.JobDemandRecord.enterprise_size,
    "job_function_category": models.JobDemandRecord.job_function_category,
    "source_platform": models.JobDemandRecord.source_platform,
}
```

**排除**：`job_description` / `responsibility_text` / `requirement_text` / `job_skill_text` 等自由文本不做分组键（近乎唯一，无统计意义；其中 `job_skill_text` 走 §5 技能词云专用通道）。

### 3.2 度量（`metric`）

```python
_JOB_DEMAND_METRICS = {
    "record_count": func.count(models.JobDemandRecord.id),          # 岗位记录数
    "job_count":   func.sum(models.JobDemandRecord.job_count),      # 岗位需求量（招聘人数求和）
    "avg_salary_min": func.avg(models.JobDemandRecord.salary_min),  # 平均起薪（float）
    "avg_salary_max": func.avg(models.JobDemandRecord.salary_max),  # 平均顶薪（float）
}
```

- 每行**始终**附带 `record_count`（与 `aggregate_major_distribution_records` 返回 `distribution_total + record_count` 的双列范式一致），度量列按 `metric` 追加为 `value`。
- `avg_salary_*` 在 `salary_min/max` 为 `NULL` 时被 SQL `avg` 自然忽略；聚合行内同时返回 `salary_min_null_count` 供调用方判断数据完整度。

## 4. 六个维度的映射

| 维度 | 实现方式 | 是否本接口覆盖 |
|------|----------|----------------|
| 岗位需求 TOP | `group_by=job_title` + `metric=job_count`（或 `record_count`）+ `order=desc&limit=10` | ✅ 核心覆盖 |
| 学历分布 | `group_by=education_requirement` + `metric=record_count` | ✅ 核心覆盖 |
| 经验分布 | `group_by=experience_requirement` + `metric=record_count` | ✅ 核心覆盖 |
| 薪资分布 | `group_by=city`（或 `job_title`）+ `metric=avg_salary_min/max`；**另见 §5 直方图** | ✅ 核心覆盖 |
| 能力雷达 | 复用 `GET /open/v1/record-assets/graphs/job-capability`（`open_record_assets.py:778`），非记录聚合 | ❌ 不在本接口 |
| 技能词云 | 见 §5，走 `aggregations.skill_keywords` 派生字段 | ⚠️ 派生覆盖 |

## 5. 派生分布（`aggregations` 顶层字段）

沿用内部 `industry_distribution` 挂载方式（`internal/record_assets.py:572` 的 `aggregations` 字典 +
`list_response(..., aggregations=...)`），本接口在 `items` 之外返回两个派生对象：

### 5.1 `salary_histogram`（薪资直方图）

`salary_min/max` 为 float（`domain_normalize/job_demand_writer.py` 的 `_coerce_float`），无统一月/年单位。
P0 建议**不**在 SQL 里硬编码分桶（单位不统一会导致桶边界失真），而是：

- 方案 A（推荐）：返回 `aggregations.salary_summary = {min, max, avg_min, avg_max, p50_min}`，
  分桶交给客户端根据实际 min/max 动态切分。
- 方案 B（可选）：SQL `CASE WHEN` 按固定区间（如 `salary_min/1000` 取整）分桶，仅在数据单位已确认统一时启用。

`p50_min`（中位起薪）用 Postgres `percentile_cont(0.5) WITHIN GROUP (ORDER BY salary_min)` 实现，
需在 `sqlalchemy.func` 中封装；若追求跨库兼容，P0 可先只返回 `avg/min/max`。

### 5.2 `skill_keywords`（技能词云）

`job_skill_text` 为自由文本（逗号/顿号分隔），直接 `GROUP BY` 无意义。两条路径：

- 路径 A（推荐）：`job_demand_requirement_item` 表已含 `item_name` / `normalized_name` / `item_type`
  （`models.JobDemandRequirementItem`），对 `item_type` 为技能类、且 `normalized_name` 非空的项做
  `GROUP BY normalized_name` 计数——复用已有归一化结果，避免在接口层重复分词。
- 路径 B（兜底）：拉取命中过滤条件的 `job_skill_text`，在应用层按分隔符切分计数（Top-K）。

P0 优先路径 A，返回 `aggregations.skill_keywords = [{"keyword": ..., "count": ...}]`。

## 6. 校验与护栏（Guardrails）

对齐 `aggregate_major_distribution_records`（`open_record_assets.py:673`）与内部接口（`internal/record_assets.py:503`）：

1. **白名单校验**：`group_by` 未知值 → `422 {"error": "unknown_group_by", "unknown": [...]}`；
   `metric` 未知值 → `422 {"error": "unknown_metric", "known": [...]}`。
2. **空 / 重复校验**：`group_by` 为空 → `422 {"error": "group_by_required"}`；重复项 → `422 {"error": "duplicate_group_by"}`。
3. **无动态 SQL**：所有 `group_by`/`metric` 只能映射到白名单字典中的 SQLAlchemy 列对象，禁止拼接字符串。
4. **限流/上限**：`limit` 上限 200；`group_by` 维度数上限（如 ≤ 3）防止笛卡尔爆炸。
5. **审计**：复用 `_audit_open_record_read`（或等价 `write_audit`），记录 `route="job_demand_aggregate"` 与 `result_count`。

## 7. 响应示例

```json
{
  "data": {
    "items": [
      {"job_title": "跨境电商运营", "record_count": 128, "value": 412},
      {"job_title": "外贸业务员",    "record_count": 96,  "value": 260}
    ],
    "aggregations": {
      "salary_summary": {"min": 3.0, "max": 40.0, "avg_min": 7.8, "avg_max": 12.4},
      "skill_keywords": [{"keyword": "数据分析", "count": 210}, {"keyword": "英语", "count": 185}]
    },
    "total": 2,
    "page": 1,
    "page_size": 20
  }
}
```

（`value` 为 `metric` 对应的度量列；`record_count` 恒返回。）

## 8. 实现要点

1. **位置**：新增到 `nexus-api/nexus_api/api/open_record_assets.py`，紧邻 `list_job_demand_records`
   （`:572`）之后，复用 `_contains`、`_serialize_job_demand_record`、`list_response`、`pagination_params`。
2. **SQL 骨架**（对齐 `aggregate_major_distribution_records:698`）：

   ```python
   columns = [_JOB_DEMAND_GROUP_COLUMNS[name] for name in group_by]
   metric_expr = _JOB_DEMAND_METRICS[metric]
   grouped = (
       select(*columns, metric_expr.label("value"),
              func.count(models.JobDemandRecord.id).label("record_count"))
       .where(*filter_clauses)
       .group_by(*columns)
       .order_by(desc("value") if order == "desc" else asc("value"), *columns)
       .limit(limit)
   )
   ```

3. **过滤子句**：`_contains` 用于 `job_title/company_name/city/education/industry/experience`；
   `employment_type` / `enterprise_size` 用等值（与 `list_job_demand_records_for_dataset:643` 一致）。
4. **能力雷达不纳入本接口**：由既有 `graphs/job-capability` 承担，避免在同一端点混入图数据语义。
5. **Top-K 用分页实现**：§2.1 的独立 `limit` 参数在落地时改为复用 `pagination_params` 的
   `pageSize`（`?pageSize=10&order=desc` 即 Top-10），与兄弟端点 `aggregate_major_distribution_records`
   保持一致，避免同一端点两套截断语义。
6. **路由注册顺序（关键）**：`open.py` 已注册 `/record-assets/job-demand-records/{record_id}`，
   会抢先匹配 `/job-demand-records/aggregate`。落地时将 `main.py` 中
   `open_record_assets_router` 移到 `open_router` **之前**，保证字面量路径
   `/aggregate` 先于 `{record_id}` 命中。

## 9. 测试计划

新增 `nexus-api/tests/test_job_demand_records_aggregate.py`：

- `group_by=education_requirement` 返回分组计数，行数与去重教育水平一致。
- `metric=job_count` 返回 `sum(job_count)` 且 `record_count` 恒在。
- `metric=avg_salary_min` 正确忽略 `salary_min IS NULL` 行。
- `order=desc&limit=5` 仅返回 Top-5 且按 `value` 降序。
- 未知 `group_by` / `metric` → 422 且 `detail.error` 正确；空 / 重复 `group_by` → 422。
- `industry=电子商务` 过滤后聚合结果仅含命中记录。
- `aggregations.salary_summary` / `skill_keywords` 字段存在且类型正确。
- 审计事件 `job_demand_aggregate` 落库（`result_count` 正确）。

## 10. 与内部接口的关系

- 内部 `/internal/v1/record-assets/job-demand-records?fields=industry_distribution` 保持不动（console 消费）。
- 本开放端点作为其**超集**（行业 + 其他维度 + 多度量 + 派生分布），二者共享分组/度量的底层列映射，
  但开放端点是独立路由，避免内部 `major` 语义耦合到对外契约。
