# Task Package: 最新资产类型公开工具集审核

日期：2026-10-26。单 Agent 顺序实施。

依据：ARCHITECT.md 的业务 API 服务边界、SPEC.md 的资产中心及公开消费约束、Prototype v2.2 当前可见资产入口、WORKFLOWS.md API Contract / Permission-Audit Gate。

目标：核对 docs/generated/public-function-tools 与当前 16 类可见资产入口，补齐职业分类大典，修复专业布点描述、参数、响应及退役接口泄漏。

冻结契约：增加 API Key 认证只读 GET /open/v1/occupation-dictionary，复用 /v1 查询与审计；职业大类/小类/名称组合检索和分页不变。专业布点 /open/v1/major-offerings 及 /aggregate 仅代表教育部同步事实，不使用旧 Pipeline B 或文档推导数据。移除同路径旧聚合注册，保留院校课程统计。旧布点记录接口保持 HTTP 410，标记 deprecated 并从工具中排除。资源发现增加职业分类大典。

范围：相关 nexus-api 路由/OpenAPI、生成脚本、生成产物、定向测试及合同/验证文档。

禁止：不修改数据模型、治理、后台同步、权限机制，不引入 AI 步骤或依赖；不覆盖其他未提交工作。

验收：16 类资源均有有效 GET 工具；新字典认证、过滤、分页、只读、审计测试；专业布点实际路由与 OpenAPI 一致且无重复公开路径；退役接口排除；生成确定性与 --check；相关公开消费回归。

结果：实现及定向验证完成，见 [验证证据](../review/wk_public_tools_and_major_export_evidence.md)。
