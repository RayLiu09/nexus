# 基于公开 OpenAPI 生成 function tools 清单

自动生成；共 55 个工具。来源 `/open/v1`，不包含内部接口、已退役接口、流式接口或 C 类增量接口。

调用方按资源标签按需加载工具；使用 `responses-tools.json` 的 Responses function 格式，或 `chat-completions-tools.json` 的 Chat Completions 格式。

参数按 `path`、`query`、`body` 分组。HTTP 执行器依据 `http-bindings.json` 调用接口，重复数组查询参数使用 repeated keys；API Key 由执行器注入，不能作为模型参数。

`strict=false` 保留公开 OpenAPI 的可选参数、默认值和自由证据对象；执行器仍须按 OpenAPI 校验参数。外部搜索省略 auto_ingest 时，执行器必须注入 false，显式 true 可能触发入库。

文档只读准入沿用 available/current-ref；当前 open:* 权限不提供组织过滤。业务记录按独立领域边界公开。

当前覆盖资产中心 16 类可见资源：产教政策、产业报告、行业报告、专业简介、专业布点数据、专业教学标准、标准课程库、人才需求调研、人才培养方案、职业分类大典、职业能力分析、市场岗位、产业园区、企业数据、课程教材、教学案例。共享文档类通过 find_documents 的 resource_type/domain(s) 筛选；独立记录和投影使用各自专用工具。

专业布点使用 list_major_offerings / aggregate_major_offerings，来源为教育部政务服务平台直接同步数据，无 AI 治理；不可用专业简介或培养方案统计替代。职业分类大典使用 query_occupation_dictionary，支持职业大类、小类、名称组合过滤，返回定义与工作任务。两类数据仅表示已入库覆盖。

专业布点 Excel 下载由 /v1/major-offerings/export 及内部 Console 接口提供，属于二进制下载，不列为 JSON function tool。完整资源与接口映射见 [公开消费合同](../../api/public_agent_data_api.md)。

重新生成：`nexus-api/.venv/bin/python scripts/generate_public_function_tools.py`；检查漂移：追加 `--check`。无需启动服务或读取数据库。

| 工具 | HTTP | 资源标签 |
| --- | --- | --- |
| `find_documents` | `GET /open/v1/assets` | assets |
| `get_available_asset` | `GET /open/v1/assets/{asset_id}` | assets |
| `list_available_asset_versions` | `GET /open/v1/assets/{asset_id}/versions` | assets |
| `find_textbooks` | `GET /open/v1/course-textbooks` | public-business |
| `get_textbook` | `GET /open/v1/course-textbooks/{profile_id}` | public-business |
| `discover_data_resources` | `GET /open/v1/data-resources` | public-discovery |
| `query_enterprises` | `GET /open/v1/enterprises` | public-business |
| `get_enterprise` | `GET /open/v1/enterprises/{enterprise_id}` | public-business |
| `resolve_business_entities` | `POST /open/v1/entity-resolutions` | public-discovery |
| `get_evidence_bundle` | `POST /open/v1/evidence-resolutions` | public-evidence |
| `search_firecrawl` | `POST /open/v1/external-search/firecrawl` | external-search |
| `search_web_search` | `POST /open/v1/external-search/web-search` | external-search |
| `query_industrial_parks` | `GET /open/v1/industrial-parks` | public-business |
| `get_industrial_park` | `GET /open/v1/industrial-parks/{park_id}` | public-business |
| `get_public_knowledge_chunk` | `GET /open/v1/knowledge-chunks/{chunk_id}` | knowledge-chunks |
| `aggregate_major_courses` | `GET /open/v1/major-courses/aggregate` | major-courses |
| `list_major_offerings` | `GET /open/v1/major-offerings` | major-offerings |
| `aggregate_major_offerings` | `GET /open/v1/major-offerings/aggregate` | major-offerings |
| `find_major_profile_documents` | `GET /open/v1/major-profile-documents` | public-discovery |
| `query_market_jobs` | `GET /open/v1/market-jobs` | public-business |
| `aggregate_market_jobs` | `GET /open/v1/market-jobs/aggregate` | public-business |
| `get_market_job` | `GET /open/v1/market-jobs/{job_id}` | public-business |
| `get_available_normalized_ref` | `GET /open/v1/normalized-refs/{ref_id}` | normalized-refs |
| `list_chunks_for_normalized_ref` | `GET /open/v1/normalized-refs/{ref_id}/chunks` | normalized-refs |
| `get_normalized_ref_content` | `GET /open/v1/normalized-refs/{ref_id}/content` | normalized-refs |
| `get_public_governance_result_for_ref` | `GET /open/v1/normalized-refs/{ref_id}/governance-result` | normalized-refs |
| `read_existing_graph` | `GET /open/v1/normalized-refs/{ref_id}/knowledge-graph` | public-evidence |
| `get_knowledge_outline` | `GET /open/v1/normalized-refs/{ref_id}/knowledge-outline` | public-evidence |
| `get_outline_node_context` | `GET /open/v1/normalized-refs/{ref_id}/outlines/{outline_type}/nodes/{node_id}/context` | public-evidence |
| `list_document_sections` | `GET /open/v1/normalized-refs/{ref_id}/sections` | public-evidence |
| `read_document_section` | `GET /open/v1/normalized-refs/{ref_id}/sections/{section_id}` | public-evidence |
| `get_task_outline` | `GET /open/v1/normalized-refs/{ref_id}/task-outline` | public-evidence |
| `query_occupation_dictionary` | `GET /open/v1/occupation-dictionary` | occupation-dictionary |
| `qa_knowledge` | `GET /open/v1/qa` | qa |
| `run_query_router_v2_open` | `POST /open/v1/query` | query |
| `get_raw_object_download_url` | `GET /open/v1/raw-objects/{raw_object_id}/download-url` | raw-objects |
| `list_ability_analyses` | `GET /open/v1/record-assets/ability-analyses` | record-assets |
| `get_ability_analysis` | `GET /open/v1/record-assets/ability-analyses/{analysis_id}` | record-assets |
| `list_ability_items` | `GET /open/v1/record-assets/ability-analyses/{analysis_id}/ability-items` | record-assets |
| `list_ability_relations` | `GET /open/v1/record-assets/ability-analyses/{analysis_id}/relations` | record-assets |
| `get_ability_analysis_tasks` | `GET /open/v1/record-assets/ability-analyses/{analysis_id}/tasks` | record-assets |
| `find_ability_items` | `GET /open/v1/record-assets/ability-items` | public-business |
| `get_job_capability_graph` | `GET /open/v1/record-assets/graphs/job-capability` | record-assets |
| `get_occupational_capability_graph` | `GET /open/v1/record-assets/graphs/occupational-capability` | record-assets |
| `get_teaching_standard_knowledge_graph` | `GET /open/v1/record-assets/graphs/teaching-standard-knowledge` | record-assets |
| `search_evidence` | `GET /open/v1/search` | search |
| `list_open_talent_training_plans` | `GET /open/v1/talent-training-plans` | talent-training-plans |
| `get_open_talent_training_plan` | `GET /open/v1/talent-training-plans/{item_id}` | talent-training-plans |
| `get_open_course_knowledge_graph` | `GET /open/v1/talent-training-plans/{item_id}/course-knowledge-graph` | talent-training-plans |
| `get_open_position_capability_graph` | `GET /open/v1/talent-training-plans/{item_id}/position-capability-graph` | talent-training-plans |
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
- `GET /open/v1/record-assets/major-distribution-records`：deprecated_or_streaming
- `GET /open/v1/record-assets/major-distribution-records/aggregate`：deprecated_or_streaming
