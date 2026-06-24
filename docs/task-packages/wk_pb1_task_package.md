# Pipeline B Wave 1 任务包 — 路由与 structured_parse

- **依据**：
  - 实施计划 §三 B1 / 决策记录（`docs/pipeline_b_implementation_plan.md`）
  - 设计 §3.4 / §3.5 / §八（`docs/pipeline_b_job_occupation_structured_data_design.md`）
  - 合同冻结 §3 / §4 / §5.0（`docs/pipeline_b_contract_freeze.md`）
- **状态**：B0 评审已通过；**B1.1 / B1.2 / B1.3 / B1.4 / B1.5 全部完成，待人工总评**（所有子切片代码与测试已提交）
- **本期目标**：让 xlsx / csv 在 `ingest_validate` 后正确路由进 Pipeline B，实现 `structured_parse` 阶段并产出可被 `profile_detect` 消费的中间表示；通过 feature flag 控制灰度，未启用前路由仍走 Pipeline A 保持现状
- **不在范围**：profile_detect、领域 normalize、领域表写入、知识单元加工、爬虫 payload 解析
- **依赖**：B0 合同冻结评审通过

---

## 1. 拆解（5 个 task package）

| 子切片 | 名称                                        | 估算      | 主交付                                                                                              | 状态      | 触发 Review Gate                                                      |
| ------ | ------------------------------------------- | --------- | --------------------------------------------------------------------------------------------------- | --------- | --------------------------------------------------------------------- |
| B1.1   | 路由 + ingest_validate 配置                 | 0.5 day   | `_pipeline_type_for()` 扩展（feature flag 保护）+ `config/ingest_validate.json` 补 csv + 单测       | ✅ 已交付 | Data Model Gate（路由表行为）·Version State Gate（feature flag 灰度） |
| B1.2   | `structured_parse` 模块脚手架 + xlsx parser | 1-1.5 day | `nexus_app/structured_parse/` 新模块 + 中间表示 schemas + xlsx parser + 单测（覆盖样本 1 / 样本 2） | ✅ 已交付 | Data Model Gate（中间表示契约）                                       |
| B1.3   | Worker 集成 structured_parse 阶段           | 0.5-1 day | `_run_record_pipeline` 增加 `structured_parse` 步骤 + stage 状态机 + 失败兜底 + 审计事件            | ✅ 已交付 | Version State Gate（失败状态转移）·Permission And Audit Gate（审计）  |
| B1.4   | csv / json parser                           | 0.5 day   | csv_parser + json_parser + worker 集成 csv + 单测                                                   | ✅ 已交付 | Data Model Gate（中间表示扩展）                                       |
| B1.5   | 样本端到端集成测试                          | 0.5 day   | 样本 1 / 样本 2 端到端跑通；损坏样本 fallback；feature flag 开启                                    | ✅ 已交付 | 上游 Gate 回归确认                                                    |

合计：约 3-4 day。

### 累计测试统计

- B1.1: 41 unit tests (`test_pipeline_routing.py`)
- B1.2: 48 unit tests (`tests/structured_parse/test_schemas.py` + `test_xlsx_parser.py`)
- B1.3: 14 unit + integration tests (`test_structured_parse_worker.py`)
- B1.4: 70 unit tests (`test_csv_parser.py` + `test_json_parser.py`) + 3 worker tests
- B1.5: 13 end-to-end tests (`tests/integration/test_pipeline_b_b1_e2e.py`)
- **共 189 new tests**, 全绿。完整回归 529 passed + 1 skipped, 无任何 regression。

---

## 2. 子切片详情

### 2.1 B1.1 路由 + ingest_validate 配置（本轮实施）

**Source context**：

- 实施计划 B1 / 决策 4（structured_parse 格式实现优先级）
- 合同冻结 §三（pipeline_type 路由表）/ §四（normalize_schemas.json 扩展契约）
- 现状代码：
  - `nexus_app/ingest/gateway.py:72-82` `_pipeline_type_for()` — 现规则：CRAWLER/DATABASE/WEBHOOK + JSON mime → RECORD；其他 → DOCUMENT（xlsx 当前也走 DOCUMENT）
  - `nexus_app/ingest/gateway.py:118-122` `_submit_ingest(... settings: Settings ...)` — feature flag 可通过 settings 注入
  - `config/ingest_validate.json` — 已含 xlsx/xls mime + 扩展，**缺 `text/csv` + `.csv`**
  - `nexus_app/config.py:71` `worker_pool_enabled: bool = True` — pydantic Settings flag 范例
  - `nexus_app/worker/runner.py:454` `pipeline_type = PipelineType(job.payload.get("pipeline_type", ...))` — worker 已识别 payload.pipeline_type

**Goal**：在不破坏现状的前提下，让路由表具备区分 xlsx/csv 进入 Pipeline B 的能力，通过 feature flag 控制灰度。未开启 flag 时所有路由行为不变；开启 flag 后 xlsx/csv 路由到 RECORD。

**Scope**：

- `nexus_app/config.py` `Settings` 新增 2 个 feature flag：
  - `pipeline_b_xlsx_enabled: bool = Field(default=False, alias="PIPELINE_B_XLSX_ENABLED")`
  - `pipeline_b_csv_enabled: bool = Field(default=False, alias="PIPELINE_B_CSV_ENABLED")`
- `nexus_app/ingest/gateway.py`：
  - `_pipeline_type_for(source_type, mime_type, *, settings=None)` 签名扩展，可选 `settings`；缺省退化为 `get_settings()`
  - 增加 xlsx mime 列表常量 + csv mime 列表常量（模块级 `XLSX_MIME_TYPES` / `CSV_MIME_TYPES`，便于测试与维护）
  - 增加 xlsx/csv 路由分支，受 feature flag 保护
  - `_submit_ingest()` 调用处显式传 `settings`（已可获得）
- `config/ingest_validate.json`：mime_whitelist 补 `text/csv`；extension_whitelist 补 `.csv`
- 新增 `nexus_app/tests/test_pipeline_routing.py`：覆盖
  - 现有路由不变（DOCUMENT / RECORD JSON）
  - flag 关闭：xlsx → DOCUMENT、csv → DOCUMENT
  - flag 开启 xlsx：xlsx → RECORD；其他不变
  - flag 开启 csv：csv → RECORD；其他不变
  - 双 flag 开启：xlsx + csv → RECORD
  - 边界 case：未知 mime / 空 mime / nas + xlsx + flag

**Out of scope**：

- xlsx parser 实现（B1.2）
- worker 阶段集成（B1.3）
- csv/json parser（B1.4）
- normalize_schemas.json 新增 record 契约（B1.2 引入中间表示后再加）

**Forbidden changes**：

- 禁止删除 / 改名 `_pipeline_type_for()`（仅扩展签名）
- 禁止改动现有 CRAWLER/DATABASE/WEBHOOK/JSON 路由分支
- 禁止移除 `ingest_validate.json` 任何既有 mime / extension
- 禁止把 feature flag 默认值设为 `True`（B1.5 才开）
- 禁止在 worker 侧改动现有 `_run_record_pipeline` 与 `_run_document_pipeline`
- 禁止把 settings 模块全局变量化（必须通过依赖注入）

**Deliverables**：

- `nexus_app/config.py` 新增 2 个 feature flag 字段（diff < 10 行）
- `nexus_app/ingest/gateway.py` 路由函数扩展（diff < 50 行）
- `config/ingest_validate.json` 新增 1 mime + 1 extension（diff 2 行）
- `nexus_app/tests/test_pipeline_routing.py` 新文件（约 100-150 行单测）

**Acceptance**：

- `uv run pytest nexus-app/nexus_app/tests/test_pipeline_routing.py -v` 全绿
- `uv run pytest nexus-app/nexus_app/tests/test_ingest_validate_stage.py -v` 无 regression
- `uv run pytest nexus-app/nexus_app/tests/test_contract_enums.py -v` 无 regression
- flag 默认关闭时，xlsx 提交仍走 DOCUMENT（与 main 行为完全一致）
- flag 开启时，xlsx 提交进 RECORD pipeline；但此时 worker 会因 `_run_record_pipeline` 尚未支持 xlsx 而 fail（这是预期，B1.3 才会接 structured_parse 让它真正可用）—— B1.1 不要求 worker 路径打通

**触发 Review Gate**：

- Data Model Gate（路由表是 Job.payload.pipeline_type 写入行为变更）
- Version State Gate（feature flag 灰度策略；本期无新状态机分支）

---

### 2.2 B1.2 structured_parse 模块脚手架 + xlsx parser（下轮）

**简述**：新增 `nexus_app/structured_parse/` 模块，提供中间表示数据模型（`ParsedWorkbook` / `ParsedSheet` / `ParsedRow` / `ParsedCell`，含 `trace = {sheet, row, column, merged_range?}`），实现 xlsx parser（基于 openpyxl 复用），满足合同冻结 §3.4 全部硬要求：

- 合并单元格 forward-fill（列方向 + 横向首列值）
- 多行单元格保留 `\n`
- Excel datetime 归一为 ISO8601（含时区，从 DataSource 配置取，默认 `Asia/Shanghai`）
- sheet 顺序与命名保留
- 序号列丢弃（列名匹配走 structured_parse 模块自有配置，避免触动 governance_rules.json）
- 占位行**不**在本阶段过滤（设计 §3.4 明确）

详细任务包待 B1.1 完成后另行展开。

### 2.3 B1.3 Worker 集成 structured_parse 阶段（下轮）

**简述**：`_run_record_pipeline()` 增加 `structured_parse` 步骤（pipeline_type=RECORD 且 mime 非 JSON 时）；写 stage 状态机 `current_stage = "structured_parse"`；失败时 stage failed → job failed；写 `PIPELINE_FAILED` 审计。详细任务包待 B1.2 完成后另行展开。

### 2.4 B1.4 csv / json parser（下轮）

**简述**：复用 B1.2 中间表示，为 csv（按 RFC 4180）与 json（数组 / 对象数组）实现 parser；爬虫 payload 留位。详细任务包待 B1.2 完成后另行展开。

### 2.5 B1.5 样本端到端集成测试（下轮）

**简述**：样本 1 / 样本 2 经 B1.1-B1.4 完整链路跑通；损坏样本 / 空 sheet fallback；feature flag 开启演示；产物：`nexus-app/tests/integration/test_pipeline_b_b1_e2e.py`。

---

## 3. 全切片通用约束（B1.1-B1.5）

### 3.1 命名与位置

- 新增模块：`nexus_app/structured_parse/`（B1.2+ 引入）
  - `__init__.py`：模块入口，导出公共 API
  - `schemas.py`：Pydantic 中间表示
  - `xlsx_parser.py`：xlsx 解析器
  - `csv_parser.py`：csv 解析器（B1.4）
  - `json_parser.py`：json 解析器（B1.4）
  - `config.py`：模块自有配置（序号列别名、占位行 pattern 等）
- 路由相关代码保留在 `nexus_app/ingest/gateway.py`

### 3.2 Feature flag 策略

- B1.1 引入 `PIPELINE_B_XLSX_ENABLED` / `PIPELINE_B_CSV_ENABLED`，默认 `False`
- B1.2-B1.4 持续在 flag 关闭状态下开发并测试（开 flag 后才会真正命中新代码路径）
- B1.5 完成时开 flag 跑端到端验收
- 生产灰度由运维通过环境变量 / `.env` 控制

### 3.3 Forbidden changes（B1 整体）

继承 B0 / `CLAUDE.md` / `pipeline_b_implementation_plan.md` §三 B1：

- 禁止在 Pipeline B 路径调 MinerU
- 禁止重排 / 重命名 sheet
- 禁止扁平化多行单元格
- 禁止丢失合并单元格语义
- 禁止把 `trace` 用于前端定位
- 禁止把 record_type 识别提前到 `ingest_validate` 阶段
- 禁止修改 `governance_rules.json`（决策 8）
- 禁止动业务 / 控制台 API（B4/B5/B6/B8 才动 API）
- 禁止动 `ai_analysis_rules` / `ai_prompt_profile`（B5 才动）

### 3.4 代码实现约束（继承 wk_5 风格）

- 单一职责：每个模块 / 类 / 函数只负责一个明确职责
- 类型注解：公共函数必须有完整类型注解
- 命名：类 PascalCase / 函数 snake_case / 常量 UPPER_SNAKE_CASE / 私有 `_leading_underscore`
- 注释：解释 **WHY** 而非 WHAT；遵循 `code-comments.md`
- 测试：每个公共行为有对应 pytest 用例；新增模块测试覆盖率 ≥ 80%

---

## 4. 验收与签字

### 4.1 B1.1 验收清单

- [ ] feature flag 字段加入 `Settings`，环境变量名为 `PIPELINE_B_XLSX_ENABLED` / `PIPELINE_B_CSV_ENABLED`
- [ ] `_pipeline_type_for()` 签名扩展（`settings` 参数可选）
- [ ] `XLSX_MIME_TYPES` / `CSV_MIME_TYPES` 模块级常量
- [ ] `config/ingest_validate.json` 补 csv
- [ ] `test_pipeline_routing.py` 新增，覆盖 5+ case
- [ ] 既有测试全绿（`test_ingest_validate_stage.py`、`test_contract_enums.py`）
- [ ] `_submit_ingest()` 调用处传入 `settings`

### 4.2 签字栏（B1.1 完成后填写）

```
后端 owner（_______________）：审阅 §2.1 实现 → 签字 / 待修改
Test owner（_______________）：审阅单测覆盖 → 签字 / 待修改
```

### 4.3 B1 整体完成条件

- B1.1-B1.5 全部 acceptance 通过
- feature flag 开启后样本 1 / 样本 2 跑通至 `profile_detect` 入口（B2 才有 profile_detect 实现，B1 终点是产出中间表示）
- 触发的全部 Review Gate 拿到签字
- `pipeline_b_implementation_plan.md` 状态从"未排期"变更为"B1 已完成"

---

## 5. 与既有契约 / 文档的回写

| 通过 Review 后回写                  | 目标文档                                              | 章节                        |
| ----------------------------------- | ----------------------------------------------------- | --------------------------- |
| feature flag 命名最终态             | `pipeline_b_implementation_plan.md`                   | §三 B1 Scope / §七 回滚策略 |
| 中间表示 schema 收敛差异（B1.2 后） | `pipeline_b_contract_freeze.md`                       | §五.0 / §3.4                |
| 路由表实际行为                      | `pipeline_b_job_occupation_structured_data_design.md` | §3.4                        |
| Worker stage 状态机扩展（B1.3 后）  | `ARCHITECT.md`                                        | Pipeline B 段               |
