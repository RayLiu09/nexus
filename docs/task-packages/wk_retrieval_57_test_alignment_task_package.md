# Task Package: 检索旧失败用例对齐当前代码

日期：2026-10-26。状态：已完成。用户授权：按照最新代码逻辑修复 57 项失败用例。

## 契约与范围

- 遵循 ARCHITECT/SPEC 的标签索引范围：结构化领域拒绝 tag_filters；文档 normalized ref 与 outline 支持标签。
- 对齐 7 月 22 日内部教材工具的 LLM 可见性，以及专业布点 API 直入库和只读检索契约。
- 修改检索测试、golden 数据/计划/cassette、测试辅助类和验收证据；不改变生产行为、不恢复旧 Pipeline/结构化标签、不访问业务数据库。
- 将通用标签组合/排序/审计用例迁到受支持文档，结构化用例保留字段过滤正向与标签拒绝负向覆盖。
- 历史 Excel golden 夹具替换为确定性当前领域数据/API 响应；DAG 保留有效依赖与数据传递验证。
- 不触碰其他任务的 Docker、电商文档/脚本改动。

## 验收

- 完整 `tests/retrieval` 通过；不新增 skip/xfail 隐藏失败。
- 原 57 项均有明确迁移、替换或负向守卫对应，文档标签检索、组合、分数、审计失败隔离及工具隐藏性仍有断言。
- 测试模型客户端显式替身，不依赖开发环境凭证或外部模型调用。
- `git diff --check` 通过；记录最终数量和相关验证。

## 完成证据

- 完整检索套件：`693 passed, 12 skipped in 14.41s`，0 失败、0 错误。原结果为 `625 passed, 57 failed, 12 skipped`。
- 57 项原失败均已映射到通过的当前用例，映射逐项对照最终 JUnit 结果验证；原有 12 项 pending golden 保持跳过，未新增 skip/xfail。
- 文档引用覆盖 AND/OR/WEIGHTED/LINEAR/RRF、可选桶降级、空集、审计与写审计异常隔离；结构化领域覆盖字段过滤、拒绝旧标签及无标签分数注入。
- 教育部专业布点夹具经过实际 Provider + 直入库处理器，HTTP 使用 MockTransport，验证免认证、重复跳过、不覆盖和无资产/AI 治理产物。
- cassette 使用显式 FakeEmbeddingClient；DAG 验证岗位需求 `normalized_name` → 文档 ability 标签的数据传递及下游结果。
- 单 Agent 差异审查完成；未修改生产行为、数据库配置或迁移，不涉及新增架构/API/权限规则，未触发新的高风险变更 Review Gate。
- 详细证据：`docs/review/retrieval_57_test_alignment_evidence_2026-10-26.md`。
