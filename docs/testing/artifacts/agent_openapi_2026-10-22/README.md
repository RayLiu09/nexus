# Agent OpenAPI 实际验收证据索引

完整结论与全部请求索引见 [测试报告](../../agent_openapi_scenario_test_report_2026-10-22.md)。

- [summary.json](summary.json)：六场景结论、HTTP 与业务断言汇总。
- [business_assertions.json](business_assertions.json)：43项断言的观察值和来源标签，37项通过、6项失败。
- [contract_verification.json](contract_verification.json)：运行服务 OpenAPI 摘要及55个生成工具匹配结果。
- `01`–`09` 的 `*_plan.json`：不含凭据的工具调用计划。
- 对应 `*_results.json`：112次真实 HTTP 请求的参数、状态码、trace、耗时及有界响应。
- [db_before.json](db_before.json)、[db_after.json](db_after.json)：强制只读 SQL 的初始/最终核验；前者在初期发现后取样，后者在全部 HTTP 后取样。
- [db_intermediate.json](db_intermediate.json)：定位主题筛选、检索知识类型、审计 trace 和并发入库的中间核验证据。

区域参数执行中按用户要求从浙江调整为重庆市/成都市。`04`起为区域修订；`06`含重庆政策真实索引类型检索及主题反例；`07`–`09`补充重庆园区企业和岗位完整分页。保留前序记录供追溯，不能把浙江结果计入最终区域验收。

所有状态码均满足HTTP计划预期；业务语义仍有失败。第9批同一采集时间范围的样本从457变为474，保留原457期望产生的失败记录，不将其覆盖成通过。完整结论按报告中的场景矩阵评判。

认证头不会被记录。超过650字符的原文在结果中替换为excerpt、original_chars和sha256；响应短文本和结构字段保留。提供的Key已进行精确泄露扫描，未发现命中；临时凭据及未截断的本地原文响应已删除。复现请用新的运行环境变量注入凭据，方法见报告。

无需网络、数据库或Key即可复算业务断言（当前预期退出1，表示六项已知问题）：

```bash
nexus-api/.venv/bin/python scripts/verify_agent_openapi_acceptance_evidence.py \
  --evidence-dir docs/testing/artifacts/agent_openapi_2026-10-22
```
