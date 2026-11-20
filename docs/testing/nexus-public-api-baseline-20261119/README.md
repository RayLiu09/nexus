# nexus-public-api 资产检索基线材料

测试日期：2026-11-19。覆盖当前资产中心18类入口、每类5题，共90题；17类85题通过原有[nexus-public-api skill](../../../.agents/skills/nexus-public-api/SKILL.md)实际取数，电商示范基地5题记录为公开能力缺口。

阅读入口：[分析报告](../../review/nexus_public_api_asset_baseline_2026-11-19.md)、[90题逐题答复](questions-and-answers.md)、[任务包](../../task-packages/wk_nexus_public_api_baseline_task_package.md)。本目录只包含测试定义、脱敏结果和测量数据，没有修改业务代码、skill、配置或数据库业务数据。公开查询仍按原机制写入查询审计。

## 文件说明

| 文件 | 内容与使用边界 |
| --- | --- |
| `testset.json` | 冻结的85题及依赖调用计划；每类5题，保留问题、范围与实际参数形状 |
| `coverage-gap-testset.json` | 基地类5题，标为公开工具未覆盖，没有伪造接口答复 |
| `questions-and-answers.md` | 90题答复、三轮工具链耗时、限制与来源锚点 |
| `answers.json` | 机器可读的90题答案、证据状态、引用及测量摘要 |
| `resource-discovery.json` | 测试时运行服务的公开资源发现快照 |
| `evidence-index.json` | 85道实测题的来源锚点、trace与返回规模 |
| `summary.json` | 主测试、轮次、类别、工具、题目及补测阶段汇总 |
| `call-measurements.json` / `.csv` | 逐次请求状态、HTTP耗时、字节数、trace；通过phase区分主测试和补测 |
| `question-measurements.json` | 255次问题执行的多步调用链、完成状态及耗时 |
| `executed-plans-round1.json` | 第一轮143次调用已解析的真实参数，包含当时有效的ref/chunk/section ID |
| `replay-round1.jsonl` | 由第一轮已解析参数生成的skill `serve`输入，便于固定参数复核 |
| `output-projection.json` | 同一课程查询的full/digest/summary输出对照，每种5次 |
| `response-shape-analysis.json` | 教材大metadata、图片数组及8K预算退化的脱敏测量 |
| `traceability-check.json` | 真实命中与normalized、chunk读取的ID、raw-object及423个图片URI副本核验 |

## 测量口径

主测试为85题各3轮，并发1，30秒超时，同一skill `serve`会话复用连接；共255次问题执行、429次HTTP调用。先行探针已经预热部分数据，没有清缓存，因此第一轮也不能称为真正冷缓存。岗位固定`received_to`，其他数据没有数据库一致快照。远端服务为`http://10.100.11.51:8000`，部署Git SHA未核实。

`elapsed_ms`是skill发送请求至完整读取HTTP响应的时间，不包含本地结果投影和进程启动。`chain_wall_ms`包含题目内多步调用和测试驱动开销，不包含Agent理解问题、工具规划与组织答案的耗时。本轮没有完整智能体端到端计时，不是并发容量压测。

分位数采用nearest rank：`sorted_values[ceil(n*p)-1]`。每题只有3轮、每类只有15个样本，类别P95等于最大值，仅作描述。不得用总请求数除运行时间推算服务容量。

阶段分开统计：

| phase | 尝试数 | 成功数 | 说明 |
| --- | ---: | ---: | --- |
| baseline | 429 | 429 | 249/255问题计划完整走完；政策2题各3轮无语义命中，停止后续取证 |
| focused | 100 | 78 | 热点、输出模式与扩大检索范围；2次503、10次500、10次传输失败均保留 |
| supplement | 11 | 11 | 正文不足后的定向取证；不并入原问题链时间 |
| recheck | 6 | 6 | 新会话教材恢复、精确标签复核 |
| tracecheck | 2 | 2 | normalized与chunk溯源副本核验 |

独立`call`的8K预算探针、资源发现和更早的预热请求不混入上述主测试指标。HTTP成功不代表有足够证据作答；`answer_status`为本Agent依返回证据标记的可答状态，并非金标准准确率。

## 固定参数复核

在仓库根目录运行，前提是当前进程已通过既有安全配置提供`NEXUS_API_KEY`。不要把密钥写入参数或测试文件。以下只是复核命令，本报告完成后没有再次自动运行请求：

```bash
python3 .agents/skills/nexus-public-api/scripts/nexus_call.py doctor

python3 .agents/skills/nexus-public-api/scripts/nexus_call.py serve \
  --base-url http://10.100.11.51:8000 --timeout 30 \
  --out-file /tmp/nexus-public-api-replay-results.jsonl \
  < docs/testing/nexus-public-api-baseline-20261119/replay-round1.jsonl
```

回放文件保留当时真实ID及岗位时间上限；资产版本变化后可能不再可消费。它是已解析请求的固定回放，不会自动从新目录重新发现ID，也不保证重现原缓存和故障时段。输出文件可能包含公开证据内容，不应当作脱敏指标直接提交。

回放显式使用digest与12,000字符预算，而正式主测试以`executed-plans-round1.json`中的模式执行，多数为full。当前digest对大metadata削减不足，预算超限可能退化到minimal并丢失引用；因此回放仍能观察HTTP状态与耗时，但不能据HTTP 200宣称原始答案与引用完整复现。该问题已在分析报告中列为优先优化项。

需要重新发现依赖时，`testset.json`中占位符约定如下，步骤索引从0开始：

- `$ref: [step, ...path]`：从此前响应路径取真实字段；路径包含整数时可对`items`列表索引。
- `$refs: [step, limit]`：取此前目录返回的去重`normalized_ref_id`数组。
- `$bundle: [step, limit]`：把目录ref转为`kind=normalized_ref`的批量证据引用。
- `$hits: [step, limit]`：把真实搜索命中chunk ID转为`kind=chunk`的证据引用。

无候选时停止依赖步骤，记录缺口，不构造ID。原始三轮驱动和本地配置映射仅位于`/tmp`，未作为持久测试框架交付；若未来需要持续集成，应单独界定动态发现、答案金标准和环境固定方式。

## 完整性与限制

`summary.run.suite_sha256`对应冻结`testset.json`的字节SHA-256，`skill_sha256`对应本次执行器。不要修改冻结测试集后继续引用原哈希。原始完整正文与凭据不入本目录；答案保留必要摘要和可解析证据锚点。

本轮是只读性能分析，不代表任何响应、索引、检索路由或数据质量修复已实施；潜在优化仍需同参数、同部署及证据等价的对照验证。

2026-11-19最终离线核验已通过：12个JSON与143行回放均可解析；18类每类5题、85题各3轮、429次主测试调用、各阶段错误数与汇总一致；分位数重算一致；冻结测试集和skill执行器哈希一致；trace及normalized血缘副本匹配；Markdown本地链接有效；新产物无行尾空白，也未发现本地已配置凭据值。`git diff --check`通过；原有容器构建文档及其他工作区文件保持原状。以上为本轮材料完整性核验，不是独立业务事实金标准评审。
