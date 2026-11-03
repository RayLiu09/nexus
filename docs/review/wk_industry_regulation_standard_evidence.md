# 行业法规标准分类、资产列表与数据校正证据

对应任务包：[wk_industry_regulation_standard_task_package.md](../task-packages/wk_industry_regulation_standard_task_package.md)。

## 交付合同

- 正式分类 `industry_regulation_standard`，名称“行业法规标准”；资产中心入口/标题为“法规标准”。
- 路径 `/asset-center/policy/industry-regulation-standards`，内部 GET `/internal/v1/industry-regulation-standards`。
- 列表顶部“全部 / 财经商贸类 / 低空经济类”及计数，与区域、行业、内容标签共同过滤，切换主题重置分页。
- 列表操作：知识块视图、解析预览、原文下载。复用标准化文档列表，不建领域模型、outline 或证据图。
- `industry_research_kb` 仅语义切块；分类层阻止继承知识类型的 graph_profile。
- 公开发现新增此资源；共享文档 `resource_type` 接受新代码，公开 function tools 已重新生成并检查漂移。

## 分类规则与边界

输入仅 normalized_document 的正文/块；不直接治理原始文件、原始 JSON 或 MinerU 输出。
规则 `normative_document.v1` 在所有行业通用，组合以下证据，不依赖低空经济主题词：

1. 法规/规章/办法/规则/标准/技术规范/监管审定程序/主管部门操作指南等文件身份。
2. 正文自指与规范结构：适用范围、术语和定义、规范性引用文件、执行要求、检验规则，或连续法规条号。
3. 发布主体、文号、标准编号等来源身份。
4. 编号、发布实施信息明确的标准封面允许确认类型，但不推定条款完整性；带明确官方文本来源的法规单条摘录按法规处理。
5. OCR 空白、缺失章节编号、暂行文本和征求意见稿不改变文档类型；效力单独记录，征求意见/草案标记 draft，其他未核验效力标记 needs_review，不据此改变治理状态。

保留发展目标/重点任务/财政支持/投资补助政策；不把标准体系建设方案、报告/白皮书、法规解读、新闻、立项登记、附件链接清单、标准编制说明归为标准正文。院校专业教学标准、课程教材继续使用原类别。

实际跨行业正例包括：直播电商监督管理办法、SB/T 11240—2023《直播电子商务平台管理与服务规范》、能源行业数据分类分级指南、电网设备无人机巡检技术导则、中央企业发展规划管理办法、贵阳市数字经济促进条例。测试另覆盖食品、医疗、制造、交通、信息技术、农业机械等行业。

## 开发库实际执行

日期：2026-11-02。扫描期间接入作业持续生成标准化文档，因此早期清单 1,991、复扫 2,001 与最终执行 2,006 的数量不同。范围为当前目录选择的版本、最新 generated normalized ref、最新正式治理结果，分类为产业政策/教育政策/产业报告/行业报告及已归类法规标准；不把历史分类结果误当当前分类。

- 最终执行扫描 **2,006** 份，读取标准化正文失败 **0**；随后补充复核并纠正 5 份完整法律正文。
- 实际纠正 **103** 份，原分类均为 industry_policy；其中首轮 98 份，后续补充 5 份法律正文。
- 新规则版本 `a46781ed-a4d1-4540-95c8-e2a47b170dcd`；历史规则内容不改写。
- 执行 trace `2cbbfc2e-a697-421d-886d-18a959bfc9d7`：98 条新治理结果；补充法律 trace `8a7a111d-ff2a-4920-a36c-b3cc5218b20d`：5 条新治理结果；每条均有对应结果审计，另有 2 条规则版本审计。
- 逐份验证旧结果存在，level/tags/org_scope/index_admission/quality_summary/status 与新结果相同；normalized ref 分类一致、语义 emissions 无 graph_profile。
- 元数据投影另有逐项审计，不保留冗余治理结果反向指针；正式结果通过 normalized_ref_id 正向关联。
- 同一 98 份再次 apply：scanned=98、accepted=98、updated=0，规则版本不变。
- 直接调用开发库列表读模型在首轮校验时为全部 **98**、财经商贸类 **6**、低空经济类 **78**；补充 5 份法律后当前“全部”为 **103**，实时列表计数为财经商贸类 **6**、低空经济类 **79**。主题按既有筛选口径计算，不要求两类覆盖所有行业。

完整资产 ID、版本 ID、normalized ref ID、原分类及命中证据见 [results JSON](wk_industry_regulation_standard_results.json)；不包含正文或存储凭证。

指定批次逐份分析：

| 文件同步批次 | 总份数 | 归入法规标准 | 保留产业政策 |
| --- | ---: | ---: | ---: |
| dad133ff-5a5d-475e-a407-5cb01349f267 | 20 | 18 | 2 |
| 9a0f840f-3f83-4bf4-8f61-7d6063e9e62d | 16 | 15 | 1 |

保留的三份为《体育总局航管中心关于促进低空经济发展的若干意见》《低空飞行服务保障体系建设总体方案》《民用航空监视技术应用政策》：正文分别以发展促进措施、体系建设任务、监视技术发展目标与分期应用策略为主，不是统一合规或技术条款正文。

## 验证与 Review Gate

- 新分类及 seed 相关 pytest：29 passed。
- API 分类纠正/审计/幂等、标签/主题筛选、现有政策列表及公开资源发现：50 passed；补充迁移事务与缺失正文 fail-closed 测试后，新测试文件 4 passed。
- Console 入口、路由、主题请求及列表/图入口：4 files，30 passed。
- Console `npm run typecheck`：通过。
- `generate_public_function_tools.py --check`：通过；`git diff --check`：通过。
- 扩展检查 knowledge-emissions 与既有教材规则测试：19 passed，1 条既有失败。失败为 `test_job_demand_classification_requires_actual_vacancy_evidence`，断言默认 Prompt 包含 job_demand；本次未更改 default_prompts.py，HEAD 同样不包含该文字，属于既有基线不一致。
- 沙箱内 Starlette TestClient 的事件循环挂起；沙箱外使用隔离 SQLite 重跑后完成上述 API 测试，没有使用共享开发库执行测试写入。
- 本机 8000/3000 无运行服务，因此未声称已完成浏览器/运行实例联调；部署后的 API/Worker 必须重新加载规则和代码，Console 加载新前端代码。

Data Model / Rule Engine / AI Governance / Permission And Audit / API Contract / Frontend UX Gate 的实现证据如上。按 WORKFLOWS.md 要求，合并前仍需人类 Review；本次未合并或部署。

## Follow-up: 显示顺序调整

- 治理审核“数据分类”下拉选项固定以“产业政策”“行业法规标准”为第一、第二项，其余选项保留规则给定顺序；不重写数据库规则。
- 资产中心市场数据同级顺序调整为“市场岗位 → 产业园区 → 企业数据 → 电商示范基地”，链接及计数键保持原样。
- 验证：现有治理审核、资产中心目录和概览共 3 个测试文件 14 项通过；Console TypeScript 检查、`git diff --check` 通过。
- 后续资产中心入口顺序：“产教政策 → 法规标准 → 教育政策 → 产业报告 → 行业报告”；仅移动“法规标准”，其余入口相对顺序不变。目录现有 8 项测试通过。
