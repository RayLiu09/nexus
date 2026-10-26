# 岗位分析 OpenAPI 与 SKILL 适配任务包

日期：2026-10-26；单 Agent 顺序实施。依据用户在缺口分析后的明确实施要求、ARCHITECT/SPEC/WORKFLOWS，以及职业能力分析 SKILL/reference。

目标：岗位地区与标准职业面向检索可用；标准公开读取不依赖 active；技能以 NEXUS 资料生成新的 PGSD，不依赖既有 PGSD 或额外权威性核验。

冻结接口：`GET /open/v1/market-jobs` 和 `/aggregate` 增加 `region`，对原始岗位地址做转义子串检索，与其他条件 AND、分页前过滤；不以采集地区冒充工作地点。`GET /open/v1/teaching-standard-libraries` 增加 `occupation`，匹配现有 source-scoped 职业面向事实的对应行业、职业类别/代码和主要岗位。标准响应增加有定位的 `career_orientation`，保留原响应字段。标准、课程、资源发现、候选和 exact-ref 图谱移除 active 限制，保留当前 available/ref/分类/投影一致性。

范围：公开查询/DTO/工具生成与测试；职业面向纵向表规则提取、专用无 AI 幂等补录及测试；指定 SKILL/reference/生成器/来源展示与导出适配；必要根文档、接口说明和验证证据。

平台来源契约：`provider=nexus` + `resourceType` + `recordId`（文档可选 normalizedRefId/sectionId），无需 publisher/发布日期/外部 URL；verified 表示已读采用内容。三类检索分别从平台大典、平台标准、NEXUS 证书联网搜索取得；后者显式 auto_ingest=false。不引入其他检索工具，不保存正式成果。

禁止：不更改权限或治理决策，不改变标准生命周期、不重算课程建议/派生标签、不执行 LLM 补录、不依赖旧 PGSD，不新增数据库主表，不修改无关 Docker/其他用户技能。

验收：地区过滤列表/聚合一致、特殊字符按文本匹配；review 标准/课程可读、不可读与旧 ref 仍隐藏；职业面向去重/分页/条件组合与正文证据正确，横纵表均支持；补录幂等且只更新职业面向；平台来源离线展示/导出且无凭据；生成器校验保留 PGSD/KSA/证据/ID 约束；工具重生成 --check 通过。API Contract、Permission/Audit 和技能输出契约审查记录至 review evidence；不未经用户指令提交/推送。

实施状态：代码和自动化/本地浏览器验证完成。验证范围、开发库补录及人工 Review Gate 状态见 [审查证据](../review/wk_occupational_competency_openapi_skill_review_evidence.md)。用户已在查看实现和验证结果后授权本轮提交并推送。
