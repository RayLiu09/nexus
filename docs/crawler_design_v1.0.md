# NEXUS Crawler 定向采集与实时联网检索设计 v1.0（实施版）

> **状态**：实施契约，待 Architecture / API Contract / Data Model / Semantic Retrieval / Permission And Audit Review。
> **目标**：为 NEXUS 提供低频、受控、可追溯的 Crawler 文档采集能力，通过 Firecrawl 抓取全国/省级政策、报告、区域电子商务/数字经济数据等 HTML/PDF/Markdown 内容，并经 Pipeline A 沉淀为治理后的 NEXUS 数据资产。
> **非目标**：不建设通用无边界互联网爬虫；不提供 Console 模板维护或站点白名单维护界面；不做候选 URL 人工审核；不让 Firecrawl 或实时 WebSearch 内容绕过 `raw_object`、标准化、治理、版本和索引准入。

---

## 1. 结论与原则

本设计包含两条独立链路：

1. **Crawler 定向采集入库链路**：低频同步运行。用户可用通用配置创建 Crawler 计划，也可用系统内置计划快速启动。Firecrawl 抓取的 HTML/PDF/Markdown 必须先落 `raw_object`，并以 `Job.payload.pipeline_type="document"` 进入 Pipeline A，形成 `normalized_document` / `normalized_asset_ref` 后再治理、入库和索引。
2. **实时联网检索链路**：Query Router 在既有规则下仅对符合条件的无本地证据请求返回 `external_web_results`。结果只属于当前请求，不创建资产，不进入治理，不入索引，不进入跨请求缓存。

两条链路不得自动互相转换：实时 WebSearch 返回的 URL 或正文不自动进入 Crawler 计划或资产管道；Crawler 采集作业也不依赖用户检索触发。

核心原则：

- Crawler 是通用采集能力，Firecrawl 是当前默认 Web Document Connector。
- 内置计划只有一套，通过 JSON 配置定义，用于全国/省级职业教育政策、产教融合政策、电子商务、数字经济、政策报告和区域数据等定向采集。
- 官方权威站点通过 JSON 配置定义；Console 不提供模板或站点配置维护界面。
- 区域选择默认全国，可选择省份；不同区域对应不同官方权威站点列表。
- 官方权威站点列表是来源种子和权威性证据，不表示 Crawler 只能从这些站点搜索信息。
- Crawler 是低频同步运行任务；同步边界到 Firecrawl 抓取完成、自动过滤、`raw_object` 持久化和 Pipeline Job 提交，不等待 Pipeline A 全链路完成。
- 不做候选 URL 人工审核；自动过滤和失败只进入运行摘要诊断。
- 爬取内容必须在 `raw_object` 入库阶段去重：同一次 run 中多个 URL 返回同一份内容、多次 run 抓到同一份内容，均不得重复创建有效原始对象、资产版本或索引内容。
- `pipeline_type` 在 ingest gateway 创建 Job 时冻结；Worker 只读取 `Job.payload.pipeline_type`，不做运行时推断。
- AI 治理输入只能是 `normalized_document` 或 `normalized_record`（经 `normalized_asset_ref`），不能是 Firecrawl 原始输出、raw snapshot 或搜索摘要。

---

## 2. 总体架构

```text
配置文件
  ├─ policy_report_regional_v1.json
  └─ crawler_region_sites.json
        |
        v
nexus-console
  ├─ 快速启动：区域下拉（默认全国）+ 主题关键词 + 执行计划
  └─ 通用配置：主题 + 可选目标站点 URL + 执行计划 + 抓取方式
        |
        v
internal crawler API
        |
        v
同步 run_plan
  -> Firecrawl Search / Scrape / Batch Scrape / controlled Crawl
  -> URL safety + 官方权威站点证据/path 校验 + 自动质量门 + URL 去重
  -> accepted_snapshot summary
  -> raw_object
  -> Job(payload.pipeline_type="document")
        |
        v
Pipeline A
  -> ingest_validate
  -> assetize
  -> parse (HTML -> MinerU-HTML, PDF -> pipeline, Markdown -> markdown adapter)
  -> normalize -> normalized_document / normalized_asset_ref
  -> AI governance + rules
  -> available / review_required
  -> knowledge_chunk + index_manifest
        |
        v
Search / QA / Query Router v2 section_contexts
```

NEXUS 负责资产、原始内容、治理、版本、索引、权限和审计。Firecrawl 只负责受控的网页发现和正文抓取，不拥有 NEXUS 资产事实。

---

## 3. 业务范围与分类口径

内置计划覆盖全国和省级公开来源中的以下内容：

- 职业教育政策。
- 产教融合、校企合作、产业学院、实训基地相关政策。
- 电子商务政策与报告，包括跨境电商、农村电商、直播电商、旅游电商。
- 数字经济相关政策、报告和区域数据。
- 区域电子商务/数字经济数据、统计公报、运行情况、白皮书、发展报告。

治理分类 code 只复用现有三类：

| 治理分类 code | 本阶段内容 |
| --- | --- |
| `industry_policy` | 职业教育、产教融合、电子商务、数字经济等政策、通知、实施意见、行动计划、专项规划 |
| `industry_report` | 产业报告、区域经济报告、电子商务/数字经济发展报告、白皮书、统计公报、运行情况 |
| `talent_demand_report` | 区域人才需求、就业需求、岗位需求报告或统计，不包括未授权招聘明细抓取 |

职业教育、产教融合、区域经济、产业群、跨境电商、农村电商、直播电商、旅游电商和数字经济是主题、标签或元数据维度，不新增治理分类 code。岗位明细只接受未来合规结构化供应商、批量文件或授权 API，不用 Firecrawl 抓普通招聘网页替代授权。

时间有效性默认策略：

| 资产类别 | 高有效性窗口 | 时间判定优先级 | 超窗处理 |
| --- | --- | --- | --- |
| `industry_policy` | 5 年 | `effective_period`，其次 `published_at` | 明确废止/替代则拒绝；无法确认时降低质量并进入 `review_required` |
| `industry_report` | 2 年 | `statistical_period`，其次 `published_at` | 降低时效质量；可由人工确认历史参考价值 |
| `talent_demand_report` | 2 年 | `statistical_period`，其次 `published_at` | 默认不自动通过；只能作为人工确认的历史趋势参考 |

---

## 4. 配置文件契约

### 4.1 内置模板配置

模板由 JSON 文件维护，不提供 Console 维护界面。建议路径：

```text
nexus-app/config/policy_report_regional_v1.json
```

示例契约：

```json
{
  "schema_version": "crawler_template.v1",
  "template_code": "policy_report_regional_v1",
  "template_name": "全国/省级政策、报告与区域电子商务数字经济数据采集",
  "default_region_code": "national",
  "supported_region_scope": ["national", "province"],
  "content_goals": [
    "vocational_education_policy",
    "industry_education_integration_policy",
    "ecommerce_policy",
    "cross_border_ecommerce",
    "rural_ecommerce",
    "live_ecommerce",
    "tourism_ecommerce",
    "digital_economy_policy",
    "industry_report",
    "regional_ecommerce_data",
    "regional_digital_economy_data"
  ],
  "allowed_classification_codes": [
    "industry_policy",
    "industry_report",
    "talent_demand_report"
  ],
  "default_keywords": [
    "职业教育",
    "产教融合",
    "电子商务",
    "跨境电商",
    "农村电商",
    "直播电商",
    "旅游电商",
    "数字经济",
    "区域经济",
    "发展报告",
    "统计公报"
  ],
  "query_templates": [
    "{region} ({keywords}) (政策 OR 通知 OR 实施意见 OR 行动计划 OR 专项规划)",
    "{region} ({keywords}) (职业教育 OR 产教融合 OR 校企合作 OR 产业学院)",
    "{region} ({keywords}) (电子商务 OR 跨境电商 OR 农村电商 OR 直播电商 OR 旅游电商)",
    "{region} ({keywords}) (数字经济 OR 区域经济 OR 产业集群 OR 产业群)",
    "{region} ({keywords}) (发展报告 OR 白皮书 OR 统计公报 OR 运行情况 OR 数据)"
  ],
  "time_effectiveness": {
    "industry_policy": { "preferred_within_years": 5 },
    "industry_report": { "preferred_within_years": 2 },
    "talent_demand_report": { "preferred_within_years": 2 }
  },
  "firecrawl": {
    "country": "CN",
    "languages": ["zh-CN"],
    "only_main_content": true,
    "formats": ["markdown", "html"],
    "max_discovery_depth": 1,
    "allow_external_links": false,
    "allow_subdomains": false,
    "max_pages_per_run": 50,
    "timeout_seconds": 120
  },
  "pipeline_policy": {
    "connector_type": "firecrawl_document",
    "content_kind": "web_document",
    "pipeline_type": "document"
  }
}
```

实现必须记录模板配置 hash：`crawler_run.summary.template_config_hash`，并写入 `raw_object.metadata_summary`。

### 4.2 区域官方权威站点配置

区域官方权威站点由 JSON 文件维护，不提供 Console 维护界面。这份配置用于快速启动的默认目标站点、权威来源证据和官方机构种子，不是“只能搜索这些站点”的硬限制。建议路径：

```text
nexus-app/config/crawler_region_sites.json
```

示例契约：

```json
{
  "schema_version": "crawler_region_sites.v1",
  "discovery_policy": "authority_seed_not_exclusive",
  "description": "站点列表用于配置全国/省级官方权威机构种子站点和来源证据，不表示 Crawler 只能从这些站点搜索信息；运行时仍需对最终 URL 执行安全、来源和质量门校验。",
  "regions": [
    {
      "region_code": "national",
      "region_name": "全国",
      "scope_type": "national",
      "sites": [
        {
          "site_name": "中华人民共和国教育部",
          "base_url": "http://www.moe.gov.cn/",
          "source_kind": "education_authority",
          "include_paths": [],
          "exclude_paths": []
        },
        {
          "site_name": "中华人民共和国商务部",
          "base_url": "https://dzswgf.mofcom.gov.cn/zcfb/page1.html",
          "source_kind": "commerce_authority",
          "include_paths": [],
          "exclude_paths": []
        },
        {
          "site_name": "中华人民共和国商务部电子商务与信息化司",
          "base_url": "https://dzsws.mofcom.gov.cn/",
          "source_kind": "commerce_authority",
          "include_paths": [],
          "exclude_paths": []
        },
        {
          "site_name": "中华人民共和国工业和信息化部",
          "base_url": "https://www.miit.gov.cn/gxsj/index.html",
          "source_kind": "industry_authority",
          "include_paths": [],
          "exclude_paths": []
        },
        {
          "site_name": "中华人民共和国国家发展和改革委员会",
          "base_url": "https://www.ndrc.gov.cn/",
          "source_kind": "development_reform_authority",
          "include_paths": [],
          "exclude_paths": []
        }
      ]
    },
    {
      "region_code": "zhejiang",
      "region_name": "浙江省",
      "scope_type": "province",
      "sites": [
        {
          "site_name": "浙江省商务厅",
          "base_url": "https://zcom.zj.gov.cn/",
          "source_kind": "commerce_authority",
          "include_paths": [],
          "exclude_paths": []
        },
        {
          "site_name": "浙江省人民政府",
          "base_url": "https://www.zj.gov.cn/",
          "source_kind": "official_site",
          "include_paths": [],
          "exclude_paths": []
        }
      ]
    },
    {
      "region_code": "yunnan",
      "region_name": "云南省",
      "scope_type": "province",
      "sites": [
        {
          "site_name": "云南省商务厅",
          "base_url": "https://swt.yn.gov.cn/",
          "source_kind": "commerce_authority",
          "include_paths": [],
          "exclude_paths": []
        },
        {
          "site_name": "云南省人民政府",
          "base_url": "https://www.yn.gov.cn/",
          "source_kind": "official_site",
          "include_paths": [],
          "exclude_paths": []
        }
      ]
    }
  ]
}
```

实现必须记录站点配置 hash：`crawler_run.summary.region_sites_config_hash`，并写入 `raw_object.metadata_summary`。

### 4.3 URL 安全与官方站点规则

所有快速启动和自定义 Crawler 计划都必须通过服务端 URL 校验：

- 自定义用户 URL 必须是 `https://`。
- JSON 内置官方权威站点可保留机构公开的 `http://` 地址，但这只适用于代码评审后的配置文件，不适用于用户自定义 URL。
- 禁止 localhost、内网地址、裸 IP、非 HTTP(S) scheme。
- 禁止跳转到非允许 host。
- 默认 `allow_external_links=false`。
- 默认 `max_discovery_depth<=1`，系统级上限不得被用户扩大。
- 禁止无边界 `crawlEntireDomain`。
- Search 可优先使用官方权威站点 host 作为 `includeDomains` 或权威性信号；用户未提供目标站点时执行受控全网搜索，最终 URL 仍必须通过安全、来源和质量门校验，且不能把官方站点配置误用成“只能搜索这些站点”的全局限制。

### 4.4 去重规则

Crawler 内容去重必须在 `raw_object` 入库阶段执行，不通过扫描历史 `crawler_run.summary` 完成。原因是 `crawler_run` 是执行台账，不是去重索引；历史运行过多时扫描 summary 不具备可扩展性，也容易把诊断字段误当事实来源。

当前同步 runner 在采集阶段做两件事：

1. Search 返回 URL 的本次 run 内去重，避免对完全相同 URL 重复 scrape；重复 URL 记入 `filter_reasons.duplicate_url`。
2. 对通过质量门的内容计算 `content_hash=sha256:<hash>` 并写入 `accepted_snapshots`，作为 `raw_object.checksum` 的输入证据。

入库阶段必须基于 `raw_object.checksum`、`source_object_key` 和 assetize 幂等规则执行内容级去重。同一份文件从多个来源获取时，允许保留多个来源证据到 lineage，但不得重复创建有效原始对象、可用资产版本或重复提交同内容索引。去重只保存 hash、URL 和原因码，不在 run summary 或审计中保存大段正文。

---

## 5. Console 行为

Console 提供两种创建方式：

1. **快速启动**：使用内置 JSON 模板。用户选择区域（默认全国，可选省份）、主题关键词和执行计划。目标站点从区域官方权威站点 JSON 自动带出。
2. **通用配置**：用户指定主题关键词、可选目标站点 URL（支持多个地址）、抓取方式和执行计划。不提供目标站点时执行受控全网搜索。自定义配置仍受 URL 安全、最大深度、最大页数、外链策略和质量门约束。

快速启动表单：

```text
区域：全国（默认）/ 省份下拉
主题关键词：默认带出，可追加
目标站点：根据区域官方权威站点配置带出
执行计划：运行一次 / 定期执行
```

通用配置表单：

```text
计划名称
主题关键词
目标站点 URL，可选，支持多个；为空时全网搜索
抓取方式：搜索发现 / 指定 URL / 站点栏目
执行计划：运行一次 / 定期执行
```

模板和官方权威站点不在 Console 中维护。Console 只读取配置并展示可用区域、默认关键词和目标站点。

---

## 6. 同步运行与最小状态

Crawler 是低频任务，采用同步执行：后端接到运行请求后完成 Firecrawl 调用、自动过滤、`raw_object` 持久化、Pipeline Job 提交和 `crawler_run.summary` 写入后返回；不等待 Pipeline A 的 parse/normalize/governance/index 完成。

`crawler_run.status` 只保留：

| 状态 | 含义 |
| --- | --- |
| `running` | 本次采集正在同步执行 |
| `succeeded` | Firecrawl 调用完成，符合条件内容已提交 Pipeline，没有阻断性失败 |
| `partial_failed` | 至少一个内容已提交 Pipeline，但存在抓取、过滤或入库失败 |
| `failed` | 配置校验、Firecrawl 调用失败，或没有内容成功提交 Pipeline |

第一阶段不需要 `crawler_run_item` 表。运行详情保存在 `crawler_run.summary`：

```json
{
  "discovered_count": 42,
  "accepted_count": 21,
  "filtered_count": 19,
  "submitted_count": 21,
  "raw_persisted_count": 20,
  "duplicate_count": 1,
  "ingest_failed_count": 0,
  "failed_count": 2,
  "filter_reasons": {
    "outside_allowed_domain": 6,
    "topic_mismatch": 8,
    "empty_content": 3,
    "unsafe_url": 2,
    "duplicate_url": 1
  },
  "accepted_snapshots": [
    {
      "url": "https://...",
      "source_url": "https://...",
      "title": "政策标题",
      "content_hash": "sha256:...",
      "content_chars": 12000,
      "raw_representation": "html"
    }
  ],
  "submitted": [
    {
      "url": "https://...",
      "raw_object_id": "raw_...",
      "job_id": "job_...",
      "content_hash": "sha256:...",
      "duplicate": false,
      "pipeline_type": "document"
    }
  ],
  "failures": [
    {
      "url": "https://...",
      "reason": "firecrawl_timeout"
    }
  ],
  "template_config_hash": "sha256:...",
  "region_sites_config_hash": "sha256:..."
}
```

过滤结果仅用于运行诊断，不进入候选审核队列，不创建治理审核任务，不创建正式资产。

定期执行第一阶段可先保存 `schedule_cron` 并由轻量 poller 或运维 cron 触发同一个同步 runner；不得引入 RabbitMQ、Celery 或独立调度平台作为前置依赖。

---

## 7. API 契约

第一阶段内部控制面 API 建议收敛为：

```text
GET  /internal/v1/crawler/config
GET  /internal/v1/crawler/regions
GET  /internal/v1/crawler/regions/{region_code}/sites

POST /internal/v1/crawler/plans
GET  /internal/v1/crawler/plans
GET  /internal/v1/crawler/plans/{plan_id}
POST /internal/v1/crawler/plans/{plan_id}/archive
POST /internal/v1/crawler/plans/{plan_id}/run

GET  /internal/v1/crawler/runs
GET  /internal/v1/crawler/runs/{run_id}
```

不提供以下 API：

```text
POST/PATCH crawler templates
POST/PATCH source registries
candidate approve/reject
```

`accepted_count` 表示通过质量门的文档快照数；`submitted_count` 表示已完成 raw/job 提交的记录数，其中 duplicate 项可能复用已有 `raw_object` 并创建 `duplicate_skipped` job。

`POST /run` 同步返回：

```json
{
  "run_id": "run_...",
  "status": "succeeded",
  "summary": {
    "discovered_count": 30,
    "accepted_count": 20,
    "filtered_count": 8,
    "submitted_count": 20,
    "raw_persisted_count": 19,
    "duplicate_count": 1,
    "ingest_failed_count": 0,
    "failed_count": 2,
    "accepted_snapshots": [
      {
        "url": "https://...",
        "content_hash": "sha256:..."
      }
    ],
    "submitted": [
      {
        "url": "https://...",
        "raw_object_id": "raw_...",
        "job_id": "job_...",
        "duplicate": false,
        "pipeline_type": "document"
      }
    ],
    "filter_reasons": {
      "topic_mismatch": 5,
      "outside_allowed_domain": 3
    }
  }
}
```

Mutation 必须要求 `Idempotency-Key`，并写审计。
Crawler plan 创建后不可编辑；需要调整配置时创建新计划，旧计划通过 archive 废弃。

---

## 8. Firecrawl Document Connector

Firecrawl Connector 使用 Firecrawl v2 的 Search、Scrape、Batch Scrape 和受控 Crawl 能力。NEXUS 使用方式：

| Firecrawl 能力 | 使用方式 | 限制 |
| --- | --- | --- |
| Search | 候选 URL 发现；默认 `country=CN`、中文语言环境，可使用官方权威站点 host 作为优先来源或 `includeDomains` | 搜索摘要不入库；最终 URL 必须再次校验；官方站点配置不是全局搜索硬限制 |
| Batch Scrape | 对通过自动质量门的 URL 抓取正文和 metadata | 只抓 `markdown`、`html` 和必要 metadata；默认 `onlyMainContent=true` |
| Scrape | 单 URL 补抓或重试 | 不作为循环发现链接的爬行器 |
| Crawl | 仅用于已配置站点栏目发现 | 必须限制 include/exclude path、depth、limit，禁止外链和无边界全站爬 |

抓取结果进入 Pipeline 前必须包含最小证据：

```json
{
  "connector_type": "firecrawl_document",
  "content_kind": "web_document",
  "pipeline_type": "document",
  "source_url": "https://...",
  "final_url": "https://...",
  "canonical_url": "https://...",
  "publisher": "发布机构",
  "published_at": "2026-02-18",
  "retrieved_at": "2026-08-04T10:00:00Z",
  "content_hash": "sha256:...",
  "raw_representation": "html|markdown|original_binary|firecrawl_snapshot",
  "firecrawl_job_id": "...",
  "crawler_plan_id": "...",
  "crawler_run_id": "...",
  "template_code": "policy_report_regional_v1",
  "template_config_hash": "sha256:...",
  "region_code": "national",
  "region_sites_config_hash": "sha256:..."
}
```

Firecrawl API key 只存在后端配置或密钥管理中，不进入 Console、日志、审计摘要或响应体。

---

## 9. Pipeline A 路由与 HTML/Markdown 处理

当前 Crawler 不包含 JSON package 场景。Firecrawl 文档采集使用显式 Connector 路由：

| `DataSource.source_type` | `connector_type` | `raw_object.mime_type` | `pipeline_type` |
| --- | --- | --- | --- |
| `crawler` | `firecrawl_document` | `text/html` | `document` |
| `crawler` | `firecrawl_document` | `text/markdown` | `document` |
| `crawler` | `firecrawl_document` | `application/pdf` | `document` |
| `crawler` | `firecrawl_document` | `application/vnd.nexus.firecrawl-html-snapshot+json` | `document` |
| `database` / `webhook` | any | JSON/record | `record` |

`pipeline_type` 不能由前端或调用方任意指定。ingest gateway 必须基于已批准 Connector 配置、`content_kind` 和 MIME 白名单推导一次，写入 `Job.payload.pipeline_type`。

原始留存策略：

1. Firecrawl 返回 HTML：`raw_object.mime_type=text/html`，raw body 保存 HTML，metadata 保存 Firecrawl 证据。
2. Firecrawl 只返回 Markdown：`raw_object.mime_type=text/markdown`，raw body 保存 Markdown，标记 `raw_representation=markdown`。
3. PDF 原件可合法下载：`raw_object.mime_type=application/pdf`，进入现有 MinerU Pipeline。
4. 需要完整保留 Firecrawl 包：使用 `application/vnd.nexus.firecrawl-html-snapshot+json`，parse stage 解包后按 HTML/Markdown 处理。

Parse 规则：

```text
text/html -> MinerU-HTML
application/pdf -> MinerU pipeline，OCR 自动策略照旧
text/markdown -> markdown document adapter
firecrawl snapshot json -> 解包后按 HTML/Markdown 处理
```

`raw_object.metadata_summary` 和 `normalized_asset_ref.lineage` 必须携带 `source_url`、`final_url`、`canonical_url`、`firecrawl_job_id`、`crawler_plan_id`、`crawler_run_id`、模板配置 hash、区域站点配置 hash 和内容 hash。`normalized_asset_ref` 仍必须包含 v3.0 要求的 `source_type`、`content_type`、`title`、`language`、`governance`、`quality`、`lineage` 字段。

---

## 10. 政策/报告 Section Context 召回

政策、报告、区域电子商务/数字经济 HTML 资产要支持 Query Router v2 的 runtime `document_section_context`。第一阶段不新增持久化 section 表，依赖 `knowledge_chunk.locator.heading_path` 和 chunk 顺序聚合。

Pipeline A 标准化必须尽量保留结构：

```json
{
  "block_id": "block-001",
  "type": "heading",
  "text": "一、发展基础",
  "order": 1,
  "heading_path": ["一、发展基础"],
  "source_locator": {
    "url": "https://...",
    "css_selector": "...",
    "text_anchor": "一、发展基础"
  }
}
```

`knowledge_chunk.locator` 必须写入：

```json
{
  "heading_path": ["一、发展基础", "（二）重点产业"],
  "block_start_order": 12,
  "block_end_order": 16,
  "source_url": "https://...",
  "text_anchor": "...",
  "section_key": "hash(normalized_ref_id + heading_path)"
}
```

HTML section builder 优先级：

1. HTML `h1`/`h2`/`h3`/`h4`。
2. Markdown heading。
3. 中文编号标题，如 `一、`、`二、`、`（一）`、`1.`。
4. 段落长度和结构兜底。

低质量结构必须打 `quality_flags`，例如 `weak_heading_structure`。Query Router v2 仅在命中资产属于 `industry_policy` / `industry_report` / `talent_demand_report`，且查询意图是总结、措施、趋势、阶段、任务、政策条款或区域发展时展开 section context；精确事实、下载、关键词存在性和跨资产比较保持 compact chunk evidence。

---

## 11. 审计与安全

必须审计：

- Crawler 计划创建、修改、禁用。
- Crawler run 启动和完成。
- Firecrawl provider 调用摘要。
- 自动过滤统计和原因码。
- `raw_object` 持久化、ingest batch 提交、Job 创建。
- Pipeline 既有 `INGEST_BATCH_SUBMITTED`、`RAW_OBJECT_PERSISTED`、`INGEST_VALIDATE_COMPLETED`、`VERSION_STATUS_CHANGED`、`PIPELINE_FAILED`。

不得写入日志或审计摘要：

- Firecrawl API key。
- 大段网页正文。
- L3/L4 明文。
- 用户敏感查询全文。

实时 WebSearch 保持既有边界：外部结果只存在于当前响应，不写 `raw_object`、资产、标准化对象、治理、chunk、索引或跨请求缓存。Provider 失败、429/5xx 或超时时不影响本地检索。

---

## 12. 实施切片与验收

实施切片：

1. `crawler_contract_sync`：同步本文档、根契约和任务包。
2. `crawler_config_and_plan_api`：读取 JSON 模板和区域站点配置；新增 `crawler_plan` / `crawler_run`；实现只读配置、计划 CRUD 和同步 run API 的 fake runner。
3. `firecrawl_sync_runner`：实现 Firecrawl client、同步 runner、URL safety、自动质量门和 run summary。
4. `crawler_pipeline_a_ingest`：Firecrawl HTML/PDF/Markdown 写 `raw_object`，创建 Pipeline A Job。
5. `console_crawler_plan_ux`：Console 快速启动、自定义配置、区域下拉、站点预览和运行结果。
6. `policy_report_section_context`：HTML/Markdown heading path、chunk locator 和 Query Router v2 runtime section context 回归。

关键验收：

- 用户可用快速启动创建全国或省级 Crawler 计划，区域默认全国，省份对应官方权威站点来自 JSON 配置。
- 用户可用通用配置指定主题、多个目标站点 URL 和执行计划。
- 用户不提供目标站点时，Crawler 计划以受控全网搜索模式运行。
- 模板和官方权威站点没有 Console 维护界面。
- Crawler run 同步返回 `running` / `succeeded` / `partial_failed` / `failed` 中的最终状态和 summary。
- 无候选 URL 审核任务；过滤 URL 仅进入运行诊断。
- Firecrawl 抓取 HTML/PDF/Markdown 后以 `pipeline_type=document` 进入 Pipeline A。
- AI 治理只基于 `normalized_asset_ref`。
- 政策/报告/区域数据资产的 chunk locator 具备 `heading_path`、block order 和 source URL，Query Router v2 可返回 bounded `document_section_context`。
- 无敏感日志、无密钥泄露、无反向指针、无 RabbitMQ/Celery 前置依赖。

---

## 13. 必须通过的 Review Gates

- **Architecture Review**：确认 `crawler + firecrawl_document -> document` 的 ingest-time frozen 路由。
- **Data Model Gate**：确认 `crawler_plan` / `crawler_run` 为执行台账，不引入资产反向指针或当前版本指针。
- **API Contract Gate**：确认 config、regions、plans、run API、状态枚举和错误码。
- **Permission And Audit Gate**：确认 URL safety、密钥保护、敏感内容外发阻断、审计字段和日志边界。
- **Semantic Retrieval Integration Gate**：确认 HTML/Markdown chunk locator 支持 policy/report runtime section context，且只有治理通过的资产进入索引。
- **Frontend UX Gate**：确认快速启动、自定义配置、运行诊断和失败状态符合 Console P0 信息架构。
