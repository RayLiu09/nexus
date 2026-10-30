# 电商示范基地应用层与 Console 验证记录

日期：2026-10-30
范围：`/asset-center/market/ecommerce-demo-bases`、只读查询接口和资产中心入口计数。

## 已完成的自动验证

- PostgreSQL 只读事务：迁移版本为 `20261030_0129`；`ecommerce_parks` 返回国家 170 条、省级 142 条；国家批次为首批 34、第二批 63、增补 73；国家江苏筛选 15 条；省级地区为江苏 79、山东 33、河南 9、湖北 18、广西 1、甘肃 2。
- 后端目标测试：`tests/test_ecommerce_demo_bases_api.py` 与资产中心计数回归筛选共 9 项通过。覆盖 JWT、参数校验、字面量查询、分页、聚合一致性、来源链接、只读方法和完整快照统计。
- Console Vitest：4 个测试文件、28 项通过。
- Console `npm run typecheck` 通过。
- 变更文件 ESLint（使用安装的 Next core-web-vitals/TypeScript 配置）通过；仓库默认配置缺少 `eslint-plugin-testing-library`，因此未修改依赖绕过该环境问题。
- Console `npm run build -- --webpack` 通过。Turbopack 构建在当前受限环境的字体/CSS worker 权限阶段失败，Webpack 构建作为可重复的生产构建验证。
- Playwright Chromium：桌面 1440×1000 与平板 834×1194 各执行国家入口/批次/图表柱状图和地图点击、URL 恢复、省份列表/分页/组合筛选/空结果、地图失败重试 3 项，共 6 项通过；记录了 0 个写请求和 0 个页面错误。

## 页面证据

截图来自隔离验收 API（312 条持久化快照）和最新 Console 生产构建：

- [桌面国家视图](artifacts/ecommerce-demo-bases/desktop-national.png)
- [桌面省份视图](artifacts/ecommerce-demo-bases/desktop-provincial.png)
- [平板国家视图](artifacts/ecommerce-demo-bases/tablet-national.png)
- [平板省份视图](artifacts/ecommerce-demo-bases/tablet-provincial.png)

## 评审状态

本记录是自动化和工程验收证据，不替代 `WORKFLOWS.md` 要求的人工 API Contract、Frontend UX 和 Acceptance Review Gate。人工评审、合并和生产部署状态仍由项目负责人确认。
