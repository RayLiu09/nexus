# Open API 详情与证据检索第二轮性能验收报告

**实测时间**：2026-11-16 15:47（Asia/Shanghai）  
**目标环境**：`http://10.100.11.51:8000`  通过本地 `.env.dev` 的 `BUILDIN_API_CALLER` 在进程内映射为 API Key；密钥没有写入脚本输出、报告或统计文件。  
**测试性质**：只读 GET，以及业务语义上只读的证据批量解析 POST；固定真实 ID 语料；不启动 Worker、不提交写入任务、不保存正文响应。

本轮覆盖任务3中依赖真实 ID 的详情、正文、章节、大纲、图谱、语义检索和证据接口。探针先验证 ID 链路和能力，再对每个接口执行 10 次请求、并发 4、超时 30 秒。响应正文只在内存中用于计算字节数和识别 `trace_id`，随后丢弃。脱敏统计见 [`open_api_detail_retrieval_perf_2026-11-16.json`](../testing/artifacts/open_api_detail_retrieval_perf_2026-11-16.json)，可复现探针见 [`open_api_detail_retrieval_perf.py`](../../tools/open_api_detail_retrieval_perf.py)。

## 真实 ID 语料与依赖链

| 对象 | ID | 用途 |
| --- | --- | --- |
| asset | `702681e6-6354-4c96-a18a-24e22077d44d` | 资产详情和版本列表 |
| normalized ref | `d02e497d-c818-4194-8793-c9fe555b62ad` | 产业报告详情、治理、正文、chunks、章节、图谱、搜索范围 |
| knowledge chunk | `f7592c05-45a0-4dd3-93ca-6b2ae2cbc0dd` | chunk 详情和证据解析 |
| document section | `web-block-0001` | 章节详情 |
| graph node | `884860f1-641d-4a63-b5a2-926e03525317` | 图谱节点范围过滤 |
| knowledge-outline ref | `18940e50-cd19-4c1c-b896-4543e38a13d2` | 知识大纲和节点上下文 |
| knowledge-outline node | `01722d82-63fd-43fe-86fc-312f80c8ae87` | 知识大纲节点上下文 |
| task-outline ref | `be6079d7-4ac8-43c3-b182-3558bb7344de` | 任务大纲和节点上下文 |
| task-outline node | `node-project-af9fe567b74e` | 任务大纲节点上下文 |

已验证的完整读取链路为：

```text
asset → asset versions → normalized ref → governance result
      → content → chunks → chunk detail → sections → section detail
      → graph → graph node scope → search → evidence bundle
```

两个教材 ref 分别覆盖知识大纲和任务大纲。它们都返回 `available=true`，并且节点上下文可读取；这避免把产业报告不具备大纲能力的 404 当作性能失败。语义检索请求使用 `urllib.parse.urlencode` 编码中文查询参数，避免直接拼接中文 URL 导致客户端编码异常。

## 性能结果

本轮共 170 次请求，耗时 2.788 秒，吞吐量 60.98 RPS。所有接口均为 10/10 成功、状态码 200、无传输错误；170/170 个成功响应带有 `meta.trace_id`。

| 接口 | P50 (ms) | P95 (ms) | P99 (ms) | 响应体 P95 (bytes) | 观察 |
| --- | ---: | ---: | ---: | ---: | --- |
| `GET /open/v1/assets/{asset_id}` | 23.472 | 28.836 | 28.836 | 27,601 | 正常 |
| `GET /open/v1/assets/{asset_id}/versions` | 14.028 | 24.992 | 24.992 | 719 | 正常 |
| `GET /open/v1/normalized-refs/{ref_id}` | 16.257 | 45.082 | 45.082 | 12,890 | 正常 |
| `GET /open/v1/normalized-refs/{ref_id}/governance-result` | 18.089 | 32.103 | 32.103 | 2,511 | 正常 |
| `GET /open/v1/normalized-refs/{ref_id}/content` | 137.131 | 173.921 | 173.921 | 302,410 | 正文读取的响应体最大，延迟随之升高 |
| `GET /open/v1/normalized-refs/{ref_id}/chunks` | 21.102 | 39.144 | 39.144 | 7,820 | 正常 |
| `GET /open/v1/knowledge-chunks/{chunk_id}` | 17.842 | 25.352 | 25.352 | 1,207 | 正常 |
| `GET /open/v1/normalized-refs/{ref_id}/sections` | 48.703 | 53.980 | 53.980 | 1,634 | 正常 |
| `GET /open/v1/normalized-refs/{ref_id}/sections/{section_id}` | 50.559 | 54.452 | 54.452 | 668 | 正常 |
| `GET /open/v1/normalized-refs/{ref_id}/knowledge-graph` | 79.221 | 100.405 | 100.405 | 48,285 | 图谱完整读取响应较大 |
| `GET /open/v1/normalized-refs/{ref_id}/knowledge-graph?node_id=...` | 36.824 | 302.212 | 302.212 | 41,130 | 尾延迟明显，列入后续专项分析 |
| `GET /open/v1/normalized-refs/{ref_id}/knowledge-outline` | 18.631 | 22.218 | 22.218 | 1,761 | 正常 |
| `GET .../outlines/knowledge/nodes/{node_id}/context` | 22.018 | 24.365 | 24.365 | 579 | 正常 |
| `GET /open/v1/normalized-refs/{ref_id}/task-outline` | 23.013 | 28.787 | 28.787 | 3,416 | 正常 |
| `GET .../outlines/task/nodes/{node_id}/context` | 36.855 | 42.160 | 42.160 | 4,680 | 正常 |
| `GET /open/v1/search` | 427.531 | 478.266 | 478.266 | 211 | 当前主要性能热点 |
| `POST /open/v1/evidence-resolutions` | 42.392 | 248.029 | 248.029 | 3,791 | 批量证据解析有尾延迟 |

## 结论与后续建议

- 详情、正文、章节、大纲、图谱、搜索和证据接口的真实 ID 读取链路已跑通，认证、响应契约和 trace 关联均通过本轮验收。
- `/open/v1/search` 的 P95 为 478.266 ms，明显高于其他轻量详情接口。后续优先拆分搜索耗时：向量召回、过滤条件下推、重排和结果序列化，并按同一 ref/query 语料做分段计时。
- 正文接口返回约 302 KB，P95 为 173.921 ms。对 Agent 检索应优先使用 chunks、sections 或大纲上下文的受限读取，只有需要全文时才调用 content；这能降低网络传输和上下文占用。
- 图谱节点范围查询 P95 为 302.212 ms，且响应约 41 KB。后续应检查 `node_id` 过滤是否在查询层生效，以及节点/边上限对 SQL 和序列化的影响。
- 证据批量解析的 P95 为 248.029 ms。可继续评估同一 normalized ref 下 chunk 与 ref 合并读取、批量查询和最大字符数预算，避免 Agent 在单轮中重复解析同一证据。
- 本轮是固定单语料的黑盒基线，不能据此推断不同 ref 大小、并发量、缓存命中率或向量后端负载下的容量。下一轮应在相同语料下增加冷/热缓存对照，并分别记录搜索阶段耗时。

可复现命令：

```bash
set -a; source .env.dev; set +a
export NEXUS_OPEN_API_KEY="$BUILDIN_API_CALLER"
python3 tools/open_api_detail_retrieval_perf.py \
  --base-url http://10.100.11.51:8000 \
  --requests-per-endpoint 10 --concurrency 4 --timeout-seconds 30 \
  --output docs/testing/artifacts/open_api_detail_retrieval_perf_2026-11-16.json
```
