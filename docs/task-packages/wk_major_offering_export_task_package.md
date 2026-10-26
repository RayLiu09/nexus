# Task Package: 专业布点检索区调整及 Excel 导出

日期：2026-10-26。单 Agent 顺序实施。

依据：用户要求、SPEC.md 专业布点只读契约及 Prototype v2.2 专业布点列表。

目标：按钮改为“检索”，移除学校标识码筛选及来源提示，支持当前已应用条件下全部数据导出 Excel。

范围：专业布点列表/页面参数、共享领域排序、GET /v1/major-offerings/export 与内部身份别名 /internal/v1/major-offerings/export，复用 Console 下载代理。导出列为年份、省份、专业代码、专业名称、学校标识码、学校名称、年限、备注；保留代码文本及空值。采用 write-only 工作簿和分批数据库读取，记录读取审计。

禁止：不改数据、同步与去重口径，不恢复编辑删除或旧管道，不新增依赖，不更改无关列表。

验收：Excel 真实解析、筛选范围与全量导出、空结果表头、文本/公式处理、认证和审计；按钮/筛选/导出 URL 回归；类型检查。无需迁移。按 API Contract、Permission/Audit、Frontend UX Gate 记录验证。

结果：实现及定向验证完成，本地 API 已重启，见 [验证证据](../review/wk_public_tools_and_major_export_evidence.md)。
