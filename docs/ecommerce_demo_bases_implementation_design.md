# 电子商务示范基地实施方案设计

> 日期：2026-10-30。状态：数据库迁移、完整源文件和幂等初始化已实现；接口和 Console 页面仍待实施。
> 本期目标：资产中心 → 市场数据 → 电子商务示范基地，包含国家、省级两个只读视图。
> 用户约束：数据持久化到数据库；后续检索查询数据库；不提供编辑、删除等操作。

## 1. 实施结论与边界

推荐采用 **JSON 初始化导入 → PostgreSQL 业务事实表 → 认证只读 API → Console 双视图**。
JSON 是初始化数据源，页面运行时不读取样例文件，也不请求商务部接口。
名称检索、条件筛选、分页、总数、批次统计和地区分布全部由数据库查询完成。

国家和省级记录共用 `ecommerce_parks`，以 `level` 区分；不混入现有
`industrial_park`。数据库存储来源事实，不因为在资产中心展示而自动获得
`available`、已治理、已索引等技术资产状态。

这是参照现有园区业务表、职业分类大典等边界提出的独立只读业务域。实施时须在
`ARCHITECT.md`、`SPEC.md` 中明确该边界：初始化不触发 Asset Pipeline，
不创建 asset/version/normalized ref，不调用 MinerU、LiteLLM 或向量索引。
若未来纳入资产治理，应另建遵循 `assetize → normalize → govern` 的任务；
原始 JSON 不得直接成为治理输入。

一期提供初始化命令、查询和展示；不提供页面新增、编辑、删除、批量管理、在线同步、
定时采集、交易指标、Excel 导出或基地详情正文抓取。初始化命令只插入来源记录，
重试不重复；已有来源键对应不同内容时报告冲突，不执行覆盖更新或删除。

## 2. 已核对的数据与官网展示

### 2.1 数据证据

实际文件位于 `docs/samples/`：

| 数据文件 | 实际内容 | 对实现的影响 |
| --- | --- | --- |
| `国家电子商务示范基地.json` | 30 个地区分组，展开后 170 条；首批 34、第二批 63、增补 73；`PATH` 和名称均未重复 | 可初始化地区分布与批次视图；数字来自数据库导入结果，不写死在组件中 |
| `省级电子商务示范基地.json` | 已按官网地区入口和分页接口补齐 6 个省级入口，共 142 条：江苏 79、山东 33、河南 9、湖北 18、广西 1、甘肃 2；每省的分页元数据保存在 `sourceProvinces` | 142 条是当前接口可见的完整记录集；各省 `sumPaper` 是来源声明值，数据库总数仍以实际导入行数为准 |

国家数据字段为 `TITLE`、`COUNTY`、`PROVINCE_CDE`、`VERSION`、`YEAR`、
`PATH`、`LABEL`、`XH`、`LOCATION`，外层另有 `provinceName`、`location`。
本次所有记录的 `COUNTY` 都是省级地区名称，不能据此生成市、区县或详细地址。
`YEAR` 存在前导空白，例如 ` 2020年9月`，需要做确定性的首尾空白清理。

单页省级接口记录只有 `TITLE`、`YEAR`、`PUBLISH_TIME`、`PATH`、`LABEL`、`NO`，
接口本身不在条目内返回省份。补齐脚本将请求时的已验证省份名称和代码以 `_PROVINCE_NAME`、
`_PROVINCE_CDE` 采集元数据写入样例，用于数据库分区和追溯；这不是从基地名称推断的字段。
省级数据仍不提供城市或批次字段。

国家样例中 `LABEL=true` 有 30 条，`false` 有 140 条；补齐后的省级 142 条均为 `true`。
不能用 `LABEL` 推断国家级/省级，也不能把字符串 `"false"` 按普通非空字符串转成 true。

### 2.2 官网可借鉴的交互

已读取 <https://dzswgf.mofcom.gov.cn/ecps/sfjd/index> 的 HTML 和内联脚本：

- 顶部国家/省级切换。
- 国家视图的“整体情况／首批／第二批／增补”。
- 国家基地总数与批次数量，以及按地区数量分布的柱状图。
- 中国地图上的地区入口；地区浮层显示序号、基地名称、批次、日期。
- 原站只为 `LABEL=true` 的记录提供名称链接。

NEXUS 保留以上信息结构，使用现有页面样式、ECharts 和表格组件。
源页面的政府站点页头、导航、页脚和三秒自动轮播不进入 Console。
官网脚本还写死了直辖市、省区、计划单列市的批次分类计数，但本次 JSON 不含完整分类证据，
因此本期只展示数据能够支撑的批次和省级地区分布。

`location/LOCATION` 是原网页像素定位 CSS，例如 `top: 300px; left: 734px`，
不是经纬度。仅归档于原始文件，不进入地理计算，也不作为可执行样式注入页面。

## 3. 页面与交互

### 3.1 入口和路由

在现有“市场数据”资源注册表中增加一项“电子商务示范基地”，建议放在产业园区之后。
不创建新的一级导航或市场数据汇总页。

```text
资产中心
  市场数据
    市场岗位
    产业园区
    电子商务示范基地
      [国家电子商务示范基地] [省级电子商务示范基地]
    企业数据
```

页面统一为 `/asset-center/market/ecommerce-demo-bases`：

- 默认 `?level=national`；省级使用 `?level=provincial`。
- 国家筛选示例：`?level=national&batch=second&province_code=320000&page=1&pageSize=20`。
- 筛选和分页写入 URL，可刷新、分享和浏览器返回；国家/省级切换时清理另一视图不适用条件。
- 提交检索、重置、批次或地区变更回到第 1 页，翻页保留已提交条件。
- 筛选栏位于列表顶部右侧，使用一个“检索”按钮，支持回车和窄窗口换行。

首页计数键为 `market/ecommerce-demo-bases`，复用现有
`GET /internal/v1/asset-center/counts` 的一次聚合请求。
计数是两级数据库记录数之和，本次初始化实际为 **312 条**（国家 170、省级 142），
表示名录记录数，不声称为跨级别去重后的物理基地数；不使用来源分页声明值累加。

### 3.2 国家电子商务示范基地

```text
电子商务示范基地
国家电子商务示范基地 | 省级电子商务示范基地

整体情况 | 首批 | 第二批 | 增补
当前条件匹配数量、批次数量（按已入库数据计算）

按地区数量分布柱状图
中国省级地区分布地图

基地名称 [         ]  地区 [全部]  认定年份 [全部]  检索  重置
序号 | 基地名称 | 地区 | 批次 | 认定年月 | 操作
分页
```

- 批次使用稳定代码 `first/second/supplement`，界面分别显示首批/第二批/增补。
- 柱状图与地图点击某地区后，更新 `province_code`，重新执行数据库查询；提供“全部地区”清除。
- 图表、匹配数和表格均使用同一组已提交条件，聚合发生在分页之前。
  选中地区后其他地区不再计入当前条件统计；所有数值明确标注为“当前条件”。
- 地图采用随应用部署的中国省级行政区静态 GeoJSON，通过行政区代码映射聚合结果。
  这是省级地区数量分布，不是基地精确地址或经纬度分布；不调用在线地图 API。
- 地图中没有样例记录的地区标注“当前数据未收录”，不能表达为现实中没有基地。
  图例区分未收录与已有地区在当前条件下匹配为零。
- 地图悬停显示地区和匹配数，点击后下方表格呈现该地区名录；表格也提供独立地区选择，
  图形加载失败时仍可检索和阅读名录。
- 表格列为展示序号、基地名称、地区、批次、认定年月、查看原文。
  `LABEL=false` 的名称为普通文本，原文操作不可用并提示“来源未开放链接”。
- 不新增基地介绍、联系人、运营企业等样例没有的字段。

图表客户端按需加载 ECharts，使用 `ResizeObserver` 适配容器，卸载时 dispose。
桌面展示完整图表；较窄窗口顺序堆叠，表格独立横向滚动，不新增移动端导航工程。
GeoJSON 在前端实现切片中选定、检查行政区代码与边界完整性，并随应用静态分发。

### 3.3 省级电子商务示范基地

采用分页列表，无地图与批次切换：

| 列 | 来源与展示 |
| --- | --- |
| 序号 | 当前检索结果的连续序号；源 `NO` 仅留作溯源，不能当全库主键 |
| 基地名称 | `TITLE`，完整名称可读 |
| 认定年月 | `YEAR`，例如 `2019年7月` |
| 来源发布时间 | `PUBLISH_TIME`，与认定年月分列 |
| 操作 | 查看原文，按来源链接标志控制 |

支持基地名称和认定年份检索，默认每页 20 条，可选 20/50/100。
初次导入后显示“当前已收录 142 条；已补齐当前官网提供的 6 个省级地区入口”。
来源说明可展开查看各省分页声明（江苏 79/4 页、山东 33/2 页等），不把来源声明值重复累计到列表总数。
省份筛选只使用补齐脚本记录的请求省份元数据；不提供城市、批次筛选，也不通过 LLM 补齐这些字段。

### 3.4 只读与异常状态

- 页面只有视图切换、检索、重置、分页、图表选择和查看原文。
- 不出现新增、编辑、删除、批量操作、导入、保存按钮或可编辑单元格。
- 加载中呈现骨架/加载状态；失败呈现错误、重试和 trace ID；失败不能显示成 0 条。
- 数据库尚未初始化时显示“暂无电子商务示范基地数据”；检索无结果显示“未找到匹配基地”。
- 来源原文在新标签打开，使用 `noopener noreferrer`。原文不可访问不影响已入库记录读取。
- 不展示“实时数据”“最新全国名录”等无法由离线样例证明的文案；本地导入时间不冒充源数据更新时间。

## 4. 数据持久化设计

### 4.1 业务事实表 `ecommerce_parks`

采用新表与 Alembic 结构迁移，不改造已有园区、企业、技术资产或治理结果表。
国家与省级同表，以下为待冻结字段契约：

| 字段 | 类型/约束 | 映射及含义 |
| --- | --- | --- |
| `id` | VARCHAR(36)，主键 | 遵循现有 UUID 字符串约定 |
| `level` | VARCHAR(16)，非空，CHECK | `national` / `provincial`，由导入文件类型确定 |
| `source_path` | TEXT，非空 | 规范化后的 `PATH`；只允许固定原站的 `/news/...html` 相对路径 |
| `title` | TEXT，非空 | `TITLE`，去首尾空白，保留原有名称 |
| `province_code` | VARCHAR(6)，可空 | 国家数据 `PROVINCE_CDE`；省级样例为空 |
| `province_name` | VARCHAR(128)，可空 | 国家数据外层 `provinceName`，与条目地区字段交叉校验 |
| `batch_code` | VARCHAR(16)，可空，CHECK | `VERSION` 映射到 `first/second/supplement`；省级为空 |
| `recognized_period` | VARCHAR(32)，非空 | 清理空白后的 `YEAR`，不补造具体日期 |
| `recognized_year` | SMALLINT，可空 | 从有效 `YYYY年M月` 确定性解析，用于年份筛选 |
| `recognized_month` | SMALLINT，可空，CHECK 1–12 | 与年份成对为空或有效；不存伪造的每月 1 日 |
| `source_publish_at` | TIMESTAMPTZ，可空 | 省级 `PUBLISH_TIME` 按 Asia/Shanghai 解析，再按统一时区存储 |
| `source_link_enabled` | BOOLEAN，非空 | 严格解析 `LABEL`，不代表级别、记录有效性或链接可用性验证结果 |
| `source_order` | INTEGER，非空 | 国家 `XH`、省级 `NO`；只作来源顺序 |
| `source_locator` | TEXT，非空 | 原始 JSON Pointer，如 `/0/datalist/0`、`/datalist/0` |
| `created_at` | TIMESTAMPTZ，非空 | 本地入库时间 |

唯一约束：`UNIQUE(level, source_path)`。名称不是唯一键；跨级同名不自动合并。
CHECK 约束限制枚举，并要求国家记录包含有效地区与批次，省级允许相应字段为空。
来源 URL 在返回时按 `https://dzswgf.mofcom.gov.cn` + `source_path` 派生，不另存重复列。
不新增 `current_version_id`、业务编辑状态或治理状态字段。

初始索引建议：`(level, province_code)`、`(level, batch_code)`、
`(level, recognized_year)`。名称以参数化 `ILIKE` 做字面包含匹配，
对用户输入的 `%`、`_` 做转义。当前 312 条不需要 Elasticsearch 或向量库；
名称查询的普通 B-tree 不能加速任意包含匹配，不以此声称性能收益。
数据规模增长后根据真实执行计划再评估 `pg_trgm`。

### 4.2 来源追踪

事实表直接保留 `source_payload`、`source_locator` 和来源路径，足以从数据库记录追溯到
完整 JSON 条目。初始化文件摘要只用于当前命令的日志和审计摘要，不建立额外的导入记录表。
成功导入按级别写入审计事件，审计目标指向已持久化的 `ecommerce_parks` 记录。

## 5. 初始化与幂等规则

新增 `nexus-app/scripts/import_ecommerce_demo_bases.py`，独立领域模块负责校验与写入。
命令支持明确的 `--national-file`、`--provincial-file` 和 `--apply`；默认 dry-run。
发布流程显式执行初始化，应用启动和页面请求不执行隐式写库。

```text
读取文件 → 校验整体结构、来源元数据与逐条字段 → 展平/确定性映射
  → dry-run：输出计划计数、覆盖说明、字段错误和冲突，不写数据库/对象存储
  → apply：原始文件留存 → 开启领域写入事务
      → 按 level + source_path 幂等插入/跳过
      → 写入导入凭证和审计 → 一起提交
```

- 每个文件一笔领域事务；必需字段错误、地区冲突、重复键内容不一致时整个文件不导入。
  两份文件分别报告结果，一个失败不得伪装成两级都已初始化成功。
- 国家地区使用 `provinceName` 和 `PROVINCE_CDE` 的经校验映射；`COUNTY` 仅交叉验证。
  省级保持地区为空，不推断。
- `YEAR`、`PUBLISH_TIME` 的含义分别为认定年月、来源发布时间，不能互相覆盖。
- `source_path` 先解析再校验，拒绝协议相对地址、站外地址、路径穿越和非预期页面路径。
  不提供任意 URL 拉取能力；文本按文本渲染，不作为 HTML 注入。
- 事务内使用数据库唯一约束和冲突安全插入。相同键且业务字段相同跳过；相同键内容不同
  报冲突，回滚该文件事务，不采用 upsert 更新。并发初始化同样遵循此规则。
- 无任何删除、缺失标记、清空重建或全量覆盖行为；后续接口页面变化不被自动解释为删除。
- 一次文件导入成功后，事实、凭证和成功审计可见；失败不留下部分业务记录。
  对象留存与数据库不能跨系统原子提交，使用内容摘要复用已上传文件，重试不重复上传；
  留存成功而业务导入失败的原始证据可保留，不计入页面统计。
- 新增审计事件建议为 `ECOMMERCE_DEMO_BASE_IMPORT_COMPLETED`，失败事件为
  `ECOMMERCE_DEMO_BASE_IMPORT_FAILED`；按现有枚举持久化方式评审后接入。
  审计只记操作者、文件摘要、计数、凭证 ID、安全错误码和 trace ID，不记录整份 JSON。

初始化工具是部署数据装载能力，不是用户编辑入口。业务 API、页面、Server Action
不暴露任何事实新增/修改/删除能力；后续来源修订不在本期范围内。

## 6. 数据库读取 API

新增查询路由位于 `nexus-api`，延续园区/企业的 Console 认证内部 API 风格。
复用父路由 `require_user`，不新增公开匿名路径。后续如果需要外部 Agent 消费，
应另行在 `nexus-api` 定义正式 `/v1` 或现有 `/open/v1` 适配，本期不开放。

| 方法与路径 | 功能 |
| --- | --- |
| `GET /internal/v1/ecommerce-demo-bases` | 数据库分页列表 |
| `GET /internal/v1/ecommerce-demo-bases/aggregate` | 当前条件下的总数、批次、地区聚合、筛选选项和来源覆盖说明 |
| `GET /internal/v1/asset-center/counts` | 既有接口增加 `market/ecommerce-demo-bases` 计数键 |

列表参数为 `level`（必填）、`q`（名称字面包含，最长 256 字符）、`batch`、
`province_code`、`recognized_year`、`page`、`pageSize`。
复用现有分页约束：默认 20，`pageSize` 最大 200；页面默认选项 20/50/100。
省级请求携带批次、地区条件时返回明确的 422，不静默忽略。
默认排序为国家地区代码、来源序号、ID；省级为来源序号、ID，确保分页顺序稳定。

列表遵循现有 `ListResponse`：`data` 为类型化记录数组，
`meta` 包含 `trace_id/page/page_size/total`。记录仅返回页面需要的业务字段和
派生的 `source_url`；原始 JSON、存储 URI、凭证操作人不下发。
`meta.total` 是所有条件过滤后的数据库 COUNT，先过滤再分页。

聚合遵循现有 `ApiResponse`，`data` 定义为：

```text
matched_total: number
batch_counts: [{ code, name, count }]
province_counts: [{ province_code, province_name, count }]
filter_options: { batches, provinces, recognized_years }
coverage: {
  imported_total,
  source_files: [{ filename, coverage_kind, source_row_count,
                   source_declared_total, source_declared_pages,
                   source_current_page, imported_at }]
}
```

`matched_total/batch_counts/province_counts` 共用列表查询条件并对全量匹配记录聚合，
不接收分页参数。`filter_options` 来自该 level 的已入库记录，独立于当前名称等筛选，
避免选中条件后其他可选项消失。`coverage` 是该级别导入来源的说明，不随检索条件改变；
其中 `imported_total` 来自该级别事实表 COUNT，不累计各次凭证的条数。
省级的批次、地区统计数组为空，不能生成无依据分组。

两个新接口只有 GET，无 POST/PATCH/PUT/DELETE，无导入接口或前端写入代理。
未认证请求返回既有 401；无权限遵循既有 403；参数错误为 422；服务异常沿用
错误封装与 trace ID，不能返回伪造空列表。公开参考数据按现有 Console 身份边界读取，
不为本次公开样例引入新组织范围或敏感级别体系。

查询服务采用参数化 SQLAlchemy 查询，列表和聚合共享筛选构造器；不在浏览器下载
全表后筛选或计数。列表与聚合为独立读取，初始化提交后刷新即见数据库结果。
页面不依赖运行环境是否保留 `docs/samples` 或能否连通商务部网站。

## 7. 工程落点与实施切片

当前工程已有资源注册表、catch-all 业务路由、园区表格、内部列表接口和首页聚合能力，
沿用这些入口增加分支，避免重写资产中心。

| 切片 | 建议范围 | 交付与验收 |
| --- | --- | --- |
| A：模型与初始化，约 1 天 | `nexus-app` 新领域模块、两张模型、结构迁移、初始化命令、相关测试 | 170+20 入库，重复不增、冲突不覆盖、失败回滚、原始留存及审计；Data Model、Permission And Audit Gate |
| B：只读接口，约 0.5–1 天 | `nexus-api` 类型化 Schema、新内部 router、路由注册、首页 counts、API 测试 | 数据库筛选/分页/聚合一致；拒绝写操作；API Contract Gate |
| C：双视图，约 1–1.5 天 | Console 资源注册、现有资源路由分支、国家图表/地图、只读列表、静态地图和测试 | 国家参考展示、省级列表、URL 状态、只读/加载/错误态；Frontend UX、Acceptance Gate |

各切片启动前再创建对应的小任务包，冻结文件所有权和字段映射。若实际工作超出 1.5 天，
继续拆分国家可视化与列表联调；本次设计采用单 Agent 调研，不创建并行 Agent 合同。

建议主要文件：

- `nexus-app/nexus_app/models.py` 与后续 Alembic revision，迁移编号以实施时链头为准。
- `nexus-app/nexus_app/reference_data/ecommerce_demo_bases.py`。
- `nexus-app/scripts/import_ecommerce_demo_bases.py`。
- `nexus-api/nexus_api/api/internal/ecommerce_demo_bases.py` 与 `internal/__init__.py`。
- `nexus-api/nexus_api/api/internal/asset_center.py`，扩展现有固定聚合查询，不加首页 N+1 请求。
- `nexus-console/lib/asset-center/catalog.ts`、`lib/api.ts`。
- `nexus-console/app/asset-center/[domain]/[[...resource]]/page.tsx`。
- 新组件 `EcommerceDemoBasesView`、`NationalDemoBaseDistribution`、`DemoBasesTable` 及对应测试。

实现前按 `nexus-console/AGENTS.md` 阅读实际安装 Next.js 的对应指南。
实施阶段同步更新 `ARCHITECT.md`、`SPEC.md`、`readme.md` 和 Prototype v2.2。
当前只新增方案与任务包，不把提案写成已上线能力。

仓库另有 `docs/ecommerce_big_data_implementation_plan.md` 初稿，涉及在线 Provider、
交易指标和三个视图。本次用户要求更小：两个本地 JSON、示范基地、数据库只读查询。
本设计以此次范围为准，不将旧稿的同步框架改动或交易数据并入任务，也不覆盖旧稿文件。

## 8. 验收与验证要求

1. **持久化**：迁移与 apply 后数据库有国家 170 条、省级 142 条、合计 312 条；
   重启 API/Console 并在运行镜像不携带样例文件时仍能查询；页面请求不读取样例或外站。
2. **幂等与只读**：重复初始化条数不变；内容冲突不能更新已有事实；失败文件无部分事实；
   API 无写路由，未认证无法读，事实 CRUD 操作无法通过 UI 或代理触发。
3. **统计**：国家全部 170、首批 34、第二批 63、增补 73；江苏全部 15；
   国家地区聚合之和等于当前匹配数；首页初始 312。
4. **省级覆盖**：分页总数为 142；六个省级入口的记录数为 79/33/9/18/1/2；
   各省 `sumPaper/sumPage` 仅为来源响应元数据，不重复计入数据库总数；省份来自请求元数据，
   不出现根据基地名猜出的省份。
5. **字段语义**：清理认定年月空白；发布时间与认定年月分列；严格解析字符串 false；
   CSS 不作经纬度，COUNTY 不当区县，源序号不作唯一键。
6. **查询**：名称、认定年份、国家地区与批次组合按数据库 AND 条件过滤；
   列表、聚合及分页前总数一致；特殊字符按字面匹配，分页顺序稳定。
7. **页面**：两个视图可切换并刷新恢复；筛选变更回第一页；地图/柱状图联动；
   没有增删改控件；图形失效仍可使用列表；失败不显示伪造零值。
8. **来源与审计**：事实可以由凭证、raw object 和 JSON Pointer 追溯到原始条目；
   链接固定原站且服从 LABEL；成功/失败初始化有可追踪的操作者与安全摘要。

实施验证建议：领域 importer/migration 测试；API 列表、聚合、认证和拒绝写方法的合同测试；
Vitest 资源注册与交互测试；Console typecheck、改动文件 lint、生产 build；
Playwright 桌面/平板验收与截图。命令以各切片的实际测试文件为准，不在设计阶段声称通过。

本次设计验证已完成：Python 标准库读取并统计两份 JSON，检查唯一来源路径、批次、
字段缺失和来源页元数据；读取官网 HTML/脚本确认展示结构；检查现有数据库模型、
资源路由、认证父路由、统一响应与分页约定。未逐条验证外链可用性，未运行应用实现测试。

实施合入前需完成 Data Model、API Contract、Permission And Audit、Frontend UX、
Acceptance Review Gates。本方案不修改现有资产版本状态、AI 治理或语义检索，
因此不触发这些模块的变更审批。
