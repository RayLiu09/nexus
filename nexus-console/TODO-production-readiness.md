# nexus-console 生产可用性待办（Production Readiness Backlog）

> 编制时间：2026-05-20
> 性质：与 `plan.md`（UI 重构路线图）**互补**的工程待办清单。
> `plan.md` 的目标：把 v3.2 中保真原型实现为「UI 风格舒适、体验友好」的控制台界面。
> 本文件的目标：盘点把上述 UI 变成「真正可用的企业控制台」**还差什么**——契约、认证、性能、测试、可观测、部署等非 UI 维度的风险与待办。
>
> 两份文档**不耦合执行**，本文件中的事项可独立立项、按需排期。

---

## 风险等级说明

- 🔴 阻断级：不解决，发布即崩
- 🟠 高风险：解决不彻底，上线后频繁返工
- 🟡 中风险：影响产品质量，可上线后迭代
- 🔵 长尾：容易被低估，建议立项前明确

---

## 🔴 阻断级

### R1. 后端契约对齐 / API 盘点

**问题**：`plan.md` 假定 `/v1/...` 接口齐全，但实际仅部分就绪。`/tag-review` `/search` 后端缺位，写操作（裁定 / 批量重试 / 规则发布 / 撤销标签）的幂等键 + trace_id 回写约定未定义。

**待办**：

- [ ] 与后端共同盘点 14 个页面所需 API，产出 `docs/api-contract-status.md`：每个接口标注 `ready / mock / planned`
- [ ] 写操作约定 `Idempotency-Key` header 规范，`lib/api.ts` 内置生成与重试
- [ ] 后端响应统一回写 `trace_id`，前端错误信息附带（与阶段 -1 A4 微文案模板对齐）
- [ ] mock 数据与真实 API 同源：基于 Zod schema 生成 mock 工厂，避免字段漂移（见 R10）

---

### R2. 认证 / 授权 / 多租户

**问题**：`/login` 页是占位；无真实 session 流；topbar 三 pill（环境/角色/组织）暗示多租户上下文但无 token 存储/刷新/降权方案；无 route guard。

**待办**：

- [ ] 选型：Cookie-based session vs JWT；refresh token 策略；与后端 IAM 对齐
- [ ] `app/(authed)/layout.tsx` route group 做未登录跳转
- [ ] `lib/auth.ts`：getCurrentUser / hasPermission / hasRole；与 SPEC 中 RBAC 对齐
- [ ] role-based UI 隐藏：危险动作按钮、heatmap 中"不可见"列、L4 数据脱敏
- [ ] 三 pill 切换的真实数据流（环境切换可能触发 reload；组织切换需 invalidate query cache）
- [ ] 401 / 403 / token 过期的统一处理（不弹 toast，而是回登录或权限页）

---

### R3. 危险操作事务一致性

**问题**：规则发布触发 31 条索引 stale + 45 条 re-governance；批量裁定影响多 ref；网络中断会导致 UI 与后端状态不一致。`plan.md` 仅在验收门槛要求"idempotency 注释"，无具体方案。

**待办**：

- [ ] 危险动作清单（与阶段 -1 A3 联动），每项标注：是否需要 confirm dialog / two-step / undo toast / time-locked
- [ ] Idempotency-Key 在前端生成（uuid v7）+ 重试时复用同一 key
- [ ] 失败回滚：乐观更新 + 失败时显式回退 UI 状态 + 错误 toast 附 trace_id
- [ ] 长事务进度反馈（规则发布后 stale index / re-governance 是异步的，UI 需 poll 状态机）
- [ ] 二次确认链：高 blast-radius 操作（撤销 caller / 删除 provider / 发布跨域规则）走输入确认词二次确认

---

## 🟠 高风险

### R4. 性能与数据规模

**问题**：原型用静态小数据，真实环境资产目录 10w+ 行；workbench 一屏 7 区块独立 fetch = 首屏 7+ RTT；无虚拟滚动 / 服务端分页约定。

**待办**：

- [ ] 制定性能预算：首屏 LCP < 1.5s、TTI < 2.5s、单页 bundle < 200KB（gzip）
- [ ] 长列表策略：>500 行启用 Antd `Table virtual` 或 TanStack Virtual
- [ ] 服务端分页统一约定：`?page=1&pageSize=50&sort=...`，与后端对齐
- [ ] 列固定：表格关键列 `fixed: 'left' | 'right'`
- [ ] 首屏 RSC 并行 fetch：用 `Promise.all` 或 React 19 `use()` hook，避免瀑布式
- [ ] 重型组件懒加载：Monaco（rules）/ 图表（assets 域分布）`next/dynamic({ ssr: false })`
- [ ] Lighthouse CI：每页 PR 自动跑分，性能预算超阈值阻断合并

---

### R5. 实时性 / 轮询策略

**问题**：批次状态、作业进度、SLA 倒计时需要动态更新，`plan.md` 无方案。

**待办**：

- [ ] 选型决策：轮询 / SSE / WebSocket（建议先轮询，热点页面再升级）
- [ ] 标准 refresh interval：高频 30s（jobs running、ingest processing）/ 中频 60s（governance queue）/ 低频 5min（资产目录）
- [ ] TanStack Query `refetchInterval` + `refetchIntervalInBackground: false`（标签页切走停止轮询）
- [ ] SLA 倒计时：纯前端 setInterval + dayjs 计算，避免轮询后端
- [ ] 多人协作冲突提示：governance 裁定时若已被他人处理，显示"已被 @张敏 处理"并刷新

---

### R6. 测试覆盖

**问题**：`plan.md` 整文档没有"测试"，14 页 + 危险动作链路 + 权限矩阵零自动化保障。

**待办**：

- [ ] 引入 **Vitest + Testing Library**：组件单测，覆盖 shared/\* 与关键业务组件
- [ ] 引入 **MSW**：mock 后端响应，与 R1 mock 工厂同源
- [ ] 引入 **Playwright**：关键流程 E2E（登录 → 创建 batch → 治理裁定 → 检索验证）
- [ ] CI 门槛：lint + typecheck + unit + build；E2E 在 staging 跑
- [ ] 视觉回归：Playwright `toHaveScreenshot` 或 Chromatic（与 plan 阶段 4 sticky tab 之类的样式收尾联动）
- [ ] a11y 自动化：`@axe-core/playwright` 在 E2E 中跑，对应 plan 阶段 -1 A2

---

### R7. 工作量重估

**问题**：`plan.md` 估 22-28 天，但未计入：阶段 -1 实际 3-5 天（9 项规范）、P2.7 资产详情 5 tab + 数据整合实际 3-4 天、`app/rules/page.tsx`（Monaco + DSL + publish flow）单独 3-5 天、本文件涉及的非 UI 工作量。

**待办**：

- [ ] 立项时重估为 **45-60 天单人**（含本文件待办）
- [ ] 关键路径项（R1 / R2 / 资产详情 / 规则页）拆为前置子项，避免阻塞后续

---

## 🟡 中风险

### R8. 设计资源

**问题**：`plan.md` 多处要求"设计 review"，但无设计师在循环里；中保真原型缺高保真 / 交互动效 / 微文案库。

**待办**：

- [ ] 立项时确认设计资源：兼职 / 全职 / 外包
- [ ] 高保真稿覆盖：14 页 + 关键 drawer + 四态
- [ ] 微文案文案库：错误信息 / 空状态 / 危险确认 / 术语表（与 plan A4 联动）
- [ ] 动效规范：transition timing / easing / `prefers-reduced-motion`
- [ ] 缺设计资源时的退路：开发兼任，但每页 PR 必须 ≥ 1 名 reviewer 是产品方，避免纯工程视角

---

### R9. i18n 启动时机

**问题**：`plan.md` 阶段 2 的 14 页用中文硬编码，上线后补 i18n = 重写所有 JSX 字符串。

**待办**：

- [ ] 选型：`next-intl` 或 `react-i18next`（推荐 `next-intl`，与 App Router 对齐）
- [ ] **从 P2.1 起强制 i18n key**，新代码不硬编码（`.claude/rules/i18n.md` 已要求）
- [ ] 中文 key 起步：先建 `i18n/zh-CN.json`，按 `module.section.label` 命名
- [ ] 英文版可推后，但 key 体系必须先立
- [ ] CI 检测：grep JSX 中的中文字符，新增即报警（白名单：注释、document title 兜底）

---

### R10. mock 与真实数据偏差

**问题**：`plan.md` 风险章节说"先 mock 再接 API"，mock 数据形态可能与最终 API 偏差大（字段名、嵌套深度、空值语义）。

**待办**：

- [ ] Zod schema 同源：每个 API 响应定义 `z.object`，由 schema 推导 TS 类型 + mock 工厂
- [ ] mock 工厂用 `@faker-js/faker` 生成符合 schema 的随机数据
- [ ] 后端 OpenAPI 输出后，编写脚本对比前端 schema 是否同步
- [ ] mock 切换开关：`NEXT_PUBLIC_USE_MOCK=true` 时启用 MSW，否则走真实 API

---

### R11. 可观测性（错误上报 / 埋点 / 监控）

**问题**：`plan.md` 提到 trace_id 显示，但无前端错误上报 / Web Vitals / 用户行为埋点。

**待办**：

- [ ] 错误上报：Sentry 或自建（与 IT 政策对齐）；上报内容含 trace_id、用户 ID、URL、操作上下文
- [ ] Web Vitals 上报：`web-vitals` 包 + 自建 endpoint
- [ ] 用户行为埋点：关键操作（治理裁定、规则发布、检索验证）记录次数 + 耗时
- [ ] 数据反馈闭环：每月看一次"哪些功能在用 / 哪些没人点"，作为后续迭代依据

---

## 🔵 长尾

### R12. 部署形态

**待办**：

- [ ] 立项时明确：私有化 / SaaS / 离线？
- [ ] 影响：CSP 严格度、字体本地化、CDN 选型、构建产物大小限制、Docker 镜像
- [ ] 私有化场景需提供 nginx 反代示例 + 健康检查 + 升级回滚 runbook

---

### R13. 浏览器兼容矩阵

**待办**：

- [ ] 立项时明确最低支持浏览器版本（建议 Chrome/Edge ≥ 100，Safari ≥ 15）
- [ ] 国内政企场景核对国密浏览器 / 360 安全浏览器兼容
- [ ] CI 内 Playwright 多浏览器项目跑 E2E
- [ ] React 19 + Next 16 + Tailwind v4 都不兼容老版浏览器，明确取舍

---

### R14. 开发者上手成本

**待办**：

- [ ] `nexus-console/CONTRIBUTING.md`：本地启动、调试、提交规范、shared 组件使用示例
- [ ] 选型 Storybook 或 Ladle：作为 shared/\* 组件文档（与 plan 阶段 1 联动）
- [ ] 新人 onboarding checklist：必读文档 / 必看代码 / 必跑命令

---

## 落地建议

| 时机                  | 处理项                                     |
| --------------------- | ------------------------------------------ |
| **立项前评审**        | R1 / R2 / R7 / R8 / R12 / R13              |
| **plan 阶段 -1 内补** | R3（与 A3 联动）/ R10（与 A1 mock 联动）   |
| **plan 阶段 1 内补**  | R6 测试基建 / R9 i18n 起步 / R14 docs 起步 |
| **plan 阶段 3 内补**  | R4 性能 / R5 实时性 / R11 可观测           |

---

## 与 plan.md 的关系

- `plan.md` = **UI 路线图**：14 页骨架、token、组件、视觉、四态。
- 本文件 = **生产可用补集**：契约、认证、事务、性能、测试、i18n、可观测、部署。

两份文档共同覆盖时，才能得到一个真正可用的企业控制台。任何阶段里只跑 `plan.md` 的进度，都意味着**本文件中的待办在累积技术债**。
