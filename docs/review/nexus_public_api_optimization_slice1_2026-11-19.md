# nexus-public-api 优化单元1验证

日期：2026-11-19。输入为[90题性能基线](nexus_public_api_asset_baseline_2026-11-19.md)和用户对实施顺序及消费原则的授权。关联[任务包](../task-packages/wk_nexus_public_api_optimization_slice1_task_package.md)。本单元已形成可验证的工作区交付，没有提交、合并、部署或数据库迁移。

## 最终行为

1. **内容先行，证据按需。** 新增`answer`本地输出模式，常驻`serve`默认采用；单次`call`默认full兼容。返回有用正文、业务事实、统计口径及少量续查ID，省略完整metadata/lineage/locator/图片与证据数组。需要核实/引用时用真实ID读取bundle、章节或详情。完整服务端响应和normalized副本不变。
2. **明确标签优先。** skill及流程规定：已知业务标签足以满足问题时，指定type、exact和any/all；正文问题仍需有正文支持，不能用目录命中代替正文。精确不足时再按问题转语义路径，不在执行器中擅自改写请求语义。
3. **内部不足可联网，来源明确。** 路由提示提供external fallback；保留用户仅平台范围和敏感外传约束，默认auto_ingest=false。网络answer保留真实标题、URL、可用日期及站点，标记source_kind=web；普通平台工具标记platform；可能混合来源的问答/路由标记mixed_or_unspecified。skill要求最终答复区分平台事实、网络材料及模型归纳。没有增加自动LLM规划器，是否补充仍由使用skill的Agent按内容决定。
4. **预算收缩仍可继续查询。** answer优先缩减冗余和正文，必要抽样明确标记返回数/原数组数，保留meta.total/sample_count等。课程列表超预算先返回完整本页的ID/名称/类型目录，并明确省略学时、正文、标签等字段；需要这些字段再get。极小预算仍可能minimal，不保证任意输出大小都能容纳引用。
5. **错误后连接释放。** HTTP 4xx/5xx、显式关闭及传输异常后丢弃连接，下一请求新建；成功持久连接继续复用。原错误仍返回，不自动重试、不重放可能写入的请求。该修复针对可验证的客户端恢复边界，不代表远端500/503已定位或修复。
6. **发现路由一致性。** 增加major_distribution、occupation_dictionary、standard_course、occupational_ability_analysis的实际发现编码别名；teaching_standard、talent_training_plan优先对应结构化工具，显式document路由仍可读文档补充。

`digest`也修正了教材搜索递归保留完整metadata的问题，保留必要locator与有限身份字段。原始full不变。answer的source_kind表示取数通道，并不证明来源权威、事实正确或最终答案准确。

## 真实验收

通过原skill执行器连接`http://10.100.11.51:8000`，初验9次、最终复核4次，共13次HTTP，13/13返回200。无并发、无自动重试。沙箱曾阻止9次请求，这些未到达服务端，不计服务失败；获得网络执行权限后重新执行。远端版本未核实，未升级服务。

| 形状 | 实际HTTP bytes | 模型收到的紧凑JSON bytes | 保留与限制 |
| --- | ---: | ---: | --- |
| 最终教材answer，8K字符预算 | 411,313 | 2,309 | 3条内容、3组chunk/ref；省略完整证据，字节减少99.44% |
| 教材digest，12K字符预算 | 411,314 | 5,688 | 3条命中及定位，未退化为minimal |
| 最终课程answer，12K字符预算 | 228,658 | 7,195 | 全部66条ID/名称/类型，meta.total=66；字节减少96.85%，详情字段按需取 |
| 显式读取首条课程详情 | 2,377 | 1,683 | 真实返回ID可用于get；HTTP 18.3ms |
| 显式读取教材首条chunk证据 | 1,798 | 1,569 | bundle返回1项及locator；HTTP 11.4ms |

本地投影发生在HTTP响应完整读取之后。上述百分比只是该请求的模型输入JSON字节减少，**不能解释为网络响应、数据库查询或完整智能体作答速度同比提升**。真实教材初验HTTP为4535.8/73.8/96.0ms，最终新会话复核696.6ms，仍有显著波动；没有从缓存状态变化中推导改造收益。

精确标签请求为`resource_type=teaching_case,tag_type=topic,tags=[数据安全],is_exact_matched=true,tags_match=all`，3/3均返回4份，HTTP113.5/104.4/90.4ms。此路径适用于该明确标签，不代表所有自然语言内容问题都可由标签回答。

在基线已确认基地无公开能力后，用公开词“商务部 国家电子商务示范基地 认定 名单”补充联网搜索一次，count=3、time_range=OneYear、auto_ingest=false。HTTP200/450.5ms，返回3条正文、真实标题、URL和供应商提供的PublishTime/SiteName；source_kind=web，ingestion.enabled=false，入库/提交数量均0。**3条均为百度百科页面/变体，不是已核实官方名单。** 该结果验证来源与内容可供模型使用；不足以替代认定公告或证明完整名单，最终答复仍须标注这一限制。网络日期为供应商返回值，本轮没有独立核验页面发布时间。

初验课程投影曾仅返回5/66，带抽样标记；最终增加目录优先策略后另行复核为66/66。初验数据保留，不覆盖成最终结果。

逐次状态、字节数、trace、网络来源及两个执行器版本哈希见[初验](../testing/nexus-public-api-optimization-slice1-20261119/live-initial.json)、[最终复核](../testing/nexus-public-api-optimization-slice1-20261119/live-final.json)、[汇总](../testing/nexus-public-api-optimization-slice1-20261119/summary.json)。只保存脱敏测量与必要公开来源信息，没有完整返回正文或凭据。

## 回归与合同自查

- `python3 skills/nexus-public-api/tests/test_nexus_call.py`：25个测试通过。覆盖大图片数组、8K/12K内容与ID保留、显式证据定位、full兼容、统计范围与抽样标记、课程66条目录、网络元数据日期/站点保留、默认不入库、精确参数不被改写、路由及CLI默认值。
- 错误恢复故障测试覆盖401/403/429/500/503：本次只发一次，状态/正文保留，连接释放；下一请求新建。另覆盖成功复用、will_close和RemoteDisconnected。没有在远端人为制造故障。
- 对基线第一轮143次已保存的受限响应离线执行answer/12K投影：全部合法JSON、无minimal；trace、原始total、sample_count/missing_counts（存在时）一致；所有搜索命中及其chunk/ref和内容保留。17次缩减内容，7次顶层列表抽样，均有标记。数据为当时记录的受限响应，不是重新读取完整原文，也不是答案准确率金标准。
- `nexus-api/.venv/bin/python scripts/generate_public_function_tools.py --check`通过，公开OpenAPI与分发工具资产一致。
- skill-creator的`quick_validate.py`通过；新路由均引用有效工具。项目readme、ARCHITECT、SPEC区分standalone skill与Console联网开关，没有改变Console默认行为。

离线逐项结果见[143次投影核验](../testing/nexus-public-api-optimization-slice1-20261119/offline-projections.json)。原90题基线文件及其历史哈希不覆盖；当前执行器哈希已改变是本单元预期变更。

WORKFLOWS合同自查：服务端认证/准入/审计、检索范围与Top-K、normalized血缘、API Schema及写入语义均无变更；full回归与真实按需取证覆盖引用可恢复性。新增投影改变Agent上下文，不对最终语言答案质量作自动保证。涉及引用消费的Semantic Retrieval及Permission And Audit人工Review Gate仍应在合并前审核，本报告为实现与验证证据，不代替人工批准；本轮没有执行合并发布。

## 下一实施单元的边界

客户端已避免错误后继续复用连接；远端500/503仍应根据基线trace取得服务端分段日志与堆栈。接着设计服务端可选answer/compact投影，在保持full及按需溯源兼容的情况下减少hydration、序列化和实际HTTP字节，才可验证网络与检索耗时收益。当前不直接改服务端过滤、索引或默认阈值。岗位/企业SQL、基地公开接口各自作为后续独立单元。
