# NEXUS Crawler 定向采集与实时联网检索设计 v1.0（初稿）

> **状态**：初稿，待架构 / API Contract / Security Review。
> **目标**：以定向、可验证的外部采集补足 NEXUS 冷启动期数字经济、电子商务及产业群相关的政策、报告与区域人才需求资产；同时提供用户主动开启的、仅当次有效的实时联网检索。
> **非目标**：不将联网检索作为 `unknown`、`scenario_2` 或 `scenario_3` 的降级；不建设任意站点、无限深度的通用爬虫；不以实时 WebSearch 内容直接写入治理或索引。

---

## 1. 结论与原则

本设计包含两条彼此独立的链路：

1. **定期定向采集链路**：Firecrawl Connector 采集的文档和未来合规数据供应商 Connector 提供的结构化数据，必须经过 NEXUS 原始留存、标准化、治理、版本和索引，才成为可检索资产。
2. **实时联网检索链路**：仅当 `scenario_1`（产业/行业报告）或 `scenario_4`（教材/通用知识）没有可用的本地 NEXUS 资产证据时，Query Router 自动调用当前配置的 WebSearch Provider。结果仅属于当前请求，且不留存、不治理、不索引。

两条链路不得互相自动转换：实时 WebSearch 返回的 URL 或正文不自动进入采集候选或资产管道；定期采集作业也不依赖任意用户检索触发。

核心原则：

- 联网发现不等于 NEXUS 事实；只有通过资产管道的内容可以作为 NEXUS 已治理证据。
- 采集范围由版本化的来源注册表、专题采集计划和查询模板决定，不由 LLM 自由生成互联网查询。
- `pipeline_type` 在 Connector / ingest gateway 创建 Job 时显式决定并冻结在 `Job.payload.pipeline_type`；Worker 不做路由推断。
- 采集 Connector 的来源、许可、抓取规则和内容质量必须可追溯。
- 合规数据供应商 Connector 在本设计中仅定义抽象入口与入站契约；不实现任何具体供应商适配器、认证或数据拉取逻辑。
- WebSearch 由符合条件的无本地证据请求自动触发；不设置
  `external_search` 专属权限门禁，已认证的 Console 用户和 API caller 都可使用。
- 即使不做专属权限限制，敏感查询外发阻断、供应商额度、速率、超时、审计和安全防护仍是强制约束。

---

## 2. 总体架构

```text
                  source_registry（来源注册表）
                              |
                  collection_plan（专题采集计划）
                              |
             +----------------+----------------+
             |                                 |
             v                                 v
 Firecrawl Connector              Structured Provider Connector (abstract)
 Markdown / HTML / PDF            future API / JSON / CSV / XLSX
             |                                 |
 pipeline_type=document              pipeline_type=record
             |                                 |
             v                                 v
        Pipeline A                        Pipeline B
 raw -> parse -> normalized_document    raw -> normalize -> normalized_record
             \                                 /
              \                               /
               -> governance -> available/review_required -> index
                                      |
                              本地 NEXUS 检索 / QA


 用户检索请求
      |
      +--> 本地 NEXUS 检索（始终执行）
      |
      +--> scenario_1 / scenario_4 且本地无有效证据
              |
              v
          WebSearch Provider -> external_web_results（仅当前响应）
```

NEXUS 负责资产、原始内容、治理、索引、权限和审计。Connector 负责按批准计划采集外部内容。NEXUS 不承担一个可随意访问任何网站的常驻通用网络爬虫。

---

## 3. 定期定向采集链路

### 3.1 本阶段范围与主题口径

本阶段只覆盖数字经济、电子商务及其产业群相关的公开文档和区域人才需求数据。地域能力覆盖**中国大陆 31 个省级行政区**（省、自治区、直辖市），并支持按省级行政区下钻至地市、区县、园区等范围；采集计划可以选择全国、一个省级行政区或多个省级行政区，不能把浙江省固化为平台默认范围。NEXUS 本阶段不要求建设行政区字典或将抽取结果映射为统一行政区代码，而是保留从内容中提取的地域范围文本及其证据。采集范围如下：

| 治理分类 code | 本阶段纳入内容 | 优先来源 |
| --- | --- | --- |
| `industry_policy` | 产业政策；职业教育政策；产教融合、校企合作、产业学院、实训基地相关政策；专项规划、实施意见、行动计划、通知 | 国家/省/市县教育、人社、发改、工信、商务及其他主管部门与政府门户 |
| `industry_report` | 产业报告；职业教育行业报告；区域经济、产业集群、园区、数字经济与电子商务发展报告；白皮书、统计公报 | 统计部门、政府公开报告、获授权协会/研究机构 |
| `talent_demand_report` | 区域数字经济/电子商务人才需求报告、就业需求和岗位需求统计、人才需求调研报告 | 公共就业/统计部门、学校公开调研报告与已授权数据源 |

职业教育、产教融合、区域经济、产业集群、园区、数字经济和电子商务均是上述三种既有治理分类下的主题、标签和检索维度，**不得新增分类 code**。“产业群”也不是资产类别；它用于表达数字经济产业群、电子商务产业群、跨境电商产业群等主题标签。分类必须复用现有 `governance_rules_v2.json` 的 `industry_policy`、`industry_report`、`talent_demand_report`，而不是由 Firecrawl 或 LLM 临时定义新 code。

本阶段不采集泛商业资讯、未验证转载、营销软文、论坛/博客内容，也不以网页抓取方式获得未经授权的招聘明细。区域人才需求的正式数据可来自公开报告；高频岗位明细仍只预留未来合规结构化供应商 Connector 抽象入口。

### 3.2 来源注册表 `source_registry`

来源注册表是可选的**高置信来源白名单**，用于优先、约束并提升已登记可信来源的采集效率；它不是搜索的必填名单，可以为空。存在白名单条目时，Firecrawl Search 使用其域名构造 `includeDomains`；为空时可进行受控候选发现。未预注册来源只要能够验证为官方统计、政府公开报告或具有明确授权的协会/研究机构，并通过来源、授权、内容、地域和时间质量阈值，即可进入 NEXUS 治理链路；证据不足或未达阈值的候选才进入 `review_required`。被明确禁用、授权失效或违反采集策略的来源仍不得抓取或导入。

建议字段：

| 字段 | 说明 |
| --- | --- |
| `id` / `code` | 稳定标识，例如 `zhejiang_government_portal` |
| `source_kind` | `official_site` / `statistics_agency` / `licensed_provider` / `industry_association` |
| `base_domains` | 精确允许的主域名与子域策略 |
| `allowed_classification_codes` | 可选；只能填写 `industry_policy`、`industry_report`、`talent_demand_report` |
| `authority_tier` | `official_national` / `official_provincial` / `licensed_commercial` 等 |
| `license_basis` | 授权、开放数据或使用条款依据；岗位数据必须非空 |
| `connector_kind` | `firecrawl_document` / `licensed_structured_provider` |
| `allowed_content_types` | 允许的 MIME 白名单 |
| `crawl_rate_policy` | 同域并发、QPS、页数、正文大小上限 |
| `enabled` / `expires_at` | 可用状态与定期复核时间 |
| `version` | 配置版本，写入所有采集证据 |

来源等级要求：

- 产业/职业教育/产教融合政策：仅官方站点可自动进入后续治理；转载、媒体和聚合页拒绝自动采集。
- 产业、职业教育行业和区域经济报告：官方统计、政府公开报告、具有明确授权的协会或研究机构可进入候选；无发布机构、付费墙绕过、版权不明内容拒绝。
- 区域数字经济、电子商务人才需求报告：优先公共就业、统计和已签约数据源。
- 岗位明细：只接受已授权 API、批量文件或合作数据供应商；不能以 Firecrawl 抓取普通招聘网页替代数据授权。

### 3.3 专题采集计划 `collection_plan`

采集计划约束主题、地域、来源、频率、查询模板和质量门。计划由管理员创建、版本化和审计；不是自由输入的一次性网页搜索。

以下仅为“浙江省电子商务与数字经济”专题计划示例；其他省级行政区使用同一契约，以各自的地域范围、来源注册表和查询变量创建计划：

```yaml
plan_code: zj_ecommerce_digital_economy_2026
name: 浙江省电子商务与数字经济产业及人才需求采集
scope:
  region_scope:
    level: province
    names: [浙江省] # 示例值；不要求行政区代码映射
  industries: [数字经济, 电子商务]
  industry_clusters: [数字经济产业群, 电子商务产业群]
  classification_codes:
    - industry_policy
    - industry_report
    - talent_demand_report
source_registry_codes:
  - zhejiang_government_portal
  - zhejiang_statistics
  - zhejiang_industry_authority
# 可为空；为空时仍可由质量门核验高置信来源后进入治理链路
refresh:
  industry_policy: weekly
  industry_report: monthly
  talent_demand_report: weekly
time_effectiveness:
  industry_policy:
    preferred_within_years: 5
    basis: [effective_period, published_at]
  industry_report:
    preferred_within_years: 2
    basis: [statistical_period, published_at]
  talent_demand_report:
    preferred_within_years: 2
    basis: [statistical_period, published_at]
quality:
  min_authority_score: 0.85
  min_relevance_score: 0.80
  min_completeness_score: 0.75
  require_canonical_url: true
  require_publish_date_for_policy_and_report: true
```

查询模板独立版本化，只允许变量替换：

```text
{region} ({industry_1} OR {industry_2}) (政策 OR 通知 OR 实施意见 OR 行动计划 OR 专项规划)
{region} ({industry_1} OR {industry_2}) (发展报告 OR 白皮书 OR 统计公报 OR 运行情况)
{region} ({industry_1} OR {industry_2}) (人才需求 OR 就业需求 OR 招聘需求 OR 人才报告)
{region} ({industry_1} OR {industry_2}) (职业教育 OR 产教融合 OR 校企合作 OR 产业学院)
{region} ({industry_1} OR {industry_2}) (产业集群 OR 产业群 OR 园区 OR 区域经济)
```

`{region}` 是采集计划的地域范围变量，运行时可替换为全国、任一省级行政区或计划批准的多个省级行政区名称。来源注册表非空时，实际执行叠加其域名范围；为空时，由候选来源策略和质量门决定是否继续抓取与进入治理。`site:` 只是辅助限定，不能替代对结果 URL 的精确域名校验。

### 3.4 Firecrawl Document Connector：文档采集进入 Pipeline A

Firecrawl Connector 使用 Firecrawl v2 的官方能力，但 NEXUS 只开放来源注册表和采集计划允许的组合。官方文档： [Search](https://docs.firecrawl.dev/api-reference/endpoint/search)、[Batch Scrape](https://docs.firecrawl.dev/api-reference/endpoint/batch-scrape)、[Crawl](https://docs.firecrawl.dev/api-reference/endpoint/crawl-post)、[Document Parsing](https://docs.firecrawl.dev/features/document-parsing)。

采集器按以下受控模式运行：

| Firecrawl 能力 | NEXUS 使用方式 | 禁止或限制 |
| --- | --- | --- |
| `POST /v2/search` | 只用于候选 URL 发现；搜索地域/语言默认中国大陆中文环境：`country=CN`，并在 `scrapeOptions.location` 中使用 `languages=["zh-CN"]`；白名单非空时传 `includeDomains`，同时传 `location`、`tbs` 和必要时 PDF 类别。搜索阶段不请求完整正文。 | 白名单为空时可不传 `includeDomains`，但结果必须经过来源、授权、内容、地域和时间质量门；不把 `site:` 当作唯一域名控制；不以搜索摘要直接入库。 |
| `POST /v2/batch/scrape` | 对候选质量门通过的 URL 批量抓取；使用 `maxConcurrency`、完成/失败/页面 webhook 以及自定义 metadata 关联 NEXUS 采集任务。 | 不突破已登记白名单或候选来源策略允许的域名、URL 数量和并发上限。 |
| `POST /v2/scrape` | 仅用于单 URL 补抓、重试或小批量人工批准任务。 | 不作为循环发现链接的爬行器。 |
| `POST /v2/crawl` | 仅用于已批准官方站点的固定栏目或 sitemap 目录增量发现。必须设置 `includePaths`、`excludePaths`、小 `limit`、有限 `maxDiscoveryDepth`，且 `allowExternalLinks=false`、`allowSubdomains=false`。 | 禁止 `crawlEntireDomain=true` 的无边界站点全爬；禁止忽略 robots.txt。 |

Firecrawl Search 支持 `includeDomains`，并支持位置、国家、时间范围与 PDF 类别过滤。NEXUS 默认使用 `country=CN` 和中文语言环境；必须优先使用这些结构化约束，而不是仅在 query 文本拼接 `site:`。任一省级专题都以计划的地域变量构造地域约束和查询模板。`source_registry.base_domains` 非空时提供预先登记的高置信域名约束；为空时由后续质量门核验发布机构、公开性/授权、原文链接、内容、地域和时间，核验通过后同样可以进入治理链路。

候选质量门通过后，Connector 向 Batch Scrape 仅请求 NEXUS 需要的 `markdown`、必要元数据和结构信息；默认使用 `onlyMainContent=true`，不请求 screenshot、audio、video 等临时签名 URL。页面抓取任务使用 Firecrawl 返回的任务 ID 建立 NEXUS 外部任务映射；处理 `started`、`page`、`completed`、`failed` webhook 时按 `(provider, provider_job_id, page_final_url)` 幂等，webhook 重放不得产生重复 raw object 或重复资产版本。

对于官方文档格式，Firecrawl 可通过 URL `/v2/scrape` 解析 PDF、Word 和 Excel 为 Markdown；PDF 支持 `auto`、`fast`、`ocr` 模式。NEXUS 将其用于正文提取和采集质量检查，但不把 Firecrawl Markdown 直接视为原件：

1. 原 URL 可按来源策略和授权允许时，由 Connector 独立下载原始 PDF/Office 文件并持久化为 `raw_object`，进入 MinerU Document Pipeline。
2. 无法合法取得二进制原件时，将 Firecrawl 返回的 Markdown 与完整采集证据封装为文档型原始快照，标记 `raw_representation=firecrawl_markdown_snapshot`；不伪称其为原始 PDF。
3. PDF 返回的 `numPages` / `totalPages` 显示截断时，候选质量门拒绝自动入库或进入 `review_required`，不将不完整正文索引为完整报告。

候选 URL 进入抓取前必须通过：精确域名、协议（HTTPS）、内容类型、最大深度、最大页面数、同域限速和 robots/授权策略校验。禁止页面内 URL 无限跟随，默认抓取深度为 `0`，经计划批准最多为 `1`。

Firecrawl 输出的采集对象必须包含：

```json
{
  "connector_type": "firecrawl_document",
  "content_kind": "web_document",
  "pipeline_type": "document",
  "source_url": "https://approved.example.gov.cn/...",
  "canonical_url": "https://approved.example.gov.cn/...",
  "publisher": "发布机构",
  "published_at": "2026-02-18",
  "retrieved_at": "2026-07-17T10:00:00Z",
  "content_hash": "sha256:...",
  "raw_representation": "original_binary|firecrawl_markdown_snapshot",
  "firecrawl_job_id": "...",
  "firecrawl_page_id": "...",
  "collection_plan_code": "zj_ecommerce_digital_economy_2026",
  "source_registry_version": "v1",
  "crawler_rule_version": "v1",
  "query_template_version": "v1"
}
```

原 URL、规范 URL、Firecrawl source/final URL、HTTP 状态、抓取时间、内容 hash、Firecrawl Job ID、计划和规则版本写入 `raw_object.metadata_summary`、`normalized_asset_ref.lineage` 和审计摘要的最小必要字段。Document Pipeline 形成 `normalized_document` 后才进入治理。

### 3.5 合规数据供应商 Connector：Pipeline B 的抽象扩展入口

该 Connector 是面向岗位招聘明细、区域人才需求指标和其他已授权结构化数据的**抽象扩展入口**。本期不实现任何供应商 SDK、HTTP API、认证、轮询或数据拉取逻辑，也不预设具体供应商。未来任一合规供应商适配器都必须实现同一 Connector 协议并输出 JSON、CSV 或 XLSX；它不使用 Firecrawl 作为结构化数据主通道。

抽象协议至少应声明：

| 能力 | 契约 |
| --- | --- |
| `connector_kind` | 固定为已注册的供应商 Connector 类型，不能由调用方任意填写 |
| `capabilities` | 支持的资产类别、MIME、地域、增量方式和覆盖期粒度 |
| `validate_source` | 校验供应商注册、授权状态和适用的数据类别 |
| `fetch` | 未来实现的受控拉取入口；本期只保留接口，不发起网络调用 |
| `build_ingest_envelope` | 将有效数据转换为带来源/授权/覆盖期证据的标准入站对象 |
| `health` | 未来供应商连接健康检查入口；本期不产品化运维面板 |

所有未来实现必须输出如下标准入站声明：

```json
{
  "connector_type": "licensed_structured_provider",
  "content_kind": "structured_record",
  "pipeline_type": "record",
  "dataset_type": "job_demand_dataset.v1",
  "source_license_id": "license-...",
  "coverage_region": {
    "name": "浙江省",
    "level": "province"
  },
  "coverage_period": "2026-01-01/2026-03-31",
  "collection_plan_code": "zj_ecommerce_digital_economy_2026"
}
```

上例的浙江省仅为专题示例；正式数据必须保留全国/省级/地市/区县/园区等原始地域范围文本及对应来源证据，不要求映射为 NEXUS 行政区代码。符合该协议的未来供应商数据进入 Pipeline B，形成 `normalized_record` 和岗位需求领域表。必须保留来源平台、记录 ID、原链接、发布时间、覆盖期、地域、字段字典版本和授权依据。缺少授权依据的岗位明细不得自动入库。

### 3.6 显式 Pipeline 路由契约

当前 `crawler` 被固定路由到 Pipeline B；本设计需要替换为 Connector 允许类型驱动的、创建 Job 时冻结的路由契约：

| 已批准 Connector | `content_kind` | MIME 白名单 | `pipeline_type` | 标准化产物 |
| --- | --- | --- | --- | --- |
| `firecrawl_document` | `web_document` | `application/pdf`、`text/html`、`text/markdown`、允许的 Office MIME | `document` | `normalized_document` |
| future `structured_provider` adapter | `structured_record` | `application/json`、`text/csv`、XLSX MIME | `record` | `normalized_record` |
| 既有 crawler package | `structured_record` | `application/json` | `record` | `normalized_record` |
| 不匹配 | 任意 | 任意 | 拒绝创建 Job | `failed` |

`pipeline_type` 不能由请求调用方任意指定。ingest gateway 从已批准 Connector 配置、`content_kind` 和 MIME 白名单推导一次，写入 `Job.payload.pipeline_type`。这是一项架构与 API 契约调整，需要 Data Model / API Contract / Semantic Retrieval Integration Review 后实施。

### 3.7 候选质量门、治理维度与去重

采集结果在进入 ingest 前执行候选质量门：

| 维度 | 最低要求 |
| --- | --- |
| 来源权威性 | 来源注册表非空且命中时按高置信来源处理；注册表为空或候选未命中时仍可发现，发布机构、原文链接、授权/条款和来源等级必须完整核验。官方统计、政府公开报告、具有明确授权的协会/研究机构通过质量阈值后可进入治理链路；证据不足或未达阈值才进入 `review_required` |
| 治理分类 | 仅允许 `industry_policy`、`industry_report`、`talent_demand_report`；职业教育、产教融合、区域经济、产业群等通过主题/标签表达，不新增分类 code |
| 产业/行业领域 | 数字经济、电子商务及产业群等主题/标签须有标题或正文证据 |
| 地域范围 | 提取国家/省/市/区县/园区等范围文本及 locator/evidence；至少一个可验证地域证据，且必须与采集计划批准的全国/省级范围相容；本阶段不要求行政区代码映射 |
| 时间因素 | 区分 `published_at`、政策 `effective_period`、报告/人才数据 `statistical_period`；按资产类别执行不同有效性窗口 |
| 主题相关性 | 资产类别、产业/行业、地域和时间因素在标题、元数据或正文证据中可验证 |
| 内容完整性 | 非登录页、非验证码页、非空壳页，正文大小和结构达标 |
| 合规性 | 授权/条款允许，岗位数据有授权依据 |
| 去重 | `canonical_url + published_at + content_hash`；跨来源相同正文只保留权威原始来源 |

时间有效性采用以下默认策略，并作为可版本化的采集计划质量门而不是永久数据删除规则：

| 资产类别 | 默认高有效性窗口 | 时间判定优先级 | 超窗处理 |
| --- | --- | --- | --- |
| `industry_policy` | 5 年内 | `effective_period`，其次 `published_at` | 已明确失效、废止或被替代则拒绝；超过 5 年但状态无法判定时降低质量并进入 `review_required`，不自动入库 |
| `industry_report` | 2 年内 | `statistical_period`，其次 `published_at` | 超过 2 年降低时效质量，不自动入库；允许人工确认其仍具有基准/历史参考价值 |
| `talent_demand_report` | 2 年内 | `statistical_period`，其次 `published_at` | 超过 2 年默认不自动入库；只能作为经人工确认的历史趋势参考 |

标准化和治理阶段必须把下列指标写入 `normalized_asset_ref` 的标准字段或其 `governance` / `quality` / `lineage` 子字段，并对关键值保存 locator/evidence：`classification_code`（仅上述三种既有 code）、`industry_domains`、`industry_clusters`、`region_scope`（地域范围文本）、`published_at`、`effective_period`、`statistical_period`、`time_effectiveness_status`、`source_authority_tier`、`collection_plan_code`。AI 建议只能在 schema、既有分类/标签白名单、证据、置信度和规则校验通过后采纳；无法确认产业/行业、地域或时间时进入 `review_required`。

满足高阈值的对象进入 ingest；信息不足、主题冲突、来源不明、产业/地域/时间证据不足或正文截断的对象进入人工复核候选，不创建正式资产；不合规或明显无关对象丢弃，并保留最小审计原因。

同一来源内容发生变更时，以稳定 `source_object_key` 关联到同一资产，创建新 `asset_version`；绝不通过新增反向指针表达当前版本。

---

## 4. 实时 AI WebSearch 链路

### 4.1 用户与 API 行为

Query Router 的内外入口不接受用户强制 WebSearch 的选项。本地 NEXUS 检索始终先执行；只有 `scenario_1` 或 `scenario_4` 的成功本地检索没有可用 chunk/上下文证据时，才自动调用 WebSearch。`scenario_2`（结构化岗位/能力/布点）、`scenario_3`（专业信息/图谱）、`scenario_5` 和 `unknown` 永不调用该 Provider。

当前默认 Provider 是 Firecrawl Search，配置使用既有 `FIRECRAWL_API_ENDPOINT` 与 `FIRECRAWL_API_KEY`；通过 `AI_WEB_SEARCH_PROVIDER` 选择适配器，后续供应商必须实现相同的 request-scoped `AIWebSearchClient` 契约。NEXUS 不提供 `web_only`，也不把外部结果改写为本地召回结果。

### 4.2 返回模型与展示

响应中将本地和外部结果严格分区：

```json
{
  "local_results": {
    "source_refs": [],
    "markdown": "基于 NEXUS 已治理资产的结论"
  },
  "external_web_results": [
    {
      "source_type": "external_web",
      "provider": "ai_web_search",
      "title": "公开网页标题",
      "url": "https://...",
      "domain": "example.gov.cn",
      "snippet": "公开搜索摘要",
      "published_at": "2026-...",
      "retrieved_at": "2026-07-17T10:00:00Z",
      "rank": 1
    }
  ],
  "warnings": [
    "external_web_results_are_not_governed_nexus_assets"
  ]
}
```

前端展示为“**NEXUS 已治理资料**”和“**公开网络实时结果**”两个分区。外部区必须展示来源域名、URL、检索时间和“未纳入 NEXUS 治理与验证”标识。外部结果不得分配 `normalized_ref_id`、`knowledge_chunk_id`、`asset_id` 或虚构的 NEXUS citation。

### 4.3 非留存边界

`external_web_results` 只存在于处理本次请求的内存上下文和响应体。不得创建、更新或写入：

- `raw_object`、`ingest_batch`、`job`
- `asset`、`asset_version`
- `normalized_document`、`normalized_record`、`normalized_asset_ref`
- `governance_result`、`knowledge_chunk`、`index_manifest`
- 跨请求结果缓存、学习样本或 Prompt 数据集

若 Composer 对外部结果生成摘要，必须逐条以外部 URL 引用，标记为“公开网络实时信息”，不得声称其已经被 NEXUS 治理、验证或收录。

### 4.4 安全、隐私和故障处理

不设置专属访问权限不等于无安全控制。强制要求：

- 发送前对 query 执行敏感数据检测；L3/L4、个人信息、内部项目标识、API key、令牌、文件路径和客户敏感信息命中时，阻断外发并返回明确 warning。
- 只向 WebSearch Provider 发送经过策略处理后的 query；不发送会话历史、内部检索正文、内部资产元数据、用户身份或权限信息。
- 外部页面/摘要是非可信输入；禁止由其触发新的工具调用、文件下载、二次网页抓取或改变系统指令。
- 限制单次结果数、响应大小、总超时、并发、供应商调用成本；供应商 429/5xx/超时时不影响本地检索结果。
- Provider 未配置、失败、429/5xx 或超时时，返回 `external_search_unavailable` warning 和正常本地结果。
- 审计只记录 `query_hash`、`online_search_requested`、`provider`、结果数、域名列表、延迟、错误类型和 trace ID；不记录外部正文、完整摘要或敏感原 query。

---

## 5. 配置、作业和审计

定期采集使用 PostgreSQL Job 表和既有 Worker 轮询机制；不将 RabbitMQ、Celery 或一个独立常驻调度平台作为前置依赖。外部 Connector 可以由已有 crawler 系统按计划执行并调用 scan-task / ingest 接口，NEXUS 接收已验证的对象并运行既有资产管道。

建议新增的审计事件或审计摘要字段：

| 范围 | 字段 |
| --- | --- |
| 采集计划 | `collection_plan_id`、`collection_plan_version`、`source_registry_id`、`source_registry_version` |
| 抓取执行 | `connector_kind`、`crawler_rule_version`、`query_template_version`、`canonical_url_hash`、`content_hash`、`retrieved_at` |
| 质量门 | `authority_score`、`relevance_score`、`completeness_score`、`candidate_decision`、`rejection_reason_code` |
| 实时检索 | `online_search_requested`、`web_search_provider`、`external_result_count`、`external_result_domains`、`external_search_latency_ms`、`external_search_error_type` |

所有 mutation，包括来源注册表、采集计划、查询模板、Connector 配置的创建/更新/禁用和人工复核，必须审计。API key、供应商密钥、完整网页正文和敏感 query 不得写日志或审计摘要。

---

## 6. 实施切片与验收

本初稿只冻结目标架构和契约方向，不包含实现。建议后续拆分为以下 0.5-1.5 天任务包：

1. 来源注册表与专题采集计划数据模型、审计和 Console 管理契约。
2. Firecrawl Document Connector 与 `crawler -> document` 明确路由契约。
3. 合规结构化供应商 Connector 抽象协议、能力声明与标准入站契约；不实现具体供应商。
4. 候选质量门、去重和人工复核队列。
5. Query Router `online_search` API 契约与 AI WebSearch Adapter。
6. Console 联网搜索开关、结果分区、错误和隐私提示。

关键验收：

- Firecrawl 抓取的 PDF 能以 `pipeline_type=document` 进入 Pipeline A，生成带来源血缘的 `normalized_document` 并在治理通过后索引。
- 未来合规 JSON 岗位数据能依照抽象协议以 `pipeline_type=record` 进入 Pipeline B，保留数据来源、授权、时间和地域证据。
- 未注册域名、来源等级不足、内容不完整或不合规的对象不得创建正式资产。
- 同一规范 URL 内容更新产生新版本；相同正文的跨来源重复可追溯且不重复索引。
- 只有 `scenario_1` / `scenario_4` 本地无有效证据时允许外部请求；其余场景、`unknown`、本地有证据和敏感 query 均不得发起外部请求。
- 实时外部结果在请求结束后不落库、不入治理、不入索引、不进入跨请求缓存。
- 敏感 query 被阻断外发；Provider 故障不影响本地检索。

---

## 7. 需经评审确认的变更

实施前需完成：

- **Architecture Review**：将 crawler 固定 record 路由改为 Connector 声明、ingest-time frozen 的 document/record 路由。
- **API Contract Review**：定义文档型 crawler ingress、`online_search` 请求选项和 `external_web_results` 响应模型。
- **Data Model Gate**：确认来源注册表、采集计划、候选记录的单向关系、版本和审计字段。
- **Permission And Audit Gate**：确认“无 `external_search` 专属权限限制”与现有基础认证、敏感外发拦截、审计和供应商保护策略共同成立。
- **Semantic Retrieval Integration Gate**：确认只有治理通过的采集资产进入索引，实时外部结果永不进入索引。
