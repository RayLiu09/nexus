# Chunk Quality Report

Generated at: 2026-08-02 03:28:39 UTC
Source: live read-only database query
Scope: normalized refs with `status=generated` and asset versions in `available/review_required` by default
Database writes: none

## Executive Summary

- Normalized refs analyzed: 37
- Chunks analyzed: 8706
- Pass refs: 12
- Warning refs: 17
- Block refs: 8

## Scope And Methodology

- This report is generated from read-only SQL over `normalized_asset_ref`, `asset_version`, and `knowledge_chunk`.
- No database tables, rows, migrations, jobs, or index manifests are written.
- Document refs are expected to carry chunk provenance through `locator`, `source_block_ids`, and `heading_path`.
- Record refs are not penalized for missing locators, because record chunks may be locator-null by contract.
- `block` means the ref should be reviewed before chunk/index rebuild or public QA use; it does not mutate asset status.

## Priority Findings

- Blocked refs requiring review: 8
- Policy/report refs that should be considered for derived section context: 9
- Refs with oversized chunks above hard max: 7
- Document refs with heading path coverage below 80%: 4
- Highest-priority blocked refs: 3.O2O模式的特征与商业价值.docx; 《网店运营》微课大纲【2.26】.xlsx; 2025年1-9月我国电子商务发展情况.pdf; 电子商务相关岗位需求数据.xlsx; （高职电子商务类专业简介）5307  电子商务类.pdf
- Worst oversized chunks by ref: 47411-A0电子商务数据分析实践（初级）.pdf max=43126; 2025直播电商行业发展白皮书.pdf max=4181; 短视频拍摄与剪辑.pdf max=3481; 《直播运营实务》教材 .docx max=2994; 《零售门店O2O运营》课程标准.pdf max=2980
- Lowest heading coverage refs: 3.O2O模式的特征与商业价值.docx heading=0.0%; （高职电子商务类专业简介）5307  电子商务类.pdf heading=0.0%; （中职电子商务类专业简介）7307 电子商务类.pdf heading=0.0%; 47411-A0电子商务数据分析实践（初级）.pdf heading=61.7%

## Ref-Level Metrics

| normalized_ref_id | title | type | knowledge_types | chunks | locator_cov | heading_cov | p95_chars | max_chars | table_rows | outline_cov | status | warnings | actions |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |
| b29297bb-a8fd-468a-8f0b-054c3c632522 | 《零售门店O2O运营》课程标准.pdf | document | course_standard_authoring_process | 87 | 100.0% | 100.0% | 268 | 2980 | 16 | 0.0% | warning | oversized chunks detected; residual navigation/publication noise detected | add_hard_max_guard; inspect_noise_filter |
| 7b064d6f-6916-4a93-b010-897881bca2e6 | 【教学案例】1.云南白药携手美团买药：以价值共生开拓O2O增长新蓝海模式实战落地.pdf | document | course_textbook | 17 | 100.0% | 100.0% | 406 | 946 | 0 | 0.0% | pass | - | - |
| 1d2ec59f-057a-4da7-843d-5600e200b05e | 2.现代零售行业的关键特征.pdf | document | industry_research_kb | 20 | 100.0% | 100.0% | 213 | 247 | 0 | 100.0% | warning | policy/report asset has no persisted document_section model | build_section_model |
| a71a0f78-1382-4b32-a2df-94a5339ff329 | 1.零售行业的发展历程及趋势.pdf | document | industry_research_kb | 23 | 100.0% | 100.0% | 191 | 281 | 0 | 100.0% | warning | policy/report asset has no persisted document_section model | build_section_model |
| e325e915-c544-4be8-bfc6-bb2012765269 | 《直播运营实务》教材 .docx | document | course_textbook | 782 | 100.0% | 99.9% | 215 | 2994 | 6 | 0.0% | warning | oversized chunks detected; near-empty chunk ratio > 2%; residual navigation/publication noise detected | add_hard_max_guard; inspect_noise_filter |
| bd3c1fac-8028-401b-8fa0-e25f814b8f45 | 2.现代零售行业的关键特征.docx | document | industry_research_kb | 21 | 100.0% | 95.2% | 206 | 238 | 0 | 0.0% | warning | near-empty chunk ratio > 2%; policy/report asset has no persisted document_section model | inspect_noise_filter; build_section_model |
| 29a55a76-73d5-4a87-a624-4c4455a59b4a | 5.零售门店O2O运营平台架构.docx | document | course_textbook | 19 | 100.0% | 94.7% | 228 | 232 | 0 | 94.7% | pass | - | - |
| 433dfc58-e628-4f3d-9a12-f90387342290 | 1.零售行业的发展历程及趋势.docx | document | industry_research_kb | 25 | 100.0% | 96.0% | 184 | 269 | 0 | 0.0% | warning | near-empty chunk ratio > 2%; policy/report asset has no persisted document_section model | inspect_noise_filter; build_section_model |
| 413c9be2-c095-4d9d-a6e6-d5000a4f4276 | 4.零售门店O2O运营的运作模式.docx | document | course_textbook | 19 | 100.0% | 94.7% | 217 | 259 | 0 | 0.0% | pass | - | - |
| 9089c5c8-e4a9-4579-af5a-dcbb8aca7817 | 3.O2O模式的特征与商业价值.docx | document | - | 0 | 0.0% | 0.0% | 0 | 0 | 0 | 0.0% | block | document has no chunks | rebuild_chunks |
| cf17cbcc-e83a-4749-bd3c-97872e6cf852 | 《网店运营》微课大纲【2.26】.xlsx | record | - | 0 | 0.0% | 0.0% | 0 | 0 | 0 | 0.0% | block | ref has no chunks | rebuild_chunks |
| fb96858c-32a7-4a8e-b8f4-c9d2ef6cdd6c | 北京市人才发展报告.pdf | document | industry_research_kb | 1289 | 100.0% | 100.0% | 576 | 2462 | 45 | 0.0% | warning | residual navigation/publication noise detected; policy/report asset has no persisted document_section model | inspect_noise_filter; build_section_model |
| adb6af18-6e74-41a1-afb0-ede73b0369e4 | 1.教育强国建设规划纲要（2024—2035年） .pdf | document | industry_research_kb | 43 | 100.0% | 100.0% | 347 | 576 | 0 | 0.0% | pass | - | - |
| f082eafb-12b7-444c-9047-fb6670af311c | 北京市十五五规划.pdf | document | industry_research_kb | 419 | 100.0% | 100.0% | 337 | 2804 | 0 | 0.0% | warning | oversized chunks detected; residual navigation/publication noise detected | add_hard_max_guard; inspect_noise_filter |
| 9da5d100-592d-4eda-a5fc-3b771788c017 | 2022年中国电子商务报告.pdf | document | industry_research_kb | 774 | 100.0% | 99.9% | 498 | 822 | 194 | 0.0% | warning | residual navigation/publication noise detected; policy/report asset has no persisted document_section model | inspect_noise_filter; build_section_model |
| c46461e8-f702-41f3-86af-5ba73f16d000 | 2025年1-9月我国电子商务发展情况.pdf | document | industry_research_kb | 12 | 100.0% | 100.0% | 163 | 230 | 0 | 0.0% | block | near-empty chunk ratio > 10% | rebuild_chunks |
| 75030a11-98cf-4262-bf91-45eeadf34d75 | （高职电子商务专业教学标准）电子商务专业教学标准-高等职业教育专科.pdf | document | course_standard_authoring_process | 85 | 100.0% | 100.0% | 355 | 402 | 17 | 0.0% | warning | residual navigation/publication noise detected | inspect_noise_filter |
| f39f078d-7fdc-44eb-b68f-3fe3342c2174 | 直播电商服务专业教学标准（中等职业教育）.pdf | document | course_standard_authoring_process | 70 | 100.0% | 100.0% | 326 | 418 | 7 | 0.0% | pass | - | - |
| 063bfeb9-0874-42f3-8979-1e57bea4e5aa | 移动商务专业教学标准（高等职业教育专科）.pdf | document | course_standard_authoring_process | 68 | 100.0% | 100.0% | 274 | 388 | 7 | 0.0% | pass | - | - |
| 68a58d01-a513-4fff-95c6-f2d599375080 | 网络营销与直播电商专业教学标准（高等职业教育专科）.pdf | document | course_standard_authoring_process | 74 | 100.0% | 100.0% | 281 | 339 | 11 | 0.0% | pass | - | - |
| 013105a2-9710-44ee-a1f0-b159a88bb5c2 | 市场营销专业教学标准（高等职业教育专科）.pdf | document | course_standard_authoring_process | 76 | 100.0% | 100.0% | 251 | 332 | 13 | 0.0% | pass | - | - |
| 593c8d0b-559f-4567-8ddd-37856b662d64 | 农村电子商务专业教学标准（高等职业教育专科）.pdf | document | course_standard_authoring_process | 80 | 100.0% | 100.0% | 307 | 432 | 15 | 0.0% | pass | - | - |
| e9e1ce2a-bae4-4954-9891-7ab2e43f8d3b | 跨境电子商务专业教学标准（高等职业教育专科）.pdf | document | course_standard_authoring_process | 74 | 100.0% | 100.0% | 293 | 385 | 10 | 0.0% | warning | residual navigation/publication noise detected | inspect_noise_filter |
| 98c910cb-4562-45ec-99d3-a7f732caafdf | 电子商务相关岗位需求数据.xlsx | record | - | 0 | 0.0% | 0.0% | 0 | 0 | 0 | 0.0% | block | ref has no chunks | rebuild_chunks |
| 224ba35f-c7a5-4ae0-8680-7a7859549ee4 | 武鸣职校《新媒体营销》 - 刷格式.pdf | document | course_textbook | 1335 | 100.0% | 100.0% | 291 | 1553 | 50 | 100.0% | warning | residual navigation/publication noise detected | inspect_noise_filter |
| be6079d7-4ac8-43c3-b182-3558bb7344de | 47411-A0电子商务数据分析实践（初级）.pdf | document | course_textbook | 1416 | 100.0% | 61.7% | 769 | 43126 | 57 | 0.0% | warning | missing heading_path ratio > 20%; oversized chunks detected; near-empty chunk ratio > 2%; residual navigation/publication noise detected | inspect_heading_extraction; add_hard_max_guard; inspect_noise_filter |
| 94901be8-2a89-4d26-bc97-2b6ddc06ccb5 | 短视频拍摄与剪辑.pdf | document | course_textbook | 1026 | 100.0% | 100.0% | 262 | 3481 | 3 | 68.7% | warning | oversized chunks detected; near-empty chunk ratio > 2%; residual navigation/publication noise detected | add_hard_max_guard; inspect_noise_filter |
| b7e32f6e-7b77-43d0-9a0e-00d6f6148e20 | 商务部等6部门关于更好服务实体经济 推进电子商务高质量发展的指导意见.pdf | document | industry_research_kb | 20 | 100.0% | 100.0% | 270 | 277 | 0 | 0.0% | pass | - | - |
| 7e6c1f51-1b41-403b-a046-74ff179e6539 | （高职电子商务类专业简介）5307  电子商务类.pdf | document | major_profile_knowledge | 36 | 100.0% | 0.0% | 458 | 507 | 0 | 0.0% | block | missing heading_path ratio > 50% | rebuild_chunks |
| 1b2bef04-0c0f-4026-9d7c-609689d87fb3 | （中职电子商务类专业简介）7307 电子商务类.pdf | document | major_profile_knowledge | 30 | 100.0% | 0.0% | 364 | 453 | 0 | 0.0% | block | missing heading_path ratio > 50% | rebuild_chunks |
| 8de3f82a-523a-476f-9318-e4dbe60c5d6e | 电子商务专业布点数量.xlsx | record | structured_record_table | 32 | 0.0% | 0.0% | 188 | 189 | 0 | 0.0% | pass | - | - |
| e167eef9-56d8-45a4-baba-b807fb97f2dd | 2.（专业布点数）专业布点数.xlsx | record | structured_record_table | 2 | 0.0% | 0.0% | 197 | 197 | 0 | 0.0% | pass | - | - |
| cee5927f-38e8-4037-86ac-10f66a6b9077 | 2.（职业能力分析）大数据技术应用专业职业能力分析表.xlsx | record | - | 0 | 0.0% | 0.0% | 0 | 0 | 0 | 0.0% | block | ref has no chunks | rebuild_chunks |
| 2f15d9ab-b1ce-45c4-b8f9-46af6c078321 | 1.（岗位需求）电子商务岗位招聘数据.xlsx | record | - | 0 | 0.0% | 0.0% | 0 | 0 | 0 | 0.0% | block | ref has no chunks | rebuild_chunks |
| 6ad68d75-471d-4d4c-abff-f73fe0e34a16 | 2025直播电商行业发展白皮书.pdf | document | industry_research_kb | 223 | 100.0% | 100.0% | 675 | 4181 | 56 | 0.0% | warning | oversized chunks detected; residual navigation/publication noise detected; policy/report asset has no persisted document_section model | add_hard_max_guard; inspect_noise_filter; build_section_model |
| 1251b47d-829e-4af6-9627-72c399bc3ca8 | （跨境电商行业报告）2025上半年跨境电商行业报告.pdf | document | industry_research_kb | 307 | 100.0% | 100.0% | 618 | 2694 | 39 | 0.0% | warning | oversized chunks detected; residual navigation/publication noise detected; policy/report asset has no persisted document_section model | add_hard_max_guard; inspect_noise_filter; build_section_model |
| 31df3090-8745-4cd9-87ce-8c68c81784bd | （电子商务产业报告）中国电子商务报告（2024）.pdf | document | industry_research_kb | 202 | 100.0% | 99.5% | 754 | 1027 | 0 | 0.0% | warning | residual navigation/publication noise detected; policy/report asset has no persisted document_section model | inspect_noise_filter; build_section_model |

## Aggregate Signals

- Total refs: 37
- Total chunks: 8706
- Missing locator chunks: 34
- Missing heading path chunks: 649
- Oversized chunks: 19
- Low-information chunks: 8
- Table-row chunks: 546

## Recommended Next Actions

1. Review every `block` ref before index rebuild or public QA use.
2. Add a policy/report derived section model for refs with good heading coverage but no section context.
3. Add a hard-max guard for oversized semantic units.
4. Inspect residual TOC/footer/copyright noise and update `semantic_repack` filters only with regression tests.
5. Re-run this report after any chunk rebuild, outline rebuild, or section model prototype.
