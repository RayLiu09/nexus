# nexus-public-api 优化单元3：电商示范基地公开消费

日期：2026-11-19；单Agent。用户授权补齐基地公开查询、资源发现、skill路由及原五道缺口问题。上游embedding稳定性暂不处理。继承前两单元工作区，不提交、推送或部署。

## 来源与目标

依据ARCHITECT/SPEC独立只读`ecommerce_parks`业务域、Prototype市场数据“电商示范基地”双视图、WORKFLOWS API Contract及Permission And Audit Gate。现有内部Console接口保持原行为；公开消费通过nexus-api正式`/open/v1`适配。

## 冻结合同

- 新增GET `/open/v1/ecommerce-demo-bases`（`query_ecommerce_demo_bases`）、`/aggregate`（`aggregate_ecommerce_demo_bases`）、`/{base_id}`（`get_ecommerce_demo_base`），统一public-business标签、API Key认证、trace与脱敏读取审计、返回前Key状态复查。
- 查询直接使用现有`ecommerce_parks`事实，不依赖asset/version/normalized ref，不创建语义索引。level可选national/provincial，省略查询两级；q仅名称字面包含，province_code精确、recognized_year精确、batch枚举组合为AND。provincial+batch返回422。分页默认20、上限200；稳定排序level/province_code/source_order/id。
- 显式公开DTO仅返回已有业务字段、安全派生source_url；详情补充source_file/source_locator，禁止返回source_payload、伪造ref或缺失的运营主体/地址/产业定位。来源链接关闭或路径非法时URL为空，不对外抓取。
- aggregate使用同一过滤条件；group_by为province_code/level/recognized_year/batch_code白名单，1–4项不重复，默认province_code+level+recognized_year。全量匹配后分组再分页，meta.total为分组数，matched_total为名录记录数，missing_counts给出选定维度NULL/空值数；不去重物理基地。coverage返回国家/省级已入库数量及地区覆盖，标明离线快照、缺失字段、不代表全国完整或最新。
- discovery增加ecommerce_demo_base，count为两级名录记录总数，knowledge_types为空，仅catalog/structured_query，不宣称通用证据bundle或语义能力。同步生成3个工具、skill路由与说明，统计优先aggregate，详情/来源按需获取。

## 范围与禁止

允许新增公开API模块/公共展示helper/公开DTO、注册路由、资源发现及必要测试；可将内部来源URL/展示helper移到公共非路由模块，保持Console响应兼容。更新生成工具、skill、readme/ARCHITECT/SPEC、API合同及本单元证据。

不改数据库结构/业务数据、导入/采集/治理、Console页面与接口合同、现有检索排序/权限、embedding、岗位/企业SQL；不扩大联网入库；不提交/推送/部署。真实数据库只能只读查询，若用于验证，将必要公开业务字段复制到隔离SQLite，禁止真实库启动lifespan/worker/seed或写入。测试数据与线上证据明确区分。

## 验收与Gate

1. 列表/详情/聚合过滤一致，字面通配符、AND、跨级、空结果、分页稳定、分组数与记录数、NULL/空值统计、批次/年份语义均覆盖；大source_payload不读取/不返回。
2. 认证缺失401、权限/撤销/过期403、未知ID404、非法参数422、写方法405；读取审计包含actor/trace/route/数量与必要ID，不含q/来源URL/原文；中途撤销不返回结果或写成功审计。已有内部接口回归。
3. discovery新增能力与实际参数一致；OpenAPI生成与skill分发一致，最小路由/answer投影兼容。通过skill执行隔离新API，重跑原5题，保存可复核答复、来源、缺口、状态、字节及P50/P95，不能声称远端已部署。
4. API Contract与Permission And Audit提供实现自查和测试证据，人工Gate留待合并前审核；不把自动验证替代人工批准。

## 交付状态

实现与自动验证完成，见[Review证据](../review/nexus_public_api_optimization_slice3_2026-11-19.md)。API 75项、skill26项通过；生成工具58个、发现18类，漂移及格式/语法/产物校验通过。实际nexus_dev只读确认国家170/省级142，复制必要业务字段到隔离SQLite，由原skill执行器重跑五题，最终56次HTTP全部成功；115组以50/50/15三页完整取得。

未提交、推送、部署、迁移或修改真实业务数据。API Contract和Permission And Audit人工Review Gate留待合并前审核。原基线及前两单元记录保留。
