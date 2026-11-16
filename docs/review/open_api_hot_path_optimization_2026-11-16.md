# Open API 高频检索路径优化记录

本次针对高频的 `/open/v1/search` 和 `/open/v1/normalized-refs/{ref_id}/content` 实施内部性能优化。接口路径、请求参数、响应字段、可用版本门禁、权限过滤和审计事件均保持不变。

上一轮真实环境基线见 [`open_api_detail_retrieval_performance_report_2026-11-16.md`](open_api_detail_retrieval_performance_report_2026-11-16.md)：`/open/v1/search` P95 为 478.266 ms，正文接口 P95 为 173.921 ms，正文响应体 P95 约 302 KB。

## 实施内容

### 正文读取

- 在每个 API worker 内增加有界 TTL 缓存，键为 `normalized_ref.id + checksum + object_uri`。
- 默认 TTL 为 120 秒，最多缓存 16 个已解析 payload，避免跨版本或对象地址复用旧内容，也限制大正文常驻内存。
- 缓存命中时跳过对象存储读取和 JSON 解码；缓存只保存已成功解析的 JSON 对象，404、503 和非法 JSON 不会进入缓存。
- 将 ref 和 version 的读取合并为一次 version 查询，避免先调用可用性检查再重复读取 version。
- 使用 `json.loads(bytes)` 直接解析对象存储返回值，去掉额外的 UTF-8 decode 中间对象。

### 语义检索

- 增加按 `embedding_model + dimension + exact query` 索引的 60 秒进程内 embedding 缓存，最多 512 条。
- 生产适配器共享 worker 级缓存；注入测试或特殊 provider 时使用独立缓存，避免向量跨 provider 复用。
- 空候选集仍在 embedding 前短路，保持原有无结果语义。
- `_enrich_with_nexus_refs` 已加载的 version 可用状态通过内部标记传给过滤阶段，避免每次搜索再次查询同一批 version。内部标记在响应序列化前移除。
- 命中结果的 ref 过滤使用集合成员判断，保持结果顺序和去重规则不变。

## 验证

- `nexus-app/tests/index/test_pgvector_search.py`：3/3 通过，新增测试确认同一 adapter 对重复 query 只调用一次 embedding provider，返回结果保持一致。
- `python3 -m py_compile`：API、缓存、适配器及相关测试文件通过。
- 缓存 smoke checks：命中、TTL 数据结构、容量淘汰、available 过滤和内部标记清理通过。
- `git diff --check`：通过。
- `nexus-api/tests/test_lineage_endpoints.py -k reuses_cached_payload` 在当前环境 180 秒内未完成，耗时发生在完整 SQLite schema fixture 初始化阶段，未产生测试断言结果；需要在常规 CI 或已初始化测试数据库环境中执行该接口回归。

## 风险与后续测量

缓存是单进程的，多个 worker 之间不会共享；首次请求或缓存过期后的并发请求仍可能各自完成一次加载。缓存键包含 checksum 和 object URI，normalized ref 内容变化会自然产生新键。embedding 缓存只复用相同模型、维度和查询文本的向量，不改变召回阈值、排序或权限结果。

部署新版本后，应使用上一轮相同的真实 ID 语料和并发条件复测，并额外比较：

1. `/open/v1/normalized-refs/{ref_id}/content` 冷缓存与热缓存的对象存储请求数、P50/P95；
2. `/open/v1/search` 重复 query 与唯一 query 的 embedding provider 调用次数和 P95；
3. 搜索结果中的 `trace_id`、可用版本过滤、审计记录和响应字段是否与基线一致。
