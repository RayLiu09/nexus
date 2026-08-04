# /open/v1 开放资产检索接口文档

本文档描述 NEXUS 当前实际注册的 `/open/v1` 开放接口中，面向上游系统进行数据资产检索、知识检索、结构化记录查询和检索结果溯源的接口。

依据源码：

- `nexus-api/nexus_api/api/open.py`
- `nexus-api/nexus_api/api/open_record_assets.py`
- `nexus-api/nexus_api/api/major_profiles.py`
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

开放资产目录、规范化资产、知识 chunk、原文件下载、专业画像和专业分布记录默认只暴露已达到 `available` 版本的数据。

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
| 专业画像 | GET | `/open/v1/major-profiles` | 查询可用专业画像 |
| 专业画像 | GET | `/open/v1/major-profiles/{profile_id}` | 获取专业画像详情 |
| 职业能力分析 | GET | `/open/v1/record-assets/ability-analyses` | 查询职业能力分析资产 |
| 职业能力分析 | GET | `/open/v1/record-assets/ability-analyses/{analysis_id}` | 获取职业能力分析详情 |
| 职业能力分析 | GET | `/open/v1/record-assets/ability-analyses/{analysis_id}/tasks` | 获取职业任务树 |
| 职业能力分析 | GET | `/open/v1/record-assets/ability-analyses/{analysis_id}/ability-items` | 获取能力项列表 |
| 职业能力分析 | GET | `/open/v1/record-assets/ability-analyses/{analysis_id}/relations` | 获取能力关系列表 |
| 就业需求 | GET | `/open/v1/record-assets/job-demand-records` | 跨数据集查询岗位需求记录 |
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

## 7. 专业画像接口

### 7.1 查询专业画像

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

### 7.2 获取专业画像详情

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

## 8. 职业能力分析记录资产接口

### 8.1 查询职业能力分析

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

### 8.2 获取职业能力分析详情

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

### 8.3 获取职业任务树

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

### 8.4 查询能力项

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

### 8.5 查询能力关系

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

## 9. 就业需求记录资产接口

### 9.1 跨数据集查询岗位需求记录

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

### 9.2 获取岗位需求记录详情

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

### 9.3 获取岗位需求抽取项

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

## 10. 专业分布记录资产接口

### 10.1 查询专业分布记录

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

### 10.2 聚合查询专业分布统计

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

## 11. 图谱检索接口

### 11.1 按岗位查询岗位能力图谱

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

### 11.2 按专业查询职业能力图谱

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

### 11.3 按专业查询教学标准知识图谱

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

## 12. 调用示例

### 12.1 智能检索

```bash
curl --silent \
  -H "X-API-Key: <caller_key>" \
  -H "Content-Type: application/json" \
  -X POST "http://127.0.0.1:8000/open/v1/query" \
  -d '{"query":"现代零售行业的关键特征是什么"}'
```

### 12.2 资产目录按标签检索

```bash
curl --silent \
  -H "X-API-Key: <caller_key>" \
  "http://127.0.0.1:8000/open/v1/assets?tag_type=major&tags=电子商务&is_exact_matched=true&page=1&pageSize=20"
```

### 12.3 获取 chunk 引用详情

```bash
curl --silent \
  -H "X-API-Key: <caller_key>" \
  "http://127.0.0.1:8000/open/v1/knowledge-chunks/<chunk_id>"
```
