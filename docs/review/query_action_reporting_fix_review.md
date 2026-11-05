# 检索动作重复与来源计数修复验证

日期：2026-11-05。实现与针对性验证完成；合并前仍需 API Contract、Permission/Audit、Semantic Retrieval 和 Frontend UX 人工 Review Gate。

## 原因与修复

问题样例：`请查找重庆市2026年低空经济领域相关政策，以及产业链分布`。

1. 初次和补充规划均显示“选择查询工具”，实际属于不同阶段；同一函数的不同条件也只有相同标题。现改为“分析问题并选择查询方式”“根据已有结果补充查询”“检查并补全证据”，工具标题附带中文业务查询条件。只展示白名单业务值，UUID、凭证和原始参数不进入动作说明。
2. 旧 `source_count` 填写整轮注册表长度，前端将其作为本次动作结果展示。原问题修复前实测出现：`find_documents` 未命中，但计数为 38；园区查询未命中时计数为 38 / 40。现 `source_count` 表示当前响应实际关联的引用数，`new_source_count` 表示本次新注册数，`total_source_count` 显式表示累计数。前端只将本次计数归属到动作，不展示累计数；旧空结果事件即使带有累计字段也不显示该数量。
3. 旧调用引用绑定按“工具名 + 查询范围”扫描整个注册表，存在空响应继承早前引用的可能。现注册函数直接返回当前响应关联的编号，空响应返回空数组，重叠记录返回原编号与新增编号，不依赖来源原工具名反查。
4. 原执行器未阻止模型重复请求同样的工具参数。现按工具名和规范化 JSON 参数在单轮内复用成功/空结果，不发 HTTP、不新增虚假动作，复用数量写入查询审计。不同条件仍独立执行；失败请求允许正常重试。补充阶段也明确提示不要重复同样请求。

未修改 HTTP 路由、权限、入库开关、执行预算或数据库模型，未覆盖 active Prompt 配置。未进行提交、推送或合并。

## 自动验证

| 验证 | 结果 |
| --- | --- |
| runtime / executor / SSE 回归 | 50 passed |
| 前端查询单元测试 | 34 passed |
| TypeScript | passed |
| Playwright 桌面 / 平板 | 6 passed，包含本次计数显示及原有键盘、引用、停止与窄屏场景 |
| 修改的 ChatMessage 定向 ESLint | 0 errors / 0 warnings，使用已安装 Next 配置；不代表全仓库 lint |
| git diff --check | passed |

新增回归覆盖：成功后空结果不继承来源、重叠来源的当前编号、同参成功/空结果复用、参数顺序不影响复用、不同条件保留、失败后可重试、业务条件脱敏、规划阶段标题区分，以及旧累计事件在前端不会造成误归属。

```bash
nexus-api/.venv/bin/python -m pytest nexus-api/tests/test_public_query_runtime.py nexus-api/tests/test_public_query_tools.py nexus-api/tests/test_query_router_v2_stream_endpoints.py -o addopts='' -q
cd nexus-console
npm test -- app/query
npm run typecheck
NEXUS_E2E_BASE_URL=http://127.0.0.1:3000 npx playwright test e2e/query-public-tools.spec.ts --reporter=list --workers=1
```

## 原问题实际模型复测

通过已有有效业务专家身份调用本地内部 SSE 和公开业务接口，搜索入库关闭，Worker / 调度 / 同步关闭。修复后实际模型执行约 62.01 秒完成，形成 40 条引用；不将单次延迟变化作为性能改善证据。部分文档未有可用知识目录，目录读取返回 404，之后继续执行章节读取；本次未改动知识目录接口和相关数据。

| 代表动作及条件 | 本次引用 | 本次新增 | 累计引用 | 结果 |
| --- | --- | --- | --- | --- |
| 重庆、产业政策、低空经济、2026-01-01 起 | 4 | 4 | 4 | 成功 |
| 重庆、低空经济 | 20 | 20 | 24 | 成功 |
| 园区关键词“低空” | 0 | 0 | 24 | 未找到匹配内容 |
| 行业“低空经济”、重庆、产业政策 | 2 | 2 | 26 | 成功 |
| 标题“低空”、产业政策 | 14 | 14 | 40 | 成功 |
| 企业补充查询 | 0 | 0 | 40 | 未找到匹配内容 |

检查所有本次实际空结果动作，其 `source_count` / `new_source_count` 均为 0。不同条件的文档查询仍保留，现可从标题中的条件区分。重复请求去重由确定性回归测试验证，不以模型某次是否恰好选择重复参数作为验收依据。

将本次实际步骤回放到桌面和 390px 窄屏浏览器，均显示两条未命中动作及本次引用数，长条件标题不产生横向溢出。截图为本机 `/tmp/nexus-query-process-desktop.png` 和 `/tmp/nexus-query-process-mobile.png`。

来源计数表示可引用的注册条目，并非 API 匹配总数。原有 40 条引用上限不变，达到上限后的成功查询可能不新增引用，但不能因此标为“未找到匹配内容”。当前回复仍需按引用核对证据，参数不同也不代表相关性一定提高。

本机实际事件和输出记录：`/tmp/nexus-query-process-smoke-before.json`、`/tmp/nexus-query-process-smoke-after.json`；临时文件不提交。
