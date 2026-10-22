# Agent OpenAPI 实际场景验收测试报告

日期：2026-10-22（Asia/Shanghai）。测试对象为当前工作区的真实 `nexus-api`，通过用户提供的 Key 进行 HTTP 调用。**六个场景结论：4 个通过（其中标准课程带数据质量问题）、1 个部分通过、1 个未通过；不能按全部验收通过交付。**

共执行 **112 次真实 HTTP 请求，覆盖 28 个公开 function tools**。所有请求的状态码均符合计划中的 HTTP 预期；业务与边界离线核验共 **43 项，37 项通过、6 项未通过**。HTTP 成功与业务验收通过分别统计。

## 1. 验收依据、变更和范围

依据：[`agent_openapi_gap_analysis_2026-10-22.md` 第 6 节](../agent_openapi_gap_analysis_2026-10-22.md)、[公开接口合同](../api/public_agent_data_api.md)、[本次任务包](../task-packages/wk_agent_openapi_live_acceptance_task_package.md)。

用户在执行过程中要求“采用重庆市或成都市作为区域参数”。本报告以 **`region=重庆市` 为政策主场景，`region=成都市` 为补充数据边界场景**。浙江的前序调用保留为执行历史，不计为最终区域场景通过。主题仍为 `low_altitude`，日期仍为近两年 `2024-10-22` 至 `2026-10-22`；未为了获得结果放宽这些条件。补充 `finance_commerce` 查询用于对比，不能代替低空主题验收。

园区链路补充重庆本地园区。园区 API 没有声明 `region` 参数，因此按实际合同使用 `q=重庆&industry=电商` 检索名称/简介中的地域文字，再核对详情地址；没有向接口传入无效的地域参数。院校专业对照使用数据中确实同时存在的湖州样本，不能把无对应资料的院校强行拼接。

本次测试只消费现有资料和业务记录。没有调用外部搜索自动入库、构建/重建大纲或图谱、治理、修改资产状态、修改权限/API Key 等接口。C 类接口不在范围内。没有插入业务测试夹具，也没有使用 Mock/TestClient 作为实际验收结果。本报告不以之前的单元测试通过数代替真实 HTTP 结果。

## 2. 环境、版本与执行方式

| 项目 | 实际值 |
| --- | --- |
| 代码基准 | 分支 `main`，HEAD `bc021183ea6748d7ab5af99ae5cb7e4654a36a46` |
| 被测实现 | HEAD 加当前工作区尚未提交的 A/B 接口实现；不能把 HEAD 单独视为已包含被测实现 |
| API 地址 | `http://127.0.0.1:8000/open/v1` |
| 运行环境 | development，Python 3.12；实际 PostgreSQL、对象存储、pgvector/嵌入调用链 |
| 认证 | 提供的真实 Key，经执行器注入 `X-API-Key`；另验证 Bearer 兼容方式；报告和计划不含 Key |
| 启动控制 | `WORKER_POOL_ENABLED=false`、`CRAWLER_SCHEDULER_ENABLED=false`、`DATA_SYNC_RUNTIME_ENABLED=false` |
| 临时 API 生命周期 | 2026-10-22 17:36 左右启动；17:57:21 正常关闭 |
| HTTP 证据批次完成时间 | 17:40:06 至 17:52:37；每个结果文件记录 UTC 批次完成时间 |
| Console | 本任务未启动；结束时端口 3000 无监听 |
| 工具执行方式 | 按生成的 `http-bindings.json` 将工具名映射为实际 HTTP method/path/query/body；由 Python `httpx` 发起请求 |
| 工具合同校验 | 从运行服务导出 `/openapi.json` 后执行生成器 `--openapi ... --check`，55 个公开工具产物与运行合同匹配 |

启动时曾受沙箱网络限制导致数据库连接失败；获准使用正常本地网络环境后启动成功。沙箱内的传输失败已重跑，未纳入下面 112 次有效 HTTP 统计。健康探测和 OpenAPI 合同下载也不混入场景请求计数。

API 常规启动包含幂等 Prompt seed 的既有流程，本任务没有调用配置变更 API；业务只读指接口消费行为。读取接口会写访问审计，不把“只读”解释为数据库完全没有写操作。

## 3. 场景结果矩阵

| 场景 | 最终样本/范围 | 验收结果 | 关键结论 |
| --- | --- | --- | --- |
| S1 近两年区域低空产教政策及条款引用 | 重庆市主链路；成都市补充 | **未通过** | 章节与引用可用，真实索引类型下检索可用；低空主题过滤误命中，资源发现缺少检索类型映射。成都市严格日期筛选无数据 |
| S2 电子商务专业标准、核心课程及建议学时 | 电子商务，330701，高等职业教育本科 | **通过，附数据质量问题** | 选定 active 标准的 11 条 core 记录均带来源及 suggested 语义；其中“互联网产品设计”存在空白差异重复 |
| S3 教材章节设计实训任务 | 《01 新零售教材》及《47411-A0电子商务数据分析实践（初级）》 | **通过** | 知识/任务大纲区分明确；缺失不构建；95/25 个节点上下文块可截断续读；可形成有来源的任务建议 |
| S4 行业最新采集岗位及学历分布 | 互联网电商，固定采集时间范围 | **部分通过** | 两轮聚合分别与独立 SQL 一致；默认排序不等于采集时间排序；延迟入库使同一筛选样本从 457 变为 474，缺少可冻结快照的参数 |
| S5 园区候选合作企业 | 重庆跨境电子商务台湾产业园(通用时代) | **通过** | 10 家企业均保留真实 park_id；候选企业详情有经营范围与来源；不宣称已建立校企合作 |
| S6 院校专业简介与培养方案对照 | 湖州职业技术学院，跨境电子商务，530702 | **通过** | 院校、专业名、代码一致；两份独立文档锚点；12 门方案课程带证据，未访问退役简介投影 |

场景状态按该任务必须满足的业务断言判定；“通过，附数据质量问题”不代表重复课程检查通过。S2 的归属、学时语义和来源三个必要断言通过，额外重复数据检查仍列入问题清单。

## 4. 资源发现与准入边界

以下为首轮资源发现返回的真实计数，时间为约 17:40。文档、投影、独立记录各自采用合同边界，单位不能混用，也不表示全国覆盖率。

| 资源 | code | 首轮计数 | 单位 |
| --- | --- | ---: | --- |
| 产教政策 | `industry_policy` | 708 | documents |
| 产业报告 | `industry_report` | 282 | documents |
| 行业报告 | `sector_report` | 189 | documents |
| 专业简介 | `major_profile` | 85 | documents |
| 人才需求调研 | `talent_demand_report` | 14 | documents |
| 人才培养方案 | `talent_training_plan` | 24 | documents |
| 教学案例 | `teaching_case` | 193 | documents |
| 专业布点数据 | `major_distribution` | 63 | records |
| 职业能力分析 | `occupational_ability_analysis` | 14 | records |
| 市场岗位 | `market_job` | 87,102 | records |
| 产业园区 | `industrial_park` | 11,373 | records |
| 企业数据 | `enterprise` | 76,031 | records |
| 专业教学标准 | `teaching_standard` | 2 | standards |
| 标准课程库 | `standard_course` | 67 | courses |
| 课程教材 | `course_textbook` | 164 | textbooks |

独立 SQL 在 `REPEATABLE READ READ ONLY` 事务中核验本次响应内 **317 个不同 normalized_ref_id**：全部为 `generated`，锚定 `available` 版本，并且是各自版本最新的 generated ref。该结论覆盖本次返回的引用集合，不等于扫描所有未返回文档。

非 available ref 的章节读取返回 404；批量证据中 available 文档、不可用文档、未知文档、独立岗位、独立园区依次返回 `available / not_found / not_found / available / available`。不可用和不存在的公共 item 除输入 ID 外形状一致，业务记录没有被虚构 normalized_ref。

## 5. S1：重庆市/成都市区域政策检索与条款引用

### 5.1 请求和观察

主筛选：`find_documents(query={resource_type: industry_policy, topic: low_altitude, region: 重庆市, published_from: 2024-10-22, published_to: 2026-10-22})`。

- 重庆市严格条件返回 **7 份**；去掉日期条件返回 **35 份**。7 份文档的存储 `publish_date` 均落在近两年内。
- 成都市严格条件返回 **0 份**；去掉日期条件返回 **3 份**，三者 `publish_date` 均为空。该地域补充场景记为**日期元数据缺口阻塞**，不能用入库时间代替正式日期，也不能编造政策条款。
- 重庆市结果包含《重庆电子商务腾飞计划（2026-2028年）》的两个文档版本来源。进一步以该标题和 `topic=low_altitude` 作为反例查询，仍返回 **2 份**；预期为 0，断言失败。
- 按合同复核 7 份结果的标题及本 ref 的 industry/topic 标签：均不满足现有主题规则的标题/标签条件。这里的规则不是“检索正文”；其中部分综合规划正文确有低空条款，不能据此证明标题/标签筛选实现正确。腾飞计划全文读取后也没有“低空”内容，是明确误命中的对照样本。

反例 trace：`227c864b-13bc-4f85-8708-12a4fab3b9b3`。初步定位到公开筛选复用 `_document_topic_predicate` 时，内部标签 EXISTS 仅显式关联 Asset，未正确关联外层 normalized ref；需修复后用跨 ref 的相反主题数据回归。本次仅记录问题，未修改被测业务实现。

### 5.2 检索类型与引用链

`kb=industry_policy` 或省略 kb 的调用均返回 0。独立查询发现现有政策知识块使用 **`industry_research_kb`**；按实际类型调用同一组文档范围，返回 **10 条**结果，均属于选定的 7 个 ref，且保留 block 引用。教材的真实语义检索也返回 5 条结果，说明检索链路确实执行，不能把前述零结果简单归因于嵌入服务不可用。

资源发现只返回 `code=industry_policy`，没有对应的可用检索知识类型字段；生成的 search 工具也没有资源分类与索引类型的映射。因此目前需要执行者额外了解配置/库中类型才能完成调用链，这是 Agent 自主发现能力缺口。`kb` 与 `knowledge_types` 也不能同时传；本次正确请求使用单一 `kb=industry_research_kb`。

| 可核验引用 | 来源 ref | block | 实际读取内容与可用解释 |
| --- | --- | --- | --- |
| 《重庆市数字贸易和服务贸易高质量发展行动方案》低空相关条款 | `fdaaa8e2-5ba0-4829-a5fe-6e8570b17226` | `web-block-0019` | 第（四）项包含推进“低空飞行器”等领域产品升级和出口，可用于低空产业与外贸需求背景 |
| 同方案人才条款 | 同上 | `web-block-0038` | 第（二十）项“推动高校开设数字贸易、服务贸易相关专业”“加强服务贸易人才培训基地建设”，属于数字贸易人才条款，不能改写成低空专业建设专项要求 |
| 《重庆电子商务腾飞计划》产教条款（补充电商政策引用） | `5e6a5808-4ac3-4cae-8b96-dac632ae7242` | `web-block-0047` | 第 19 项“支持院校深化产教融合，与电商平台共建高校电商实训基地”；只支持电商产教结论，不能当作低空产教专项政策 |

限定检索 trace：`efba015a-7bda-4068-b003-fedb385720a8`；低空条款读取 trace：`7e39da29-3750-4669-a613-0ac0fefec98c`；人才条款读取 trace：`ccaaae0a-15c2-48d8-abc7-83a843d24144`；知识块批量解析 trace：`237da0a6-03b4-4994-beab-4ec64cb421ac`。

四条检索命中的 chunk 通过 `get_evidence_bundle(kind=chunk)` 再次解析，均 available 并保留 source_block_ids。网页资料以 block 和 md_char_range 定位，没有物理页码时不编造页码。

日期核查的额外观察：上述行动方案 metadata 的 `publish_date=2025-05-23` 对应文件落款；正文页头另有“发布日期：2025-11-28”。两者均在此次两年区间内，但需在业务口径中明确“落款/发文日期”和“网页公开日期”。本次证明筛选依据存储源日期，不宣称已验证所有源站日期元数据的提取准确性。

结论：**引用能力可用；低空筛选准确性和自主检索类型发现未通过。现有证据不足以把两类独立条款拼接成“重庆低空产教专项政策”的结论。**

## 6. S2：电子商务专业教学标准与建议学时

选中标准库 `359fa704-488e-4829-9952-a7038c343f08`，专业 **电子商务 / 330701 / 高等职业教育本科**，不是高职专科 530701。源 ref 为 `b289c57a-0aad-4513-b1a8-827e9529c850`，源版本 `40a3c962-5b11-4aef-8998-fd809a1c2ab7`。

调用链：标准查询 → 标准详情 → `query_standard_courses(library_id=..., course_type=core)` → 课程详情 → 标准原文块及批量证据。以下保留接口原始课程名称和全部 11 条记录，不静默合并。

| 核心课程原始名称 | 课程代码 | 建议总学时 | 建议实践学时 | 来源页 |
| --- | --- | ---: | ---: | ---: |
| 平台运营 | `VC330701-C01` | 48 | 32 | 3 |
| 零售门店020 运营管理 | `VC330701-C02` | 48 | 32 | 3 |
| 行业数据化 运营 | `VC330701-C03` | 64 | 40 | 3 |
| 品牌建设 | `VC330701-C04` | 48 | 32 | 3 |
| 网络营销推广 | `VC330701-C05` | 48 | 32 | 3 |
| 互联网销售管理 | `VC330701-C06` | 64 | 40 | 3 |
| 供应链管理 | `VC330701-C07` | 64 | 40 | 3 |
| 智能客服 | `VC330701-C08` | 48 | 32 | 3 |
| 用户体验设计 | `VC330701-C09` | 64 | 40 | 3 |
| 互联网产品 设计 | `VC330701-C10` | 64 | 40 | 3 |
| 互联网产品设计 | `VC330701-C11` | 64 | 40 | 3 |

所有记录均属于选定 active 标准、同一专业代码和同一 ref。学时字段为 **`hours_semantics=suggested`**，标签为 `tag_semantics=derived`；例如平台运营建议 48 总学时、32 实践学时，另有 48–64 范围与规则设置依据，不能表述为“原标准规定平台运营必须 48 学时”。

平台运营来源绑定 `block-p03-050`、page=3、heading=专业核心课程、table_row_index=1。实际 `read_document_section` 读取了该完整原文表格（字符预算 20000），可核对课程领域与任务描述。接口没有使用培养方案课程聚合替代标准课程库。

课程查询 trace：`ceeeb8e1-96b5-44bb-a9e2-851722e34900`；原文表格 trace：`b73f3f76-02c9-402a-9655-d2f960f9acce`。

数据质量观察：`互联网产品 设计` 与 `互联网产品设计` 去除空白后重名，分别拥有不同课程记录；11 条记录仅有 10 个去空白后的名称。另有 `零售门店020 运营管理` 等原始识别文本，应由源数据/派生治理流程核对。本次不修正式数据，不把重复两行简单当成不同课程计算学时总和。

## 7. S3：教材章节与实训任务设计

| 样本 | ref | 已有大纲 | 反向大纲 |
| --- | --- | --- | --- |
| 《01 新零售教材》 | `18940e50-cd19-4c1c-b896-4543e38a13d2` | knowledge，188 节点；“第一章 新零售基础认知”节点 `12714963-6036-4b24-babd-ef17505f405f` 下 95 chunks | task：available=false，total=0 |
| 《47411-A0电子商务数据分析实践（初级）》 | `be6079d7-4ac8-43c3-b182-3558bb7344de` | task，542 节点；“工作任务一 市场数据采集”节点 `node-task-6b4c72329d28` 下 25 chunks | knowledge：available=false，total=0 |

分别以 `max_chars=100` 读取、再携带 `next_offset` 与 `next_char_offset` 续读，与 20000 字符预算的基准上下文逐块对比：95/25 个 chunks 的字符均完整，无遗漏或重复。理论教材首个 chunk 从字符 100 续读剩余 22 字符；实训教材在第二个 chunk 从字符 85 续读，验证不能只增加 offset 而丢弃半个 chunk。

理论大纲第二页 offset=50 也被实际读取；缺失大纲与文档检索空列表具有不同语义。理论教材的已有证据图谱返回 `available=false, reason=not_generated`，没有启动构建。

任务上下文包含“智能门锁近三年的市场趋势”“月销量超过500单的竞品”“标题、链接、价格、月销量”等真实任务背景与指标；这些是教材内容，不代表本次已经采集了市场业务数据。可据此生成如下 **Agent 设计建议**：

1. 任务名称：智能门锁市场与竞品数据采集；目标是选择渠道、确定指标、制作表格并解释市场趋势。
2. 输入：教师提供的合规模拟数据或已授权数据；以教材的三年趋势窗口和月销量超过 500 单的竞品规则作为练习条件。
3. 操作：制定指标字典；建立关键词与月度搜索指数表；建立商品名/链接/价格/月销量竞品表；核对缺失、单位和来源；说明选品与定价判断的依据。
4. 交付：采集计划、两张数据表、字段口径与来源清单、简短分析。评价可围绕口径完整、过程可追溯、结果可复算制定；具体权重由教师决定，不伪称教材已有评分制度。

来源为上述 task ref + node + chunks（保留 `source_block_ids` 和 locator），任务全文读取 trace：`490a0ef2-733e-443e-9f87-a25cfcbfba8c`；续读 trace：`d2fba50d-57e0-4efe-a0a5-98cc3dd5f3a7`。设计建议没有写回系统。

## 8. S4：行业岗位、全量学历聚合与快照问题

一致的筛选条件：`industry=互联网电商`（存储文本包含匹配），`collected_from=2026-10-22T00:00:00Z`、`collected_to=2026-10-22T09:39:00Z`。这里的“行业”不是标准行业字典精确匹配，包含复合行业文本；时间按 UTC 明确传递。`collected_at` 是采集时间，`created_at`/`received_at` 是入库链路时间；本接口没有虚构招聘发布日期。

初轮列表只读 5 条，聚合样本为 457；后续聚合重复仍为 457。测试后期完整分页为 200 + 200 + 74 = **474 条不同 raw_jobs.id**，与末轮聚合和末轮独立 SQL 全部一致。

| 学历原始值 | 初轮记录数 | 末轮记录数 | 末轮比例（分母474） |
| --- | ---: | ---: | ---: |
| 大专 | 160 | 165 | 34.81% |
| 本科 | 118 | 126 | 26.58% |
| 学历不限 | 116 | 119 | 25.11% |
| 中专/中技 | 48 | 49 | 10.34% |
| 高中 | 15 | 15 | 3.16% |

末轮 missing_counts.education=0。“学历不限”是源字段值，不当成 null 或“没有学历”。这些统计覆盖已入库记录，不代表岗位真实去重后的招聘需求量、企业数量或全国总体。

**通过部分：** 聚合使用全量过滤后的 raw_jobs，与 raw_job_provenance 对应；两次只读 SQL 分别确认初轮、末轮分布。接口明确 `source=raw_jobs`、`unit=records`、`deduplication_key=raw_jobs.id`、`coverage=ingested_records_only`。没有访问旧 JobDemandRecord 投影。

**未通过部分一：最新采集排序。** 初轮前 5 条的采集时间依次为 `09:26:38`、`09:26:13`、`09:26:42`、`09:26:32`、`09:22:22` UTC，非降序。接口按 created_at DESC/id DESC 返回，不能将第一条称为“最新采集岗位”。末轮全部 474 条可在 Agent 侧按 collected_at 排序，最新实际记录为 `76f7e529-ed07-4b4e-920e-dc3442b8fdc4`，采集时间 `09:38:58.086319Z`，其入库时间为 `09:44:40.452758Z`。

**未通过部分二：跨调用快照。** 即使 collected_to 固定，后到数据仍会加入过去的采集窗口，457 → 474 就是实测反例。当前没有 snapshot_id、as_of 或 received_at 上界条件。三页末轮读取期间和末轮 SQL 观察一致，但不能据此宣称跨任意多次调用具有事务快照保证。

初轮聚合 trace：`4f181a2c-f47e-4ebb-97f2-0180036e82ab`；末轮聚合 trace：`082db68a-d4da-436e-9fcb-f1b4f7dbc4a8`。计划中 4 个“仍为457”的检查均失败，完整保留在第9批证据；这些是并发数据一致性发现，不是统计 SQL 算错。

Agent 可在当前有限样本下完整分页后排序，交付末轮分布，并明确采集时间窗口与查询时点；产品若要保证“最新采集”和可复现跨工具统计，仍需补排序及快照合同。

## 9. S5：重庆园区与候选合作企业

选中园区：**重庆跨境电子商务台湾产业园(通用时代)**，ID `791815d2-05eb-49d8-81bc-5ffdd895b9c1`。详情位于重庆市江北区金源路53号；industry_tags 为“电子商务、跨境电商”。来源：[园区来源页面](https://y.qianzhan.com/yuanqu/item/1b8fe50d65af2f53.html)。

`query_enterprises(park_id=...)` 返回 10 家，数量等于园区详情 enterprise_count，全部 `industrial_park_id` 与选中园区一致。实际读取了多家详情；与跨境电子商务专业相对相关的候选建议为：

| 候选企业 | 记录ID | 已有经营范围依据 | Agent 建议方向 |
| --- | --- | --- | --- |
| 斯里普文化传播（重庆）有限公司 | `784acec7-2202-4067-802e-692b65273b34` | 货物进出口、出版物互联网销售等 | 可进一步核实内容商品与跨境电商运营实践机会 |
| 纵帆供应链管理（重庆）有限公司 | `5e267a70-f1c2-487a-a080-d89084732359` | 供应链管理、普通货物仓储、国内货物运输等 | 可进一步核实物流与供应链实践机会 |

这两项是基于已有园区关系和经营范围提出的候选建议，**没有证据表明企业已与某院校建立合作，也没有证据表明其当前接受实习生**。工程咨询、能源营销等其他园区企业不会因“同在园区”自动视为跨境电商专业的优先候选。

经营范围在源记录中已有“...”截断，详情沿用该原始值；完整经营事项需查源补齐，不能自行扩写。企业详情的 source_url 已保留在机器证据中。

园区企业查询 trace：`3f7e4a4c-7270-4ad8-8a9d-3a2a8771c75f`；斯里普详情 trace：`2f24ecbf-e4e6-4ec9-b5c9-a002a3c1b0c7`；纵帆详情 trace：`bb44306d-ab38-4562-b1a2-90179c5abb71`。

## 10. S6：院校专业简介与培养方案对照

匹配结果：**湖州职业技术学院 / 跨境电子商务 / 530702**。简介元数据教育层次为“高职专科”；专业匹配以院校、专业名和代码三项为主，保留层次原文，不强行统一各来源的描述。

| 来源 | 独立锚点 | 实际读取 |
| --- | --- | --- |
| 湖州职业技术学院2025年跨境电子商务专业介绍 | ref `a8fbbb03-0c69-421e-bcd9-822a34e96a03` | 39 个原文块、限定语义检索5条、单块正文、批量证据 |
| 同院校跨境电子商务人才培养方案 | plan `dd91dbd4-bb1a-4fcf-93ea-8384be728ad9`；ref `5d82fef8-87f3-4fe9-bb94-3ff1828442e0` | 详情、方案原文、12门课程及其 evidence.block_ids、工作岗位能力表 |

可输出的对照：

- 简介 `block-p00-005` 强调“跨境电商+产业带”、绿色家居和纺织服装等区域产业、平台运营、国际市场拓展和数字化营销。
- 方案 `block-p00-017` 的工作岗位与职业能力表列出跨境电商运营、海外推广、数据分析等方向及相关课程；这是独立的方案来源证据。
- 12 门课程为：国际贸易基础、国际商务文化与礼仪、跨境电子商务法律法规、数据采集与处理、跨境电商基础、进出口业务操作、视觉营销设计、跨境电商选品管理、跨境电商B2C运营、跨境电商营销、跨境电商客户服务、跨境电商供应链管理。
- 可以据此判断简介强调方向在方案课程/岗位描述中存在对应内容；不能据本次资料证明实际开课、师资到位、教学成效或校企合作落地。课程接口没有给出学时字段时不补造数值，也不把标准课程 suggested 学时迁移到该方案。

简介单块 trace：`5e170d74-b6bd-4f9d-bc49-312c9fa22d67`；方案能力表 trace：`cdc42702-67e9-4c3b-bc47-c929677bbd5b`；双来源证据解析 trace：`97230b8f-3aa0-4c1d-9491-0d6ab39e55b4`。实际调用路径全部使用 `/major-profile-documents` 和 `/talent-training-plans`，未调用退役 MajorProfile 接口。

## 11. 认证、边界、审计与只读证据

| 检查 | 实际结果 |
| --- | --- |
| 有效 X-API-Key / Bearer | 均200 |
| 缺少 Key / 无效 Key | 均401 |
| pageSize=201 | 422 |
| 源日期起止倒置 | 422 |
| 重复 aggregate group_by | 422 |
| evidence 31项、section max_chars=20001 | 均422 |
| 未知 ref、非available ref | 均404 |
| 当前资源中不存在的标题 | 200、data=[]、total=0 |
| 标准库与不存在专业代码交集 | 200、total=0 |
| 教材ref与政策知识类型的 AND 检索 | 0结果，未越出范围 |
| 无对应类型大纲 | available=false，与空查询区分 |
| 无既有图谱 | available=false、reason=not_generated |
| 标准/教材/方案当前准入边界 | 对317个返回ref进行独立核验，未见违反 |
| 新成功消费接口读取审计 | 96 条 public_data_read 审计均能与对应成功请求的 trace 对上 |
| 语义检索审计 trace | 7 次 search 审计均 trace_id=null；响应带trace但审计未关联，未通过 |

检索审计初步原因：search handler 读请求 header 的 x-trace-id，而默认响应 trace 由 middleware 放入 request.state；客户端不主动提供 trace header 时审计丢失关联。新增 `audit_read` 路由使用 request.state，因此本轮新消费工具的审计关联正常。

前后强制只读 SQL 快照检查了17张表的 count 和 max(updated_at)。asset、asset_version、normalized_asset_ref、governance_result、job、大纲、图谱 build、标准库/课程、教材、培养方案、园区及企业等15张表未变；raw_jobs 和 provenance 均从 **87102 增至87371（+269）**，符合测试之外并发入库的观察。本任务所有 HTTP 工具均属于只读 allowlist，且关闭本地Worker和调度；没有调用业务写接口。没有追踪外部入库执行进程，也没有把 count/max 检查夸大成逐行事务证明。

本次没有实际撤销/过期 Key、没有改权限来测试403；未验证组织细粒度隔离。当前组织过滤为 P0 noop，不能据此声称验证了租户/组织隔离。也未覆盖所有55个工具、UI、外部搜索或负载压力。

## 12. 问题清单与处置建议

| ID | 优先级/性质 | 可复现事实 | 影响 | 建议 |
| --- | --- | --- | --- | --- |
| D01 | P1 / 筛选缺陷 | 重庆电商腾飞计划在 low_altitude 条件仍返回2份；7份候选均不满足声明标题/本ref标签规则 | Agent 主题答案混入无关政策 | 修正主题标签子查询的ref关联，增加跨ref相反主题回归 |
| D02 | P1 / Agent发现缺口 | 资源code=industry_policy；实际kb=industry_research_kb；直接使用资源code检索为0，发现响应无映射 | Agent 无法仅靠发现结果可靠完成文档内检索 | 公开可用 knowledge_types 或资源到索引类型映射，并明确未知类型行为 |
| D03 | P1 / 场景能力限制 | market-jobs按created_at排序；前5条collected_at非降序 | 第一条不能视为最新采集 | 提供采集时间排序和稳定ID次序，明确默认排序 |
| D04 | P1 / 可复现统计限制 | 固定collected_to仍457→474；晚到记录入库时间09:44而采集时间早于09:39 | 列表、分页、聚合不能保证跨调用快照一致 | 提供受控as_of/received_at上界或快照机制，并统一聚合口径 |
| D05 | P2 / 源投影数据质量 | 互联网产品设计存在空白差异重复，11条core记录只有10个标准化名称 | 重复计数及学时求和误导 | 按课程来源序号/标准身份核对去重，保留派生与人工修正审计 |
| D06 | P1 / 审计关联缺陷 | 7条search审计trace_id为空，但HTTP响应有trace | 无法按默认trace完成检索审计追溯 | 统一从request.state读取trace，补带/不带header两类回归 |

补充数据限制：成都市三份政策缺正式日期；部分教材出版社/年份等缺失；企业经营范围源值已截断；同一政策多站点转载作为不同文档计数；文件落款日期与网页公开日期可能不一致。这些均未在测试中填补或改写正式数据。

**本次没有修复上述业务缺陷，也没有把失败结果覆盖成通过。** 修复后应按下节重跑受影响请求和业务断言；涉及筛选、检索和审计合同的修改仍需对应 Review Gate。

## 13. 请求统计与性能样本

- 状态码分布：200×103、401×2、422×5、404×2；没有5xx或有效批次传输错误。
- 计划中的状态码/trace/局部语义检查共234项，229项通过、5项失败。失败为主题反例1项、晚到数据造成的原457快照期望4项。
- 独立业务核验43项，37通过、6失败；它与计划检查有交叉，两个计数不相加作为“总用例数”。
- 客户端单次耗时：最小2.73ms、中位37.62ms、P95（nearest rank）810.07ms、最大3421.52ms。顺序执行、含初次检索开销，仅为本轮样本，不是压测或SLA结论。

## 14. 复现与证据文件

脚本：[`test_agent_openapi_scenarios.py`](../../scripts/test_agent_openapi_scenarios.py)、[`verify_agent_openapi_live_db.py`](../../scripts/verify_agent_openapi_live_db.py)、[`verify_agent_openapi_acceptance_evidence.py`](../../scripts/verify_agent_openapi_acceptance_evidence.py)。

在有相同当前工作区、数据库、对象存储及嵌入配置的环境中，先按第2节关闭Worker/采集调度启动API，再从仓库根目录执行。Key通过终端隐藏输入进入环境变量，不写命令行字面量或计划文件：

```bash
read -r -s -p 'API Key: ' NEXUS_OPENAPI_KEY
export NEXUS_OPENAPI_KEY
nexus-api/.venv/bin/python scripts/test_agent_openapi_scenarios.py \
  --plan docs/testing/artifacts/agent_openapi_2026-10-22/04_regional_revision_plan.json \
  --output /tmp/nexus-openapi-regional-rerun.json
unset NEXUS_OPENAPI_KEY
```

其他批次同理替换plan。计划包含本次发现的真实ID，因此数据库不同需要重新发现并替换ID；数据继续入库时不能期待仍为457或474。第9批保留初轮457的期望是为了展示快照问题。场景脚本在局部断言失败时保存完整脱敏证据并返回1，不能忽略退出码。

不需要Key即可离线复算本报告43项断言：

```bash
nexus-api/.venv/bin/python scripts/verify_agent_openapi_acceptance_evidence.py \
  --evidence-dir docs/testing/artifacts/agent_openapi_2026-10-22
```

当前应输出37通过、6失败并返回1，代表已知验收问题仍存在。该命令是证据复核，不会发起新的真实HTTP测试。数据库核验脚本只能在配置数据库可达的环境中执行，内部明确设置 `REPEATABLE READ READ ONLY`；输出不包含连接凭据。

证据已去除请求认证头，长原文保留前650字符、长度及SHA256，避免将大段原文重复铺满报告。未截断的结构字段、ID、计数、locator、响应trace和耗时均保留。凭据曾暂存在权限0600的临时文件，结束后删除；服务日志未包含认证头。仓库证据与脚本进行了提供Key的精确扫描，未发现泄露。

| 批次结果文件（同目录有对应plan） | 请求数 |
| --- | ---: |
| [01_discovery_results.json](artifacts/agent_openapi_2026-10-22/01_discovery_results.json) | 16 |
| [02_chains_results.json](artifacts/agent_openapi_2026-10-22/02_chains_results.json) | 21 |
| [03_evidence_results.json](artifacts/agent_openapi_2026-10-22/03_evidence_results.json) | 29 |
| [04_regional_revision_results.json](artifacts/agent_openapi_2026-10-22/04_regional_revision_results.json) | 6 |
| [05_continuation_and_cq_results.json](artifacts/agent_openapi_2026-10-22/05_continuation_and_cq_results.json) | 16 |
| [06_semantic_and_bounds_results.json](artifacts/agent_openapi_2026-10-22/06_semantic_and_bounds_results.json) | 10 |
| [07_cq_park_and_references_results.json](artifacts/agent_openapi_2026-10-22/07_cq_park_and_references_results.json) | 6 |
| [08_cq_enterprise_details_results.json](artifacts/agent_openapi_2026-10-22/08_cq_enterprise_details_results.json) | 3 |
| [09_full_population_results.json](artifacts/agent_openapi_2026-10-22/09_full_population_results.json) | 5 |

独立证据：[`business_assertions.json`](artifacts/agent_openapi_2026-10-22/business_assertions.json)、[`db_before.json`](artifacts/agent_openapi_2026-10-22/db_before.json)、[`db_after.json`](artifacts/agent_openapi_2026-10-22/db_after.json)、[`contract_verification.json`](artifacts/agent_openapi_2026-10-22/contract_verification.json)。另见[证据索引](artifacts/agent_openapi_2026-10-22/README.md)。前后快照在初始发现和部分早期读取之后/全部HTTP结束后取样，覆盖大纲续读/图谱读取期间；不是API启动前完整库备份。

## 附录 A：43项业务与边界断言

| 类别 | 断言 | 结果 |
| --- | --- | --- |
| COMMON | 15 visible resource types | 通过 |
| COMMON | all HTTP status expectations satisfied | 通过 |
| COMMON | all HTTP responses carry trace IDs | 通过 |
| BOUNDARY | returned document refs are current generated refs on available versions | 通过 |
| BOUNDARY | batch evidence separates available records and hides unavailable refs | 通过 |
| BOUNDARY | hidden and unknown refs have identical public item shape | 通过 |
| BOUNDARY | section continuation reconstructs source exactly | 通过 |
| S1 | stored source dates fall within requested two years | 通过 |
| S1 | low-altitude candidate matches declared title/tag topic rule | 未通过 |
| S1 | indexed policy search is scoped to selected refs and retains block citations | 通过 |
| S1 | chunk batch resolution preserves availability and source blocks | 通过 |
| S1 | discovery supplies policy semantic index type for Agent calls | 未通过 |
| S2 | all core courses belong to selected standard and professional code | 通过 |
| S2 | suggested hours and derived tags are explicitly distinguished from source facts | 通过 |
| S2 | courses retain page, section, and source block bindings | 通过 |
| DATA | core course projection has no duplicate names after whitespace normalization | 未通过 |
| S3 | theory outline kind is available and opposite kind is explicitly absent | 通过 |
| S3 | theory continuation preserves all chunk characters without loss or duplication | 通过 |
| S3 | training outline kind is available and opposite kind is explicitly absent | 通过 |
| S3 | training continuation preserves all chunk characters without loss or duplication | 通过 |
| S3 | missing graph differs from an empty filtered query | 通过 |
| S3 | job count/latest_update unchanged across outline and graph reads | 通过 |
| S3 | knowledge_outline_node count/latest_update unchanged across outline and graph reads | 通过 |
| S3 | task_outline_node count/latest_update unchanged across outline and graph reads | 通过 |
| S3 | knowledge_graph_build count/latest_update unchanged across outline and graph reads | 通过 |
| S3 | capability_graph_staging_build count/latest_update unchanged across outline and graph reads | 通过 |
| S4 | initial aggregate independently matches raw_jobs SQL | 通过 |
| S4 | final aggregate independently matches raw_jobs SQL | 通过 |
| S4 | complete final pagination and aggregate agree, with no duplicate record IDs | 通过 |
| S4 | aggregate covers whole source population rather than first five records | 通过 |
| S4 | default first page is ordered by collection time descending | 未通过 |
| S4 | same collection cutoff preserves a stable sample over the test window | 未通过 |
| S4 | source provenance and collection time retained without invented publication date | 通过 |
| S5 | Chongqing park and all enterprises preserve actual park foreign key | 通过 |
| S5 | cq_enterprise_784acec7 detail retains stored relation and source URL | 通过 |
| S5 | cq_supply_chain_candidate_detail detail retains stored relation and source URL | 通过 |
| S5 | records do not assert existing school-enterprise cooperation | 通过 |
| S6 | introduction and training plan match institution, professional name, and code | 通过 |
| S6 | comparison preserves two independent normalized document references | 通过 |
| S6 | all 12 plan courses retain their own plan/ref and source block evidence | 通过 |
| S6 | scoped introduction semantic search retains correct document reference | 通过 |
| AUDIT | semantic search audit automatically shares response trace IDs | 未通过 |
| AUDIT | new successful data tools have persisted trace-linked public read audits | 通过 |

每项观察值、来源标签可见 `business_assertions.json`。六个未通过项均在问题清单中逐项解释。

## 附录 B：全部112次实际请求的索引

每条请求的完整path、query/body、脱敏响应和检查结果见对应批次JSON；下面提供按执行顺序的工具、HTTP状态、耗时和trace，便于审计定位。浙江前序记录和区域修订明确分为S1/S1_REVISED。

| 序号 | 场景 | 请求标签 | 工具 | HTTP | 耗时ms | trace_id |
| ---: | --- | --- | --- | ---: | ---: | --- |
| 001 | COMMON | `resource_discovery` | `discover_data_resources` | 200 | 822.53 | `5d1be422-215f-4dff-b77e-cd80a5f86b03` |
| 002 | COMMON | `missing_key` | `discover_data_resources` | 401 | 2.73 | `df290098-ab50-4db2-8b20-8496e829192c` |
| 003 | COMMON | `invalid_key` | `discover_data_resources` | 401 | 6.28 | `7128f06b-389e-4d1d-b2c8-01c15f2ffe80` |
| 004 | COMMON | `bearer_key` | `discover_data_resources` | 200 | 163.66 | `70d2067c-df9e-407a-8d75-9db3010fefdc` |
| 005 | S1 | `exact_policy` | `find_documents` | 200 | 151.52 | `c692a102-b1fa-4f2c-8106-a7bc8150001e` |
| 006 | S1 | `all_policies` | `find_documents` | 200 | 107.19 | `26e58808-85e0-4891-a9b7-2e4a93bfb778` |
| 007 | S2 | `ecommerce_standard` | `query_teaching_standards` | 200 | 30.48 | `bdd69102-21b8-4134-9173-570afde99903` |
| 008 | S3 | `textbooks` | `find_textbooks` | 200 | 304.69 | `4ec478fb-f61b-4180-846f-3e5c1ddd2f03` |
| 009 | S4 | `jobs_initial` | `query_market_jobs` | 200 | 139.90 | `c94ca399-776a-47ab-8801-1111aef91206` |
| 010 | S4 | `industry_coverage` | `aggregate_market_jobs` | 200 | 105.47 | `9772cf91-ebb7-473a-983b-d0de0693071c` |
| 011 | S5 | `parks` | `query_industrial_parks` | 200 | 149.15 | `85fe4413-98f9-41cc-9556-97650f029640` |
| 012 | S6 | `major_introductions` | `find_major_profile_documents` | 200 | 527.54 | `826d92d0-43c3-4a9d-8173-b5ef9f9a2e15` |
| 013 | S6 | `training_plans` | `list_open_talent_training_plans` | 200 | 40.44 | `5ce3b30a-5183-45db-a162-e670fcf08424` |
| 014 | BOUNDARY | `empty_query` | `find_documents` | 200 | 203.41 | `3d1e0854-3df5-4457-9be8-6652f5e35a18` |
| 015 | BOUNDARY | `invalid_page_size` | `query_market_jobs` | 422 | 9.22 | `0fcbdfc7-8481-4e8c-820b-db62f712d160` |
| 016 | BOUNDARY | `missing_ref` | `list_document_sections` | 404 | 9.94 | `1f2ae2fd-f920-445d-9bc0-80778851ef24` |
| 017 | S1 | `policy_sections` | `list_document_sections` | 200 | 184.06 | `78870212-8b4c-410f-873f-4888bfd66bec` |
| 018 | S1 | `policy_scoped_search` | `search_evidence` | 200 | 3421.52 | `4cb62b91-e990-427a-85f2-3b0a7da3d77b` |
| 019 | S1 | `policy_date_mismatch` | `find_documents` | 200 | 629.05 | `af089690-527b-441d-b5fb-a8d0213e2669` |
| 020 | S2 | `standard_detail` | `get_teaching_standard` | 200 | 25.05 | `49dcf3a9-bd8d-4f5e-a16a-5ccfd52d7da4` |
| 021 | S2 | `standard_core_courses` | `query_standard_courses` | 200 | 163.93 | `ceeeb8e1-96b5-44bb-a9e2-851722e34900` |
| 022 | S2 | `standard_sections` | `list_document_sections` | 200 | 58.49 | `fadc173d-78d2-4c8e-9d20-e4365f6ec7eb` |
| 023 | S3 | `theory_detail` | `get_textbook` | 200 | 20.07 | `2838c8dd-96d7-4b3b-b09f-25add9573b07` |
| 024 | S3 | `theory_knowledge_outline` | `get_knowledge_outline` | 200 | 25.54 | `0e9597ef-abd5-4730-8ae7-e8fad81a7e43` |
| 025 | S3 | `theory_task_outline` | `get_task_outline` | 200 | 18.90 | `79db0633-dd38-4b74-93ac-4621d46d5d06` |
| 026 | S3 | `training_detail` | `get_textbook` | 200 | 21.61 | `54c2b7cd-cd93-404b-8574-c533ff1bd969` |
| 027 | S3 | `training_knowledge_outline` | `get_knowledge_outline` | 200 | 20.30 | `e05b35ce-a951-4dc1-9c32-7d9a11408baa` |
| 028 | S3 | `training_task_outline` | `get_task_outline` | 200 | 24.88 | `18c4f820-c942-4537-9152-b3ff4f839976` |
| 029 | S3 | `textbooks_all` | `find_textbooks` | 200 | 1644.09 | `ddc250e2-b78f-4232-90f2-e3216911bb33` |
| 030 | S4 | `jobs_same_filter` | `query_market_jobs` | 200 | 49.01 | `5745048a-9512-44f3-891f-9c7408669283` |
| 031 | S4 | `education_distribution` | `aggregate_market_jobs` | 200 | 69.66 | `4f181a2c-f47e-4ebb-97f2-0180036e82ab` |
| 032 | S5 | `ecommerce_parks` | `query_industrial_parks` | 200 | 306.25 | `dbfab422-dafd-4fa0-99ba-7e17b41d518a` |
| 033 | S6 | `all_major_introductions` | `find_major_profile_documents` | 200 | 452.83 | `58daaa44-6614-4a89-a600-22d3111117a6` |
| 034 | S6 | `all_training_plans` | `list_open_talent_training_plans` | 200 | 21.87 | `5dd56288-ddfd-47ae-8db7-c1e0a9ec0d63` |
| 035 | BOUNDARY | `invalid_date_range` | `find_documents` | 422 | 5.76 | `c3cbce4c-ad11-4b89-a8ec-9355f4278669` |
| 036 | BOUNDARY | `duplicate_aggregate_dimensions` | `aggregate_market_jobs` | 422 | 6.43 | `2111ada2-9219-42de-ad41-f22fd8beafa7` |
| 037 | BOUNDARY | `missing_batch_evidence` | `get_evidence_bundle` | 200 | 10.73 | `3e0c8796-1c05-49b3-9df5-f3f72dddcb33` |
| 038 | S1 | `policy_search_explicit_type` | `search_evidence` | 200 | 509.40 | `c64f5fad-8d69-408a-8799-4bf22daf769c` |
| 039 | S1 | `policy_sections_continued` | `list_document_sections` | 200 | 37.15 | `a077d279-12d1-4d3e-b4e4-40d70b13465a` |
| 040 | S1 | `policy_clause_read` | `read_document_section` | 200 | 33.53 | `a1e57d34-4887-4630-b45c-c5bf4c7e7604` |
| 041 | S1 | `low_altitude_title_dated` | `find_documents` | 200 | 36.35 | `aea16653-2454-4f63-9ec5-dbea121ef204` |
| 042 | S1 | `low_altitude_title_undated` | `find_documents` | 200 | 91.74 | `86b528a9-cef6-4ef3-9a9b-856ed07ef683` |
| 043 | S2 | `core_course_detail` | `get_standard_course` | 200 | 16.57 | `8f1a336d-1b1a-41bb-bdbe-40f57d60cfd3` |
| 044 | S2 | `source_standard_table` | `read_document_section` | 200 | 34.44 | `b73f3f76-02c9-402a-9655-d2f960f9acce` |
| 045 | S2 | `standard_evidence_bundle` | `get_evidence_bundle` | 200 | 39.58 | `035228b9-d38a-490d-a2fd-6d3e6603fe36` |
| 046 | S3 | `theory_node_context_small` | `get_outline_node_context` | 200 | 60.18 | `b20764df-18ae-4938-afbe-75ac31d81c7f` |
| 047 | S3 | `theory_node_context_full` | `get_outline_node_context` | 200 | 40.42 | `2336c395-87a9-4f02-9a58-0509822e1c31` |
| 048 | S3 | `training_node_context_small` | `get_outline_node_context` | 200 | 62.95 | `4cf86866-089a-4562-b370-68f8c23700ab` |
| 049 | S3 | `training_node_context_full` | `get_outline_node_context` | 200 | 31.52 | `490a0ef2-733e-443e-9f87-a25cfcbfba8c` |
| 050 | S3 | `theory_outline_page2` | `get_knowledge_outline` | 200 | 21.61 | `009ee3d1-d274-4d35-85d9-95da5d9ecf83` |
| 051 | S3 | `theory_existing_graph` | `read_existing_graph` | 200 | 21.17 | `c9932bb3-6094-4c70-a7ee-ccfc3311fa13` |
| 052 | S4 | `job_detail_0cff7465` | `get_market_job` | 200 | 11.15 | `11945645-378a-4055-8a06-e08eea17d97b` |
| 053 | S4 | `job_detail_69132d80` | `get_market_job` | 200 | 9.91 | `a9d73a7d-05a0-4955-8b08-b39e30fa1f6d` |
| 054 | S4 | `education_distribution_repeat` | `aggregate_market_jobs` | 200 | 69.18 | `da5eb9f9-65c7-4d7c-ab22-3adf454b4aea` |
| 055 | S5 | `selected_park` | `get_industrial_park` | 200 | 11.35 | `963aa272-07db-40af-ba1f-16fc85744631` |
| 056 | S5 | `park_enterprises` | `query_enterprises` | 200 | 15.18 | `eff3df5c-225c-4a77-ad5b-12dbb3dc3cde` |
| 057 | S6 | `matched_introduction` | `find_major_profile_documents` | 200 | 832.13 | `32b1da53-6064-4cc9-a59c-7a540a192afe` |
| 058 | S6 | `matched_plan_query` | `list_open_talent_training_plans` | 200 | 19.74 | `78765e42-e3f7-4a4d-bfbc-0f6a26455ad4` |
| 059 | S6 | `matched_plan_detail` | `get_open_talent_training_plan` | 200 | 27.71 | `554b5e11-e632-4b2c-bf54-fbe037dabee3` |
| 060 | S6 | `introduction_sections` | `list_document_sections` | 200 | 44.53 | `44ee6ed0-0e1f-4dfa-a600-5c61eeae03c7` |
| 061 | S6 | `plan_courses` | `list_training_plan_courses` | 200 | 28.68 | `2ff3acb9-e453-42ef-96d6-797dd79c4a7c` |
| 062 | S6 | `plan_sections` | `list_document_sections` | 200 | 37.17 | `d16e01fa-9d01-40e4-8440-0304aa1be1da` |
| 063 | S6 | `comparison_evidence_bundle` | `get_evidence_bundle` | 200 | 61.52 | `97230b8f-3aa0-4c1d-9491-0d6ab39e55b4` |
| 064 | BOUNDARY | `non_available_ref` | `list_document_sections` | 404 | 7.91 | `62698c85-5667-4867-a59e-16fd2e4a75f2` |
| 065 | BOUNDARY | `mixed_visibility_evidence` | `get_evidence_bundle` | 200 | 48.11 | `c8948369-d883-405e-ab8b-f7dec12b2460` |
| 066 | BOUNDARY | `cross_classification_scope` | `search_evidence` | 200 | 624.67 | `797e1aa0-effe-4bec-913d-941ee99d0b22` |
| 067 | S1_REVISED | `重庆市_dated` | `find_documents` | 200 | 72.52 | `e1616332-491c-4f1e-bee3-fcda814420be` |
| 068 | S1_REVISED | `重庆市_undated` | `find_documents` | 200 | 170.57 | `00e34db9-c83e-4de8-9d1b-42323b6787d6` |
| 069 | S1_REVISED | `重庆市_finance_commerce_dated` | `find_documents` | 200 | 74.01 | `453e5073-5fd2-4619-ae6c-edef82543df8` |
| 070 | S1_REVISED | `成都市_dated` | `find_documents` | 200 | 23.81 | `37655448-98d8-41a9-8ad8-c71093acd91d` |
| 071 | S1_REVISED | `成都市_undated` | `find_documents` | 200 | 66.26 | `508ce9d1-f9c5-4a5a-8438-6dbf523c6fbd` |
| 072 | S1_REVISED | `成都市_finance_commerce_dated` | `find_documents` | 200 | 32.76 | `b78cdc74-c4ba-4b14-909c-09058bd2cbb2` |
| 073 | S3 | `theory_context_continue` | `get_outline_node_context` | 200 | 43.34 | `9196b797-0c3f-4881-8657-ef94758401c4` |
| 074 | S3 | `training_context_continue` | `get_outline_node_context` | 200 | 29.78 | `d2fba50d-57e0-4efe-a0a5-98cc3dd5f3a7` |
| 075 | S3 | `textbook_scoped_search` | `search_evidence` | 200 | 810.07 | `97192ebe-d610-4825-a536-428a7bba1291` |
| 076 | S5 | `enterprise_e908bfe7` | `get_enterprise` | 200 | 45.21 | `032d747b-7c1a-45c6-ae1b-0c6b6f1cf199` |
| 077 | S5 | `enterprise_975690c6` | `get_enterprise` | 200 | 19.63 | `67b64baf-d04c-48d1-9772-3fdc84e384ed` |
| 078 | S5 | `enterprise_e8acf093` | `get_enterprise` | 200 | 14.73 | `71f9b79e-f236-437a-bcab-c097b2dbccf9` |
| 079 | S6 | `introduction_identity_block` | `read_document_section` | 200 | 27.38 | `5e170d74-b6bd-4f9d-bc49-312c9fa22d67` |
| 080 | S6 | `plan_source_position_table` | `read_document_section` | 200 | 35.49 | `cdc42702-67e9-4c3b-bc47-c929677bbd5b` |
| 081 | S1_REVISED | `cq_policy_sections_0` | `list_document_sections` | 200 | 25.79 | `713f7f29-d61e-40e7-9f33-4fff73ec5cc2` |
| 082 | S1_REVISED | `cq_policy_sections_1` | `list_document_sections` | 200 | 26.73 | `ac23f56e-1a15-4944-b3d0-404186a8ed3d` |
| 083 | S1_REVISED | `cq_policy_sections_2` | `list_document_sections` | 200 | 25.17 | `1d20de4b-b0aa-403d-bd1b-61c7fdb088e9` |
| 084 | S1_REVISED | `cq_policy_sections_3` | `list_document_sections` | 200 | 25.87 | `6dcb8380-3cce-481f-bcbf-232fa7b28c7b` |
| 085 | S1_REVISED | `cq_policy_sections_4` | `list_document_sections` | 200 | 25.40 | `59181b1d-06c7-4e94-830d-5a8a1313d6ca` |
| 086 | S1_REVISED | `cq_policy_sections_5` | `list_document_sections` | 200 | 26.52 | `c702401c-dbba-41d8-95c8-c7a6523daead` |
| 087 | S1_REVISED | `cq_policy_sections_6` | `list_document_sections` | 200 | 38.53 | `b29c3d3d-ba61-465b-bd7b-03856f0ff06d` |
| 088 | S1_REVISED | `cq_policy_scoped_search` | `search_evidence` | 200 | 489.19 | `a1ce72e9-09f4-4dcd-8389-7f8d8a348efc` |
| 089 | S1_REVISED | `cq_search_actual_index_type` | `search_evidence` | 200 | 1032.72 | `efba015a-7bda-4068-b003-fedb385720a8` |
| 090 | S1_REVISED | `cq_low_altitude_clause` | `read_document_section` | 200 | 32.48 | `7e39da29-3750-4669-a613-0ac0fefec98c` |
| 091 | S1_REVISED | `cq_talent_clause` | `read_document_section` | 200 | 34.77 | `ccaaae0a-15c2-48d8-abc7-83a843d24144` |
| 092 | S1_REVISED | `cq_ecommerce_talent_clause` | `read_document_section` | 200 | 54.26 | `626da395-6284-43d8-8085-e3678e2d65a2` |
| 093 | S1_REVISED | `topic_false_positive_control` | `find_documents` | 200 | 63.09 | `227c864b-13bc-4f85-8708-12a4fab3b9b3` |
| 094 | S5_REVISED | `cq_ecommerce_parks` | `query_industrial_parks` | 200 | 393.58 | `373c4a25-9331-4c4c-a0cb-6c32d97a64fb` |
| 095 | S6 | `introduction_scoped_search` | `search_evidence` | 200 | 689.48 | `71e2ac99-86ff-4af9-9a63-9d72310a592a` |
| 096 | BOUNDARY | `oversize_evidence_batch` | `get_evidence_bundle` | 422 | 7.85 | `d122c8d5-9f6e-489c-824e-c0f0c402930a` |
| 097 | BOUNDARY | `oversize_section_budget` | `read_document_section` | 422 | 5.63 | `4ae32af8-2406-4dc4-9895-600cd556a323` |
| 098 | BOUNDARY | `standard_major_intersection` | `query_standard_courses` | 200 | 235.60 | `122b1349-9aae-481c-a7c0-f0365217750d` |
| 099 | S5_REVISED | `cq_selected_park` | `get_industrial_park` | 200 | 12.09 | `bb3b25db-0666-4ebc-ad84-c10b118402a8` |
| 100 | S5_REVISED | `cq_park_enterprises` | `query_enterprises` | 200 | 11.77 | `3f7e4a4c-7270-4ad8-8a9d-3a2a8771c75f` |
| 101 | S1_REVISED | `cq_chunk_reference_bundle` | `get_evidence_bundle` | 200 | 36.63 | `237da0a6-03b4-4994-beab-4ec64cb421ac` |
| 102 | BOUNDARY | `section_initial100` | `read_document_section` | 200 | 26.30 | `8cd58799-129f-4c46-b476-8d3440c9e1e4` |
| 103 | BOUNDARY | `section_resume100` | `read_document_section` | 200 | 29.09 | `e46c0ec3-cd0f-47cf-ba48-f6338f62879e` |
| 104 | BOUNDARY | `entity_major_candidates` | `resolve_business_entities` | 200 | 56.35 | `4e00ef14-05ac-4807-979c-b249cdfe3b26` |
| 105 | S5_REVISED | `cq_enterprise_91df77d0` | `get_enterprise` | 200 | 94.82 | `a23385ab-5d6b-4919-bfbd-b02c171d65f0` |
| 106 | S5_REVISED | `cq_enterprise_75a9540a` | `get_enterprise` | 200 | 51.47 | `8dd12319-1ef8-4290-a6b3-e24f8d074729` |
| 107 | S5_REVISED | `cq_enterprise_784acec7` | `get_enterprise` | 200 | 10.49 | `2f24ecbf-e4e6-4ec9-b5c9-a002a3c1b0c7` |
| 108 | S5_REVISED | `cq_supply_chain_candidate_detail` | `get_enterprise` | 200 | 38.06 | `bb44306d-ab38-4562-b1a2-90179c5abb71` |
| 109 | S4 | `jobs_full_page_1` | `query_market_jobs` | 200 | 166.32 | `3aac067c-1efb-4112-81b1-1a7021219f1f` |
| 110 | S4 | `jobs_full_page_2` | `query_market_jobs` | 200 | 155.52 | `1f41ad19-20d4-4f1f-bba4-0bde932f3fa3` |
| 111 | S4 | `jobs_full_page_3` | `query_market_jobs` | 200 | 88.22 | `33cbd1bf-acdc-4077-ba8c-4aef64429aec` |
| 112 | S4 | `aggregate_final_snapshot_check` | `aggregate_market_jobs` | 200 | 70.96 | `082db68a-d4da-436e-9fcb-f1b4f7dbc4a8` |
