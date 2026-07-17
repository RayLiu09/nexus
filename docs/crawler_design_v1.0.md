# NEXUS Crawler 定向采集与实时联网检索设计 v1.0（初稿）

> **状态**：初稿，待架构 / API Contract / Security Review。
> **目标**：以定向、可验证的外部采集补足 NEXUS 冷启动期的产业政策、行业报告与区域人才需求资产；同时提供用户主动开启的、仅当次有效的实时联网检索。
> **非目标**：不将联网检索作为 `unknown` 或本地未命中的默认降级；不建设任意站点、无限深度的通用爬虫；不以实时 WebSearch 内容直接写入治理或索引。

---

## 1. 结论与原则

本设计包含两条彼此独立的链路：

1. **定期定向采集链路**：Firecrawl Connector 采集的文档和未来合规数据供应商 Connector 提供的结构化数据，必须经过 NEXUS 原始留存、标准化、治理、版本和索引，才成为可检索资产。
2. **实时联网检索链路**：用户在检索请求中显式选择 `online_search=true` 后，AI WebSearch 仅返回当前请求的公开网络结果；结果不留存、不治理、不索引。

两条链路不得互相自动转换：实时 WebSearch 返回的 URL 或正文不自动进入采集候选或资产管道；定期采集作业也不依赖任意用户检索触发。

核心原则：

- 联网发现不等于 NEXUS 事实；只有通过资产管道的内容可以作为 NEXUS 已治理证据。
- 采集范围由版本化的来源注册表、专题采集计划和查询模板决定，不由 LLM 自由生成互联网查询。
- `pipeline_type` 在 Connector / ingest gateway 创建 Job 时显式决定并冻结在 `Job.payload.pipeline_type`；Worker 不做路由推断。
- 采集 Connector 的来源、许可、抓取规则和内容质量必须可追溯。
- 合规数据供应商 Connector 在本设计中仅定义抽象入口与入站契约；不实现任何具体供应商适配器、认证或数据拉取逻辑。
- `online_search` 默认关闭；开启后不设置 `external_search` 专属权限门禁，已认证的 Console 用户和 API caller 都可使用。
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
      +--> options.online_search=true
              |
              v
          AI WebSearch -> external_web_results（仅当前响应）
```

NEXUS 负责资产、原始内容、治理、索引、权限和审计。Connector 负责按批准计划采集外部内容。NEXUS 不承担一个可随意访问任何网站的常驻通用网络爬虫。

---

## 3. 定期定向采集链路

### 3.1 来源注册表 `source_registry`

来源注册表是采集可靠性和合规性的唯一入口。未注册域名、未登记供应商、过期授权或被禁用来源不得进入抓取或导入。

建议字段：

| 字段 | 说明 |
| --- | --- |
| `id` / `code` | 稳定标识，例如 `zhejiang_government_portal` |
| `source_kind` | `official_site` / `statistics_agency` / `licensed_provider` / `industry_association` |
| `base_domains` | 精确允许的主域名与子域策略 |
| `allowed_asset_classes` | `industry_policy` / `industry_report` / `regional_talent_demand` / `job_demand_dataset` |
| `authority_tier` | `official_national` / `official_provincial` / `licensed_commercial` 等 |
| `license_basis` | 授权、开放数据或使用条款依据；岗位数据必须非空 |
| `connector_kind` | `firecrawl_document` / `licensed_structured_provider` |
| `allowed_content_types` | 允许的 MIME 白名单 |
| `crawl_rate_policy` | 同域并发、QPS、页数、正文大小上限 |
| `enabled` / `expires_at` | 可用状态与定期复核时间 |
| `version` | 配置版本，写入所有采集证据 |

来源等级要求：

- 产业政策：仅官方站点可自动进入后续治理；转载、媒体和聚合页仅允许作为人工线索，不自动采集。
- 行业报告：官方统计、政府公开报告、具有明确授权的协会或研究机构可进入候选；无发布机构、付费墙绕过、版权不明内容拒绝。
- 区域人才需求报告：优先公共就业、统计和已签约数据源。
- 岗位明细：只接受已授权 API、批量文件或合作数据供应商；不能以 Firecrawl 抓取普通招聘网页替代数据授权。

### 3.2 专题采集计划 `collection_plan`

采集计划约束主题、地域、来源、频率、查询模板和质量门。计划由管理员创建、版本化和审计；不是自由输入的一次性网页搜索。

浙江省电子商务与数字经济示例：

```yaml
plan_code: zj_ecommerce_digital_economy_2026
name: 浙江省电子商务与数字经济产业及人才需求采集
scope:
  region: 浙江省
  industries: [电子商务, 数字经济]
  asset_classes: [industry_policy, industry_report, regional_talent_demand]
source_registry_codes:
  - zhejiang_government_portal
  - zhejiang_statistics
  - zhejiang_industry_authority
  - approved_talent_data_provider
refresh:
  industry_policy: weekly
  industry_report: monthly
  regional_talent_demand: weekly
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
```

实际执行必须叠加来源注册表的域名范围。`site:` 只是辅助限定，不能替代对结果 URL 的精确域名校验。

### 3.3 Firecrawl Connector：文档采集进入 Pipeline A

Firecrawl 的职责是对已批准来源做两阶段定向采集：

1. **Search**：基于采集计划和查询模板发现候选 URL，只保存候选元信息以供本次采集任务判断。
2. **Scrape / 受控下载**：仅对通过来源校验的 URL 获取 Markdown、HTML 或 PDF 原件/快照。

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
  "collection_plan_code": "zj_ecommerce_digital_economy_2026",
  "source_registry_version": "v1",
  "crawler_rule_version": "v1",
  "query_template_version": "v1"
}
```

PDF 必须优先作为二进制原件写入 `raw_object`，由 MinerU 走已有 Document Pipeline 解析。HTML 和 Markdown 也以文档原始表示写入 `raw_object`，形成 `normalized_document`。原 URL、规范 URL、发布时间、抓取时间、内容 hash、计划和规则版本写入 `raw_object.metadata_summary`、`normalized_asset_ref.lineage` 和审计摘要的最小必要字段。

### 3.4 合规数据供应商 Connector：Pipeline B 的抽象扩展入口

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
  "coverage_region": "浙江省",
  "coverage_period": "2026-01-01/2026-03-31",
  "collection_plan_code": "zj_ecommerce_digital_economy_2026"
}
```

符合该协议的未来供应商数据进入 Pipeline B，形成 `normalized_record` 和岗位需求领域表。必须保留来源平台、记录 ID、原链接、发布时间、覆盖期、地域、字段字典版本和授权依据。缺少授权依据的岗位明细不得自动入库。

### 3.5 显式 Pipeline 路由契约

当前 `crawler` 被固定路由到 Pipeline B；本设计需要替换为 Connector 允许类型驱动的、创建 Job 时冻结的路由契约：

| 已批准 Connector | `content_kind` | MIME 白名单 | `pipeline_type` | 标准化产物 |
| --- | --- | --- | --- | --- |
| `firecrawl_document` | `web_document` | `application/pdf`、`text/html`、`text/markdown`、允许的 Office MIME | `document` | `normalized_document` |
| future `structured_provider` adapter | `structured_record` | `application/json`、`text/csv`、XLSX MIME | `record` | `normalized_record` |
| 既有 crawler package | `structured_record` | `application/json` | `record` | `normalized_record` |
| 不匹配 | 任意 | 任意 | 拒绝创建 Job | `failed` |

`pipeline_type` 不能由请求调用方任意指定。ingest gateway 从已批准 Connector 配置、`content_kind` 和 MIME 白名单推导一次，写入 `Job.payload.pipeline_type`。这是一项架构与 API 契约调整，需要 Data Model / API Contract / Semantic Retrieval Integration Review 后实施。

### 3.6 候选质量门与去重

采集结果在进入 ingest 前执行候选质量门：

| 维度 | 最低要求 |
| --- | --- |
| 来源权威性 | 域名命中来源注册表，发布机构与来源等级匹配资产类别 |
| 主题相关性 | 地域、产业主题和资产类别在标题、元数据或正文证据中可验证 |
| 时间有效性 | 政策/报告可解析 `published_at`；政策额外提取有效期或状态 |
| 内容完整性 | 非登录页、非验证码页、非空壳页，正文大小和结构达标 |
| 合规性 | 授权/条款允许，岗位数据有授权依据 |
| 去重 | `canonical_url + published_at + content_hash`；跨来源相同正文只保留权威原始来源 |

满足高阈值的对象进入 ingest；信息不足、主题冲突、来源不明或发布日期无法验证的对象进入人工复核候选，不创建正式资产；不合规或明显无关对象丢弃，并保留最小审计原因。

同一来源内容发生变更时，以稳定 `source_object_key` 关联到同一资产，创建新 `asset_version`；绝不通过新增反向指针表达当前版本。

---

## 4. 实时 AI WebSearch 链路

### 4.1 用户与 API 行为

检索界面增加开关：

```text
[ ] 联网搜索公开资料
```

默认关闭。开启后，系统提示“联网结果来自公开网络，未纳入 NEXUS 治理与资产库，结果不会保存”。不配置 `external_search` 专属权限，也不按 Console 用户或 API caller 额外限制；现有 Console session / API key 鉴权仍然是入口基础认证。

Query Router 的内外入口使用同一选项：

```json
{
  "query": "2026年浙江省电子商务和数字经济的产业政策、报告与人才需求",
  "options": {
    "online_search": true,
    "online_search_mode": "supplement"
  }
}
```

`online_search_mode` 在初期固定为 `supplement`。本地 NEXUS 检索始终执行；不提供 `web_only`，也不把联网结果改写成 NEXUS 的本地召回结果。

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
- Provider 失败时，返回 `external_search_unavailable` warning 和正常本地结果。
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
- `online_search=false` 时没有任何外部请求；`true` 时本地和外部结果分区返回。
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
