# Task Package: 文档主题过滤的 normalized ref 范围

日期：2026-11-16。单 Agent 顺序实施。

## 来源与目标

- 来源：公开 Agent OpenAPI 场景报告 S1 的主题误命中记录、`WORKFLOWS.md` Semantic Retrieval / API Contract Review Gate、现有 `document_ref_query` 与 Console 目录过滤实现。
- 目标：保证 `topic=finance_commerce|low_altitude` 只检查当前可消费 normalized ref 的正式标题/标签，不被同一资产历史 ref 或其他资产的标签污染。

## 冻结范围

- 允许修改：`nexus-api/nexus_api/api/internal/assets.py` 的主题 EXISTS 关联表达式、文档主题过滤回归测试、任务包和必要的验证证据。
- 公共 `/open/v1/assets` 与内部文档目录继续共享主题谓词；保留标题命中、`industry/topic` 标签类型和现有主题词表。
- 当前 ref 由既有 catalog resolver 选择；本切片不改变 available/current-ref 状态规则和标签生成逻辑。

## 不在范围内

- 不修改主题词表、治理分类、标签归一化规则、检索知识类型或语义索引。
- 不处理岗位排序/快照、SQL 索引、资源发现映射或 P2 性能问题。

## 实施内容

- 将主题标签 EXISTS 写成显式 `TagAssetIndex` FROM，并排除标签表自身的自动相关；仅让 `target_id` 关联外层 `catalog_ref_id`。
- 增加同一资产历史 normalized ref 带主题标签、当前 ref 不带标签时的 Console 与公共查询回归断言。
- 保留不同资产隔离、标题主题命中、重叠主题和分页计数测试。

## 验收

- 历史 ref 的主题标签不会使当前 ref 命中；其他资产标签不会串入当前资产。
- 公共和内部主题过滤定向测试通过，OpenAPI/Schema 无变化，`git diff --check` 通过。
