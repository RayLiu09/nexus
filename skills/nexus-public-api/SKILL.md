---
name: nexus-public-api
description: Call NEXUS public /open/v1 data tools (55 read-only tools across 16 resource tags) for documents, policies, major offerings, teaching standards, market jobs, enterprises, industrial parks, occupation dictionary, ability analyses, evidence bundles, knowledge chunks and web search. Use when the user asks for NEXUS asset-center data, vocational-education data, job/major/industry data, document citations or evidence, or explicitly asks to call a NEXUS public API.
---

# NEXUS Public API

通过 `/open/v1` 只读接口查询 NEXUS 资产中心公开数据。工具清单从公开 OpenAPI 生成，共55个工具、16个资源标签，覆盖17类可见资产入口；执行契约与参数Schema随Skill一起分发。

- 检索路由：先运行 `route <route>` 或 `route --resource-type <type>`，只加载当前资产形态所需的最小工具集合。
- 工具索引：仅在路由无法覆盖任务或需要探索时运行 `list`，不要凭记忆猜工具名。
- 参数定义：陌生工具、Schema 版本变化或参数失败时用 `schema <tool>`；路由已列出的稳定工具不必每次重复读取 Schema。
- 作答内容：常驻`serve`默认`answer`，保留业务事实、相关正文和最小续查ID，省略完整血缘/定位数组。先用已返回内容分析；需要核对原文或输出精确引用时才用`bundle`/章节读取，避免每次检索后固定取证。
- 配置诊断：使用 `doctor` 查看密钥来源、base URL、工具数量、路由和生成资产一致性，不输出密钥值。
- 执行器：`scripts/nexus_call.py`（仅 Python 标准库，无第三方依赖）。

## 前置配置

```bash
export NEXUS_API_KEY=<api-key>                          # 必需，执行器注入 X-API-Key
export NEXUS_API_BASE_URL=http://127.0.0.1:8000          # 可选，默认本机 8000
```

API Key 默认从进程环境变量读取。Windows 需要显式读取用户或机器作用域时，使用 `--api-key-source windows-user|windows-machine`；`machine` 作用域通常可被同机其他账户读取，只应在明确接受该风险时使用。不要把它写进命令行参数、文件或日志。

## 使用流程

在 Skill 目录下执行。仓库内可用 `skills/nexus-public-api`；安装后可用 `~/.claude/skills/nexus-public-api`：

```bash
SKILL=skills/nexus-public-api

# 1. 按资源标签选最小工具集
python3 "$SKILL/scripts/nexus_call.py" route document
python3 "$SKILL/scripts/nexus_call.py" route --resource-type industry_policy

# 2. 仅在需要时查看参数、执行器默认值与副作用
python3 "$SKILL/scripts/nexus_call.py" schema find_documents

# 3. 先 dry-run 核对 URL / body
python3 "$SKILL/scripts/nexus_call.py" call find_documents \
  '{"query":{"resource_type":"industry_policy","pageSize":5}}' --dry-run

# 4. 正式调用（输出响应 JSON；HTTP 状态与 trace_id 在 stderr）
python3 "$SKILL/scripts/nexus_call.py" call find_documents \
  '{"query":{"resource_type":"industry_policy","pageSize":5}}' \
  --response-mode answer --max-output-chars 12000

# 5. 对搜索结果中的引用批量取证；refs.json 可是引用数组或 {"references":[...]} 对象
python3 "$SKILL/scripts/nexus_call.py" bundle --args-file refs.json \
  --response-mode summary --max-output-chars 12000

# 6. 需要正文时显式切换 content，并限制每条正文字符数
python3 "$SKILL/scripts/nexus_call.py" bundle --args-file refs.json \
  --response-mode content --max-content-chars 2000

# 7. 同一 Agent turn 需要连续调用多个工具时，可用 JSONL 常驻执行器复用连接
printf '%s\n' \
  '{"tool":"find_documents","args":{"query":{"pageSize":5}},"response_mode":"digest"}' \
  '{"tool":"search_evidence","args":{"query":{"q":"低空经济","kb":"industry_research_kb","top_k":8}},"response_mode":"digest"}' \
  | python3 "$SKILL/scripts/nexus_call.py" serve --trace-id turn-001

# 8. 输出到文件时不经过 shell 重定向，文件始终为 UTF-8 无 BOM
python3 "$SKILL/scripts/nexus_call.py" call find_documents \
  '{"query":{"pageSize":20}}' --response-mode digest --out-file result.json
```

参数 JSON 按 `path`、`query`、`body` 三组组织：

```json
{"path":{"ref_id":"..."},"query":{"page":1,"pageSize":20},"body":{"query":"..."}}
```

## 资源标签

| 标签 | 用途 |
| --- | --- |
| `assets` | 文档目录、资产详情、版本 |
| `public-business` | 教材、企业、园区、市场岗位、教学标准、标准课程、培养方案课程等业务记录 |
| `public-discovery` | 数据资源发现、实体消歧、专业简介 |
| `public-evidence` | 证据包、知识/任务大纲、章节、图谱 |
| `normalized-refs` | 归一化文档/记录、正文、chunks、治理结果 |
| `record-assets` | 能力分析、能力条目、关系、任务、岗位/职业能力图谱 |
| `talent-training-plans` | 人才培养方案及方案图谱 |
| `major-offerings` | 专业布点列表与聚合 |
| `occupation-dictionary` | 职业分类大典 |
| `search` / `qa` / `query` | 语义检索、知识问答、一句话路由 |
| `knowledge-chunks` / `raw-objects` | 单个知识块、原始文件下载地址 |
| `major-courses` | 院校课程统计 |
| `external-search` | Firecrawl 与 DeepSeek 联网搜索 |

只加载当前任务需要的标签，不要一次向模型传入全部55个工具。

## 资产形态路由

`assets/retrieval-routes.json` 是工具选择和知识类型映射的机器可读基线。`route` 输出只是一份选择提示，不能授予超出 Skill 或服务端权限的能力。

- 文档、政策、报告、专业简介、教材和案例：使用 `document` 路由；先目录/标签发现，再按内容需求读取相关正文或限定范围语义检索。已知业务标签足够表达问题时，优先指定`tag_type`、`tags`和`is_exact_matched=true`；多个条件须全部满足时用`tags_match=all`。标签只证明资料匹配，目录本身不能支持正文结论。精确标签不足才根据问题转语义标签/内容检索，不全局强制改写匹配模式。
- 岗位、企业、园区、专业布点、职业大典、教学标准、培养方案和能力分析：优先使用对应结构化路由的 list/query/aggregate 工具，不用通用文档检索替代。
- normalized ref、chunk、section 和图谱：必须先使用已返回的 ref 或节点锚点，再读取详情。
- 外部搜索：内部数据不足以支撑问题（零命中、只有标题、正文缺失、时效/覆盖不足）时可使用`external_search`，无需为了这次只读补充再询问用户；用户限定仅本地/平台或问题涉及敏感材料时遵守其边界。不要把500/503直接解释为库内无数据。只发送公开问题词，不向外传内部正文；默认保持`auto_ingest=false`。答复区分`【平台资产】`、`【联网搜索】`和模型的`【分析归纳】`，网络来源注明真实标题、URL及可用的发布/访问时间；不得编造日期、把网页称为已入库资产，或把检索摘要写成已核实全文。

文档检索的知识类型必须遵循路由映射：`industry_policy`、`industry_report`、`sector_report` 使用 `kb=industry_research_kb`，`course_textbook` 使用 `kb=course_textbook`。路由输出中知识类型映射为空数组表示当前没有固化的语义索引，不要猜测 `kb`；先使用对应专用接口或报告数据缺口。

需要动态确认资源能力时调用 `discover_data_resources`：响应中的 `knowledge_types` 是可直接传给 `/search` 的实际类型，`retrieval_capabilities` 是公开通道能力，优先级高于资源名称或模型猜测。空的 `knowledge_types` 表示当前没有固化语义索引，应沿 `structured_query`、`catalog` 或其他明确能力继续。

不要把第一页列表当作全量统计；需要数量或分布时使用对应的 aggregate 工具。

`call` 默认full保持完整JSON兼容；skill普通检索显式使用`--response-mode answer --max-output-chars 12000`，`serve`默认answer。`answer`保留有助作答的正文/业务字段、分页/总量/缺失值及最小续查ID，不返回完整metadata/lineage/locator；网络检索保留标题、URL和时间字段，并标记`source_kind=web`，普通平台工具标记platform；可能混合来源的服务端问答/路由标记mixed_or_unspecified，应继续核对其逐项来源。该标记表示取数通道，不保证事实正确。

按需取证用`digest|content|full`：`digest`保留chunk/ref/locator和有限正文，但不重复完整metadata图片数组；`content`按`--max-content-chars`截断文本；`summary`省略常见正文。answer预算不足时逐级缩减正文及返回数组，标记`*_truncated`、`*_total_count`和`*_returned_count`，原始meta.total/sample_count保留。截断列表不能视为完整分布；需要全量分析时分页或使用聚合并分批处理。极小预算可能只保留错误/trace，应缩小查询范围。以上为HTTP读取后的本地投影，本地模式本身不减少服务端响应体或下载耗时。

标准课程列表超预算时先尝试完整保留本页课程ID、名称和类型（`projection=course_directory`），再考虑抽样；这时正文、标签、学时等省略字段需按返回ID用`get_standard_course`读取，不能将未返回字段解释为缺失。本页完整也不等于所有分页完整。

`serve` 从 stdin 读取 JSONL，每行格式为 `{"tool":"<name>","args":{"path":{},"query":{},"body":{}},"trace_id":"<optional>","response_mode":"<optional>","max_content_chars":2000,"max_output_chars":<optional>}`，每行返回一个带 `status`、`trace_id`、`elapsed_ms`、`response_bytes` 和实际 `response_mode` 的 JSON。它在同一 origin 内复用 HTTP/HTTPS 连接；可以预置多个独立调用，也可以交互式写入一行、读取结果后再写入依赖前序结果的一行。普通 `call` 仍是单次进程调用。

执行器默认在本地按公开工具Schema校验请求，错误会在发起HTTP请求前返回字段路径；只有确认服务端Schema暂时领先于随Skill分发的产物时，才显式使用`--no-validate`。HTTP错误/连接关闭后丢弃连接，下一条请求重新连接；不自动重试，不掩盖原始失败。trace、状态、耗时和响应字节数不会包含API Key、请求参数或完整响应正文。

## 调用约定

- 数组查询参数使用 repeated keys，执行器自动编码；不要在 JSON 中拼接逗号串。
- 分页统一 `page`（默认 1）与 `pageSize`（默认 20，上限 200）。
- 外部搜索省略 `auto_ingest` 时执行器强制注入 `false`；显式 `true` 必须加 `--allow-ingest`，否则拒绝执行。
- 不可消费或不存在为 404，认证问题为 401/403，参数错误为 422，上游搜索或存储不可用为 503。
- 文档读取遵循 `available` + 最新 current ref；当前 `open:*` 权限不提供组织级过滤，不要声称已做组织隔离。
- `read_document_section` 的 `section_id` 必须使用同一次 `list_document_sections` 返回的 `data.items[].id`，不能自行构造。list 的 `offset` 是 block 列表偏移；read 的 `offset` 是正文字符偏移。

## 安全边界

- 只用只读查询；不要尝试调用写入、导入或内部 Console 接口。
- 不要把 L3/L4 明文、API Key、完整原文或自由检索文本写入日志或提交到外部服务。
- 引用正文时优先走 `search_evidence` → `read_document_section` / `get_evidence_bundle`，保留 chunk/ref 与 locator。

## 典型流程

见 `references/workflows.md`：文档发现与证据、结构化业务数据、联网搜索、一句话路由。

## 刷新资产

生成产物更新后同步并检查漂移。`--check` 现在同时比较 docs 生成产物、Skill 内资产和 `retrieval-routes.json` 引用的工具名：

```bash
cp docs/generated/public-function-tools/responses-tools.json \
   docs/generated/public-function-tools/http-bindings.json \
   skills/nexus-public-api/assets/
nexus-api/.venv/bin/python scripts/generate_public_function_tools.py --check
```

## 安装与项目内启用

仓库内通过 `.claude/skills/` 的符号链接自动发现；新克隆后执行一次：

```bash
mkdir -p .claude/skills
ln -s ../../skills/nexus-public-api .claude/skills/nexus-public-api
```

安装到用户级供其他项目使用：

```bash
cp -r skills/nexus-public-api ~/.claude/skills/
```
