# nexus-public-api 优化单元2：服务端作答视图与故障定位

日期：2026-11-19；单Agent。服务端位于10.100.11.51，本机仅用于实现与测试。继承单元1变更，保留其他工作区文件。

## 冻结合同

- `/open/v1/search`新增可选`response_view=full|answer`，默认full不变；`answer_max_chars`仅限制answer每条内容，保留完整字符数/截断标记。
- answer返回canonical标题、score、正文及chunk/ref续查ID，省略完整metadata、血缘、原始对象、定位及大纲。引用通过现有chunk/ref/bundle按需读取。原始normalized副本不修改。
- adapter增加默认开启的lineage补全开关，仅answer关闭；governance/quality及当前治理值仍恢复，权限入口不变。answer enrichment只读取必要ref列，跳过大纲路径；审计继续保留chunk/ref/data-source及紧凑locator。
- 不改变scope、collection、Top-K、排序、可用性、认证、权限、审计事务或默认阈值；不重试、不降级为宽范围检索。
- skill的answer本地模式不自动推断远端已支持新参数。显式传`response_view=answer`后才能减少HTTP体积；生成工具Schema同步更新。旧服务上线前仍使用原请求。

## 范围与排除

允许修改：API search/public DTO与相应测试、pgvector adapter及vector_metadata与测试、公开工具生成产物、skill说明/必要测试、公开API合同、readme/ARCHITECT/SPEC、本任务包及验证报告。

日志调查只读远端，不检查本机容器代替远端，不重启/部署；不改数据库结构或业务数据，不修改QA/Console默认行为，不执行真实导入/联网入库。SQL专项、基地公开接口和其他领域列表投影仍为后续单元。

## 验证与Review Gate

1. 真实大lineage形状的full/answer命中、分数、内容前缀等价；默认full与显式full一致；按需chunk/ref/bundle可恢复引用；原对象不被修改。
2. 捕获SQL证明answer不读取normalized lineage列；省略血缘不影响canonical治理值与权限调用；审计actor、trace、chunk/ref/data-source及locator保留。验证不可用/非当前ref、范围、空结果、撤销Key、非法参数。
3. API与adapter针对性回归；生成工具Schema/skill同步、frontmatter和diff校验。可以用本地真实ASGI HTTP链路和隔离数据库测量，必须明确不冒称远端已部署或生产延迟。
4. 已通过用户授权的vmroot SSH/sudo只读读取10.100.11.51日志，确认两次标签503及十次教材500均对应LiteLLM embedding HTTP 429。search仅增加EmbeddingClientError→503稳定错误映射及脱敏日志，不自动重试、不改网关配置；验证连续失败后同一连接可继续查询、无成功审计且不泄露上游细节。连接中断与500相邻，尚无独立根因证据；网关具体限流/预算策略留待专项调查。
5. Semantic Retrieval Integration、Permission And Audit及API Contract Gate提供自查/测试证据；人工Gate在合并前审核，本单元不合并或发布。

## 交付状态

实现及自动验证完成，见[Review证据](../review/nexus_public_api_optimization_slice2_2026-11-19.md)。API针对性回归49项（search/QA审计23项及其他26项）、adapter/查询扩展40项、skill26项通过；生成工具漂移检查、skill frontmatter、Python语法及diff校验通过。隔离ASGI测量不冒称远端生产收益，原始数值及脚本位于`docs/testing/nexus-public-api-optimization-slice2-20261119/`。

远端故障trace已关联，凭据不落盘；SSH会话已退出。未提交、推送、部署、迁移或修改真实业务数据；人工Review Gate留待合并前审核。
