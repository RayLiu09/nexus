# 基于公开 OpenAPI 生成 function tools 清单

自动生成；共 55 个工具。来源 `/open/v1`，不包含内部接口、已退役接口、流式接口或 C 类增量接口。

调用方按资源标签按需加载工具；使用 `responses-tools.json` 的 Responses function 格式，或 `chat-completions-tools.json` 的 Chat Completions 格式。

参数按 `path`、`query`、`body` 分组。HTTP 执行器依据 `http-bindings.json` 调用接口，重复数组查询参数使用 repeated keys；API Key 由执行器注入，不能作为模型参数。

`strict=false` 保留公开 OpenAPI 的可选参数、默认值和自由证据对象；执行器仍须按 OpenAPI 校验参数。外部搜索省略 auto_ingest 时，执行器必须注入 false，显式 true 可能触发入库。

文档只读准入沿用 available/current-ref；当前 open:* 权限不提供组织过滤。业务记录按独立领域边界公开。

重新生成：`nexus-api/.venv/bin/python scripts/generate_public_function_tools.py`；检查漂移：追加 `--check`。无需启动服务或读取数据库。

| 工具 | HTTP | 资源标签 |
| --- | --- | --- |
| `find_documents` | `GET /open/v1/assets` |  |
| `get_available_asset` | `GET /open/v1/assets/{asset_id}` |  |
| `list_available_asset_versions` | `GET /open/v1/assets/{asset_id}/versions` |  |
| `find_textbooks` | `GET /open/v1/course-textbooks` | public-business |
| `get_textbook` | `GET /open/v1/course-textbooks/{profile_id}` | public-business |
| `discover_data_resources` | `GET /open/v1/data-resources` | public-discovery |
| `query_enterprises` | `GET /open/v1/enterprises` | public-business |
| `get_enterprise` | `GET /open/v1/enterprises/{enterprise_id}` | public-business |
| `resolve_business_entities` | `POST /open/v1/entity-resolutions` | public-discovery |
| `get_evidence_bundle` | `POST /open/v1/evidence-resolutions` | public-evidence |
| `search_firecrawl` | `POST /open/v1/external-search/firecrawl` |  |
| `search_web_search` | `POST /open/v1/external-search/web-search` |  |
| `query_industrial_parks` | `GET /open/v1/industrial-parks` | public-business |
| `get_industrial_park` | `GET /open/v1/industrial-parks/{park_id}` | public-business |
| `get_public_knowledge_chunk` | `GET /open/v1/knowledge-chunks/{chunk_id}` |  |
| `aggregate_major_courses` | `GET /open/v1/major-courses/aggregate` |  |
| `aggregate_major_offerings` | `GET /open/v1/major-offerings/aggregate` |  |
| `find_major_profile_documents` | `GET /open/v1/major-profile-documents` | public-discovery |
| `query_market_jobs` | `GET /open/v1/market-jobs` | public-business |
| `aggregate_market_jobs` | `GET /open/v1/market-jobs/aggregate` | public-business |
| `get_market_job` | `GET /open/v1/market-jobs/{job_id}` | public-business |
| `get_available_normalized_ref` | `GET /open/v1/normalized-refs/{ref_id}` |  |
| `list_chunks_for_normalized_ref` | `GET /open/v1/normalized-refs/{ref_id}/chunks` |  |
| `get_normalized_ref_content` | `GET /open/v1/normalized-refs/{ref_id}/content` |  |
| `get_public_governance_result_for_ref` | `GET /open/v1/normalized-refs/{ref_id}/governance-result` |  |
| `read_existing_graph` | `GET /open/v1/normalized-refs/{ref_id}/knowledge-graph` | public-evidence |
| `get_knowledge_outline` | `GET /open/v1/normalized-refs/{ref_id}/knowledge-outline` | public-evidence |
| `get_outline_node_context` | `GET /open/v1/normalized-refs/{ref_id}/outlines/{outline_type}/nodes/{node_id}/context` | public-evidence |
| `list_document_sections` | `GET /open/v1/normalized-refs/{ref_id}/sections` | public-evidence |
| `read_document_section` | `GET /open/v1/normalized-refs/{ref_id}/sections/{section_id}` | public-evidence |
| `get_task_outline` | `GET /open/v1/normalized-refs/{ref_id}/task-outline` | public-evidence |
| `qa_knowledge` | `GET /open/v1/qa` |  |
| `run_query_router_v2_open` | `POST /open/v1/query` |  |
| `get_raw_object_download_url` | `GET /open/v1/raw-objects/{raw_object_id}/download-url` |  |
| `list_ability_analyses` | `GET /open/v1/record-assets/ability-analyses` | record-assets |
| `get_ability_analysis` | `GET /open/v1/record-assets/ability-analyses/{analysis_id}` | record-assets |
| `list_ability_items` | `GET /open/v1/record-assets/ability-analyses/{analysis_id}/ability-items` | record-assets |
| `list_ability_relations` | `GET /open/v1/record-assets/ability-analyses/{analysis_id}/relations` | record-assets |
| `get_ability_analysis_tasks` | `GET /open/v1/record-assets/ability-analyses/{analysis_id}/tasks` | record-assets |
| `find_ability_items` | `GET /open/v1/record-assets/ability-items` | public-business |
| `get_job_capability_graph` | `GET /open/v1/record-assets/graphs/job-capability` | record-assets |
| `get_occupational_capability_graph` | `GET /open/v1/record-assets/graphs/occupational-capability` | record-assets |
| `get_teaching_standard_knowledge_graph` | `GET /open/v1/record-assets/graphs/teaching-standard-knowledge` | record-assets |
| `list_major_distribution_records` | `GET /open/v1/record-assets/major-distribution-records` | record-assets |
| `aggregate_major_distribution_records` | `GET /open/v1/record-assets/major-distribution-records/aggregate` | record-assets |
| `search_evidence` | `GET /open/v1/search` |  |
| `list_open_talent_training_plans` | `GET /open/v1/talent-training-plans` |  |
| `get_open_talent_training_plan` | `GET /open/v1/talent-training-plans/{item_id}` |  |
| `get_open_course_knowledge_graph` | `GET /open/v1/talent-training-plans/{item_id}/course-knowledge-graph` |  |
| `get_open_position_capability_graph` | `GET /open/v1/talent-training-plans/{item_id}/position-capability-graph` |  |
| `list_training_plan_courses` | `GET /open/v1/talent-training-plans/{plan_id}/courses` | public-business |
| `query_standard_courses` | `GET /open/v1/teaching-standard-courses` | public-business |
| `get_standard_course` | `GET /open/v1/teaching-standard-courses/{course_id}` | public-business |
| `query_teaching_standards` | `GET /open/v1/teaching-standard-libraries` | public-business |
| `get_teaching_standard` | `GET /open/v1/teaching-standard-libraries/{library_id}` | public-business |

默认排除的兼容接口：

- `GET /open/v1/major-profiles`：deprecated_or_streaming
- `GET /open/v1/major-profiles/{profile_id}`：deprecated_or_streaming
- `POST /open/v1/query/stream`：deprecated_or_streaming
- `GET /open/v1/record-assets/job-demand-records`：deprecated_or_streaming
- `GET /open/v1/record-assets/job-demand-records/aggregate`：deprecated_or_streaming
- `GET /open/v1/record-assets/job-demand-records/{record_id}`：deprecated_or_streaming
- `GET /open/v1/record-assets/job-demand-records/{record_id}/requirement-items`：deprecated_or_streaming
