# NEXUS Console 前端工程契约

本文件是 `nexus-console/` 的前端工程契约，目标是构建**现代、高效、体验友好**的企业级控制台。内容基于 v0.2 基线实现撰写，随项目演进持续更新。

> **优先级**：仓库根目录的 `CLAUDE.md`、`ARCHITECT.md`、`SPEC.md`、`WORKFLOWS.md` 是 NEXUS 全局工程契约。本文件仅为前端工作的补充；冲突时以根契约为准。

---

## 基线信息（v0.2 — 2026-06-03）

| 维度 | 版本/取值 |
|------|-----------|
| Next.js | 16.2.4（App Router） |
| React | 19.0.0 |
| Antd | 6.4.3 |
| Tailwind CSS | 4.3.0 |
| TypeScript | 5.6（strict: true） |
| 包管理器 | npm（`package-lock.json`） |
| 当前路由数 | 19（全部可构建，0 TS 错误，0 lint error） |
| 构建状态 | 通过 |

---

## 一、技术栈基线

### 已落地（严格执行）

| 维度 | 选型 | 说明 |
|------|------|------|
| 语言 | TypeScript（`strict: true`） | 禁止 `any`，外部输入用 `unknown` 收窄 |
| 包管理器 | **npm** | 严禁 `pnpm install` / `yarn` |
| 框架 | **Next.js 16（App Router）+ React 19** | 默认 Server Component；`'use client'` 仅在确需交互时使用 |
| **UI 组件库** | **Ant Design 6（`antd@^6`）** | 业务组件首选；自研组件逐步退役 |
| **样式方案** | **Tailwind CSS v4** + Antd `ConfigProvider` token | 共用同一套 Design Token 真源（`app/globals.css`） |
| 数据请求 | `lib/api.ts`（`getApiData<T>` / `postApiData<T>`） | 所有 API 调用必须经过它；禁止直接 `fetch` |
| 图标 | **`@ant-design/icons`** + **lucide-react** 补充 | Antd 组件内用官方图标；非 Antd 场景用 lucide-react |
| 错误边界 | **`react-error-boundary`** | 函数式 Error Boundary；禁止手写类组件版本 |
| 输入校验 | **Zod** | API 边界、表单校验 + 类型推导（`z.infer`） |
| 代码格式化 | **Prettier** + `prettier-plugin-tailwindcss` | `npm run format` |
| Antd SSR 集成 | **`@ant-design/nextjs-registry`** | SSR 注水避免 FOUC |

### 推荐引入（按优先级）

#### P1 — 按页面改造时逐步迁移

| 能力 | 选型 | 说明 |
|------|------|------|
| 客户端数据请求 | **TanStack Query v5** | 替代散落的 `useState + useEffect + fetch`；带缓存/失效/重试 |
| 表单 | **Antd `Form` + `useForm` + Zod** | 复杂表单优先 Antd Form；极少数场景用 React Hook Form |
| 单元测试 | **Vitest + Testing Library** | 未引入 |
| 测试 mock | **MSW** | 与 `lib/api.ts` 配合 |
| E2E 测试 | **Playwright** | 关键流程验证 |

#### P2 — 按业务需要再考虑

| 能力 | 选型 | 触发条件 |
|------|------|----------|
| 全局客户端状态 | **Zustand** | 出现真正跨页面共享的客户端态时 |
| 国际化 | **next-intl** | 多语言需求明确时 |
| 长列表虚拟化 | Antd `Table.virtual` / TanStack Virtual | 单页 DOM > 1000 节点 |
| 动效 | Framer Motion / CSS transition | 复杂过渡时；尊重 `prefers-reduced-motion` |
| 错误上报 | Sentry | 生产环境上线前 |
| 组件文档 | Ladle / Storybook 8 | 多团队协作时 |

### 严禁项

- ❌ CSS Modules / styled-components / Emotion / CSS-in-JS
- ❌ Material UI / Chakra UI / shadcn/ui
- ❌ 新增自研基础组件（Button、Input、Select、Modal、Table、Form 等） — Antd 已覆盖
- ❌ Redux / Redux Toolkit
- ❌ axios — `fetch` 已足够
- ❌ moment.js — 用 `dayjs` 或 `Intl.DateTimeFormat`
- ❌ 类组件、手写类式 ErrorBoundary
- ❌ 内联 `style={{}}` 用于可静态化的样式（运行时计算值例外，如 `style={{ width: `${pct}%` }}`）

---

## 二、常用命令

在 `nexus-console/` 目录下执行。

| 任务 | 命令 | 备注 |
|------|------|------|
| 安装 | `npm install` | CI 用 `npm ci` |
| 开发 | `npm run dev` | Next.js dev server |
| Lint | `npm run lint` | `eslint .` |
| Lint 修复 | `npm run lint:fix` | 自动修复 |
| 类型检查 | `npm run typecheck` | `tsc --noEmit` |
| 构建 | `npm run build` | |
| 格式化 | `npm run format` | `prettier --write .` |
| 格式化检查 | `npm run format:check` | `prettier --check .` |

---

## 三、关键工程约束

### 1. 服务端组件优先（RSC First）

App Router 默认 Server Component。仅在以下场景标注 `'use client'`：

- 需要 `useState` / `useEffect` / `useReducer` / `useContext`
- 监听浏览器事件（`onClick` / `onChange` 等）
- 使用浏览器 API（`window` / `localStorage`）
- 使用 Antd 交互组件（大多数 Antd 组件需要客户端运行时）

**当前实践**：17/19 页面是 Server Component（仅 `/rules` 为完整客户端页面）。交互部分拆为 `_components/` 子组件，外层 `page.tsx` 保留为 Server Component 做数据预取。

### 2. 数据请求分层

```
Server Component (RSC)
  ├─ 直接调用 getApiData<T>() 获取首屏数据
  └─ 通过 props 传给 Client Component

Client Component
  ├─ 轮询/实时刷新 → usePolling() hook
  ├─ 复杂状态 → TanStack Query（P1，尚未引入）
  └─ 写操作 → postApiData<T>()
```

**禁止**：

- ❌ 直接 `fetch` 绕过 `lib/api.ts`
- ❌ 在组件里手写 `try-catch + setState` 处理 loading/error（除非尚未引入 React Query 的页面）
- ❌ 把 token / 鉴权信息拼接在 URL 里

### 3. 样式与 Design Token

#### 单一真源

`app/globals.css` 的 `:root` 中定义的 CSS 变量是 **Design Token 单一真源**。包括 `--brand-*`、`--gray-*`、`--surface`、`--line`、`--success-*`、`--danger-*`、`--domain-d1~d6`、`--sidebar-*` 等。

#### Tailwind v4 集成

`globals.css` 顶部用 `@theme` 指令将 30+ CSS 变量注册为 Tailwind utility：

```css
@import "tailwindcss";
@theme {
  --color-brand: var(--brand);
  --color-surface: var(--surface);
  --color-line: var(--line);
  --color-success: var(--success-600);
  --color-warning: var(--warning-600);
  --color-danger: var(--danger-600);
  /* ...domain colors, text colors, etc. */
}
```

使用方式：`className="bg-surface text-brand border-line"`

#### Antd ConfigProvider 集成 — 颜色 Token 策略

**实际实现（`app/providers.tsx`）使用具体 hex 值而非 `var()` 引用**：

```tsx
const theme: ThemeConfig = {
  cssVar: { key: "nexus" },
  hashed: false,
  token: {
    colorPrimary: "#2563eb",     // = --brand-600
    colorInfo: "#3b82f6",        // = --brand-500
    colorSuccess: "#16a34a",     // = --success-600
    colorWarning: "#d97706",     // = --warning-600
    colorError: "#dc2626",       // = --danger-600
    colorTextBase: "#1f2937",    // = --text
    colorBgBase: "#ffffff",      // = --surface
    colorBorder: "#e5e7eb",      // = --line
    colorBorderSecondary: "#f3f4f6", // = --line-light
    borderRadius: 8,             // = --radius-lg
    borderRadiusLG: 12,          // = --radius-xl
    borderRadiusSM: 6,           // = --radius-md
    fontFamily: "inherit",
    fontSize: 14,
    controlHeight: 36,
  },
  components: {
    Layout: {
      headerBg: "#ffffff",       // = --surface
      siderBg: "#0f172a",        // = --sidebar-bg
      bodyBg: "#f8f9fb",         // = --bg
    },
    Menu: {
      itemSelectedBg: "rgba(37, 99, 235, 0.10)",
      itemSelectedColor: "#2563eb",
      itemHoverBg: "rgba(37, 99, 235, 0.06)",
    },
    Button: { primaryShadow: "none" },
    Card: { headerBg: "transparent" },
  },
};
```

**为什么用 hex 而非 `var()` 引用**：Antd 6 的 cssinjs 需要在构建时从语义 token 推导完整色盘（如 `--ant-color-primary-bg`、`--ant-color-primary-border`、`--ant-color-primary-hover` 等色调变体）。若传入 `var(--brand)` 等 CSS 变量引用，cssinjs 无法处理，会回退为 `#000000`（即「黑块」问题的根因）。因此**所有参与色盘推导的 derivative token 必须使用具体 hex 值**。这些 hex 值需与 `globals.css :root` 中的对应变量保持同步。

非 derivative 的组件级 token（`components.*`）理论上可使用 `var()` 引用，但当前统一使用 hex 值以保持一致性。

**修改 Design Token 时**：需同步更新 `globals.css :root` 变量、`providers.tsx` 的 `theme.token` 值，以及 `globals.css` 中任何硬编码颜色的语义类。

#### 样式书写优先级

1. **Antd 组件原生 props**（`size`、`type`、`status`、`bordered` 等）
2. **Tailwind 原子类**（布局、间距、文本对齐、响应式）
3. **语义类**（`globals.css` 中定义的 `.card`、`.hero-strip`、`.sidebar` 等，存放 Antd + Tailwind 无法表达的复杂样式）
4. **内联 `style`**：仅允许运行时计算值（如 `style={{ width: `${pct}%` }}`）

**注意**：当前 `globals.css` 中存在 ~700 行遗留语义类（`.card`、`.btn`、`.form-input`、`.sidebar`、`.topbar`、`.stat-grid` 等），它们与 Antd 组件并行存在。新增代码**不应**扩展这些遗留类，而应优先使用 Antd 组件 + Tailwind。历史语义类在对应页面迁移到 Antd 时逐步清理。

### 4. 类型安全

- `tsconfig.json` 已开 `strict: true`，不降级
- 禁止 `any`（业务代码）；外部数据用 `unknown` + Zod 收窄
- 导出函数/组件 props 必须显式标注类型
- API 响应类型在 `lib/api.ts` 已用 `ApiEnvelope<T>`，新接口必须遵循

### 5. 组件分层

#### 实际目录结构（混合态）

```
components/                   # 全局共享组件（20 个文件）
├── shared/                   # 薄壳封装（8 个：Card, Empty, ErrorState, StatusDot 等）
├── PageHeader.tsx            # 页面标题（所有页面通用）
├── ApiState.tsx              # API 错误横幅
├── StatusLabel.tsx           # 状态标签（薄壳包装 Tag）
├── Sidebar.tsx               # 侧边栏
├── AppShell.tsx              # 布局壳
├── Topbar.tsx                # 顶栏
├── PollingIndicator.tsx      # 轮询指示器
├── JobPipeline.tsx           # 作业管道（未被导入，待清理）
├── JobsContent.tsx           # 作业内容（被 /jobs 使用）
├── ...（其他历史组件）

app/<route>/
├── page.tsx                  # 页面入口（Server Component）
├── loading.tsx               # 加载骨架（11 个路由已覆盖）
├── _components/              # 路由专属组件（15 个目录）
│   ├── <Route>Content.tsx    # 页面主体内容
│   ├── <Route>Editor.tsx     # 编辑态
│   └── ...                   # 局部子组件
└── _lib/                     # 路由专属工具（仅 governance、rules 使用）
```

#### 当前设计原则

- **新增组件优先用 Antd**
- **路由专属 UI 放 `app/<route>/_components/`**，不再往 `components/` 堆
- **`components/shared/`** 仅保留确有跨页面业务规则的薄壳（如 `StatusDot`、`ErrorState`）
- **历史 `components/` 文件**：不改动时不强制迁移；改动时顺手替换为 Antd 版本

### 6. 错误处理

每个数据展示区域处理四种状态：

1. **Loading** — `loading.tsx` + Antd `Skeleton` / `Spin`
2. **Error** — Antd `Alert type="error"` + 重试按钮；全局用 `react-error-boundary`
3. **Empty** — Antd `Empty` 或 `components/shared/Empty`
4. **Success** — 正常数据展示

`ApiState` 组件用于页面级 API 错误横幅（展示 `traceId` 和错误消息）。

### 7. 可访问性（a11y）

- 纯图标按钮必须有 `aria-label`
- 表单用 Antd `Form.Item label="..."`
- Modal/Drawer 焦点管理使用 Antd 默认行为
- Sidebar 导航使用 `<nav aria-label="主导航">`

### 8. 性能

- 路由级懒加载是 Next.js 默认行为，无需手写
- 重型组件用 `next/dynamic({ ssr: false })`
- 避免 `import * as antd from 'antd'`，按需导入
- 高频变化数据避免放在顶层 Context

---

## 四、Antd 6 API 迁移参考

Antd 6 相对 v5 有部分 API 重命名。新增代码遵循新 API；历史代码在触及该文件时顺手修正。

| 旧 API (v5) | 新 API (v6) | 涉及组件 |
|-------------|-------------|----------|
| `Alert message="..."` | `Alert title="..."` | Alert |
| `Progress trailColor` | `Progress railColor` | Progress |
| `Tag bordered={false}` | `Tag variant="filled"` | Tag |
| `Steps direction="vertical"` | `Steps orientation="vertical"` | Steps |
| `Steps progressDot` | `Steps type="dot"` | Steps |
| `Steps items[].description` | `Steps items[].content` | Steps |
| `Space direction="vertical"` | `Space orientation="vertical"` | Space |
| `Statistic valueStyle` | `Statistic styles.content` | Statistic |

**当前状态**：Alert `message→title` 和 Progress `trailColor→railColor` 已全局修正；其余 API 迁移在触及对应文件时进行。

---

## 五、当前组件迁移状态

### 已完成的退役/替换

| 原组件 | 替换为 | 状态 |
|--------|--------|------|
| `components/AiPromptsContent.tsx` | `app/ai-prompts/_components/AiPromptsContent.tsx` | 旧文件仍存于磁盘，页面已切到新路径 |
| `components/DataSourcesContent.tsx` | `app/data-sources/_components/DataSourcesContent.tsx` | 旧文件仍存于磁盘，页面已切到新路径 |

### 仍在使用的历史自研组件（待迁移）

| 组件文件 | 当前消费者 | 目标迁移方向 |
|----------|-----------|-------------|
| `shared/Card.tsx` | `/jobs`, `/data-sources/[id]`, `/raw-ledger`, `/ingest`（4 个页面） | `antd/Card` |
| `shared/Empty.tsx` | 5 个页面 | `antd/Empty` |
| `EmptyState.tsx` | `/iam-audit`, `/data-sources`, `/jobs`, `/ai-prompts`, `/assets/[assetId]` | `antd/Empty` |
| `StatCard.tsx` | `/iam-audit` | `antd/Card` + `antd/Statistic` |
| `Badge.tsx` | `AiPromptsContent`, `AssetDetailTabs` | `antd/Tag` |
| `Tabs.tsx` | `AssetDetailTabs` | `antd/Tabs` |
| `ProgressBar.tsx` | `AssetDetailTabs` | `antd/Progress` |
| `JobsContent.tsx` | `/jobs` | `antd/Table` + `antd/Steps` |
| `JobPipeline.tsx` | （零引用，待删除） | — |
| `DomainTag.tsx` | （零引用，已有 governance 版本替代） | — |

### 零引用的待清理文件

| 文件 | 说明 |
|------|------|
| `components/JobPipeline.tsx` | 无任何导入 |
| `components/DomainTag.tsx` | 已有 `app/governance/_components/DomainTag.tsx` 替代 |
| `components/shared/BadgeRow.tsx` | 无任何导入 |
| `components/shared/Forbidden.tsx` | 无任何导入 |
| `components/shared/Loading.tsx` | 无任何导入 |
| `components/shared/TermTip.tsx` | 无任何导入 |
| `app/assets/[assetId]/_components/AssetDetailTabs.tsx` | 页面实际导入的是 `@/components/AssetDetailTabs` |

---

## 六、Git 与 Review

- 提交前必须通过 `npm run typecheck` + `npm run lint`
- **未经确认不要直接 commit**
- 分支命名：`feature/xxx`、`fix/xxx`、`refactor/xxx`
- Commit 格式：Conventional Commits（详见 `../.claude/rules/git-conventions.md`）
- PR 需说明：改动范围、新增/移除依赖、是否替换了自研组件

---

## 七、设计稿实现工作流

1. 先看 Antd 是否已覆盖
2. 检查设计稿用色/间距能否映射到现有 Token；不能时先补 token 到 `globals.css :root`，然后同步到 `providers.tsx theme.token`
3. 产出简短实现计划（用哪些 Antd 组件、Tailwind 原子类、Token 映射）
4. 分步骤实现（先 RSC，后客户端交互）
5. 执行 `npm run typecheck` + `npm run lint`
6. 总结：用了哪些 Antd 组件、与设计稿的偏差、缺失资源

---

## 八、安全要求

- 不暴露或打印密钥、Token、内部 URL
- 不读取或修改 `.env*`、`secrets/**`、`*.pem` 等敏感文件
- 不在源码硬编码密钥；用 `process.env.*` 或 `NEXT_PUBLIC_*`
- 不执行破坏性 shell 命令；与生产相关的操作必须先确认

---

## 九、规则导入

以下规则文件位于仓库根目录 `.claude/rules/`。

@../.claude/rules/react.md
@../.claude/rules/typescript.md
@../.claude/rules/design-system.md
@../.claude/rules/api-layer.md
@../.claude/rules/state-management.md
@../.claude/rules/error-handling.md
@../.claude/rules/performance.md
@../.claude/rules/naming-conventions.md
@../.claude/rules/code-comments.md
@../.claude/rules/testing.md
@../.claude/rules/git-conventions.md
@../.claude/rules/refactoring.md
@../.claude/rules/i18n.md
@../.claude/rules/ci-cd.md
