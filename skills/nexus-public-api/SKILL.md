---
name: nexus-public-api
description: Call NEXUS public /open/v1 data tools (55 read-only tools across 16 resource tags) for documents, policies, major offerings, teaching standards, market jobs, enterprises, industrial parks, occupation dictionary, ability analyses, evidence bundles, knowledge chunks and web search. Use when the user asks for NEXUS asset-center data, vocational-education data, job/major/industry data, document citations or evidence, or explicitly asks to call a NEXUS public API.
---

# NEXUS Public API

通过 `/open/v1` 只读接口查询 NEXUS 资产中心公开数据。工具清单从公开 OpenAPI 生成，共 55 个工具、16 个资源标签；执行契约与参数 Schema 随 Skill 一起分发。

- 工具索引：直接运行 `list`，不要凭记忆猜工具名。
- 参数定义：调用前用 `schema <tool>` 查看，避免编造字段。
- 执行器：`scripts/nexus_call.py`（仅 Python 标准库，无第三方依赖）。

## 前置配置

```bash
export NEXUS_API_KEY=<api-key>                          # 必需，执行器注入 X-API-Key
export NEXUS_API_BASE_URL=http://127.0.0.1:8000          # 可选，默认本机 8000
```

API Key 只能来自环境变量。不要把它写进命令行参数、文件或日志。

## 使用流程

在 Skill 目录下执行。仓库内可用 `skills/nexus-public-api`；安装后可用 `~/.claude/skills/nexus-public-api`：

```bash
SKILL=skills/nexus-public-api

# 1. 按资源标签选最小工具集
python3 "$SKILL/scripts/nexus_call.py" list
python3 "$SKILL/scripts/nexus_call.py" list --tag public-business

# 2. 查看参数、执行器默认值与副作用
python3 "$SKILL/scripts/nexus_call.py" schema find_documents

# 3. 先 dry-run 核对 URL / body
python3 "$SKILL/scripts/nexus_call.py" call find_documents \
  '{"query":{"resource_type":"industry_policy","pageSize":5}}' --dry-run

# 4. 正式调用（输出响应 JSON；HTTP 状态与 trace_id 在 stderr）
python3 "$SKILL/scripts/nexus_call.py" call find_documents \
  '{"query":{"resource_type":"industry_policy","pageSize":5}}'
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

只加载当前任务需要的标签，不要一次向模型传入全部 55 个工具。

## 调用约定

- 数组查询参数使用 repeated keys，执行器自动编码；不要在 JSON 中拼接逗号串。
- 分页统一 `page`（默认 1）与 `pageSize`（默认 20，上限 200）。
- 外部搜索省略 `auto_ingest` 时执行器强制注入 `false`；显式 `true` 必须加 `--allow-ingest`，否则拒绝执行。
- 不可消费或不存在为 404，认证问题为 401/403，参数错误为 422，上游搜索或存储不可用为 503。
- 文档读取遵循 `available` + 最新 current ref；当前 `open:*` 权限不提供组织级过滤，不要声称已做组织隔离。

## 安全边界

- 只用只读查询；不要尝试调用写入、导入或内部 Console 接口。
- 不要把 L3/L4 明文、API Key、完整原文或自由检索文本写入日志或提交到外部服务。
- 引用正文时优先走 `search_evidence` → `read_document_section` / `get_evidence_bundle`，保留 chunk/ref 与 locator。

## 典型流程

见 `references/workflows.md`：文档发现与证据、结构化业务数据、联网搜索、一句话路由。

## 刷新资产

生成产物更新后同步并检查漂移：

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
