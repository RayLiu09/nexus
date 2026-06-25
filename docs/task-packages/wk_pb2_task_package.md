# Pipeline B Wave 2 任务包 — profile_detect

- **依据**：
  - 实施计划 §三 B2（`docs/pipeline_b_implementation_plan.md`）
  - 设计 §3.1-§3.3 识别阶段/输入/输出、§3.5 与 governance classification 的边界
    （`docs/pipeline_b_job_occupation_structured_data_design.md`）
  - 合同冻结 §一 record_type / §二 profile_detect 输出契约 / §七 审计事件扩展
    （`docs/pipeline_b_contract_freeze.md`）
- **状态**：B1 总评已通过；**B2.1 / B2.2 / B2.3 / B2.4 全部完成，待人工总评**（所有子切片代码与测试已提交）
- **本期目标**：基于 B1 产出的 `ParsedWorkbook`（已在 `normalized_record.payload.record_body` 中），识别 `record_type` + `domain_profile` + `confidence` + `evidence`，写入 `normalized_record.profile` 与 `normalized_asset_ref.metadata_summary.profile`；低置信度触发 `review_required`。
- **不在范围**：domain_normalize、领域表写入、知识单元加工、跨 sheet 一致性校验（B7）
- **依赖**：B1 全部子切片 ✅

---

## 1. 拆解（4 个 task package）

| 子切片 | 名称                             | 估算      | 主交付                                                                                                                                                                                                                                  | 状态      | 触发 Review Gate                                                                 |
| ------ | -------------------------------- | --------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------- | -------------------------------------------------------------------------------- |
| B2.1   | profile_detect 模块脚手架 + 配置 | 0.5 day   | `nexus_app/profile_detect/` 新模块 + `ProfileDetectResult` schema + detector 配置（header alias / sheet name pattern / code prefix）+ 默认配置单测                                                                                      | ✅ 已交付 | Data Model Gate（输出契约 schema）                                               |
| B2.2   | 三类 detector 实现 + 单测        | 1-1.5 day | job_demand detector + PGSD ability_analysis detector + generic_table fallback；置信度计算；低置信度走 candidate 类型；覆盖样本 1 / 样本 2 单测                                                                                          | ✅ 已交付 | Rule Engine Gate（detector 规则配置，不可执行任意代码）                          |
| B2.3   | Worker 集成 + 审计事件           | 0.5 day   | execute_job 在 structured_parse 之后调用 profile_detect；写入 `normalized_record.profile`；新增 `RECORD_PROFILE_DETECTED` / `RECORD_PROFILE_REVIEW_REQUIRED` 审计事件 + alembic enum 同步；低置信度时 AssetVersion 转 `review_required` | ✅ 已交付 | Version State Gate（review_required 触发条件）·Permission And Audit Gate（审计） |
| B2.4   | 样本端到端 + flag-on demo        | 0.5 day   | 样本 1 识别为 `job_demand_dataset` + `job_demand.v1` ≥ 0.9 confidence；样本 2 识别为 `occupational_ability_analysis` + `ability_analysis.pgsd.v1` + analysis_model=PGSD；构造缺 header / 缺大类的退化样本走 candidate 类型              | ✅ 已交付 | 上游 Gate 回归确认                                                               |

合计：约 2.5-3 day。

### 累计测试统计

- B2.1: 60 unit tests (`tests/profile_detect/test_schemas.py` + `test_config.py`)
- B2.2: 28 unit + integration tests (`tests/profile_detect/test_detector.py`)
- B2.3: 12 worker unit + integration tests (`tests/test_profile_detect_worker.py`)
- B2.4: 20 end-to-end tests (`tests/integration/test_pipeline_b_b2_e2e.py`)
- **共 120 new tests**, 全绿。完整回归 649 passed + 1 skipped, 无任何 regression。

---

## 2. 子切片详情

### 2.1 B2.1 profile_detect 模块脚手架 + 配置（本轮实施）

**Source context**：

- 合同冻结 §二（profile_detect 输出契约）
- 设计 §3.2（识别输入：sheet/header/编码 prefix/category signatures）+ §3.5（与 governance classification 边界）
- 现状代码：B1.4 产出 `nexus_app.structured_parse.ParsedWorkbook`；profile_detect 消费的就是这份中间表示

**Goal**：搭建 profile_detect 模块的最小骨架——schema、配置、异常类——为 B2.2 detector 实现做准备。**本切片不实现 detector 业务逻辑**。

**Scope**：

- 新增 `nexus_app/profile_detect/__init__.py`：公共 API 暴露
- 新增 `nexus_app/profile_detect/schemas.py`：
  - `ProfileDetectResult`（Pydantic v2）：`record_type` / `domain` / `domain_profile` / `analysis_model` / `detector_version` / `confidence` / `evidence`
  - `ProfileEvidence`：`matched_headers` / `sheet_names` / `sample_row_count` / `matched_categories` / `matched_code_prefixes`
- 新增 `nexus_app/profile_detect/config.py`：detector 规则配置常量
  - `JOB_DEMAND_HEADER_ALIASES`：岗位需求 header 别名集合（如 `岗位名称` / `job_title` / `position` 等）
  - `JOB_DEMAND_OPTIONAL_HEADERS`：补充字段集
  - `PGSD_REQUIRED_CATEGORIES`：PGSD 必备大类（"职业能力" / "通用能力" / "社会能力" / "发展能力"）
  - `PGSD_CATEGORY_ALIASES`：大类别名集合（如 "职业技能" 映射 "职业能力"）
  - `PGSD_CODE_PREFIX_PATTERN`：能力编码正则 `^[PGSD]-\d+(\.\d+){1,2}$`
  - `PGSD_SHEET_NAME_PATTERN`：sheet 命名正则 `^\d+\.[\u4e00-\u9fa5]+$`（如 `1.数据采集`）
  - `OVERVIEW_SHEET_KEYWORDS`：概览 sheet 关键字（如 "典型工作任务"）
  - `DETECTOR_VERSION`：版本字符串（如 `"record-profile-detector.v1"`）
  - `DEFAULT_AUTO_ADMIT_THRESHOLD`：默认 0.85
- 新增 `nexus_app/profile_detect/exceptions.py`：
  - `ProfileDetectError`（基类）—— 内部错误用，正常路径不应抛
  - 注意：profile_detect 设计上**永远成功**（最差走 `generic_table_dataset` fallback），不抛异常给上层
- 单测：
  - `tests/profile_detect/test_schemas.py`：ProfileDetectResult 字段默认值、可序列化
  - `tests/profile_detect/test_config.py`：常量集合非空、PGSD code 正则匹配样本 (`P-1.1.1` / `G-1.1` / `S-1.1` / `D-1.1`)、sheet name 正则匹配样本 (`1.数据采集` / `4.可视化图表制作`)

**Out of scope**：

- detector 实现（B2.2）
- Worker 集成（B2.3）
- 端到端测试（B2.4）

**Forbidden changes**：

- 禁止在本切片实现任何 detector 业务逻辑
- 禁止把 governance_rules.json 引入为配置源（决策 8：profile_detect 配置走模块自有 config.py）
- 禁止 detector 配置允许"任意可执行代码"（Rule Engine Gate 红线：只能是常量 / 正则 / 字符串集合）
- 禁止把样本特征值硬编码为 detector 唯一识别 token（设计 §1.1 灵活性声明）

**Deliverables**：

- `nexus_app/profile_detect/` 4 文件（~150-200 行）
- `tests/profile_detect/` 2 文件（~80-120 行单测）

**Acceptance**：

- `python -m pytest tests/profile_detect/ -v` 全绿
- `nexus_app/profile_detect/__init__.py` 暴露 `ProfileDetectResult` / `ProfileEvidence` / `ProfileDetectError` / `DETECTOR_VERSION`
- 既有套件无 regression

**触发 Review Gate**：

- Data Model Gate（ProfileDetectResult 是下游 normalized_record.profile 与 metadata_summary.profile 的契约）

---

### 2.2 B2.2 三类 detector 实现 + 单测（下轮）

**简述**：实现 3 个 detector：

- `detect_job_demand(workbook)` — 检测 header signature 命中率
- `detect_ability_analysis_pgsd(workbook)` — 检测大类齐全 + code prefix + sheet 命名
- `detect_generic_table(workbook)` — fallback，总是返回低置信度结果

主分发器 `detect(workbook) -> ProfileDetectResult`：

- 依次尝试 job_demand / ability_analysis；取置信度最高者
- 置信度 < 阈值 → 降级为 `_candidate` 类型
- 都未命中 → 走 `generic_table_dataset`

详细任务包待 B2.1 完成后另行展开。

### 2.3 B2.3 Worker 集成 + 审计事件（下轮）

**简述**：在 `_run_structured_parse_*` 返回 dict 后调用 profile_detect，把 ProfileDetectResult 注入 `normalized_record.payload.profile` 与 `normalized_asset_ref.metadata_summary.profile`；写 `RECORD_PROFILE_DETECTED` 审计；低置信度时 AssetVersion 转 `review_required` + 写 `RECORD_PROFILE_REVIEW_REQUIRED` 审计；alembic enum 同步。详细任务包待 B2.2 完成后另行展开。

### 2.4 B2.4 样本端到端 + flag-on demo（下轮）

**简述**：扩展 `tests/integration/test_pipeline_b_b1_e2e.py`（或新建 `b2_e2e.py`），断言样本 1 与样本 2 经 profile_detect 输出符合预期 record_type / domain_profile / confidence。构造缺 header / 缺大类的退化样本走 candidate 类型。详细任务包待 B2.3 完成后另行展开。

---

## 3. 全切片通用约束（B2.1-B2.4）

### 3.1 命名与位置

- 新增模块：`nexus_app/profile_detect/`
- 测试：`nexus-app/tests/profile_detect/`
- 配置常量放 `nexus_app/profile_detect/config.py`（不进 governance_rules.json）

### 3.2 Forbidden changes（B2 整体）

继承 B0 / B1 与 `CLAUDE.md`：

- 禁止调用 LLM / governance_rules_version / ai_analysis_rules / ai_prompt_profile（profile_detect 是**纯规则识别**，不调用 AI）
- 禁止把 detector 配置允许任意代码执行
- 禁止把 sheet 名 / header signature 硬编码到代码（必须走 config.py）
- 禁止偏离样本结构时直接失败（必须走 candidate 类型或 generic_table 兜底）
- 禁止动业务 / 控制台 API（B4/B5/B6/B8 才动 API）
- 禁止动领域表 schema（B4 / B6 才动）
- 禁止修改 `_load_record_payload` JSON 路径（profile_detect 当前**仅作用于** structured_parse 输出，JSON 直接走既有 record_body 路径）

### 3.3 代码实现约束（继承 wk_pb1 风格）

- 单一职责：每个 detector 一个函数
- 类型注解：公共函数必须有完整类型注解
- 命名：函数 snake_case / 常量 UPPER_SNAKE_CASE
- 注释：解释 WHY；遵循 `code-comments.md`
- 测试：每个 detector 一个 TestClass；新增模块测试覆盖率 ≥ 80%

---

## 4. 验收与签字

### 4.1 B2.1 验收清单

- [ ] `nexus_app/profile_detect/__init__.py` 公共 API 暴露
- [ ] `ProfileDetectResult` Pydantic schema 字段匹配合同冻结 §二
- [ ] `ProfileEvidence` 子结构包含 5 类证据字段
- [ ] `config.py` 包含 8 个核心常量集合（aliases / patterns / version / threshold）
- [ ] PGSD code 正则匹配样本 2 的全部 4 类编码
- [ ] PGSD sheet name 正则匹配样本 2 的 4 个子表
- [ ] 单测 ≥ 10 个，全绿
- [ ] 既有套件无 regression

### 4.2 签字栏（B2.1 完成后填写）

```
后端 owner（_______________）：审阅 §2.1 实现 → 签字 / 待修改
Test owner（_______________）：审阅单测覆盖 → 签字 / 待修改
```

### 4.3 B2 整体完成条件

- B2.1-B2.4 全部 acceptance 通过
- 样本 1 / 样本 2 经 profile_detect 输出正确 record_type / domain_profile，confidence ≥ 0.9
- 触发的全部 Review Gate 拿到签字
- `pipeline_b_implementation_plan.md` §十一 状态更新为 "B2 已完成"

---

## 5. 与既有契约 / 文档的回写

| 通过 Review 后回写             | 目标文档                                              | 章节      |
| ------------------------------ | ----------------------------------------------------- | --------- |
| detector 配置最终态            | `pipeline_b_contract_freeze.md`                       | §二 / §三 |
| 实际 confidence 阈值与降级策略 | `pipeline_b_job_occupation_structured_data_design.md` | §3.3      |
| 审计事件命名最终态             | `pipeline_b_contract_freeze.md`                       | §七       |
| B2 完成                        | `pipeline_b_implementation_plan.md`                   | §十一     |
