# nexus-public-api 优化单元3：电商示范基地公开消费验证

日期：2026-11-19。关联[任务包](../task-packages/wk_nexus_public_api_optimization_slice3_task_package.md)，承接用户确认的“补齐基地公开查询、发现与skill路由”小单元。上游embedding稳定性暂不处理。实现和自动验证已完成；工作区未提交、推送、合并、部署或执行迁移，真实数据库没有业务写入。其他工作区变更保留。

## 交付行为

新增三个API Key认证的只读GET接口，位于nexus-api，未直接暴露Console内部接口：

| 公开路径 | 生成工具 | 功能 |
| --- | --- | --- |
| `/open/v1/ecommerce-demo-bases` | `query_ecommerce_demo_bases` | 两级名录、名称/地区代码/认定年/批次AND筛选与分页 |
| `/open/v1/ecommerce-demo-bases/aggregate` | `aggregate_ecommerce_demo_bases` | 全量过滤后按省份代码、级别、认定年份、批次分组，再分页 |
| `/open/v1/ecommerce-demo-bases/{base_id}` | `get_ecommerce_demo_base` | 按真实返回ID读取业务事实、来源文件及JSON定位 |

直接复用独立`ecommerce_parks`事实，不依赖asset/version/ref，不创建向量索引。列表默认20、最多200，level省略时查询两级；省级+国家批次返回422。聚合`meta.total`为组数，`aggregations.matched_total`为记录数，缺失维度计入missing_counts并保留NULL分组。coverage独立描述全库快照，不能当作当前条件匹配数；省份覆盖不计NULL/空值。

列表/详情显式延迟并禁止隐式加载source_payload，SQL捕获确认没有读取该大列。公开DTO不返回原始JSON、不制造归一化锚点。来源URL按原站固定路径派生，并尊重来源链接开关；关闭或非法路径时为空，不抓取或验证网页。原内部API仅将展示和安全URL helper移到公共非路由模块，筛选、响应及Console行为不变。

每个成功读取沿用SEARCH_QUERY_EXECUTED审计、actor/trace、route、数量和必要记录ID，返回前检查持久化API Key撤销/过期；不记录q、原文、来源URL或凭据。不新增组织隔离，保持现有公开业务域的P0权限语义。

资源发现增加`ecommerce_demo_base`，现在覆盖18类可见入口，count从表读取，knowledge_types为空，检索能力仅catalog/structured_query。生成工具由55增至58，仍16个资源标签，skill新增独立路由，不将基地替换成产业园区，不走通用bundle。运营主体、详细地址、产业定位缺失时明确报告；引用与来源详情按需读取。原标签优先、来源区分和联网默认不入库策略保留。

## 实际数据与五题答复

已连接用户授权的10.100.11.182/nexus_dev，数据库连接和事务均强制只读，确认`transaction_read_only=on`。仅读取基地安全业务列，排除source_payload；取完后断开并回滚读事务。新API验证在隔离SQLite副本执行，API审计仅写入副本，不在真实库启动lifespan、worker或seed。

两次读取的必要字段摘要SHA256相同：`c1f473d9890f4e47e4b60e17bd67a369ac2227fd36096f92f77bbbe381c9d399`。国家170、省级142，共312条名录记录；国家覆盖30个省级地区，省级覆盖6个。该数量不是跨级去重的物理基地数，也不是最新全国完整名录。

原基线中5道unsupported问题全部已能通过skill的新公开工具执行，答复和限制分别为：

| 问题维度 | 实际答复与限制 |
| --- | --- |
| 简单查找 | 列出国家级前5条和认定年月，目录总数170；顺序为接口稳定顺序，不是排名 |
| 重庆筛选 | 返回5条，均为国家级；省级快照未收录重庆，不能推断现实中无省级基地 |
| 详情溯源 | 读取石景山记录，第二批、2015年7月，国家源文件及`/0/datalist/0`定位可用；该记录未开放官方详情链接，运营主体/详细地址未存储，明确缺口 |
| 全量分布 | 省份代码×级别×认定年份115组，共312条，3条认定年份缺失，保留未知年份组 |
| 重庆/浙江比较 | 国家级重庆5条（首批1/第二批1/增补3），浙江10条（2/5/3）；两地省级未收录，产业定位字段缺失，不从名称推断 |

完整[五题答复](../testing/nexus-public-api-optimization-slice3-20261119/questions-and-answers.md)、[机器可读答案与调用锚点](../testing/nexus-public-api-optimization-slice3-20261119/answers.json)、[115组CSV](../testing/nexus-public-api-optimization-slice3-20261119/all-province-level-year-groups.csv)均可复核。答复由本Agent从skill内容整理，不是另一个未实际运行的自动LLM规划器，也不宣称答案准确率金标准。没有执行联网补充。

初验完整115组响应经skill的12K本地预算后保留100组，并正确标记data_truncated；没有用这100组冒充全量。最终改为每页50组，三页50/50/15均完整、分组唯一、记录数合计312。初验[54次调用](../testing/nexus-public-api-optimization-slice3-20261119/question-set-initial.json)保留；最终[56次调用](../testing/nexus-public-api-optimization-slice3-20261119/question-set-results.json)均HTTP200。原90题基线及历史缺口文件不覆盖。

## 性能与适用范围

通过原skill执行器做真实loopback HTTP调用，包括Schema校验、参数编码、API Key认证、连接复用、本地answer投影及真实API审计。没有为调用替换HTTP结果或伪造API业务响应。数据源来自真实库；查询执行引擎是隔离SQLite，**这些不是10.100.11.51上的生产延迟**。

| 请求 | 次数 | 本地HTTP P50/P95 | 响应体bytes |
| --- | ---: | ---: | ---: |
| 国家级前5条 | 10 | 7.65 / 9.6ms | 2051–2052 |
| 重庆两级列表 | 10 | 7.0 / 7.9ms | 1968–1969 |
| 省份×级别×年份，每页50组 | 10 | 8.6 / 11.5ms | 6095–6096 |
| 重庆级别×批次 | 10 | 54.7 / 58.1ms | 1219–1220 |
| 浙江级别×批次 | 10 | 49.8 / 59.7ms | 1220 |

发现接口首次约633.6ms，含首次OpenAPI生成等本地启动成本；详情只测一次约46ms，不能据此报告稳定P95。50ms量级的小响应与本地持久连接传输有关的可能性没有独立测量，不将其归因于SQL热点。10次顺序请求样本有限，不能外推并发容量。本单元价值是补齐公开可消费能力和统计正确性，尚无“原基地公开API变快”的可比旧基线。

可运行[验证脚本](../testing/nexus-public-api-optimization-slice3-20261119/run_base_question_set.py)。默认使用仓库来源快照；`--live-db`强制只读读取指定nexus_dev，随后在本地副本验证：

```bash
nexus-api/.venv/bin/python docs/testing/nexus-public-api-optimization-slice3-20261119/run_base_question_set.py --live-db
```

## 回归及Review Gate

- API 75项通过：`tests/test_open_ecommerce_demo_bases.py tests/test_ecommerce_demo_bases_api.py tests/test_agent_public_business.py tests/test_public_function_tools.py`。覆盖列表/分组AND筛选、字面通配符、稳定分页、unknown及空值、计数/覆盖区别、来源URL白名单、不读raw payload、无写方法、原Console兼容及资源发现18类。
- 真实认证覆盖无Key/错误Key401、撤销/过期403、未知ID404、非法参数422、写方法405；三个读取路径均验证中途撤销在审计前失败，且不返回数据、不写成功审计。
- skill执行器26项通过，包含新资源编码选取专用聚合工具和有效工具路由。生成工具`--check`、skill-creator格式校验、Python AST、产物JSON/CSV、文档链接和`git diff --check`通过。

API Contract Gate自查：3个GET、类型化公开业务字段、参数枚举/边界、稳定操作名及生成工具同步，默认已有API合同未改变。Permission And Audit Gate自查：认证/返回前Key复查/脱敏审计有回归，原始payload不下发，没有越过Console身份边界。本报告为实现及自动验证证据；按WORKFLOWS的人工Gate留待合并前审核，不代替人工批准。

## 启用与后续

需部署包含本单元的新API版本及同步skill资产后，远端才有这三个公开工具。旧服务404不能解释为基地零记录。复测应核对发现18类、数据库312条当前快照、完整分页、group/record/missing计数、按需来源及认证审计；生产数量可以随获准数据初始化变化，不应写死312。

本单元没有迁移、索引、采集、入库或线上配置变更。下一独立任务为岗位查询/聚合SQL专项：先取得实际执行计划，再保持total、sample_count、missing_counts及固定received_to口径做优化；embedding稳定性仍按用户要求搁置。
