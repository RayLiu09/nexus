# 检索 57 项失败用例修复验收

日期：2026-10-26。对应任务包：`docs/task-packages/wk_retrieval_57_test_alignment_task_package.md`。

本次按当前生产契约修复测试与夹具。完整检索套件从 **625 通过、57 失败、12 跳过** 收敛为 **693 通过、0 失败、12 跳过**。参数化扩展及补充防御断言后，实际执行项比原先增加 11 项。

## 契约与修复

| 原失败根因 | 原失败数 | 当前测试行为 |
| --- | ---: | --- |
| 结构化标签旧契约 | 45 | 岗位、专业布点、职业能力使用字段过滤；旧标签请求在进入 SQL 前被拒绝。标签组合、分数、排序及审计迁到受支持文档引用。 |
| 历史 Excel 夹具缺失 | 6 | 岗位使用确定性领域数据；专业布点使用教育部 API 模拟响应，经实际 Provider 和直入库处理器生成领域记录。移除旧 Excel Pipeline 夹具及专用模型屏蔽代码。 |
| 隐藏内部工具被当成 LLM 工具 | 6 | 为内部调用保留明确参数契约，继续验证执行器参数读写；增加两个工具对所有 LLM 场景不可见的断言。 |

覆盖保留与增强：

- 文档标签 AND/OR 集合组合、必选空桶、可选空桶、绑定延迟、跨领域桶防御、无目标类型的底层 helper 行为。
- WEIGHTED/LINEAR/RRF 分数计算与真实文档执行器排序、开关关闭时保持语义顺序；结构化岗位明细与需求项保持 SQL 顺序且不注入标签分数。
- 文档标签审计包含目标类型、目标数量、桶命中数和空交集；写审计函数异常时检索仍可完成。结构化直查及拒绝旧标签的请求不产生标签审计。
- golden 增加精确数量、错误片段和聚合序列断言，避免只判断“执行成功”。能力结果 ID 提取支持 `ability_item.id` 的当前返回结构。
- DAG 上游使用岗位需求字段查询，下游将 `normalized_name` 绑定为文档 ability 标签，并断言具体教材命中、排除与空上游降级行为。
- cassette 路径显式注入带 FakeEmbeddingClient 的非结构化执行器，避免构造默认真实模型客户端。

## 专业布点 API 夹具

`seed_major_offering_api_sample` 使用 httpx MockTransport 返回教育部接口形状，分别同步两个专业，调用实际 `MoeMajorOfferingProvider.fetch_pull_page` 和 `MajorOfferingResultHandler.accept_page`。

- 每个专业输入两条同年、同校、同专业数据，年限/备注不同：首次插入 1 条、跳过 1 条。
- 同一页重放：插入 0 条、跳过 2 条；原年限与备注保持不变。
- 请求不携带 Authorization。
- 数据直接进入 `MajorOfferingRecord`；不生成 Asset、AssetVersion、NormalizedAssetRef、AIGovernanceRun 或 KnowledgeChunk。
- golden 验证明细共 2 条、专业名称过滤命中 1 条，以及 2026 年聚合值为 2。

本次验证使用本地测试数据库和模拟 HTTP/模型结果；未访问教育部真实接口、真实 LiteLLM 或开发业务数据库，未执行数据库升级。

## 验证结果

在 `nexus-app` 执行：

```bash
.venv/bin/pytest -o addopts='' -q --tb=short tests/retrieval --junitxml=/tmp/nexus-retrieval-alignment-final.xml
```

最终结果：`693 passed, 12 skipped in 14.41s`。12 项均为原有无可执行计划/cassette 的 pending golden；无新增 skip/xfail。`git diff --check` 通过。

机器可读证据：

- `docs/testing/artifacts/retrieval_failures_2026-10-26/alignment_mapping.json`：57 项原失败到替换用例的逐项对应关系，已校验替换用例均在最终 JUnit 中通过。
- `docs/testing/artifacts/retrieval_failures_2026-10-26/alignment_verification.json`：命令、前后数量、保留的跳过项及验证边界。
- 同目录 `failure_inventory.json` 保留修复前清单。

## 范围审查

单 Agent 已检查当前差异与 ARCHITECT/SPEC 的结构化标签退役、专业布点 API 直入库、内部工具可见性契约一致。本次只有测试、夹具和任务证据变更；无生产代码、API、权限策略或数据库变更。未恢复专业布点 Excel 管道、结构化标签投影或隐藏工具的 LLM 入口。其他任务的 Docker 和电商相关改动保留。
