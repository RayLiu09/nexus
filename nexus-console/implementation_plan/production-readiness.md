# nexus-console Production Readiness 实施计划

> 编制时间：2026-06-03
> 基于：`TODO-production-readiness.md`（2026-05-20）与 v0.2 基线审计
> 认证方式：**登录用户 + API Caller 均采用 Bearer JWT**

---

## 当前基线（v0.2）已有积累

| 维度 | 状态 |
|------|------|
| TypeScript | `strict: true`，0 错误 |
| ESLint | 0 error，3 warning（可接受） |
| 数据层 | `lib/api.ts`（getApiData/postApiData）、`lib/ingestProxy.ts`、`lib/mock-data.ts` |
| 状态管理 | `lib/queryClient.ts`（TanStack Query v5）、`lib/usePolling.ts` |
| 认证骨架 | `lib/auth/`（MOCK_USERS、session、useSession，均为占位） |
| 错误边界 | `react-error-boundary` 已安装，`RouteBoundary.tsx` 已就绪 |
| 输入校验 | Zod 已安装 |
| 页面骨架 | 14+ 路由全部可构建，均有 `loading.tsx`、`error.tsx`、`not-found.tsx` |

---

## 阶段 1：阻断级 — 无此不上生产（估时 10-14 天）

### P1.1 认证体系（R2）— Bearer JWT

**认证方案**：
- 登录用户：用户名/密码 → 后端签发 Bearer JWT（access + refresh token）
- API Caller：通过 console 管理 `api_caller` 实体，签发独立的 Bearer JWT
- Token 存储：access token 存内存（闭包变量），refresh token 存 httpOnly cookie
- 前端不直接操作 token 字符串，通过 `/api/auth/*` Next.js route handler 代理

**待办**：

- [ ] 与后端对齐 JWT payload 结构（user_id、org_id、roles、exp）
- [ ] 实现 `/login` 页：Antd Form + 用户名/密码 → `POST /v1/auth/login` → 返回 token
- [ ] 实现 `lib/auth/token.ts`：内存存储 access token，自动附着 `Authorization: Bearer <token>`
- [ ] `lib/api.ts` 增强：401 → 尝试 refresh → 失败则跳 `/login`
- [ ] `app/(authed)/layout.tsx` route group：未登录重定向 `/login`
- [ ] `lib/auth/session.ts` 补全：getCurrentUser / hasPermission / hasRole / useCurrentUser
- [ ] Role-based UI 控制：管理员可见「规则配置」「AI Prompts」，普通用户隐藏
- [ ] Topbar pill 接入真实数据（当前为 mock 静态值）
- [ ] API Caller 管理：console 内创建/吊销 API Caller，签发独立 JWT

### P1.2 API 契约对齐（R1）

**待办**：

- [ ] 与后端盘点 14 个页面所需 API，产出 `docs/api-contract-status.md`
- [ ] 每个接口标注：`ready` / `partial` / `mock` / `planned`
- [ ] 写操作约定 `Idempotency-Key` header（`lib/api.ts` 内置 UUID v7）
- [ ] 后端响应回写 `trace_id`，前端 ErrorState 组件展示

### P1.3 危险操作安全（R3）

**范围**（治理相关排后）：
- 删除数据源
- 撤销/禁用 API Caller
- 批量作业操作（重试/取消）
- 规则发布（排后）

**待办**：

- [ ] 盘点非治理危险动作清单
- [ ] `components/shared/ConfirmButton.tsx`：基于 `antd/Modal` + 可选输入确认词二次确认
- [ ] 乐观更新 + 失败回退 UI 通用模式

---

## 阶段 2：性能与实时性（估时 8-12 天）

### P2.1 性能优化（R4）

- [ ] 性能预算：LCP < 1.5s，TTI < 2.5s，bundle < 200KB gzip
- [ ] 资产目录 / raw-ledger 表格切换服务端分页
- [ ] 表格关键列 `fixed: 'left' | 'right'`
- [ ] 长列表 Antd `Table virtual`
- [ ] 重型组件 `next/dynamic({ ssr: false })`
- [ ] 首屏 RSC 并行 `Promise.all` 数据预取
- [ ] Lighthouse CI 配置

### P2.2 实时性（R5）

- [ ] 三级刷新频率标准：30s / 60s / 5min
- [ ] `usePolling` 补 `refetchIntervalInBackground: false`
- [ ] SLA 倒计时纯前端

---

## 阶段 3：测试体系（估时 6-10 天）

### P3.1 测试基建（R6）

- [ ] Vitest + Testing Library（`components/shared/` 起步）
- [ ] MSW handler 基于 Zod schema + mock 工厂
- [ ] Playwright 3 条核心 E2E 流程
- [ ] CI：lint + typecheck + unit + build
- [ ] `@axe-core/playwright` a11y 自动检测

---

## 阶段 4：质量工程（估时 8-10 天）

### P4.1 Mock 与真实数据同源（R10）

- [ ] Zod schema 推导 TS 类型 + mock 工厂
- [ ] `@faker-js/faker` 随机数据生成
- [ ] `NEXT_PUBLIC_USE_MOCK` 开关
- [ ] 后端 OpenAPI 后同步校验

### P4.2 可观测性（R11）

- [ ] Sentry 错误上报
- [ ] Web Vitals 上报
- [ ] 关键操作埋点（治理部分预留）

### P4.3 i18n 基建（R9）

- [ ] `next-intl` 安装 + 配置
- [ ] `i18n/zh-CN.json` 建立
- [ ] 新增代码强制 i18n key
- [ ] CI 中文硬编码检测

---

## 阶段 5：治理业务页面（排后，估时 10-14 天）

> 前置条件：AI 数据资产治理业务规则定义完成。

### P5.1 治理中心（/governance）

- [ ] 对接真实审核队列 API
- [ ] DetailDrawer tabs（Review / AI Suggestions / Quality / Decision Trail）真实数据
- [ ] 裁定操作（adopt / reject / override）

### P5.2 标签审核（/tag-review）

- [ ] 对接真实标签审核 API
- [ ] 批量审核操作

### P5.3 规则配置（/rules）

- [ ] Monaco 编辑器 `next/dynamic`（或保持 textarea）
- [ ] 规则发布 + ETag 冲突处理
- [ ] 批量重跑结果真实数据

---

## 阶段 6：发布与运维（估时 4-6 天）

### P6.1 部署（R12）

- [ ] 明确部署方式，适配构建产物
- [ ] nginx 反代示例 + 健康检查

### P6.2 浏览器兼容（R13）

- [ ] 最低支持版本：Chrome/Edge ≥ 100, Safari ≥ 15
- [ ] 国密浏览器核对
- [ ] Playwright 多浏览器 CI

### P6.3 文档（R14）

- [ ] `CONTRIBUTING.md`
- [ ] Storybook / Ladle shared 组件文档

---

## 阶段汇总

| 阶段 | 内容 | 估时 | 优先级 |
|------|------|------|--------|
| P1 | Auth + API 契约 + 危险操作安全 | 10-14 天 | 🔴 阻断 |
| P2 | 性能 + 实时性 | 8-12 天 | 🟠 高 |
| P3 | 测试基建 | 6-10 天 | 🟠 高 |
| P4 | Mock 同源 + 可观测 + i18n | 8-10 天 | 🟡 中 |
| P5 | 治理业务页面（排后） | 10-14 天 | 🔵 延后 |
| P6 | 部署 + 兼容 + 文档 | 4-6 天 | 🔵 收尾 |

**总计**：36-52 天单人（不含 P5），含 P5 为 46-66 天。

---

## 治理变更风险缓冲

1. P1-P4 期间，治理相关页面保持当前 mock 状态
2. 业务规则确定后，P5 启动前做一次 API 契约对齐（1-2 天）
3. 规则定义大变动可能导致 rules 页 JSON → 结构化表单，额外 3-5 天
