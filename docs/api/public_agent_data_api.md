# Agent 公开用数接口与 A/B 缺口交付

本次实现以 `agent_openapi_gap_analysis_2026-10-22.md` 的 A/B 类建议和资产中心最新 16 类可见入口为范围（2026-10-26 补充职业分类大典及教育部布点同步口径）。C 类资源变更/增量同步接口不在本次交付内。公开消费别名由 `nexus-api` 提供，前缀 `/open/v1`；业务 API 保持 `/v1`，内部 Console API 不进入工具清单。

## A/B 覆盖

下表路径省略 `/open/v1`。新接口的输入和输出 DTO 可直接在 OpenAPI 查看；带“增强”的接口保留原有参数。

| 缺口 | 接口 | 行为和数据口径 |
| --- | --- | --- |
| A 资源发现 | `GET /data-resources` | 16 类入口的编码、来源类型、可消费数量、数量单位、能力、实际查询参数及限制；计数遵循公开边界 |
| 专业布点 | `GET /major-offerings`、`/aggregate` | 教育部 API 同步与控制台 Excel 导入事实直接入库，无 AI 治理；同年同校同专业跨来源去重，仅代表已入库覆盖；与专业简介、培养方案课程统计无关 |
| 职业分类大典 | `GET /occupation-dictionary` | 2022 年版已核验导入基础表，职业大类/小类/名称 AND 检索，返回类别、层级、编码、职业名称、定义、工作任务；只读、无 AI 治理、不依赖资产版本或 ref |
| A 文档发现 | 增强 `GET /assets` | 标题、resource_type、多 domains、主题、区域/行业、专业/院校/层次、源发布日期；tags_match 显式 any/all；返回白名单业务元数据 |
| A 专业简介 | `GET /major-profile-documents` | 当前文档及四项专业身份元数据，遵循人工修改和清空值；不依赖已退役 MajorProfile 投影 |
| A 市场岗位 | `GET /market-jobs`、`/{job_id}` | 同页面读取 raw_jobs + provenance；岗位/企业/行业/学历/经验/采集时间查询，保留源字段、provider/upstream ID、来源链接 |
| A 园区与企业 | `GET /industrial-parks`、`/{park_id}`；`GET /enterprises`、`/{enterprise_id}` | 名称/行业、经营范围、所属园区查询；园区企业数量及真实关系 |
| A 教学标准 | `GET /teaching-standard-libraries`、`/{library_id}` | 专业代码/名称、层次、修业年限、课程数量、引用锚点；active 库 + 当前 available 文档 + 正式分类 |
| A 标准课程 | `GET /teaching-standard-courses`、`/{course_id}` | 跨标准检索课程名、专业、类型及标签；学时语义 suggested，标签语义 derived；返回章节页码和证据绑定 |
| A 教材 | `GET /course-textbooks`、`/{profile_id}` | 教材名、理论/实训类型、出版社、主编、出版年；返回已有知识/任务大纲能力 |
| A 限定范围检索 | 增强 `GET /search` | asset_ids、normalized_ref_ids、多 knowledge_types 及文档元数据；在向量排序/top_k 前取范围交集；保留 chunk/block/locator 引用 |
| A 长文片段 | `GET /normalized-refs/{ref_id}/sections`、`/sections/{section_id}` | 以持久化 block ID 定位，字符预算、相邻块、截断状态和续读偏移；无块时使用 body 锚点 |
| B 已有大纲 | `GET /normalized-refs/{ref_id}/knowledge-outline`、`/task-outline` | 区分两类大纲；分页/子树读取；未生成时 available=false，GET 不构建 |
| B 节点上下文 | `GET /normalized-refs/{ref_id}/outlines/{outline_type}/nodes/{node_id}/context` | 同 ref 子树下的已有关联 chunks；知识大纲使用专用 FK，任务大纲使用 metadata.outline_node_id；字符与条数双重预算 |
| B 节点内检索 | 增强 `GET /search?outline_node=...`、`?task_outline_node=...` | 按对应大纲子树限定候选 chunks；与文档范围取交集 |
| B 已有图谱 | `GET /normalized-refs/{ref_id}/knowledge-graph` | exact ref，类型/节点/关系/深度与数量限制；已有证据图谱及生成能力图谱；保留存储事实、推导来源和证据；不触发构建/晋升 |
| B 批量证据 | `POST /evidence-resolutions` | 最多 30 个 chunk/ref/岗位/企业/园区/布点/能力条目 ID，逐项校验可见性；不可用与不存在均 not_found；POST 为只读解析 |
| B 同源岗位聚合 | `GET /market-jobs/aggregate` | raw_jobs 全部符合筛选记录的分组统计，非当前页；样本量、缺失值、去重键、来源和覆盖范围 |
| B 实体候选 | `POST /entity-resolutions` | 专业、课程、企业、园区候选及 exact/substring 依据；保留歧义与来源，不强行合并 |
| B 职业能力增强 | 增强 `GET /record-assets/ability-analyses?major_code=...`；新增 `GET /record-assets/ability-items` | 专业代码过滤、跨分析能力条目检索，保留任务/工作内容/分析/ref 来源；沿用独立记录边界 |
| B 培养方案增强 | 增强 `GET /talent-training-plans`；新增 `/{plan_id}/courses` | 按文档源发布日期筛选方案；课程分页读取；公开方案与两类方案图谱统一校验当前可用文档和正式分类 |
| A/B 已有能力复用 | 原有专业布点及聚合、问答、正文/chunks/下载、职业能力任务/关系、院校课程统计、培养方案图谱 | 不复制同义业务 API；由生成工具封装现有公开能力 |

## 参数合同

- 专业布点 `year`、`province_code`、`major_code`、`school_code` 精确匹配，`province_name` 行政区名称归一化后精确匹配，`major_name`、`school_name` 按转义字面子串匹配，条件按 AND 组合。聚合 `group_by` 支持 year、province_code、province_name、major_code、major_name，最多 5 项且不可重复，数组使用 repeated keys。返回选定维度、record_count、institution_count；学校按标识优先、名称兜底去重，跨年记录数可大于学校数，meta.total 为分组数。
- 职业分类大典 `major_group`、`minor_group`、`occupation_name` 均按字面子串匹配且组合为 AND，前两项可传编码前缀；返回 edition、occupation_code、occupation_category、major_group、minor_group（可空）、occupation_name、definition、work_tasks。数据来自名录及同版 PDF 补齐，所附 PDF 为社会公示稿，不声明全国完整名录。
- 列表沿用 `page`（默认 1）与 `pageSize`（默认 20，上限 200）；`meta.total` 来自全量过滤后 COUNT，排序末项包含稳定 ID。分组聚合的 total 是分组数，sample_count 是岗位记录样本量。
- 文档 `domain` 为单一正式治理分类；`domains` 是重复参数并在内部取 OR，与其他筛选条件取 AND；`major_profile` 多分类筛选兼容 `program_profile`。`resource_type` 用于文档业务类型，记录类资源应走专用 API。
- `topic=finance_commerce|low_altitude` 使用现有资产中心的主题条件，主题可重叠。`region`、`industry` 采用已有标签归一化后的精确匹配。专业/院校名称是转义后的子串匹配，专业代码/层次为精确匹配；适用身份来自文档元数据及对应方案/标准投影。
- `tags_match` 默认为 any；all 表示每个查询标签召回的 ref 集合取交集，精确/语义由 `is_exact_matched` 控制。语义依赖不可用时保持 503，不静默降为文本匹配。
- `published_from/to` 包含端点，仅比较标准化文档 `document_metadata.publish_date` 的完整 ISO 日期。仅有年份/月份或缺失日期时不参加此过滤；不使用入库时间冒充发布日期。
- 招聘 `collected_from/to` 为采集时间；同时给出时须排序正确且时区表示一致。岗位字段保持源文本，不推导规范城市、数值薪资或技能频率。聚合白名单：job_title、company_name、industry、education、experience、company_size，最多三项且不可重复；缺失数包括 NULL 和空白文本。
- `/search` 默认知识类型仍为 course_textbook；`kb` 与 `knowledge_types` 二选一。knowledge_types 最多 10 项，asset_ids 与 normalized_ref_ids 各最多 100 项。范围不相交或仅含不可用文档时直接返回空命中；不会回退全库。多知识库按 chunk ID 去重、取最高 score，再取全局 top_k。
- 章节列表 `offset/limit` 是块列表偏移，limit 上限 100；每块预览 max_chars 上限 1000。片段详情 `offset` 为 Unicode 字符偏移，max_chars 上限 20000，adjacent_blocks 为两侧各 0–3 个块；邻接块的原始定位放在 locator.context_blocks。内容不注入锚点标记。
- 大纲 `offset/limit` 对节点列表分页，limit 上限 500；parent_node_id 返回包含父节点的子树。节点内容预览最多 4000 字符并带 content_truncated。
- 节点上下文 limit 上限 100、总 max_chars 上限 20000。续读同时传返回的 next_offset 与 next_char_offset；后一字段用于继续同一 chunk 的剩余字符，不跳过被截断尾部。chunk 带 content_offset、content_total_chars、truncated。
- 图谱 graph_type 支持 evidence_grounded_kg、teaching_standard、ability_analysis、job_demand、combined；只选该 ref 对应类型最新成功/生成结果。node_id 指定邻域；depth 为 0–5 的无向连接跳数，边仍保持原方向；节点与关系类型为重复参数。max_nodes≤500、max_edges≤1000，超限返回 truncated。证据图谱返回已有事实及每个节点/边最多三项证据；长证据文本、属性/限定词对象带截断标记。教学标准图谱还要求 active 库；talent_demand_report、teaching_case 返回 semantic_only_resource。
- 批量证据 max_chars 为每项预算（100–10000），结果保持输入顺序。业务记录遵循独立公开边界，不因其存在一个 ref 就绕过文档正文准入；不为 raw_jobs/园区/企业制造 ref。

## 权限、只读与审计

文档新读取及目录/检索限定为 available 版本的最新 generated ref。教材、标准、培养方案领域读取还需当前正式分类匹配，标准还需自身 active。当前 API Caller 权限为 `open:*`，组织过滤仍为 P0 noop，本次没有引入或宣称组织级数据隔离。

所有新增读取经 API Key 认证，新增消费接口记录 SEARCH_QUERY_EXECUTED、actor、资源/ID、数量和 trace_id，摘要不记录原文、自由检索文本、来源 URL 或 API Key。持久化 caller 在返回前重新校验撤销/过期状态，防止对象存储读取等较长请求继续返回数据。已有正文/chunk/下载沿用原有 lineage 审计。只读接口仅为审计提交事务，不写业务、图谱、大纲、治理或 job 表。

认证缺失/无效为 401，撤销/过期为 403，不可消费/不存在的单项为 404，参数/上下限/组合错误为 422；对象存储临时不可用为 503。批量证据以逐项 not_found 表达不可读取，不区分隐藏与未知 ID。

旧 `/major-profiles` 以及 `/job-demand-records`（含 record-assets 下的同名路径）保留 HTTP 兼容，OpenAPI 标记 deprecated；推荐简介走文档接口，当前市场岗位走 market-jobs。旧 `/record-assets/major-distribution-records` 及其 `/aggregate` 返回 410，并标记 deprecated，不进入工具清单。`/major-offerings/aggregate` 唯一绑定 API 同步与 Excel 导入的新领域事实；同路径旧文档聚合注册已移除。院校课程统计 `/major-courses/aggregate` 保留文档样本覆盖口径，不代表全国总体。旧底层文档读取保持既有 available 合同，新增确定性证据工具使用更严格的 current-ref 边界。

专业布点 Excel 下载使用 `GET /v1/major-offerings/export`（API caller）或 `/internal/v1/major-offerings/export`（Console 用户）。应用同一筛选与排序，导出全部匹配记录而非当前页；八列与列表一致，记录读取审计，不写业务数据。该二进制接口不列为 JSON function tool。

## Function tools 与使用示例

生成结果入口：[`../generated/public-function-tools/README.md`](../generated/public-function-tools/README.md)。同目录提供：

- `responses-tools.json`：可传给 Responses API 的 function tools 数组。
- `chat-completions-tools.json`：Chat Completions function wrapper 数组。
- `http-bindings.json`：工具名与 HTTP method/path、参数位置、数组重复编码、响应 Schema、认证注入和执行器默认值。

工具来自实际公开 OpenAPI，名称是稳定 operationId，输入按 path/query/body 分组；外部引用 Schema 全部解析为内联本地定义。流式及 deprecated 操作排除；本次没有 C 类 changes 路由。工具采用 strict=false，保留公开 API 的可选字段及自由证据对象，并由执行器继续按公开合同校验。

例如，模型调用 find_documents：

```json
{
  "query": {
    "resource_type": "industry_policy",
    "topic": "low_altitude",
    "region": "浙江",
    "published_from": "2025-01-01",
    "pageSize": 5
  }
}
```

执行器将 query 映射到 `GET /open/v1/assets`，注入 X-API-Key。选出 ref 后调用 search_evidence，并将 normalized_ref_ids 限定为已选资料；再用 read_document_section 或 get_evidence_bundle 获取原文依据。按资源标签按需加载工具，不必每次向模型传入整个清单。

外部搜索现行 HTTP 默认 auto_ingest=true 保持兼容。生成的消费工具将默认值设为 false；执行器必须在模型省略该字段时注入 false，显式 true 会启用既有入库逻辑。JSON Schema 的 default 本身不会执行参数注入。

### DeepSeek 联网搜索（2026-10-26）

`POST /open/v1/external-search/web-search` 的后端使用 DeepSeek Search，工具名保持 `search_web_search`。服务端通过 `BASE_URL_DEEPSEEK` 和 `API_KEY_DEEPSEEK` 访问 `/v1/tools/search`，使用 Bearer 认证及 `need_content=true`；调用方不提交供应商凭证。

请求 `query` 最多 90 字符，预留日期条件后的上游 128 字符限制；`count` 为 1–50，默认 10。`time_range` 默认 OneYear，支持 OneDay/OneWeek/OneMonth/OneYear（近 1/7/30/365 天）或 `YYYY-MM-DD..YYYY-MM-DD`；后者须为真实日期且起始不晚于结束。预设按 UTC 当前日解析，实际范围放在 `request.resolved_time_range`。响应 `provider=deepseek_search`，结果保留正文、来源 URL 和元数据；上游不提供的 request/log/time-cost ID 为 null。

工具调用示例：

```json
{
  "body": {
    "query": "电子商务产业发展报告",
    "count": 10,
    "time_range": "OneYear",
    "auto_ingest": false
  }
}
```

只读搜索不创建业务数据源、原始对象或作业，仅记录脱敏查询审计。启用入库时，URL/正文质量检查及正式文件 authority>=3 规则通过后才进入文档管道；rerank_score 不阻断准入。新来源代码 `ds_open_external_deepseek`，原始包标记 DeepSeek provider、connector_version 和 text 正文格式，重复结果复用已保留的原始对象。原始 JSON 不直接进入 AI 治理。

未配置 DeepSeek 或上游失败返回 503 `external_search_unavailable`，不暴露服务器配置及凭证，不切换其他供应商。Firecrawl 专用发现接口及 Query Router 独立实时回退配置仍分别遵循各自接口合同。

从仓库根目录重新生成或检查：

```bash
nexus-api/.venv/bin/python scripts/generate_public_function_tools.py
nexus-api/.venv/bin/python scripts/generate_public_function_tools.py --check
```

脚本只读取应用 Schema，不启动 lifespan、不查询数据库、不调用存储、嵌入、LLM 或第三方搜索。也支持 `--openapi <exported.json>` 使用导出的公开合同。

专业布点列表支持业务专家或数据管理员通过内部 `POST /internal/v1/major-offerings/import` 上传 .xlsx，下载 `/internal/v1/major-offerings/import-template` 空模板；不开放公开写入工具。列表来源字段 `sync_run_id` / `import_id` 二选一，记录可来自 API 同步或 Excel 导入；查询与聚合统计覆盖两者。
