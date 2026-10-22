# Agent 应用用数 Open API 补充分析

日期：2026-10-22。依据当前工作区源码静态核查；未调用线上服务，也未验证数据库迁移执行情况、各接口实际数据量和运行可用性。本文是接口规划建议，不修改或冻结现有产品/API 合同。

实施进展：A/B 类已按后续任务补齐，C 类未实施；接口合同与覆盖对应见 [Agent 公开用数接口](api/public_agent_data_api.md)，可加载工具见 [基于公开 OpenAPI 生成 function tools 清单](generated/public-function-tools/README.md)。

## 1. 结论与分析范围

现有 Open API 已有资产发现、正文、知识块、下载、检索、问答、部分结构化记录及图谱能力。主要缺口是：业务入口与公开数据源不一致、领域读取能力没有公开、检索缺少精确范围控制、长文证据读取不适合 Agent 上下文预算，以及对外工具契约不完整。

当前首页显示四个领域、15 个业务入口。教育政策、课程标准、证书数据和整个用户行为领域已隐藏，不纳入本次补充范围。业务入口不等于治理分类：标准课程库与专业教学标准共用父子领域模型；园区、企业是独立业务表。

“资产中心可见”仅用于界定资产类型范围。内部列表可能包含待复核数据，不能直接作为外部数据准入条件；文档及其领域投影对外仍须满足 available 等正式合同条件。结构化业务记录遵循其自身公开边界。

## 2. 已有公开能力

以下均以当前代码注册的 `/open/v1` 为准：

- 资产：`GET /assets`、`/assets/{asset_id}`、`/assets/{asset_id}/versions`。目录支持 `domain`、`tag_type`、重复 `tags` 和精确/语义标签匹配；`domain` 实际是治理分类，不是首页四大业务领域。
- 标准化引用与证据：`GET /normalized-refs/{ref_id}`、`/governance-result`、`/content`、`/chunks`，后面三项是该引用下的子路径；另有 `/knowledge-chunks/{chunk_id}` 和 `/raw-objects/{raw_object_id}/download-url`。
- 检索与问答：`GET /search`、`GET /qa`、`POST /query`、`POST /query/stream`。`query` 是平台内 Query Router 的问答入口；外部 Agent 仍需要可组合的确定性数据工具。
- 结构化读取：职业能力分析及任务、能力条目、关系；旧岗位需求记录及其聚合；专业布点记录及聚合。
- 图谱：岗位能力、职业能力、专业教学标准图谱；人才培养方案课程图谱和岗位能力图谱。
- 人才培养方案列表和详情；院校专业开设、课程开设统计聚合。
- 外部搜索：`POST /external-search/firecrawl`、`/external-search/web-search`。它们默认 `auto_ingest=true`，存在入库副作用；工具说明必须表达这一点。纯用数场景应显式传 `false`。

这些能力应优先封装和增强，无须新建同义的问答、全文下载、职业能力树或专业布点统计接口。

## 3. 15 类入口覆盖矩阵

| 当前可见入口 | 当前业务数据源 | 现有公开覆盖 | 需要补充或修正 |
| --- | --- | --- | --- |
| 产教政策 | 正式分类 `industry_policy` 的文档与元数据 | 通用资产、正文、知识块、检索 | 标题、主题、区域、行业、发布日期精确筛选；按资产集合限制检索 |
| 产业报告 | `industry_report` 文档 | 同上 | 同上；稳定返回报告元数据和证据 |
| 行业报告 | `sector_report` 文档 | 同上 | 同上；保留与产业报告的分类区别 |
| 专业简介 | 文档列表与持久化专业身份元数据 | 通用文档能力；仍注册旧 `/major-profiles` | 公开当前文档读模型；旧结构化投影接口迁移/退役说明 |
| 专业布点数据 | `MajorDistributionRecord` 跨数据集记录 | 记录检索、分组聚合 | 优先工具封装，明确年份、省份、培养层次、数量单位和覆盖范围 |
| 专业教学标准 | `TeachingStandardLibrary` 父标准 | 通用文档与专业教学标准图谱 | 父标准身份列表/详情，连接课程库，按 ref 精确读取现有图谱 |
| 标准课程库 | `TeachingStandardCourse` 与父标准联查 | 缺少专用公开课程接口 | 跨标准课程查询、详情、学时与原文依据、推导标签及来源区分 |
| 人才需求调研 | `talent_demand_report` 文档与身份字段 | 通用文档能力 | 专业/院校等已有元数据筛选、限定报告集合的检索；保持语义文档模型 |
| 人才培养方案 | `TalentTrainingPlan` 及子表 | 列表、详情、两类图谱及相关统计 | 复用现有接口；按需求补全课程分页读取和时间筛选，不重复开发基础列表 |
| 职业能力分析 | 分析、任务、工作内容、能力条目和关系表 | 列表、详情、任务、条目、关系及图谱 | 增强专业代码过滤和跨分析能力条目检索，保留现有任务/能力读取 |
| 市场岗位 | `raw_jobs` 与 `raw_job_provenance` | 现有岗位 Open API 读 `JobDemandRecord`，数据源不同 | 建立与当前页面同源的岗位查询/详情/计数能力；明确与旧接口关系 |
| 产业园区 | `IndustrialPark` 与关联企业计数 | 只有内部领域接口 | 公开列表/详情及园区企业读取，支持名称和行业筛选 |
| 企业数据 | `Enterprise` 与所属园区 | 只有内部领域接口 | 公开列表/详情，支持名称、经营范围、园区过滤 |
| 课程教材 | `CourseTextbook`、知识大纲/任务大纲 | 通用文档、教材检索；没有公开专用教材/大纲接口 | 教材元数据检索、现有大纲只读获取、节点上下文、节点内证据检索 |
| 教学案例 | `teaching_case` 文档 | 通用文档能力 | 案例文档筛选与限定范围检索；保持语义文档模型 |

### 需要优先修正的数据口径

1. **市场岗位不能继续默认使用旧岗位需求接口代表当前岗位库。** 当前页面读取 `raw_jobs`，但 `/record-assets/job-demand-records` 及其聚合读取 `JobDemandRecord`。旧接口存在，并不证明能消费当前采集的岗位。新增接口要说明记录来源、采集时间、去重口径；这些原始岗位不能作为治理模块的直接输入。
2. **专业简介旧接口与现行文档模型脱节。** `/major-profiles` 读取 `MajorProfile`；迁移 `20261020_0119` 会删除历史 `major_profile` 投影，新流程不再生成它。部署完成该迁移后，不能依靠旧接口消费专业简介。保留专业身份元数据和通用 RAG 路径，不恢复已退役的课程、证书、能力子表抽取。
3. **现有统计口径必须标注覆盖范围。** `/major-offerings/aggregate`、`/major-courses/aggregate` 是已入库方案等来源的统计，不能代表全量院校实际开设情况，也不能与专业布点官方记录直接相加。代码仍保留旧 profile 兼容分支，迁移后的实际贡献需按部署数据确认。

## 4. 建议的工具与接口

下表所有新增路径、参数和工具名都是建议；“增强”表示在已有能力上补齐，不要求复制成另一个 API。路径统一归属 `nexus-api` 的现行公开路由边界。

| 优先批次 | Agent 工具 | 接口建议 | 主要输入与输出 |
| --- | --- | --- | --- |
| A | `discover_data_resources` | 新增 `GET /open/v1/data-resources` | 返回15类资源的稳定编码、治理分类或业务表类型、可用能力、筛选参数、单位与数量口径、限制；计数按外部可消费范围计算 |
| A | `find_documents` | 增强 `GET /open/v1/assets` | 增加标题、业务资源类型、多分类、主题、发布时间、专业/院校等适用字段；返回白名单业务元数据和可读取能力 |
| A | `find_major_profile_documents` | 新增 `GET /open/v1/major-profile-documents`，或作为增强目录的类型化工具 | 读取当前简介文档及四项身份字段，按专业代码/名称、院校、培养层次筛选；复用现有正文/知识块接口 |
| A | `query_market_jobs`、`get_market_job` | 新增 `GET /open/v1/market-jobs`、`/{job_id}` | 同当前岗位页的数据源；支持岗位/企业/行业、已有文本条件、采集时间；返回岗位原始字段、来源、采集时间和稳定ID |
| A | `query_industrial_parks`、`query_enterprises` | 新增 `GET /open/v1/industrial-parks`、`/{park_id}`，`GET /open/v1/enterprises`、`/{enterprise_id}` | 复用现有领域表，提供企业数量、所属园区、经营范围、来源；企业列表可按 `park_id` 过滤 |
| A | `query_teaching_standards` | 新增 `GET /open/v1/teaching-standard-libraries`、`/{library_id}` | 专业代码/名称、培养层次；返回标准身份、修业年限、课程数、引用锚点及公开可用状态 |
| A | `query_standard_courses`、`get_standard_course` | 新增 `GET /open/v1/teaching-standard-courses`、`/{course_id}` | 按课程名、专业、类型及已有标签过滤；返回学时、任务/内容要求、推导标签、来源章节页码与证据绑定 |
| A | `find_textbooks` | 新增 `GET /open/v1/course-textbooks`、`/{profile_id}` | 书名、理论/实训类型、出版社、主编、出版年；返回教材身份、ref 与已有知识/任务大纲能力 |
| A | `search_evidence` | 增强 `GET /open/v1/search` | 增加 `asset_ids`、`normalized_ref_ids`、多知识类型及白名单元数据条件；支持在已选资料内检索；保留 chunk、block、locator、得分 |
| A | `read_document_section` | 增强 `/normalized-refs/{ref_id}/content`，或新增其 `/sections`、`/sections/{section_id}` 子资源 | 按稳定章节/块定位读取，限制字符数和相邻上下文；返回原文片段、章节、页码、块ID、截断标志及续读游标 |
| B | `get_textbook_outline`、`get_outline_node_context` | 新增只读 `/normalized-refs/{ref_id}/knowledge-outline`、`/task-outline` 及对应节点读取路径 | 明确区分知识与任务大纲；返回已生成树/子树、节点内容、关联知识块和证据；不在 GET 中自动构建 |
| B | `read_existing_graph` | 增强现有图谱读取，按需新增 `/normalized-refs/{ref_id}/knowledge-graph` 只读适配 | 按 ref/图谱类型/节点/关系/深度限制返回已生成子图；附事实、推导来源和证据，缺少图谱时明确说明 |
| B | `get_evidence_bundle` | 新增 `POST /open/v1/evidence-resolutions`，明确为批量只读解析 | 输入有限量 chunk/ref/record ID，返回片段、证据定位与来源；减少逐条追溯请求；不把无证据输出当作已验证事实 |
| B | `aggregate_market_jobs` | 新增 `GET /open/v1/market-jobs/aggregate` | 在新岗位库中按有数据支持的岗位、企业、行业、学历等维度分组；列出过滤条件、去重规则、时间范围、缺失值和样本量 |
| B | `resolve_business_entities` | 新增 `/open/v1/entity-resolutions` 只读解析能力，或先由工具适配层组合已有查询 | 根据专业/课程/企业/园区名称返回候选ID、编码、实体类型和匹配依据；模糊名称返回候选，不强行合并 |
| C | `read_resource_changes` | 在有增量同步消费者时再设计 `/open/v1/data-resources/{code}/changes` | 基于稳定游标同步变化，覆盖退役/不可用等删除语义；只适合长驻 Agent 本地缓存，不是首批交互式查询必需 |

A/B/C 表示本次建议的交付顺序，不改变现有 P0/P1/P2 产品优先级，也不代表这些新增能力已获实施批准。A 中可分别拆为小任务包，不宜一次交付整个横切改造。

### 参数与数据前提

- 产教政策/产业报告/行业报告的 `finance_commerce`、`low_altitude` 是可重叠主题，不是治理分类；主题统计必须使用与查询一致的条件。
- 已有标签检索是 ANY 语义。需要“浙江 AND 低空经济”等组合条件时，应提供类型化筛选或显式 `any/all` 组合，不能让 Agent 自行误解为 AND。
- 当前岗位表没有独立规范化城市、薪资数值和技能统计事实。首批公开已有字段；城市筛选、薪资均值、技能频次须另行建立有证据、可审计的提取/规范化口径，不得把地址文本或薪资字符串当作可靠数值。
- 当前园区/企业模型没有完整地区、营收、规模等工商字段；应先公开已有名称、行业、经营范围、园区关系及来源，缺失字段保持缺失。
- 标准课程中的知识/技能/工具/素养标签属于推导标签；学时包含建议值。应返回来源与属性类型，不能将推导标签变成教学标准的图谱事实，不能将建议学时说成国家强制学时。
- `read_existing_graph` 只适配当前已有且通过公开准入的生成结果，不扩展知识生产 Pipeline。人才需求调研与教学案例按现有语义文档边界处理，不为它们重新引入图谱。
- 已有 `query.section_contexts` 是问答过程的上下文输出，不能替代外部 Agent 按给定文档/章节确定性读取的工具。

## 5. 工具契约与消费边界

1. **提供面向外部 Agent 的工具清单。** 平台内 `config/query_router_tools.json` 是内部调度注册表，包含 `internal.*` 工具，不是外部 HTTP/MCP 契约。可基于公开 OpenAPI 生成 function tools，并按资源按需加载；MCP 是可选适配层，不应复制业务逻辑或直接访问内部控制接口。
2. **输入输出有明确 Schema。** 现有多个领域接口使用 `dict` 响应；应补齐公开 DTO、字段含义、枚举、过滤匹配方式、分页、错误码和调用示例。给公开工具配置稳定 operationId；自然语言结果不能代替结构化返回。
3. **结果规模可控制。** 支持分页、稳定排序、字段投影、片段长度、批量ID上限和图谱大小限制；返回 `has_more`、`truncated`、续读位置。首批详情可按需延迟加载，不把整本教材或全部图谱塞给模型。
4. **证据锚点随数据返回。** 文档使用 asset/version/ref/chunk/block/locator 链；岗位等业务表使用 record ID、provider/upstream ID、来源URL和采集时间；园区企业保留自身来源。不要为业务记录伪造 normalized_ref。
5. **区分事实与推导、缺失与零、无结果与不可用。** 对聚合返回样本量、单位、去重键、时间范围和排除数；`collected_at` 不等于岗位发布日期，文档 `created_at` 不等于政策生效日。无来源统计不能推出全国或某省的完整总体。
6. **外部状态与内部状态分离。** 标准库自身的 `active` 等领域状态、资产版本 `available`、图谱构建成功分别校验；不能只靠其中一个状态放行。图谱/大纲只读接口不触发构建、重建或晋升；内部知识大纲 GET 有自动构建行为，不能直接搬到 Open API。
7. **准确表达当前权限。** 当前 API Caller 是 `open:*`，目录代码及 `permissions.py` 明确组织过滤为 P0 noop。新增工具沿用经评审的实际策略，不能宣称已有细粒度组织隔离；需要组织/字段级隔离时另立权限任务。也不能由于内部页面展示了 review_required 数据而公开这些文档。
8. **审计与敏感信息处理一致。** 公开领域读取与证据解析记录 caller、资源、查询摘要、返回数量、trace_id；批量读取逐项做可见性判断。日志不记录API Key或大段原文；原文下载继续使用已有短期签名URL接口。

跨资产的“比较课程体系”“建议专业调整”“匹配校企合作企业”等任务，首期由 Agent 组合这些读取工具完成。无需先开发一个任意 SQL 工具、通用大分析接口或新的数据复制层。

## 6. 建议验收用例

| Agent 任务 | 预期调用链 | 关键断言 |
| --- | --- | --- |
| 查找近两年浙江低空经济产教政策并引用政策条款 | 发现资源 → 文档筛选 → 文档内检索 → 章节读取 | 分类/主题/区域/日期筛选准确；按正式发布时间过滤；引用落到可用文档的块/页 |
| 对照电子商务专业教学标准，列出核心课程和建议学时 | 标准查询 → 标准课程查询 → 证据解析 | 课程属于选定专业/标准；建议值与来源事实区分；不把培养方案课程统计当作标准课程库 |
| 使用某教材一个章节设计实训任务 | 教材筛选 → 大纲读取 → 节点内容/知识块读取 | 返回已生成的大纲；准确区分知识与任务结构；不启动新构建；支持截断续读 |
| 查询某行业最新采集岗位，分析学历要求分布 | 当前市场岗位查询 → 同源聚合 → 记录追溯 | 与 raw_jobs 页面在相同过滤和快照下同源；不混入旧投影；采集时间与发布日期分开 |
| 为某专业查找产业园区中的候选合作企业 | 园区查询 → 按 park_id 查询企业 → 企业详情 | 园区关系为已有字段事实；匹配建议由 Agent 表达，不能虚构已存在校企合作关系 |
| 查某院校专业简介并与其培养方案对照 | 简介文档查询 → 简介正文/检索 → 已有培养方案接口 | 不依赖已退役 MajorProfile 行；院校、专业身份一致；保留各自引用来源 |

另外验证：所有文档只返回当前准入版本；业务记录按其独立边界公开；聚合不能从单页推算；不存在的数据字段明确缺失；禁止将“无大纲/图谱”和“空查询结果”混为一谈。

## 7. 核查依据

- `nexus-console/lib/asset-center/catalog.ts`：领域、资源及治理分类映射。
- `nexus-console/app/asset-center/_components/AssetCenterOverview.tsx`：首页真实隐藏逻辑。
- `nexus-console/app/asset-center/[domain]/[[...resource]]/page.tsx`：15 类入口的实际数据源。
- `nexus-api/nexus_api/main.py`：公开路由实际挂载。
- `nexus-api/nexus_api/api/open.py`、`open_record_assets.py`、`talent_training_plans.py`、`major_profiles.py`、`institutional_statistics.py`、`external_search.py`：现有公开接口及筛选参数。
- `nexus-api/nexus_api/api/internal/assets.py`、`raw_jobs.py`、`industrial_park_enterprise.py`、`teaching_standard_library.py`、`course_textbooks.py`、`knowledge_outline.py`、`task_outline.py`、`evidence_graph.py`：可复用的内部能力及控制边界。
- `nexus-app/alembic/versions/20261020_0119_major_profile_document_metadata.py`：专业简介投影退役。
- `nexus-api/nexus_api/permissions.py`、`auth.py`：当前认证与权限实现。
- `config/query_router_tools.json`、`nexus-app/nexus_app/retrieval/tools_registry.py`：内部工具注册表。

后续建议先完成两个口径修正及标准课程/教材/园区企业只读接口合同，再实施筛选与证据读取增强。涉及 API、权限审计、版本状态和检索的实现须分别提交对应 Review Gate。
