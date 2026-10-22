# Agent Open API A/B Review Evidence

日期：2026-10-22。实现任务包：`docs/task-packages/wk_agent_openapi_ab_implementation_task_package.md`。
范围：A/B 消费能力和公开 OpenAPI 生成的 function tools；C 类接口排除。单 Agent 顺序实施，没有数据库迁移、部署或线上写入。

本文件是可复核的实现证据，不代表人工 Review Gate 已批准；合并前由维护者按 WORKFLOWS.md 完成对应 Gate。

## API Contract Gate

- 逐项覆盖、参数口径、分页、错误、兼容、示例：`docs/api/public_agent_data_api.md`。
- 业务读取：open_business；资源发现/身份候选：open_discovery；确定性证据：open_evidence。
- `public_schemas.py` 为新接口声明输出 DTO；SearchRead 与资产目录元数据扩展进入实际 OpenAPI。
- 55 个稳定 operationId 导出的 function definitions 与 HTTP bindings：`docs/generated/public-function-tools/`。
- 工具只选公开 GET/POST，排除 deprecated 与流式操作，参数按 path/query/body 分组；没有模型可填的认证头。
- 原 HTTP 外部搜索 auto_ingest=true 默认保持不变；工具 schema 与绑定要求执行器在省略时注入 false。
- 旧 major-profiles/job-demand-records 仅标记 deprecated，保留原 HTTP 路径。

## Permission And Audit Gate

- 真实路由认证测试覆盖所有新读取类别及两个批量解析 POST；未认证返回 401。
- available/current-generated-ref、官方分类、active 标准库的多层准入；非正式、旧 ref 不返回正文/大纲/教材/标准课程。
- 结构化记录保留各自公开边界；不将 raw_jobs 当治理输入、不伪造 version/ref、不混入旧岗位投影。
- 批量每项验证；隐藏与未知 ID 均 not_found，内容不泄漏。
- 新接口审计 caller、资源/ID、数量、trace_id；摘要不带 key、原文或自由来源 URL。长读取结束前刷新并校验已持久化 caller 的撤销/过期。
- 专用测试模拟对象存储读取期间撤销调用者，断言返回 403 且没有成功读取审计。
- 权限未增加新的组织/字段过滤；当前 open:* 与 P0 org noop 在 API 文档/生成清单中明确。

## Semantic Retrieval Integration Gate

- 向量适配器原有 normalized_ref_ids/chunk_ids 交集参数复用；asset/ref/元数据范围在向量排序前求交。
- 多 KB 独立检索后按 nexus_chunk_id 去重、最高 score 合并并做全局 top_k；已选范围不相交时不调用嵌入或向量检索。
- 知识 FK 与任务大纲 metadata 关联分开处理，均限定同 ref；循环父链不会使子树读取无限递归。
- 章节读取不改 Markdown；返回块/页码与字符续读位置。节点上下文支持同一 chunk 内续读，不丢弃被截断尾部。
- 图谱只读已有生成/成功结果，按 exact ref/节点/关系/深度控制范围；事实、原文证据和推导来源可追溯。
- 语义专用人才需求调研/教学案例不产生图谱；缺少图谱或大纲不创建 build/job/node。

## 数据口径与状态合同复核

- 岗位聚合直接对过滤后的 raw_jobs 全样本分组；样本数、缺失数、计数单位、来源、去重键明确，不从一页数据推总量。
- 未新增薪资数值、城市、技能频次、全国总体等无来源字段。
- 教学标准库和课程的学时 suggested、标签 derived，证据绑定随条目返回。
- 专业简介读取文档身份元数据，遵循人工覆盖与显式清空，不恢复 retired profile 抽取。
- 没有改业务状态枚举、治理结果、反向指针、Prompt、rule、知识生产 Pipeline 或 Console UX。

## Verification

测试命令及最终结果见下方执行记录。测试使用隔离 SQLite、TestClient、内存存储和可控检索/外部搜索替身；没有请求线上 API、生产数据或真实 LLM。

覆盖文件：test_agent_public_business.py、test_agent_public_evidence.py、test_public_function_tools.py，以及既有资产目录、检索审计/大纲、培养方案、职业能力、布点、教材、标准课程、外部搜索与公开认证审计回归。

既有测试夹具的两处合同修正：外部搜索测试持久化 stub caller 以满足原有返回前撤销检查；内部标准列表断言补已有 raw_object_id 字段。生产外部搜索实现未改变。

额外验证：Python compileall、git diff --check、生成器 --check；生成器不进入 app lifespan，因此不依赖数据库/存储/LLM。

真实 PostgreSQL/MinIO/向量服务和生产数据联调、维护者人工 Gate 不由本单元/合同测试替代。

最终执行记录：

```text
nexus-api/.venv/bin/python -m pytest [下列 19 个测试文件] --tb=short
170 passed in 79.56s

最后的缺失正文逐项解析修正和标签客户端复用，定向复验：
python -m pytest tests/test_agent_public_evidence.py tests/test_open_asset_catalog_filters.py tests/test_public_function_tools.py --tb=short
20 passed in 13.92s

nexus-api/.venv/bin/python scripts/generate_public_function_tools.py --check
Function tools artifacts match public OpenAPI

python -m compileall -q nexus-api/nexus_api scripts/generate_public_function_tools.py
git diff --check
均通过
```

综合回归文件（在 nexus-api 目录执行）：

```bash
.venv/bin/python -m pytest \
  tests/test_agent_public_business.py \
  tests/test_agent_public_evidence.py \
  tests/test_public_function_tools.py \
  tests/test_talent_training_plan_api.py \
  tests/test_b6_ability_analysis_api.py \
  tests/test_b0_ability_analyses_include.py \
  tests/test_search_qa_audit.py \
  tests/test_search_qa_outline_fusion.py \
  tests/test_open_asset_catalog_filters.py \
  tests/api/test_open_audit.py \
  tests/api/test_open_caller_mid_request.py \
  tests/api/test_open_query_bounds.py \
  tests/test_open_record_graph_api.py \
  tests/test_external_search_api.py \
  tests/test_major_profile_api.py \
  tests/test_major_distribution_api.py \
  tests/test_course_textbooks_api.py \
  tests/test_raw_jobs_api.py \
  tests/test_teaching_standard_library_api.py --tb=short
```

最后定向复验新增一个缺失存储正文用例；因此现在重新执行上述综合命令应收集 171 项。

## 后续真实场景验收与提交范围

用户随后授权使用真实 Key 进行场景测试，并在收到结果后要求“提交并推送”。该授权覆盖当前 A/B 实现、生成工具及测试交付；不代表下述验收问题已修复或全部 Gate 已通过。

真实 HTTP 验收见 `docs/testing/agent_openapi_scenario_test_report_2026-10-22.md`：112次请求、28个工具、43项业务/边界断言，37项通过、6项未通过。六场景为4通过、1部分通过、1未通过；已知问题包括主题筛选关联、检索类型发现、岗位排序/快照、课程重复和search审计trace缺失。本次提交保留这些失败证据，业务实现未因本次测试而修改。

提交前复核：生成工具 `--check`、`git diff --check` 通过；离线证据复算仍为37通过、6失败，退出1符合报告中的已知问题。无关电商样例计划和采集脚本不进入本次提交。没有启动本地服务或部署。
