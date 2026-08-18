# /open/v1 开放资产检索接口文档

本文档描述 NEXUS 当前实际注册的 `/open/v1` 开放接口中，面向上游系统进行数据资产检索、知识检索、结构化记录查询、检索结果溯源和请求级公网搜索的接口。

依据源码：

- `nexus-api/nexus_api/api/open.py`
- `nexus-api/nexus_api/api/open_record_assets.py`
- `nexus-api/nexus_api/api/major_profiles.py`
- `nexus-api/nexus_api/api/talent_training_plans.py`
- `nexus-api/nexus_api/api/external_search.py`
- `nexus-api/nexus_api/main.py`

## 1. 通用约定

### 1.1 Base URL

```text
{nexus-api-base-url}/open/v1
```

本地开发环境常见地址：

```text
http://127.0.0.1:8000/open/v1
```

### 1.2 认证

所有 `/open/v1/*` 接口都需要 API Caller 凭证。任选一种方式传入：

```http
X-API-Key: <caller_key>
```

或：

```http
Authorization: Bearer <caller_key>
```

认证失败：

- `401`: 未提供 API Key，或 API Key 无效。
- `403`: API Key 已过期或已撤销。

### 1.3 Trace

可选传入：

```http
X-Trace-Id: <trace-id>
```

服务端响应 `meta.trace_id` 会返回本次请求链路 ID；检索与读取类接口也会写入审计日志。

### 1.4 返回信封

单对象接口统一返回：

```json
{
  "data": {},
  "meta": {
    "trace_id": "string",
    "page": null,
    "page_size": null,
    "total": null
  }
}
```

列表接口统一返回：

```json
{
  "data": [],
  "meta": {
    "trace_id": "string",
    "page": 1,
    "page_size": 20,
    "total": 0
  },
  "aggregations": null
}
```

错误响应通常为：

```json
{
  "error": {
    "code": "string",
    "message": "string",
    "details": []
  },
  "meta": {
    "trace_id": "string"
  }
}
```

FastAPI 参数校验失败会返回 `422`。

### 1.5 分页参数

分页列表接口支持：

| 参数 | 位置 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- | --- |
| `page` | query | integer | 否 | `1` | `1 <= page <= 10000` | 页码 |
| `pageSize` | query | integer | 否 | `20` | `1 <= pageSize <= 200` | 每页条数 |

### 1.6 可见性规则

开放资产目录、规范化资产、知识 chunk、原文件下载、专业画像、人才培养方案和专业分布记录默认只暴露已达到 `available` 版本的数据。

例外：`/open/v1/record-assets/job-demand-records` 为 Pipeline B 结构化领域事实查询，当前实现按领域事实表跨数据集查询，不强制 `asset_version=available`。

## 2. 接口总览

| 分类 | 方法 | Endpoint | 用途 |
| --- | --- | --- | --- |
| 资产目录 | GET | `/open/v1/assets` | 查询可用资产目录，支持领域和治理标签过滤 |
| 资产目录 | GET | `/open/v1/assets/{asset_id}` | 获取可用资产详情 |
| 资产目录 | GET | `/open/v1/assets/{asset_id}/versions` | 获取资产可用版本列表 |
| 规范化资产 | GET | `/open/v1/normalized-refs/{ref_id}` | 获取可用 `normalized_asset_ref` 元数据 |
| 规范化资产 | GET | `/open/v1/normalized-refs/{ref_id}/governance-result` | 获取公开脱敏后的治理结果 |
| 规范化资产 | GET | `/open/v1/normalized-refs/{ref_id}/content` | 获取规范化正文、blocks、toc 或 record body |
| 知识切片 | GET | `/open/v1/knowledge-chunks/{chunk_id}` | 按 chunk ID 获取引用内容 |
| 知识切片 | GET | `/open/v1/normalized-refs/{ref_id}/chunks` | 获取某规范化资产下的 chunk 列表 |
| 原文下载 | GET | `/open/v1/raw-objects/{raw_object_id}/download-url` | 获取原文件短期下载 URL |
| 语义检索 | GET | `/open/v1/search` | 基于 pgvector 的知识 chunk 检索 |
| 问答检索 | GET | `/open/v1/qa` | 基于检索来源生成问答结果 |
| 智能检索 | POST | `/open/v1/query` | Query Router v2 聚合检索与回答 |
| 智能检索 | POST | `/open/v1/query/stream` | Query Router v2 SSE 流式检索与回答 |
| 联网搜索 | POST | `/open/v1/external-search/firecrawl` | Firecrawl URL 发现搜索，返回标题、URL、摘要 |
| 联网搜索 | POST | `/open/v1/external-search/web-search` | Web Search 内容搜索，返回正文/摘要和供应商元数据 |
| 专业画像 | GET | `/open/v1/major-profiles` | 查询可用专业画像 |
| 专业画像 | GET | `/open/v1/major-profiles/{profile_id}` | 获取专业画像详情 |
| 人才培养方案 | GET | `/open/v1/talent-training-plans` | 按院校、专业、岗位、技能、证书、课程等结构化条件查询可用方案 |
| 人才培养方案 | GET | `/open/v1/talent-training-plans/{plan_id}` | 获取方案、课程及来源证据详情 |
| 人才培养方案 | GET | `/open/v1/talent-training-plans/{plan_id}/course-knowledge-graph` | 获取方案范围内的确定性课程知识图谱 |
| 人才培养方案 | GET | `/open/v1/talent-training-plans/{plan_id}/position-capability-graph` | 获取方案范围内可选的岗位能力图谱 |
| 职业能力分析 | GET | `/open/v1/record-assets/ability-analyses` | 查询职业能力分析资产 |
| 职业能力分析 | GET | `/open/v1/record-assets/ability-analyses/{analysis_id}` | 获取职业能力分析详情 |
| 职业能力分析 | GET | `/open/v1/record-assets/ability-analyses/{analysis_id}/tasks` | 获取职业任务树 |
| 职业能力分析 | GET | `/open/v1/record-assets/ability-analyses/{analysis_id}/ability-items` | 获取能力项列表 |
| 职业能力分析 | GET | `/open/v1/record-assets/ability-analyses/{analysis_id}/relations` | 获取能力关系列表 |
| 就业需求 | GET | `/open/v1/record-assets/job-demand-records` | 跨数据集查询岗位需求记录 |
| 就业需求 | GET | `/open/v1/record-assets/job-demand-records/aggregate` | 聚合查询岗位需求统计（TOP / 学历 / 经验 / 薪资分布） |
| 就业需求 | GET | `/open/v1/record-assets/job-demand-records/{record_id}` | 获取岗位需求记录详情 |
| 就业需求 | GET | `/open/v1/record-assets/job-demand-records/{record_id}/requirement-items` | 获取岗位需求抽取项 |
| 专业分布 | GET | `/open/v1/record-assets/major-distribution-records` | 查询专业分布记录 |
| 专业分布 | GET | `/open/v1/record-assets/major-distribution-records/aggregate` | 聚合查询专业分布统计 |
| 知识图谱 | GET | `/open/v1/record-assets/graphs/job-capability` | 按岗位查询岗位能力图谱 |
| 知识图谱 | GET | `/open/v1/record-assets/graphs/occupational-capability` | 按专业查询职业能力图谱 |
| 知识图谱 | GET | `/open/v1/record-assets/graphs/teaching-standard-knowledge` | 按专业查询教学标准知识图谱 |

## 3. 资产目录接口

### 3.1 查询可用资产目录

```http
GET /open/v1/assets
```

#### 参数

| 参数 | 位置 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- | --- |
| `domain` | query | string | 否 | - | `1..64` | 治理分类，精确匹配 `governance_result.classification` |
| `tag_type` | query | string | 否 | - | `1..32` | 标签类型，支持 `region`、`industry`、`occupation`、`major`、`ability`、`topic`、`time_range` |
| `tags` | query | array[string] | 否 | - | 1 到 10 个，每个非空且不超过 256 字符 | 可重复传入，如 `?tags=零售&tags=门店`；任一标签命中即可返回 |
| `is_exact_matched` | query | boolean | 否 | `false` | - | `true` 使用归一化标签精确匹配；`false` 使用语义标签召回 |
| `page` | query | integer | 否 | `1` | `1..10000` | 页码 |
| `pageSize` | query | integer | 否 | `20` | `1..200` | 每页条数 |

#### 返回结构

```json
{
  "data": [
    {
      "id": "asset_id",
      "data_source_id": "data_source_id",
      "source_object_key": "file.pdf",
      "asset_kind": "document",
      "title": "资产标题",
      "status": "available",
      "domain": "course_textbook",
      "normalized_ref_id": "normalized_ref_id",
      "version_id": "asset_version_id",
      "raw_object_id": "raw_object_id",
      "tags": [
        { "type": "major", "value": "电子商务" }
      ],
      "download_url_endpoint": "/open/v1/raw-objects/{raw_object_id}/download-url",
      "created_at": "2026-07-31T10:00:00",
      "updated_at": "2026-07-31T10:00:00"
    }
  ],
  "meta": {
    "trace_id": "trace_id",
    "page": 1,
    "page_size": 20,
    "total": 1
  },
  "aggregations": null
}
```

字段以当前 `OpenAssetCatalogRead` 序列化为准；除上例字段外，可能包含基础资产读模型中的扩展字段。

### 3.2 获取资产详情

```http
GET /open/v1/assets/{asset_id}
```

#### 参数

| 参数 | 位置 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| `asset_id` | path | string | 是 | 资产 ID |

#### 返回结构

```json
{
  "data": {
    "asset": {
      "id": "asset_id",
      "data_source_id": "data_source_id",
      "source_object_key": "file.pdf",
      "asset_kind": "document",
      "title": "资产标题",
      "status": "available",
      "created_at": "2026-07-31T10:00:00",
      "updated_at": "2026-07-31T10:00:00"
    },
    "versions": [
      {
        "id": "asset_version_id",
        "asset_id": "asset_id",
        "version_no": 1,
        "version_status": "available",
        "raw_object_id": "raw_object_id",
        "created_at": "2026-07-31T10:00:00"
      }
    ],
    "normalized_refs": [
      {
        "id": "normalized_ref_id",
        "version_id": "asset_version_id",
        "normalized_type": "normalized_document",
        "object_uri": "s3://bucket/normalized/xxx.json",
        "checksum": "checksum",
        "created_at": "2026-07-31T10:00:00"
      }
    ],
    "current_version": {},
    "current_normalized_ref": {}
  },
  "meta": { "trace_id": "trace_id" }
}
```

只返回有 `available` 版本的资产；资产不存在或没有可用版本时返回 `404`。

### 3.3 获取资产可用版本列表

```http
GET /open/v1/assets/{asset_id}/versions
```

#### 参数

| 参数 | 位置 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| `asset_id` | path | string | 是 | 资产 ID |

#### 返回结构

```json
{
  "data": [
    {
      "id": "asset_version_id",
      "asset_id": "asset_id",
      "version_no": 1,
      "version_status": "available",
      "raw_object_id": "raw_object_id",
      "created_at": "2026-07-31T10:00:00"
    }
  ],
  "meta": {
    "trace_id": "trace_id",
    "page": 1,
    "page_size": 100,
    "total": 1
  },
  "aggregations": null
}
```

## 4. 规范化资产与内容接口

### 4.1 获取规范化资产引用

```http
GET /open/v1/normalized-refs/{ref_id}
```

#### 参数

| 参数 | 位置 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| `ref_id` | path | string | 是 | `normalized_asset_ref.id` |

#### 返回结构

```json
{
  "data": {
    "id": "normalized_ref_id",
    "version_id": "asset_version_id",
    "normalized_type": "normalized_document",
    "object_uri": "s3://bucket/normalized/xxx.json",
    "checksum": "checksum",
    "source_type": "document",
    "content_type": "application/pdf",
    "title": "资产标题",
    "language": "zh",
    "governance": {},
    "quality": {},
    "lineage": {},
    "created_at": "2026-07-31T10:00:00"
  },
  "meta": { "trace_id": "trace_id" }
}
```

仅当关联资产版本为 `available` 时返回，否则 `404`。

### 4.2 获取公开治理结果

```http
GET /open/v1/normalized-refs/{ref_id}/governance-result
```

#### 参数

| 参数 | 位置 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| `ref_id` | path | string | 是 | `normalized_asset_ref.id` |

#### 返回结构

```json
{
  "data": {
    "classification": "course_textbook",
    "level": "L1",
    "tags": [],
    "quality_summary": {}
  },
  "meta": { "trace_id": "trace_id" }
}
```

返回内容强制使用 `public` 视图脱敏；决策链、AI 建议和置信度等内部字段不会暴露。

### 4.3 获取规范化正文内容

```http
GET /open/v1/normalized-refs/{ref_id}/content
```

#### 参数

| 参数 | 位置 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| `ref_id` | path | string | 是 | `normalized_asset_ref.id` |

#### 返回结构

```json
{
  "data": {
    "ref_id": "normalized_ref_id",
    "asset_id": "asset_id",
    "version_id": "asset_version_id",
    "normalized_type": "normalized_document",
    "body_markdown": "# 正文",
    "blocks": [
      {
        "id": "block_id",
        "type": "text",
        "text": "段落文本",
        "md_char_range": [0, 12],
        "page_no": 1
      }
    ],
    "toc": [],
    "record_body": null
  },
  "meta": { "trace_id": "trace_id" }
}
```

文档类资产主要返回 `body_markdown`、`blocks`、`toc`；记录类资产可能返回 `record_body`。

## 5. 知识切片与原文溯源接口

### 5.1 获取单个知识 chunk

```http
GET /open/v1/knowledge-chunks/{chunk_id}
```

#### 参数

| 参数 | 位置 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| `chunk_id` | path | string | 是 | `knowledge_chunk.id` |

#### 返回结构

```json
{
  "data": {
    "id": "chunk_id",
    "normalized_ref_id": "normalized_ref_id",
    "knowledge_type_code": "course_textbook",
    "chunk_type": "semantic_chunk",
    "chunk_index": 1,
    "content": "chunk 文本",
    "version_id": "asset_version_id",
    "asset_id": "asset_id",
    "locator": {
      "page_start": 1,
      "page_end": 1,
      "bbox_union": []
    },
    "source_block_ids": ["block_id"],
    "primary_block_ids": ["block_id"],
    "evidence_block_ids": ["block_id"]
  },
  "meta": { "trace_id": "trace_id" }
}
```

`primary_block_ids`、`evidence_block_ids` 仅在 chunk 元数据中存在时返回。

### 5.2 获取规范化资产下的 chunks

```http
GET /open/v1/normalized-refs/{ref_id}/chunks
```

#### 参数

| 参数 | 位置 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- | --- |
| `ref_id` | path | string | 是 | - | - | `normalized_asset_ref.id` |
| `page` | query | integer | 否 | `1` | `1..10000` | 页码 |
| `pageSize` | query | integer | 否 | `20` | `1..200` | 每页条数 |

#### 返回结构

```json
{
  "data": [
    {
      "id": "chunk_id",
      "normalized_ref_id": "normalized_ref_id",
      "knowledge_type_code": "course_textbook",
      "chunk_type": "semantic_chunk",
      "chunk_index": 1,
      "content": "chunk 文本",
      "version_id": "asset_version_id",
      "asset_id": "asset_id",
      "locator": {},
      "source_block_ids": []
    }
  ],
  "meta": {
    "trace_id": "trace_id",
    "page": 1,
    "page_size": 20,
    "total": 1
  },
  "aggregations": null
}
```

### 5.3 获取原文件下载 URL

```http
GET /open/v1/raw-objects/{raw_object_id}/download-url
```

#### 参数

| 参数 | 位置 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- | --- |
| `raw_object_id` | path | string | 是 | - | - | 原始文件对象 ID |
| `ttl_seconds` | query | integer | 否 | `900` | `60..3600` | 预签名 URL 有效期，单位秒 |

#### 返回结构

```json
{
  "data": {
    "raw_object_id": "raw_object_id",
    "download_url": "https://minio.example.com/...",
    "expires_at": "2026-07-31T10:15:00+00:00",
    "ttl_seconds": 900
  },
  "meta": { "trace_id": "trace_id" }
}
```

仅当该 `raw_object` 至少关联一个 `available` 资产版本时可下载。

## 6. 语义检索、问答和智能检索接口

### 6.1 语义检索

```http
GET /open/v1/search
```

#### 参数

| 参数 | 位置 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- | --- |
| `q` | query | string | 是 | - | `1..1024` | 检索查询 |
| `kb` | query | string | 否 | `course_textbook` | `<=128` | 知识类型代码；`textbook_kb` 为兼容值 |
| `top_k` | query | integer | 否 | `10` | `1..100` | 最大返回结果数 |
| `similarity_threshold` | query | number | 否 | `0.7` | `0.0..1.0` | 最低相似度阈值 |
| `outline_node` | query | string | 否 | - | `<=36` | 限定在某个知识大纲节点子树下检索 |

#### 返回结构

```json
{
  "data": {
    "query": "现代零售行业的关键特征是什么",
    "kb": "course_textbook",
    "results": [
      {
        "id": "backend_hit_id",
        "score": 0.92,
        "content": "命中的 chunk 文本",
        "nexus_chunk_id": "chunk_id",
        "normalized_ref_id": "normalized_ref_id",
        "version_id": "asset_version_id",
        "asset_id": "asset_id",
        "raw_object_id": "raw_object_id",
        "raw_object_uri": "s3://bucket/raw/file.pdf",
        "data_source_id": "data_source_id",
        "locator": {},
        "source_block_ids": [],
        "primary_block_ids": [],
        "evidence_block_ids": [],
        "knowledge_outline": {
          "node_id": "outline_node_id",
          "title": "知识点1：现代零售行业的四大关键特征",
          "numbering": "1",
          "level": 1,
          "path": [
            {
              "id": "outline_node_id",
              "title": "知识点1：现代零售行业的四大关键特征",
              "numbering": "1",
              "level": 1
            }
          ]
        }
      }
    ],
    "count": 1,
    "caller_id": "api_caller_id"
  },
  "meta": { "trace_id": "trace_id" }
}
```

结果会在返回前过滤为可用资产版本，并应用 API Caller 权限过滤。

### 6.2 检索问答

```http
GET /open/v1/qa
```

#### 参数

| 参数 | 位置 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- | --- |
| `q` | query | string | 是 | - | `1..2048` | 问题文本 |
| `kb` | query | string | 否 | `course_textbook` | `<=128` | 知识类型代码 |
| `top_k` | query | integer | 否 | `5` | `1..50` | 最大引用来源数 |

#### 返回结构

```json
{
  "data": {
    "question": "什么是白平衡，如何调节",
    "kb": "course_textbook",
    "caller_id": "api_caller_id",
    "answer": "回答正文",
    "sources": [
      {
        "score": 0.91,
        "content": "引用来源 chunk 文本",
        "nexus_chunk_id": "chunk_id",
        "normalized_ref_id": "normalized_ref_id",
        "version_id": "asset_version_id",
        "asset_id": "asset_id",
        "locator": {},
        "source_block_ids": [],
        "knowledge_outline": {}
      }
    ],
    "answer_confidence": 0.91
  },
  "meta": { "trace_id": "trace_id" }
}
```

`answer_confidence` 当前由引用来源中的最高检索分数派生；没有可用分数时为 `null`。

### 6.3 智能检索

```http
POST /open/v1/query
Content-Type: application/json
```

#### 请求体

| 字段 | 类型 | 必填 | 约束 | 说明 |
| --- | --- | --- | --- | --- |
| `query` | string | 是 | `1..2048` | 用户自然语言问题 |

示例：

```json
{
  "query": "现代零售行业的关键特征是什么"
}
```

#### 返回结构

```json
{
  "data": {
    "markdown": "回答正文，Markdown 格式",
    "intent": "semantic_chunk",
    "intent_confidence": 0.95,
    "invoked_tools": ["semantic_chunk"],
    "fallback_reason": null,
    "warnings": [],
    "audit_summary": {
      "query_hash": "hash",
      "route": "open_query",
      "caller_type": "api_caller"
    },
    "external_web_results": [],
    "section_contexts": [
      {
        "title": "知识点1：现代零售行业的四大关键特征",
        "normalized_ref_id": "normalized_ref_id",
        "asset_id": "asset_id",
        "chunks": []
      }
    ]
  },
  "meta": { "trace_id": "trace_id" }
}
```

该接口是开放侧 Query Router v2 主入口，会根据问题意图调用结构化工具、语义 chunk 检索、Web fallback 等能力，并返回最终 Markdown 答案和检索过程摘要。

### 6.4 智能检索流式接口

```http
POST /open/v1/query/stream
Content-Type: application/json
Accept: text/event-stream
```

#### 请求体

| 字段 | 类型 | 必填 | 约束 | 说明 |
| --- | --- | --- | --- | --- |
| `query` | string | 是 | `1..2048` | 用户自然语言问题 |

#### 返回结构

响应类型为：

```http
Content-Type: text/event-stream
```

SSE frame 由 `nexus_api.query_router_v2_sse.serialise_router_stream` 输出。消费端应按事件流处理，典型事件包含检索步骤、增量内容、最终结果或错误信息。最终结果的数据字段与 `POST /open/v1/query` 保持同源语义，至少包括 `markdown`、`intent`、`intent_confidence`、`invoked_tools`、`fallback_reason`、`warnings`、`audit_summary`、`external_web_results`、`section_contexts`。

## 7. 请求级联网搜索接口

本组接口直接调用已配置的外部搜索提供方，供上游系统主动检索公开互联网内容。
Firecrawl 与 Web Search 是两个独立接口：前者是 URL 发现结果，后者包含提供方返回的
正文或摘要，二者不共享或强制归一化结果结构。

所有结果仅存在于当前 HTTP 响应，标记 `ephemeral: true`；不会创建或更新
`raw_object`、资产、`normalized_asset_ref`、治理结果、知识块、向量索引或 Crawler
作业。外部搜索与 `/open/v1/search` 本地语义检索、`/open/v1/query` 的受控 fallback
是不同能力，调用本组接口不会触发本地检索或自动入库。

请求中的敏感内容会在调用外部提供方前被拒绝，返回 `422`。提供方未配置、限流、超时
或错误时返回 `503`，错误消息为 `external_search_unavailable`；响应及审计均不返回
供应商凭证或原始查询文本。每次成功调用写入 `SearchQueryExecuted` 审计记录，其中仅
保留查询哈希、提供方、结果数量和请求级标识。

两条接口均使用第 1.2 节 API Caller 鉴权，且具有以下附加错误语义：

| HTTP 状态 | 错误场景 | 响应语义 |
| --- | --- | --- |
| `401` | 缺少或无效 API Key | 通用 API Caller 认证失败 |
| `403` | API Key 过期、撤销，或请求执行期间被撤销 | 通用鉴权失败或 `API key revoked` |
| `422` | 请求字段不合法、空白查询，或查询命中敏感内容出站拦截 | `VALIDATION_ERROR` |
| `503` | 外部提供方未配置、限流、超时或调用失败 | `HTTP_ERROR`，消息为 `external_search_unavailable` |

### 7.1 Firecrawl 公网发现搜索

```http
POST /open/v1/external-search/firecrawl
Content-Type: application/json
```

Firecrawl 接口执行搜索发现，不会对结果 URL 执行 scrape 或 batch scrape。
当前 Firecrawl 开放接口没有独立的发布时间/时间范围过滤字段；需要表达时效偏好时，
可将其写入 `query`，但提供方结果不保证严格日期过滤。需要供应商级时间范围控制时应
使用 7.2 的 Web Search 接口。

#### 请求体

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `query` | string | 是 | - | `1..1024` | 搜索关键词；敏感内容不能出站 |
| `limit` | integer | 否 | `10` | `1..20` | 最大 URL 结果数 |
| `include_domains` | array[string] | 否 | `null` | 最多 20 项 | 可选站点域名白名单，仅搜索这些域名 |
| `country` | string | 否 | `CN` | `2..8` 字符 | Firecrawl 国家/地区参数 |
| `languages` | array[string] | 否 | `["zh-CN"]` | `1..10` 项 | Firecrawl 语言偏好 |

示例：

```json
{
  "query": "跨境电商 政策",
  "limit": 10,
  "include_domains": ["www.gov.cn", "www.mofcom.gov.cn"],
  "country": "CN",
  "languages": ["zh-CN"]
}
```

#### 返回结构

`results` 为 Firecrawl URL 发现结果，不含网页完整正文，也不代表内容已被 NEXUS 抓取
或治理。

```json
{
  "data": {
    "provider": "firecrawl",
    "query": "跨境电商 政策",
    "request": {
      "limit": 10,
      "include_domains": ["www.gov.cn", "www.mofcom.gov.cn"],
      "country": "CN",
      "languages": ["zh-CN"]
    },
    "results": [
      {
        "url": "https://www.example.gov.cn/policy/1.html",
        "title": "政策文件标题",
        "description": "搜索结果摘要"
      }
    ],
    "count": 1,
    "ephemeral": true
  },
  "meta": { "trace_id": "trace_id" }
}
```

### 7.2 Web Search 内容搜索

```http
POST /open/v1/external-search/web-search
Content-Type: application/json
```

Web Search 由已配置的 Web Search 提供方执行。它返回结果内容，因此结果结构与
Firecrawl 发现搜索不同；`content_source` 用于区分供应商给出的完整内容与摘要回退。

#### 请求体

| 字段 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `query` | string | 是 | - | `1..1024` | 搜索关键词；敏感内容不能出站 |
| `count` | integer | 否 | `10` | `1..50` | 最大结果数 |
| `time_range` | string | 否 | `OneYear` | `1..64` 字符 | 供应商时间范围参数，如 `OneMonth`、`OneYear` 或其支持的范围表达式 |

示例：

```json
{
  "query": "跨境电商 市场报告",
  "count": 10,
  "time_range": "OneYear"
}
```

#### 返回结构

`content` 为外部提供方在本次调用中返回的内容或摘要，不是 NEXUS 资产正文。`metadata`
以及 `provider_*` 字段为供应商请求元数据，可能为 `null` 或空对象。

```json
{
  "data": {
    "provider": "web_search",
    "query": "跨境电商 市场报告",
    "request": { "count": 10, "time_range": "OneYear" },
    "results": [
      {
        "result_id": "provider_result_id",
        "title": "市场报告标题",
        "url": "https://example.com/report",
        "content": "供应商返回的 Markdown 正文或摘要",
        "content_source": "content",
        "metadata": {
          "SiteName": "示例站点",
          "PublishTime": "2026-08-01",
          "RankScore": 0.95
        }
      }
    ],
    "count": 1,
    "provider_request_id": "provider_request_id",
    "provider_log_id": "provider_log_id",
    "provider_time_cost_ms": 120,
    "ephemeral": true
  },
  "meta": { "trace_id": "trace_id" }
}
```

## 8. 专业画像接口

### 8.1 查询专业画像

```http
GET /open/v1/major-profiles
```

#### 参数

| 参数 | 位置 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| `major_code` | query | string | 否 | 专业代码，精确匹配 |
| `major_name` | query | string | 否 | 专业名称，包含匹配 |
| `occupation` | query | string | 否 | 面向职业，归一化后包含匹配 |
| `training_goal` | query | string | 否 | 培养目标，包含匹配 |
| `ability` | query | string | 否 | 能力项文本，包含匹配 |
| `course` | query | string | 否 | 课程文本，包含匹配 |
| `course_group` | query | string | 否 | 课程组，精确匹配 |
| `certificate` | query | string | 否 | 证书文本，包含匹配 |
| `continuation` | query | string | 否 | 接续专业文本，包含匹配 |
| `education_level` | query | string | 否 | 学历层次，精确匹配 |
| `page` | query | integer | 否 | 页码 |
| `pageSize` | query | integer | 否 | 每页条数 |

#### 返回结构

```json
{
  "data": [
    {
      "id": "profile_id",
      "normalized_ref_id": "normalized_ref_id",
      "asset_version_id": "asset_version_id",
      "domain_profile": "major_profile",
      "major_code": "530701",
      "major_name": "电子商务",
      "education_level": "高职专科",
      "basic_study_duration": "三年",
      "training_goal": "培养目标文本",
      "source_title": "来源标题",
      "extractor_version": "v1",
      "confidence": 0.95,
      "quality_flags": {},
      "status": "available",
      "created_at": "2026-07-31T10:00:00",
      "updated_at": "2026-07-31T10:00:00"
    }
  ],
  "meta": {
    "trace_id": "trace_id",
    "page": 1,
    "page_size": 20,
    "total": 1
  },
  "aggregations": null
}
```

### 8.2 获取专业画像详情

```http
GET /open/v1/major-profiles/{profile_id}
```

#### 参数

| 参数 | 位置 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| `profile_id` | path | string | 是 | 专业画像 ID |

#### 返回结构

```json
{
  "data": {
    "id": "profile_id",
    "normalized_ref_id": "normalized_ref_id",
    "asset_version_id": "asset_version_id",
    "major_code": "530701",
    "major_name": "电子商务",
    "education_level": "高职专科",
    "training_goal": "培养目标文本",
    "evidence": {},
    "occupations": [
      {
        "id": "item_id",
        "profile_id": "profile_id",
        "normalized_ref_id": "normalized_ref_id",
        "item_index": 1,
        "text": "职业文本",
        "source_text": "证据文本",
        "evidence_block_ids": [],
        "locator": {},
        "confidence": 0.9,
        "normalized_name": "电子商务师",
        "occupation_type": "target"
      }
    ],
    "abilities": [],
    "courses": [
      {
        "id": "item_id",
        "course_group": "专业核心课程",
        "course_type": "core",
        "text": "课程文本"
      }
    ],
    "certificates": [],
    "continuations": [],
    "counts": {
      "occupation_count": 1,
      "ability_count": 0,
      "course_count": 1,
      "certificate_count": 0,
      "continuation_count": 0
    }
  },
  "meta": { "trace_id": "trace_id" }
}
```

## 9. 人才培养方案接口

人才培养方案资源对应从 `normalized_document` 提取并持久化的
`talent_training_plan.v1` 方案级投影。它面向院校专业的培养方案查询，
将专业、岗位/技能、证书和课程作为方案本地且带来源证据的事实；它们不是
行业、职业、岗位、技能、证书或课程的全局主数据。

结构化查询是此类资产的主路径。方案的培养目标/规格、课程目标/内容等可同时
由通用知识块与语义检索接口补充获取，但本组接口不执行语义召回，也不返回
通用 Evidence Graph。

### 9.1 查询人才培养方案

```http
GET /open/v1/talent-training-plans
```

#### 参数

所有业务过滤条件均为可选；同时传入多个条件时按 AND 组合。`position`、
`skill`、`certificate` 查询方案本地 JSON 属性，`course` 同时匹配课程名称、
课程目标和课程内容。

| 参数 | 位置 | 类型 | 必填 | 匹配方式 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `institution_name` | query | string | 否 | 包含 | 院校名称 |
| `major_name` | query | string | 否 | 包含 | 专业名称 |
| `major_code` | query | string | 否 | 精确 | 专业代码 |
| `education_level` | query | string | 否 | 精确 | 教育层次 |
| `study_duration` | query | string | 否 | 精确 | 修业年限，如 `三年` |
| `position` | query | string | 否 | 包含 | 职业面向中的岗位名称或岗位描述 |
| `skill` | query | string | 否 | 包含 | 职业面向岗位技能或培养规格中的能力/技能文本 |
| `certificate` | query | string | 否 | 包含 | 方案声明的证书名称或描述 |
| `course` | query | string | 否 | 包含 | 课程名称、课程目标或课程内容 |
| `page` | query | integer | 否 | - | 页码，默认 `1`，范围 `1..10000` |
| `pageSize` | query | integer | 否 | - | 每页条数，默认 `20`，范围 `1..200` |

#### 返回结构

列表仅返回方案摘要，不内嵌课程、岗位或证书明细。结果按方案创建时间倒序排列。

```json
{
  "data": [
    {
      "id": "plan_id",
      "normalized_ref_id": "normalized_ref_id",
      "asset_version_id": "asset_version_id",
      "institution_name": "杭州万向职业技术学院",
      "major_name": "跨境电子商务",
      "major_code": "630805",
      "education_level": "高职",
      "study_duration": "三年",
      "training_goal": "培养跨境电商运营人才",
      "confidence": 0.95,
      "status": "generated",
      "course_count": 24,
      "created_at": "2026-08-12T10:00:00",
      "updated_at": "2026-08-12T10:00:00"
    }
  ],
  "meta": {
    "trace_id": "trace_id",
    "page": 1,
    "page_size": 20,
    "total": 1
  },
  "aggregations": null
}
```

### 9.2 获取人才培养方案详情

```http
GET /open/v1/talent-training-plans/{plan_id}
```

#### 参数

| 参数 | 位置 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| `plan_id` | path | string | 是 | 人才培养方案投影 ID |

#### 返回结构

除列表摘要字段外，详情返回方案本地结构化属性和按源文档顺序排列的课程。`evidence`
及课程 `evidence` 保留来源块/页码等可追溯定位信息；其具体字段随解析结果变化。

```json
{
  "data": {
    "id": "plan_id",
    "normalized_ref_id": "normalized_ref_id",
    "asset_version_id": "asset_version_id",
    "institution_name": "杭州万向职业技术学院",
    "major_name": "跨境电子商务",
    "major_code": "630805",
    "education_level": "高职",
    "study_duration": "三年",
    "training_goal": "培养跨境电商运营人才",
    "training_specification": {
      "ability_requirements": [
        { "name": "跨境平台操作能力", "evidence": {} }
      ]
    },
    "career_orientation": {
      "industries": [],
      "occupations": [],
      "positions": [
        {
          "name": "跨境电商 B2C 运营岗",
          "skills": [{ "name": "跨境平台操作能力", "evidence": {} }],
          "evidence": {}
        }
      ]
    },
    "certificates": [
      { "name": "1+X 跨境电商运营职业技能等级证书", "evidence": {} }
    ],
    "evidence": {},
    "quality_flags": {},
    "courses": [
      {
        "id": "course_id",
        "item_index": 1,
        "course_name": "跨境电子商务实务",
        "course_code": null,
        "curriculum_group": "professional_core",
        "course_type": "course",
        "course_objective": "培养跨境平台操作能力",
        "course_content": "跨境平台规则与国际物流",
        "skill_refs": [{ "name": "跨境平台操作能力", "evidence": {} }],
        "knowledge_topics": [],
        "evidence": {},
        "confidence": 0.9
      }
    ]
  },
  "meta": { "trace_id": "trace_id" }
}
```

当 `plan_id` 不存在，或关联资产版本不为 `available` 时，返回 `404`。

### 9.3 获取课程知识图谱

```http
GET /open/v1/talent-training-plans/{plan_id}/course-knowledge-graph
```

该接口始终基于方案已持久化的课程行构建确定性、方案范围内的图谱，不写入或读取
通用 Evidence Graph。图谱从方案根节点开始，通过课程关联到课程目标、课程内容和
已提取的课程技能。节点与边的 `evidence` 提供对应的规范化文档来源证据。

```json
{
  "data": {
    "graph_type": "talent_training_plan_course_knowledge.v1",
    "deterministic": true,
    "normalized_ref_id": "normalized_ref_id",
    "plan_id": "plan_id",
    "nodes": [
      {
        "id": "plan:plan_id",
        "node_type": "TalentTrainingPlan",
        "display_name": "跨境电子商务",
        "evidence": {},
        "properties": {}
      },
      {
        "id": "course:course_id",
        "node_type": "Course",
        "display_name": "跨境电子商务实务",
        "evidence": {},
        "properties": {
          "course_code": null,
          "curriculum_group": "professional_core",
          "course_type": "course"
        }
      }
    ],
    "edges": [
      {
        "source": "plan:plan_id",
        "target": "course:course_id",
        "relation_type": "PLAN_HAS_COURSE",
        "evidence": {}
      }
    ]
  },
  "meta": { "trace_id": "trace_id" }
}
```

节点类型包括 `TalentTrainingPlan`、`Course`、`CourseObjective`、`CourseContent`
和 `Skill`；关系类型包括 `PLAN_HAS_COURSE`、`COURSE_HAS_OBJECTIVE`、
`COURSE_HAS_CONTENT`、`COURSE_COVERS_SKILL`。课程目标或课程内容为空时，不产生
相应节点和边。

### 9.4 获取岗位能力图谱

```http
GET /open/v1/talent-training-plans/{plan_id}/position-capability-graph
```

该接口只在方案包含有效的“岗位 -> 技能/能力”事实时返回节点和边；岗位名称本身或
未绑定技能的岗位不构成岗位能力图谱。节点和边会保留解析到的 `evidence`，但该
字段可能为空。岗位和技能均为当前方案本地节点，不能被当作全局岗位或技能主数据使用。

有有效事实时的响应：

```json
{
  "data": {
    "graph_type": "talent_training_plan_position_capability.v1",
    "deterministic": true,
    "available": true,
    "reason": null,
    "normalized_ref_id": "normalized_ref_id",
    "plan_id": "plan_id",
    "nodes": [
      {
        "id": "position:跨境电商 B2C 运营岗",
        "node_type": "Position",
        "display_name": "跨境电商 B2C 运营岗",
        "evidence": {},
        "properties": { "plan_local": true }
      },
      {
        "id": "skill:跨境平台操作能力",
        "node_type": "Skill",
        "display_name": "跨境平台操作能力",
        "evidence": {},
        "properties": { "skill_type": "ability", "plan_local": true }
      }
    ],
    "edges": [
      {
        "source": "position:跨境电商 B2C 运营岗",
        "target": "skill:跨境平台操作能力",
        "relation_type": "POSITION_REQUIRES_SKILL",
        "evidence": {}
      }
    ]
  },
  "meta": { "trace_id": "trace_id" }
}
```

没有可用岗位能力事实时仍返回 `200`，以空图明确表达该方案未提供岗位到技能的映射：

```json
{
  "data": {
    "graph_type": "talent_training_plan_position_capability.v1",
    "deterministic": true,
    "available": false,
    "reason": "no_evidenced_position_skill_facts",
    "normalized_ref_id": "normalized_ref_id",
    "plan_id": "plan_id",
    "nodes": [],
    "edges": []
  },
  "meta": { "trace_id": "trace_id" }
}
```

有效图谱还包含方案根节点 `TalentTrainingPlan`，并以 `PLAN_ORIENTS_TO_POSITION`
连接到岗位节点；岗位到技能的关系为 `POSITION_REQUIRES_SKILL`。

## 10. 职业能力分析记录资产接口

### 10.1 查询职业能力分析

```http
GET /open/v1/record-assets/ability-analyses
```

#### 参数

| 参数 | 位置 | 类型 | 必填 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `normalized_ref_id` | query | string | 否 | `<=36` | 规范化资产引用 ID，精确匹配 |
| `profile_id` | query | string | 否 | `<=36` | 能力分析 Profile ID |
| `major_name` | query | string | 否 | `<=256` | 专业名称，ILIKE 包含匹配 |
| `page` | query | integer | 否 | `1..10000` | 页码 |
| `pageSize` | query | integer | 否 | `1..200` | 每页条数 |

#### 返回结构

```json
{
  "data": [
    {
      "id": "analysis_id",
      "normalized_ref_id": "normalized_ref_id",
      "asset_version_id": "asset_version_id",
      "profile_id": "profile_id",
      "analysis_model": "PGSD",
      "major_name": "电子商务",
      "major_direction": "直播电商",
      "source_job_demand_dataset_id": "dataset_id",
      "task_count": 4,
      "work_content_count": 12,
      "ability_item_count": 30,
      "schema_version": "v1",
      "quality_summary": {},
      "created_at": "2026-07-31T10:00:00",
      "updated_at": "2026-07-31T10:00:00"
    }
  ],
  "meta": {
    "trace_id": "trace_id",
    "page": 1,
    "page_size": 20,
    "total": 1
  },
  "aggregations": null
}
```

### 10.2 获取职业能力分析详情

```http
GET /open/v1/record-assets/ability-analyses/{analysis_id}
```

#### 参数

| 参数 | 位置 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| `analysis_id` | path | string | 是 | 职业能力分析 ID |

#### 返回结构

```json
{
  "data": {
    "analysis": {
      "id": "analysis_id",
      "normalized_ref_id": "normalized_ref_id",
      "asset_version_id": "asset_version_id",
      "profile_id": "profile_id",
      "analysis_model": "PGSD",
      "major_name": "电子商务",
      "major_direction": "直播电商",
      "task_count": 4,
      "work_content_count": 12,
      "ability_item_count": 30,
      "schema_version": "v1",
      "quality_summary": {}
    },
    "profile": {
      "id": "profile_id",
      "model_code": "PGSD",
      "model_name": "能力分析模型",
      "schema_version": "v1",
      "category_schema": [],
      "code_pattern": {},
      "is_active": true,
      "is_builtin": true
    }
  },
  "meta": { "trace_id": "trace_id" }
}
```

### 10.3 获取职业任务树

```http
GET /open/v1/record-assets/ability-analyses/{analysis_id}/tasks
```

#### 参数

| 参数 | 位置 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| `analysis_id` | path | string | 是 | 职业能力分析 ID |

#### 返回结构

```json
{
  "data": {
    "analysis_id": "analysis_id",
    "analysis_model": "PGSD",
    "major_name": "电子商务",
    "tasks": [
      {
        "id": "task_id",
        "task_code": "T1",
        "task_name": "任务名称",
        "task_description": "任务描述",
        "task_description_structured": {},
        "display_order": 1,
        "trace": {},
        "work_contents": [
          {
            "id": "work_content_id",
            "content_code": "T1.1",
            "content_name": "工作内容",
            "content_description": "工作内容描述",
            "display_order": 1,
            "trace": {}
          }
        ]
      }
    ]
  },
  "meta": { "trace_id": "trace_id" }
}
```

### 10.4 查询能力项

```http
GET /open/v1/record-assets/ability-analyses/{analysis_id}/ability-items
```

#### 参数

| 参数 | 位置 | 类型 | 必填 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `analysis_id` | path | string | 是 | - | 职业能力分析 ID |
| `category` | query | string | 否 | `<=16` | 能力大类代码，如 `P`、`G`、`S`、`D` |
| `task_code` | query | string | 否 | `<=64` | 任务代码 |
| `work_content_code` | query | string | 否 | `<=64` | 工作内容代码 |
| `page` | query | integer | 否 | `1..10000` | 页码 |
| `pageSize` | query | integer | 否 | `1..200` | 每页条数 |

#### 返回结构

```json
{
  "data": [
    {
      "id": "ability_item_id",
      "analysis_id": "analysis_id",
      "task_id": "task_id",
      "work_content_id": "work_content_id",
      "ability_code": "P1",
      "ability_major_category_code": "P",
      "ability_major_category_name": "专业能力",
      "ability_sequence": 1,
      "ability_content": "能力描述",
      "normalized_terms": {},
      "confidence": 0.9,
      "quality_flags": {},
      "trace": {}
    }
  ],
  "meta": {
    "trace_id": "trace_id",
    "page": 1,
    "page_size": 20,
    "total": 1
  },
  "aggregations": null
}
```

### 10.5 查询能力关系

```http
GET /open/v1/record-assets/ability-analyses/{analysis_id}/relations
```

#### 参数

| 参数 | 位置 | 类型 | 必填 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `analysis_id` | path | string | 是 | - | 职业能力分析 ID |
| `source_type` | query | string | 否 | `<=32` | 来源节点类型 |
| `relation_type` | query | string | 否 | `<=64` | 关系类型 |
| `page` | query | integer | 否 | `1..10000` | 页码 |
| `pageSize` | query | integer | 否 | `1..200` | 每页条数 |

#### 返回结构

```json
{
  "data": [
    {
      "id": "relation_id",
      "analysis_id": "analysis_id",
      "source_type": "task",
      "source_id": "task_id",
      "relation_type": "requires",
      "target_type": "ability",
      "target_id": "ability_item_id",
      "confidence": 0.9,
      "evidence": {}
    }
  ],
  "meta": {
    "trace_id": "trace_id",
    "page": 1,
    "page_size": 20,
    "total": 1
  },
  "aggregations": null
}
```

## 11. 就业需求记录资产接口

### 11.1 跨数据集查询岗位需求记录

```http
GET /open/v1/record-assets/job-demand-records
```

#### 参数

| 参数 | 位置 | 类型 | 必填 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `job_title` | query | string | 否 | `1..256` | 岗位名称，包含匹配 |
| `company_name` | query | string | 否 | `1..256` | 公司名称，包含匹配 |
| `city` | query | string | 否 | `1..128` | 城市，包含匹配 |
| `education` | query | string | 否 | `1..128` | 学历要求，包含匹配 |
| `industry` | query | string | 否 | `1..128` | 行业名称，包含匹配 |
| `experience` | query | string | 否 | `1..128` | 经验要求，包含匹配 |
| `page` | query | integer | 否 | `1..10000` | 页码 |
| `pageSize` | query | integer | 否 | `1..200` | 每页条数 |

#### 返回结构

```json
{
  "data": [
    {
      "id": "record_id",
      "dataset_id": "dataset_id",
      "normalized_ref_id": "normalized_ref_id",
      "source_record_key": "sheet1:2",
      "source_url": "https://example.com/job",
      "source_platform": "平台",
      "source_published_at": "2026-07-31T10:00:00",
      "job_title": "运营专员",
      "employment_type": "全职",
      "job_function_category": "运营",
      "job_count": 3,
      "city": "杭州",
      "region": "浙江",
      "salary_min": 6000.0,
      "salary_max": 9000.0,
      "salary_text": "6-9K",
      "experience_requirement": "1-3年",
      "education_requirement": "大专",
      "company_name": "示例公司",
      "company_address": "公司地址",
      "enterprise_size": "100-499人",
      "industry_name": "零售",
      "job_skill_text": "技能文本",
      "job_description": "岗位描述",
      "responsibility_text": "职责文本",
      "requirement_text": "要求文本",
      "quality_flags": {},
      "trace": {},
      "created_at": "2026-07-31T10:00:00"
    }
  ],
  "meta": {
    "trace_id": "trace_id",
    "page": 1,
    "page_size": 20,
    "total": 1
  },
  "aggregations": null
}
```

### 11.2 聚合查询岗位需求统计

```http
GET /open/v1/record-assets/job-demand-records/aggregate
```

对跨数据集的岗位需求记录做服务端分组聚合，覆盖岗位需求 TOP、学历分布、经验分布、薪资分布等统计维度。`data` 为聚合行，`aggregations.salary_summary` 为过滤后的全量薪资概览。

#### 参数

| 参数 | 位置 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- | --- |
| `group_by` | query | array[string] | 否 | `job_title` | 枚举见下；最多 3 个 | 分组维度，可重复传入 |
| `metric` | query | string | 否 | `record_count` | 枚举见下 | 度量，作用于聚合行 `value` 字段 |
| `order` | query | string | 否 | `desc` | `asc` / `desc` | 按度量列排序 |
| `job_title` | query | string | 否 | - | `1..256` | 岗位名称，包含匹配 |
| `company_name` | query | string | 否 | - | `1..256` | 公司名称，包含匹配 |
| `city` | query | string | 否 | - | `1..128` | 城市，包含匹配 |
| `education` | query | string | 否 | - | `1..128` | 学历要求，包含匹配 |
| `industry` | query | string | 否 | - | `1..128` | 行业名称，包含匹配 |
| `experience` | query | string | 否 | - | `1..128` | 经验要求，包含匹配 |
| `employment_type` | query | string | 否 | - | `1..128` | 岗位类型，等值匹配 |
| `enterprise_size` | query | string | 否 | - | `1..128` | 公司规模，等值匹配 |
| `page` | query | integer | 否 | `1` | `1..10000` | 页码 |
| `pageSize` | query | integer | 否 | `20` | `1..200` | 每页条数 |

`group_by` 枚举：`job_title`、`company_name`、`city`、`region`、`education_requirement`、`experience_requirement`、`industry_name`、`employment_type`、`enterprise_size`、`job_function_category`、`source_platform`。

`metric` 枚举：

| 值 | 含义 |
| --- | --- |
| `record_count` | 岗位记录数（`count(id)`） |
| `job_count` | 岗位需求量（`sum(job_count)`，NULL 忽略） |
| `avg_salary_min` | 平均起薪（`avg(salary_min)`，NULL 忽略） |
| `avg_salary_max` | 平均顶薪（`avg(salary_max)`，NULL 忽略） |

#### 返回结构

```json
{
  "data": [
    {
      "job_title": "跨境电商运营",
      "value": 412,
      "record_count": 128
    },
    {
      "job_title": "外贸业务员",
      "value": 260,
      "record_count": 96
    }
  ],
  "meta": {
    "trace_id": "trace_id",
    "page": 1,
    "page_size": 20,
    "total": 2
  },
  "aggregations": {
    "salary_summary": {
      "min_salary": 3.0,
      "max_salary": 40.0,
      "avg_salary_min": 7.8,
      "avg_salary_max": 12.4
    }
  }
}
```

返回说明：

- `data` 中每个聚合行包含请求指定的 `group_by` 字段，以及固定字段 `value`（度量值）与 `record_count`（该分组的记录数，恒返回）。
- `meta.total` 为分组总数（分页前的聚合行数）。
- `aggregations.salary_summary` 为过滤后（忽略 `group_by`）的全量薪资统计，字段 `min_salary`、`max_salary`、`avg_salary_min`、`avg_salary_max`；无薪资数据时对应字段为 `null`。

#### 请求示例

```text
# 岗位需求 TOP（按招聘人数降序取前 10）
GET /open/v1/record-assets/job-demand-records/aggregate?group_by=job_title&metric=job_count&order=desc&pageSize=10

# 学历分布
GET /open/v1/record-assets/job-demand-records/aggregate?group_by=education_requirement

# 经验分布
GET /open/v1/record-assets/job-demand-records/aggregate?group_by=experience_requirement

# 按城市平均起薪（叠加行业过滤）
GET /open/v1/record-assets/job-demand-records/aggregate?group_by=city&metric=avg_salary_min&industry=电子商务
```

#### 错误码

- `422` `unknown_group_by`：`group_by` 包含不在枚举内的维度。
- `422` `unknown_metric`：`metric` 不在枚举内。
- `422` `group_by_required`：`group_by` 为空。
- `422` `duplicate_group_by`：`group_by` 含重复维度。
- `422` `too_many_group_by`：`group_by` 维度数超过 3。
- `422` `unknown_order`：`order` 不是 `asc`/`desc`。

### 11.3 获取岗位需求记录详情

```http
GET /open/v1/record-assets/job-demand-records/{record_id}
```

#### 参数

| 参数 | 位置 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| `record_id` | path | string | 是 | 岗位需求记录 ID |

#### 返回结构

返回结构同单条岗位需求记录：

```json
{
  "data": {
    "id": "record_id",
    "dataset_id": "dataset_id",
    "normalized_ref_id": "normalized_ref_id",
    "job_title": "运营专员",
    "company_name": "示例公司",
    "city": "杭州",
    "industry_name": "零售",
    "salary_min": 6000.0,
    "salary_max": 9000.0,
    "quality_flags": {},
    "trace": {}
  },
  "meta": { "trace_id": "trace_id" }
}
```

### 11.4 获取岗位需求抽取项

```http
GET /open/v1/record-assets/job-demand-records/{record_id}/requirement-items
```

#### 参数

| 参数 | 位置 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- | --- |
| `record_id` | path | string | 是 | 岗位需求记录 ID |

#### 返回结构

```json
{
  "data": [
    {
      "id": "item_id",
      "record_id": "record_id",
      "dataset_id": "dataset_id",
      "item_type": "skill",
      "item_name": "数据分析",
      "raw_text": "熟悉数据分析",
      "normalized_name": "数据分析",
      "taxonomy_code": "SKILL.DATA_ANALYSIS",
      "confidence": 0.9,
      "extractor_version": "v1",
      "evidence_field": "requirement_text",
      "ai_model_alias": "model_alias"
    }
  ],
  "meta": {
    "trace_id": "trace_id",
    "page": 1,
    "page_size": 1,
    "total": 1
  },
  "aggregations": null
}
```

## 12. 专业分布记录资产接口

### 12.1 查询专业分布记录

```http
GET /open/v1/record-assets/major-distribution-records
```

#### 参数

| 参数 | 位置 | 类型 | 必填 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `year` | query | integer | 否 | `1900..2200` | 年份 |
| `province_name` | query | string | 否 | `1..128` | 省份名称，会做省份名归一化 |
| `major_name` | query | string | 否 | `1..256` | 专业名称，包含匹配 |
| `major_code` | query | string | 否 | `1..64` | 专业代码，精确匹配 |
| `page` | query | integer | 否 | `1..10000` | 页码 |
| `pageSize` | query | integer | 否 | `1..200` | 每页条数 |

#### 返回结构

```json
{
  "data": [
    {
      "id": "record_id",
      "dataset_id": "dataset_id",
      "normalized_ref_id": "normalized_ref_id",
      "source_record_key": "sheet1:2",
      "source_row_no": 2,
      "year": 2025,
      "year_text": "2025",
      "province_name": "浙江省",
      "region_scope": "华东",
      "major_name": "电子商务",
      "major_code": "530701",
      "education_level": "高职专科",
      "distribution_count": 120,
      "quality_flags": {},
      "trace": {},
      "created_at": "2026-07-31T10:00:00"
    }
  ],
  "meta": {
    "trace_id": "trace_id",
    "page": 1,
    "page_size": 20,
    "total": 1
  },
  "aggregations": null
}
```

### 12.2 聚合查询专业分布统计

```http
GET /open/v1/record-assets/major-distribution-records/aggregate
```

#### 参数

| 参数 | 位置 | 类型 | 必填 | 默认值 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- | --- |
| `group_by` | query | array[string] | 否 | `year,province_name,major_name,major_code` | 枚举：`year`、`province_name`、`major_name`、`major_code` | 分组维度，可重复传入 |
| `year` | query | integer | 否 | - | `1900..2200` | 年份过滤 |
| `province_name` | query | string | 否 | - | `1..128` | 省份过滤 |
| `major_name` | query | string | 否 | - | `1..256` | 专业名称过滤，包含匹配 |
| `major_code` | query | string | 否 | - | `1..64` | 专业代码过滤 |
| `page` | query | integer | 否 | `1` | `1..10000` | 页码 |
| `pageSize` | query | integer | 否 | `20` | `1..200` | 每页条数 |

#### 返回结构

```json
{
  "data": [
    {
      "year": 2025,
      "province_name": "浙江省",
      "major_name": "电子商务",
      "major_code": "530701",
      "distribution_total": 120,
      "record_count": 1
    }
  ],
  "meta": {
    "trace_id": "trace_id",
    "page": 1,
    "page_size": 20,
    "total": 1
  },
  "aggregations": null
}
```

返回项中会包含请求指定的 `group_by` 字段，以及固定统计字段 `distribution_total`、`record_count`。

## 13. 图谱检索接口

### 13.1 按岗位查询岗位能力图谱

```http
GET /open/v1/record-assets/graphs/job-capability
```

#### 参数

| 参数 | 位置 | 类型 | 必填 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `job_title` | query | string | 是 | `1..256` | 岗位名称，包含匹配 |

#### 返回结构

```json
{
  "data": {
    "job_title": "运营专员",
    "builds": [
      {
        "id": "build_id",
        "normalized_ref_id": "normalized_ref_id",
        "build_type": "job_demand",
        "major_name": "电子商务",
        "major_code": "530701",
        "schema_version": "v1",
        "created_at": "2026-07-31T10:00:00"
      }
    ],
    "nodes": [
      {
        "id": "node_id",
        "node_type": "job_role",
        "node_key": "job:运营专员",
        "display_name": "运营专员",
        "canonical_name": "运营专员",
        "properties": {},
        "confidence": 0.9
      }
    ],
    "edges": [
      {
        "id": "edge_id",
        "source_node_id": "node_id",
        "target_node_id": "node_id_2",
        "edge_type": "requires",
        "confidence": 0.9
      }
    ]
  },
  "meta": { "trace_id": "trace_id" }
}
```

节点上限为 1000，边上限为 2000；超过时返回 `413`。

### 13.2 按专业查询职业能力图谱

```http
GET /open/v1/record-assets/graphs/occupational-capability
```

#### 参数

| 参数 | 位置 | 类型 | 必填 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `major_name` | query | string | 否 | `1..256` | 专业名称，包含匹配 |
| `major_code` | query | string | 否 | `1..16` | 专业代码，精确匹配 |

`major_name` 和 `major_code` 至少传入一个，否则返回 `422`。

#### 返回结构

```json
{
  "data": {
    "build": {
      "id": "build_id",
      "normalized_ref_id": "normalized_ref_id",
      "build_type": "ability_analysis",
      "major_name": "电子商务",
      "major_code": "530701",
      "schema_version": "v1",
      "created_at": "2026-07-31T10:00:00"
    },
    "nodes": [],
    "edges": []
  },
  "meta": { "trace_id": "trace_id" }
}
```

### 13.3 按专业查询教学标准知识图谱

```http
GET /open/v1/record-assets/graphs/teaching-standard-knowledge
```

#### 参数

| 参数 | 位置 | 类型 | 必填 | 约束 | 说明 |
| --- | --- | --- | --- | --- | --- |
| `major_name` | query | string | 否 | `1..256` | 专业名称，包含匹配 |
| `major_code` | query | string | 否 | `1..16` | 专业代码，精确匹配 |

`major_name` 和 `major_code` 至少传入一个，否则返回 `422`。

#### 返回结构

```json
{
  "data": {
    "build": {
      "id": "build_id",
      "normalized_ref_id": "normalized_ref_id",
      "build_type": "teaching_standard",
      "major_name": "电子商务",
      "major_code": "530701",
      "schema_version": "v1",
      "created_at": "2026-07-31T10:00:00"
    },
    "nodes": [],
    "edges": []
  },
  "meta": { "trace_id": "trace_id" }
}
```

## 14. 调用示例

### 14.1 智能检索

```bash
curl --silent \
  -H "X-API-Key: <caller_key>" \
  -H "Content-Type: application/json" \
  -X POST "http://127.0.0.1:8000/open/v1/query" \
  -d '{"query":"现代零售行业的关键特征是什么"}'
```

### 14.2 资产目录按标签检索

```bash
curl --silent \
  -H "X-API-Key: <caller_key>" \
  "http://127.0.0.1:8000/open/v1/assets?tag_type=major&tags=电子商务&is_exact_matched=true&page=1&pageSize=20"
```

### 14.3 获取 chunk 引用详情

```bash
curl --silent \
  -H "X-API-Key: <caller_key>" \
  "http://127.0.0.1:8000/open/v1/knowledge-chunks/<chunk_id>"
```
