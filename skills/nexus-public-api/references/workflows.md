# 典型调用流程

所有命令都在Skill目录下执行，示例省略`python3 scripts/nexus_call.py`前缀。先用`route`选择资产形态和最小工具集合；只有陌生工具、Schema变化或参数失败时再用`schema <tool>`。普通发现/检索用`--response-mode answer --max-output-chars 12000`，常驻serve默认answer。先取得有用内容作答；需要引用/复核时再取证。

## 0. 先选资产路由

```bash
route document
route --resource-type industry_policy
route market_jobs
```

路由输出包含推荐工具、资源分类、已知知识类型映射和默认预算。它不替代服务端权限校验，也不表示未映射资源类型已经有可用语义索引。

需要以服务端当前状态为准时，再调用 `discover_data_resources`；其中 `knowledge_types` 和 `retrieval_capabilities` 是资源发现返回的动态检索映射。空知识类型不应被 Agent 自行替换成资源编码。

## 1. 标签优先发现 → 有用内容 → 按需取证

```bash
# 1) 明确的业务标签优先精确检索；目录只确定候选，不等于取得正文
call find_documents '{"query":{"resource_type":"teaching_case","tag_type":"topic","tags":["数据安全"],"is_exact_matched":true,"tags_match":"all","pageSize":5}}' \
  --response-mode answer --max-output-chars 12000

# 也可按类型/主题发现；normalized_ref_id供后续限定范围
call find_documents '{"query":{"topic":"low_altitude","resource_type":"industry_report","pageSize":10}}' \
  --response-mode answer --max-output-chars 12000

# 2) 需要正文且标签/结构化字段不足时，读取相关章节或在限定范围语义检索。
#    answer返回有用正文和续查ID，省略locator/完整血缘。
#    industry_policy / industry_report / sector_report 必须显式使用 industry_research_kb。
call search_evidence '{"query":{"q":"低空经济 产业规模 增速","kb":"industry_research_kb","normalized_ref_ids":["<ref-id>"],"top_k":8}}' \
  --response-mode answer --max-output-chars 12000

# 新服务版本已部署后：显式启用服务端answer，减少HTTP体积。
# 检查data.response_view=answer；本地--response-mode不会自动启用此参数。
call search_evidence '{"query":{"q":"低空经济 产业规模 增速","kb":"industry_research_kb","normalized_ref_ids":["<ref-id>"],"top_k":8,"response_view":"answer","answer_max_chars":2000}}' \
  --response-mode answer --max-output-chars 12000

# 3) 未取得足够内容时才读取章节。依据标题/预览选择相关块，首块可能只是封面。
#    section_id必须来自list返回，不构造；已有足够正文则跳过。
#    list.offset 是 block 列表偏移；read.offset 是正文字符偏移。
call list_document_sections '{"path":{"ref_id":"<ref-id>"},"query":{"limit":20}}'
call read_document_section '{"path":{"ref_id":"<ref-id>","section_id":"<section-id>"},"query":{"max_chars":4000}}'

# 4) 用户需要引用或结论需核对原文时，才批量取证（最多30个引用）。
#    从真实搜索结果的ID构造refs.json；无需对所有候选都取证：
#    {"references":[{"kind":"chunk","id":"<chunk-id>"}],"max_chars":2000}
bundle --args-file refs.json --response-mode summary --max-output-chars 12000

# 5) 只有需要回答正文细节时才取正文，单条正文默认最多 2000 字符
bundle --args-file refs.json --response-mode content --max-content-chars 2000
```

不要将目录标题当正文。已有返回内容足够时不重复bundle。输出精确引用时再取得normalized_ref_id、chunk/block和locator，核对其支持结论。answer保留的ID仅用于续查，不代表已验证该引用。列表或正文被截断时，按需缩小范围/分页/续读，不冒充全量。

同一 Agent turn 需要连续调用多个公开工具时，可以把调用写成 JSONL 交给 `serve`，并传入同一个 `--trace-id`。每行返回独立的状态、耗时和响应字节数；执行器会复用同一服务 origin 的 HTTP 连接，并在本地先校验公开 Schema。

```bash
printf '%s\n' \
  '{"tool":"find_documents","args":{"query":{"resource_type":"industry_policy","pageSize":10}},"response_mode":"digest"}' \
  '{"tool":"search_evidence","args":{"query":{"q":"低空经济","kb":"industry_research_kb","top_k":8}},"response_mode":"digest"}' \
  | serve --trace-id turn-001
```

如果第二行参数依赖第一行返回的 ref 或 chunk，可以保持同一个 `serve` 进程，先写入第一行并读取输出，再写入第二行。不要在拿到标识前预先编造后续参数。

## 2. 结构化业务数据

```bash
# 市场岗位：region 按 raw_jobs.region 采集范围匹配，不推断工作地；统计优先 aggregate。
call query_market_jobs '{"query":{"job_title":"电商","region":"杭州","pageSize":20}}'
call aggregate_market_jobs '{"query":{"group_by":["education","experience"],"job_title":"电商"}}'

# 专业布点：仅代表已入库覆盖，不等同全国总体
call list_major_offerings '{"query":{"year":2025,"major_name":"电子商务","pageSize":20}}'
call aggregate_major_offerings '{"query":{"group_by":["province_name"]}}'

# 职业分类大典：大类/小类/名称 AND 组合
call query_occupation_dictionary '{"query":{"occupation_name":"电子商务师"}}'

# 教学标准：occupation 匹配职业面向原文/代码，可与专业条件 AND
call query_teaching_standards '{"query":{"occupation":"电子商务师","pageSize":10}}'

# 企业 / 园区
call query_enterprises '{"query":{"industry":"电子商务","pageSize":20}}'
call query_industrial_parks '{"query":{"industry":"电商","pageSize":20}}'
```

结构化岗位、企业、园区、专业布点、职业大典、教学标准、培养方案和能力分析应沿对应路由调用专用接口；只有用户明确要求某条记录的详情时，才继续调用其 get 接口。

聚合的 `total` 是分组数；岗位样本量看 `sample_count`。数组参数直接传 JSON 数组，执行器会展开为 repeated keys。

## 3. 联网搜索

内部资料不足时可走此流程：先明确缺的是正文、时效还是覆盖，保留已获得的平台事实；针对公开问题词调用一次网络搜索。仅本地/平台限定、敏感信息外传约束仍优先；500/503说明通道故障，不能作为“平台没有数据”的证据。

```bash
call search_web_search '{"body":{"query":"电子商务产业发展报告","count":5,"time_range":"OneYear","auto_ingest":false}}' \
  --response-mode answer --max-output-chars 12000
```

- `query` 最多 90 字符；`count` 1–50，默认 10。
- `time_range` 支持 `OneDay` / `OneWeek` / `OneMonth` / `OneYear`（默认）或 `YYYY-MM-DD..YYYY-MM-DD`。
- 省略 `auto_ingest` 时执行器注入 `false`；需要入库时显式 `"auto_ingest":true` 并加 `--allow-ingest`。
- 未配置供应商或上游失败返回 503；不要重试到其他搜索供应商。

答复示例结构：`【平台资产】已入库材料支持……`；`【联网搜索】某发布机构的《实际标题》（实际URL，发布日期有则填写）补充……`；`【分析归纳】基于上述材料建议……`。各结论链接对应来源，不能仅写“来源：互联网”。无发布日期就标未提供，可注明实际检索日期；摘要不足支持结论时降低结论强度。网页与库内统计不得混为同一总体，联网补充默认不入库。answer保留网络标题、URL、可用时间及内容，完整定位/平台原始对象仍按需读取。

## 4. 一句话路由与问答

```bash
# 服务端自动选择工具并返回 markdown、intent、invoked_tools、fallback_reason。
# 这不是所有资产检索的默认入口；先按路由使用专用接口。
call run_query_router_v2_open '{"body":{"query":"近一年电子商务岗位需求趋势"}}'

# 直接知识问答（返回答案与引用）
call qa_knowledge '{"query":{"q":"电子商务专业教学标准有哪些核心课程","top_k":5}}'
```

## 通用注意

- 分页 `page` 默认 1，`pageSize` 默认 20、上限 200；排序末项包含稳定 ID。
- 404 表示不可消费或不存在；422 表示参数越界/组合错误；503 表示检索、存储或上游暂不可用。
- 当前权限为 `open:*`，没有组织过滤；公开记录按各自领域边界返回。
- 不要用 `--dry-run` 的输出当作真实数据；它只用于核对 method、URL 和 body。
- 需要文件结果时使用 `--out-file <path>`，不要依赖 PowerShell 5.1 的 `>`；文件使用 UTF-8 无 BOM。
