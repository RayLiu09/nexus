# Task Package: 标签目录过滤复合索引

日期：2026-11-16。单 Agent 顺序实施。

## 来源与目标

- 来源：任务 2 SQL/索引性能优化；文档资产目录和内部目录都按当前 normalized ref 查询 `tag_asset_index`，同时约束 `target_type`、`target_id` 和 `tag_type`。
- 目标：为该高频谓词增加复合 B-tree 索引，减少标签类型过滤的残余扫描。

## 冻结契约

- 新索引：`(target_type, target_id, tag_type)`，名称 `ix_tai_target_tag_type`。
- 现有 `ix_tai_target` 保留，支持不带 tag_type 的完整标签反查和缓存失效路径。
- 不改变标签值匹配、当前 ref 解析、权限、治理和 API 返回结果。

## 不在范围内

- 不修改 SQL 谓词、主题词表、标签写入逻辑或 API schema。
- 不引入 pg_trgm、全文索引、分区或 Redis；这些需要独立执行计划和容量评测。

## 验收

- ORM 与 Alembic migration 声明一致，升级/降级名称稳定。
- 标签模型回归、主题过滤回归、编译检查和 `git diff --check` 通过。
