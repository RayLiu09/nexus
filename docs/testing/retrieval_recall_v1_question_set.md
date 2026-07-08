# NEXUS v1.0 Retrieval/Recall Question Set

- **Status**: initial ORC-11 baseline
- **Coverage rule**: at least 5 cases per v1.0 business domain
- **Domains**: `course_textbook`, `major_profile`, `major_distribution`, `job_demand`, `competency_analysis`

This document is the human-readable source for the first evaluation set. The runnable evaluator consumes JSONL with the schema documented in `docs/testing/retrieval_recall_v1_eval_plan.md`; teams can derive JSONL from the table below once fixture ids are known in the target environment.

## 1. Course Textbook

| ID | Query | Expected Channel | Expected Plan / Evidence |
| --- | --- | --- | --- |
| CT-001 | 什么是直播电商？请结合教材内容解释核心概念。 | `unstructured` | `course_textbook` semantic chunk; cite definition chunk. |
| CT-002 | 直播电商运营流程包括哪些关键步骤？ | `unstructured` | retrieve process/task chunks; cite at least two source refs. |
| CT-003 | 请比较“选品”和“直播转化”在教材中的作用差异。 | `unstructured` | multi-sub-query or one semantic query with both concepts; cite both concepts. |
| CT-004 | 教材中关于客户画像分析有哪些方法？ | `unstructured` | retrieve customer-profile analysis chunks. |
| CT-005 | 根据教材内容，总结直播复盘需要关注哪些指标。 | `unstructured` | retrieve KPI / review / metrics chunks; Markdown bullets must cite refs. |

## 2. Major Profile

| ID | Query | Expected Channel | Expected Plan / Evidence |
| --- | --- | --- | --- |
| MP-001 | 电子商务专业的培养目标是什么？ | `unstructured` | `major_profile` semantic retrieval; cite profile objective section. |
| MP-002 | 大数据技术应用专业面向哪些职业岗位？ | `unstructured` | retrieve career-facing / employment direction chunks. |
| MP-003 | 请总结电子商务专业的核心课程。 | `unstructured` | retrieve course-system chunks; cite source refs. |
| MP-004 | 计算机应用专业需要哪些职业能力？ | `unstructured` | retrieve ability/competency section chunks. |
| MP-005 | 对比电子商务和大数据技术应用两个专业的就业方向差异。 | `hybrid` or `unstructured` | two domain-specific sub queries or one comparative semantic plan; cite both majors. |

## 3. Major Distribution

| ID | Query | Expected Channel | Expected Structured Profile |
| --- | --- | --- | --- |
| MD-001 | 近三年高职电子商务专业布点数变化趋势如何？ | `structured` | `major_distribution.trend_by_year`; group by `year`. |
| MD-002 | 电子商务专业在哪些省份布点较多？ | `structured` | `major_distribution.by_province`; group by `province_name`. |
| MD-003 | 本科层次的软件工程专业布点数量是多少？ | `structured` | `major_distribution.by_education_level` or `record_list` with `education_level`. |
| MD-004 | 浙江省有哪些学校开设大数据技术应用专业？ | `structured` | `major_distribution.record_list`; filter `province_name` and `major_name`. |
| MD-005 | 对比电子商务专业在高职和本科层次的布点差异。 | `structured` | `major_distribution.by_education_level`; filter `major_name`. |

## 4. Job Demand

| ID | Query | Expected Channel | Expected Structured Profile |
| --- | --- | --- | --- |
| JD-001 | 电子商务相关岗位在哪些城市需求较高？ | `structured` | `job_demand.count_by_city`; group by `city`. |
| JD-002 | 互联网行业电商运营岗位的学历要求分布如何？ | `structured` | `job_demand.count_by_education`; filter `industry_name` / `job_title`. |
| JD-003 | 上海电商运营岗位的薪资区间大致是多少？ | `structured` | `job_demand.salary_distribution`; filter `city` and `job_title`. |
| JD-004 | 岗位需求中经常出现哪些专业技能关键词？ | `structured` | `job_demand.requirement_keyword`; inspect requirement items. |
| JD-005 | 请列出杭州地区与数据分析相关的岗位需求明细。 | `structured` | `job_demand.record_list`; filter `city` and `job_title` or requirement keyword. |

## 5. Competency Analysis

| ID | Query | Expected Channel | Expected Structured Profile |
| --- | --- | --- | --- |
| CA-001 | 大数据技术应用专业的典型工作任务有哪些？ | `structured` | `competency.task_tree`; return task tree. |
| CA-002 | 数据采集任务关联哪些能力项？ | `structured` | `competency.ability_items_by_task`; group/filter by `task_code` or `task_name`. |
| CA-003 | 职业能力大类 P 下有哪些能力项？ | `structured` | `competency.ability_items_by_category`; group/filter `ability_major_category_code`. |
| CA-004 | 工作内容和能力项之间有哪些关系？ | `structured` | `competency.relations_by_ability`; filter `relation_type`. |
| CA-005 | 请按任务梳理大数据技术应用专业的工作内容和能力要求。 | `structured` | `competency.task_tree`; cite task/content/ability source refs. |

## 6. Low-Confidence / Clarification Set

These cases are not tied to one domain. They must stop at clarification when intent confidence is below `0.78`.

| ID | Query | Expected Behavior |
| --- | --- | --- |
| LC-001 | 帮我看看这个怎么样。 | `needs_clarification`, no retrieval execution. |
| LC-002 | 哪个专业更好？ | `needs_clarification`, ask for major names and comparison criteria. |
| LC-003 | 分析一下趋势。 | `needs_clarification`, ask for domain and metric. |
| LC-004 | 给我一些结论。 | `needs_clarification`, ask for data asset scope and question. |
| LC-005 | 这个岗位情况如何？ | `needs_clarification`, ask for job title, region, or industry. |

## 7. JSONL Authoring Notes

When converting this table to JSONL:

- Use lowercase ids such as `ct-001`.
- Fill `expected_chunks`, `expected_source_refs`, `expected_record_refs`, and `expected_aggregation_points` only after fixture ids are stable.
- Keep `expect_clarification=true` for the LC cases.
- Do not include raw source content, API keys, prompt text, or sensitive values.
