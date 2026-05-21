# NEXUS Console 前端工程契约

本文件是 `nexus-console/` 的前端工程契约，基于 **frontend-craft** 最佳实践编写，目标是构建**现代、高效、体验友好**的企业级控制台。

> **优先级**：仓库根目录的 `CLAUDE.md`、`ARCHITECT.md`、`SPEC.md`、`WORKFLOWS.md` 是 NEXUS 全局工程契约（架构红线、API/UI/状态契约等）。本文件仅为前端工作的补充；冲突时以根契约为准。

---

## 一、技术栈基线

### 已确定（不再讨论）

| 维度           | 选型                                              | 说明                                                                                                                                             |
| -------------- | ------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| 语言           | TypeScript（`strict: true`）                      | 禁止 `any`，外部输入用 `unknown` 收窄                                                                                                            |
| 包管理器       | **npm**（`package-lock.json`）                    | 严禁 `pnpm install` / `yarn`；CI 用 `npm ci`                                                                                                     |
| 框架           | **Next.js 16（App Router）+ React 19**            | 默认 React Server Components；`'use client'` 仅在确需交互时使用                                                                                  |
| **UI 组件库**  | **Ant Design 6**（`antd@^6`）                     | 业务组件首选；自研组件库**逐步退役**，新代码不再扩展 `components/ui/*`。Antd 6 原生支持 React 19，**不需要** `@ant-design/v5-patch-for-react-19` |
| **样式方案**   | **Tailwind CSS v4**（`@tailwindcss/postcss`）     | 布局、间距、原子样式；**与 Antd ConfigProvider 共用同一套 Design Token**（见 §三.3）                                                             |
| 数据请求基础层 | `lib/api.ts`（`ApiEnvelope<T>` / `ApiResult<T>`） | 所有接口调用必须经过它，禁止直接 `fetch`                                                                                                         |

### 推荐引入（按优先级，逐步落地）

#### P0 — 工程基础（应尽快补齐）

| 能力                 | 选型                                                          | 理由                                                                                                                      |
| -------------------- | ------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| Antd 主题适配        | **`antd` + `ConfigProvider`**（已落地于 `app/providers.tsx`） | `theme.token` 已对齐 `globals.css` Design Token；中文 locale `zh_CN` 已注入；`cssVar: { key: "nexus" }` 启用 CSS 变量模式 |
| Antd App Router 集成 | **`@ant-design/nextjs-registry`**                             | SSR 注水避免 FOUC；Next 16 App Router 必备                                                                                |
| Tailwind             | **Tailwind v4**                                               | `@theme` 指令直接读取 `globals.css` 中的 CSS 变量，与 Antd token 同源                                                     |
| 类型检查脚本         | `"typecheck": "tsc --noEmit"`                                 | 当前 `package.json` 缺失，CI/Review 无法保障类型安全                                                                      |
| 代码格式化           | **Prettier**（含 `prettier-plugin-tailwindcss`）              | Prettier 管格式、ESLint 管质量；插件按 Tailwind 推荐顺序排列类名                                                          |
| 输入校验             | **Zod**                                                       | API 边界、表单、URL 参数的运行时校验 + 类型推导（`z.infer`）                                                              |
| 错误边界             | **react-error-boundary**                                      | React 19 函数式错误边界标准库；禁止手写类组件 ErrorBoundary                                                               |
| 图标                 | **`@ant-design/icons`** + **lucide-react** 补充               | Antd 组件内用官方图标；非 Antd 场景用 lucide-react                                                                        |

#### P1 — 体验显著提升（按页面改造时逐步迁移）

| 能力            | 选型                                                                                | 替代当前的什么                                                                            |
| --------------- | ----------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| 服务端数据获取  | **Next.js Server Components + `fetch` 缓存**                                        | 优先；首屏数据在 RSC 中获取，客户端零成本                                                 |
| 客户端数据请求  | **TanStack Query v5（React Query）**                                                | 替代散落的 `useState + useEffect + fetch`；带缓存/失效/重试/乐观更新/loading-error 状态机 |
| 表单            | **Antd `Form` + `useForm` + Zod**（通过 `zod-formik-adapter` 或自定义 `validator`） | 复杂表单优先 Antd Form；Antd 无法满足的极少数场景才用 React Hook Form                     |
| 单元测试        | **Vitest + Testing Library**                                                        | 启动快、与 Vite 生态兼容好                                                                |
| 测试网络层 mock | **MSW（Mock Service Worker）**                                                      | 与 `lib/api.ts` 配合，统一 mock 后端响应                                                  |
| E2E 测试        | **Playwright**                                                                      | 关键流程：登录、数据源添加、规则保存、检索                                                |

#### P2 — 进一步增强（按业务需要再考虑）

| 能力           | 选型                                                       | 触发条件                                                                 |
| -------------- | ---------------------------------------------------------- | ------------------------------------------------------------------------ |
| 全局客户端状态 | **Zustand**（轻量）                                        | 出现真正跨页面共享的客户端态时（用户/权限/主题）；服务端态走 React Query |
| 国际化         | **next-intl** + Antd `ConfigProvider` `locale`             | SPEC 明确多语言或英文版本时                                              |
| 长列表虚拟化   | **Antd `Table` 的 `virtual` 属性** 或 **TanStack Virtual** | 单页 DOM > 1000 节点或可见明显卡顿时                                     |
| 动效           | **Framer Motion** 或 CSS transition                        | 复杂过渡、列表排序、抽屉/Modal 等；尊重 `prefers-reduced-motion`         |
| 错误上报       | **Sentry**（待评估）                                       | 生产环境上线前                                                           |
| 组件文档/沙盒  | **Ladle** 或 **Storybook 8**                               | 需要对外发布或多团队协作时                                               |

### 严禁项（不要在新代码里引入）

- ❌ **CSS Modules / styled-components / Emotion / 原生 CSS-in-JS** — 与 Tailwind + Antd token 体系并行会造成样式分裂
- ❌ **Material UI / Chakra UI / shadcn/ui** — 与 Antd 视觉语言冲突，混用会导致设计语言失控
- ❌ **新增自研基础组件**（Button、Input、Select、Modal、Table、Form 等） — Antd 已覆盖；薄壳封装也仅在确有跨页面通用业务规则时才允许
- ❌ **Redux / Redux Toolkit** — 控制台规模不需要；客户端共享态选 Zustand，服务端态选 React Query
- ❌ **axios** — `fetch` 已足够；保留 `lib/api.ts` 单层封装
- ❌ **moment.js** — 已废弃；用 `dayjs`（Antd 内部依赖，已存在）或 `Intl.DateTimeFormat`
- ❌ **类组件、手写类式 ErrorBoundary** — 一律函数组件 + `react-error-boundary`
- ❌ **内联 `style={{}}`** — 一律走 Tailwind 类或语义类

### 迁移节奏（重要）

当前代码库存在两笔历史债：

1. **自研 `components/*`**（`StatCard.tsx`、`Tabs.tsx`、`Badge.tsx`、`EmptyState.tsx` 等 20+ 个） → 逐步替换为 Antd 等价物：
   - `Tabs` → `antd/Tabs`
   - `Badge` → `antd/Badge` / `antd/Tag`
   - `EmptyState` → `antd/Empty`
   - `StatCard` → `antd/Statistic` 包在 `antd/Card` 中
   - `ProgressBar` → `antd/Progress`
   - `ConfidenceBadge` / `DomainTag` / `StatusLabel` → `antd/Tag`（业务薄壳保留）
   - `JobPipeline` → `antd/Steps`
   - `AppShell` / `Sidebar` / `Topbar` → `antd/Layout`（`Layout.Sider` / `Layout.Header`）
   - `PageHeader` → 自研业务薄壳保留（Antd 5 已移除 PageHeader）
2. **85+ 处内联 `style={{}}`** + 散落 CSS 类 → 迁移到 Tailwind 原子类；语义类（如 `.stat-card-brand`）保留在 `globals.css` 但用 `@apply` 重写。

**节奏**：

- **新代码**：直接 Antd + Tailwind，**不再扩展自研组件**
- **改动现有页面**：顺手把所触及组件替换成 Antd 版本，但**不强制大爆炸式重构**
- **集中替换**：以页面为单位（governance / data-sources / rules / assets / jobs / ai-prompts），每个页面一个 PR，便于 review 与回滚

---

## 二、常用命令

命令需在 `nexus-console/` 目录下执行。

| 任务     | 命令                     | 备注                                            |
| -------- | ------------------------ | ----------------------------------------------- |
| 安装     | `npm install`            | CI 用 `npm ci`                                  |
| 开发     | `npm run dev`            | Next.js dev server                              |
| Lint     | `npm run lint`           | `next lint`（含 `eslint-config-next`）          |
| 类型检查 | `npx tsc --noEmit`       | **建议补脚本** `"typecheck": "tsc --noEmit"`    |
| 构建     | `npm run build`          |                                                 |
| 测试     | _未配置_                 | P1 引入 Vitest 后再补                           |
| E2E      | _未配置_                 | P1 引入 Playwright 后再补                       |
| 格式化   | `npx prettier --write .` | **建议补脚本** `"format": "prettier --write ."` |

如果命令缺失，先检查 `package.json`，不要自行发明替代命令。

---

## 三、关键工程约束

### 1. 服务端组件优先（RSC First）

Next.js 16 App Router 默认是 Server Component。**默认在服务端获取数据**，仅在以下场景标注 `'use client'`：

- 需要 `useState` / `useEffect` / `useReducer` / `useContext`
- 监听浏览器事件（`onClick` / `onChange` 等）
- 使用浏览器 API（`window` / `localStorage` / `IntersectionObserver`）
- 使用 Antd 交互组件（`Modal`、`Drawer`、`Form`、`Tabs` 等大多数 Antd 组件）

**禁止把整个页面无脑标 `'use client'`**。把交互部分拆成小组件（如 `<RulesEditor />`），外层 `page.tsx` 尽量保留为 Server Component，由它做数据预取后传 props。

### 2. 数据请求分层（不可绕过）

```
Server Component (RSC)
  ├─ 直接调用 lib/api.ts 服务端封装（首屏数据）
  └─ 通过 props 把数据传给 Client Component

Client Component
  ├─ 简单一次性请求 → 直接 await lib/api.ts
  ├─ 列表/详情/复杂状态 → TanStack Query (React Query) — P1
  └─ Mutation（创建/更新/删除） → React Query useMutation — P1
```

**禁止在新代码中**：

- ❌ 直接写 `fetch('/v1/...')` 绕过 `lib/api.ts`（参见 `app/rules/page.tsx` 这类反例，待重构）
- ❌ 在组件里手写 `try-catch + setState` 处理 loading/error，已有 React Query 的页面必须用它
- ❌ 把 token / 鉴权信息拼接在 URL 里

### 3. 样式与设计 Token（重点）

#### 单一真源：`app/globals.css` 的 CSS 变量

`globals.css` 中的 `--brand-*` / `--gray-*` / `--surface` / `--line` / `--success-*` / `--danger-*` / `--domain-d1~d6` 等是 **Design Token 单一真源**。Tailwind 与 Antd 都从这里取色。

#### Tailwind v4 集成

`globals.css` 顶部用 `@theme` 指令把 CSS 变量注册为 Tailwind utility：

```css
@import "tailwindcss";

@theme {
  --color-brand: var(--brand);
  --color-brand-strong: var(--brand-strong);
  --color-surface: var(--surface);
  --color-line: var(--line);
  --color-success: var(--success-600);
  --color-warning: var(--warning-600);
  --color-danger: var(--danger-600);
  /* ...domain colors */
}
```

之后即可在 JSX 写 `className="bg-surface text-brand border-line"`。

#### Antd ConfigProvider 集成

应用根（`app/layout.tsx` 的 `<Providers>`）配置：

```tsx
<ConfigProvider
  theme={{
    token: {
      colorPrimary: 'var(--brand)',
      colorSuccess: 'var(--success-600)',
      colorWarning: 'var(--warning-600)',
      colorError: 'var(--danger-600)',
      borderRadius: 8,
      fontFamily: 'inherit',
    },
    components: {
      Layout: { headerBg: 'var(--surface)', siderBg: 'var(--surface-alt)' },
      Menu: { itemSelectedBg: 'var(--brand-50)', itemSelectedColor: 'var(--brand-700)' },
    },
  }}
>
```

确保 Antd 与 Tailwind 视觉一致。

#### 样式书写优先级

1. **Antd 组件原生 props**（`size`、`type`、`status`、`bordered` 等）
2. **Tailwind 原子类**（布局、间距、文本对齐、响应式）
3. **语义类**（`.stat-card`、`.governance-trail` 等需要复用且 Antd 无法表达的复杂样式 → 写在 `globals.css` 用 `@apply` 组合 Tailwind）
4. **内联 `style`**：禁止；唯一例外是**运行时计算值**（如 `style={{ width: \`${percent}%\` }}`），且应优先用 CSS 变量传值（`style={{ '--w': \`${percent}%\` }}`+ CSS`width: var(--w)`）

#### 严禁

- ❌ 内联 `style={{ display: 'flex', gap: 12 }}` 等可静态化的样式
- ❌ 在组件里硬编码颜色值（`#7c3aed`、`#ef4444` 等） → 必须走 token
- ❌ 同时用 Tailwind 与 CSS Modules / styled-components

### 4. 类型安全

- `tsconfig.json` 已开 `strict: true`，**不要降级**
- 禁止 `any`（业务代码）；外部数据用 `unknown` + Zod 收窄
- 导出函数/组件 props **必须**显式标注类型
- 复杂联合/对象类型抽到 `*.types.ts` 同目录文件
- API 响应类型在 `lib/api.ts` 已用 `ApiEnvelope<T>`，新接口必须遵循

### 5. 组件分层

```
components/
├── feature/     # 业务组件（GovernanceContent、AssetsContent 等，使用 Antd）
├── layout/      # 布局壳（AppShell → 基于 antd/Layout，Sidebar、Topbar）
└── shared/      # 跨业务的薄壳封装（DomainTag、ConfidenceBadge、StatusLabel）

app/<route>/
├── page.tsx
├── _components/ # 路由专属组件（不被其他路由复用）
└── _lib/        # 路由专属工具
```

**目前所有组件都平铺在 `components/`**。**新增组件优先用 Antd**；只有在确有跨页面业务规则（如统一的 D1~D6 数据域配色 Tag）时才包薄壳到 `components/shared/`。

### 6. 错误处理

每个数据展示区域必须处理四种状态：

1. **Loading** — Antd `Skeleton` / `Spin`
2. **Error** — Antd `Result status="error"` 或 `Alert` + 重试按钮
3. **Empty** — Antd `Empty`
4. **Success** — 数据展示

模块级用 `react-error-boundary` 包裹（P0 引入），避免单点崩溃白屏。

### 7. 可访问性（a11y）

Antd 组件已内置 a11y；自定义包装时不要破坏：

- 不要在 Antd `Button` 外层套 `<a>` 而丢失 `role`
- Modal/Drawer 关闭后焦点回到触发元素（Antd 默认行为，不要覆盖）
- 纯图标按钮必须有 `aria-label`（Antd `Button` 用 `<Button icon={...} aria-label="..." />`）
- 表单用 Antd `Form.Item label="..."`，不要丢 label

### 8. 性能

- 路由级懒加载是 Next.js 默认行为，无需手写
- 重型组件（图表、编辑器、地图）用 `next/dynamic({ ssr: false })` 懒加载
- 长列表（>500 行）用 Antd `Table` 的 `virtual` 属性或 TanStack Virtual（P2）
- 图片用 `next/image`，禁止裸 `<img>` 加载远程图片
- **Antd 按需引入**：Next 16 + Antd 5 默认已 tree-shake，但应避免 `import * as antd from 'antd'`
- 高频变化数据避免放在顶层 Context；用 store 或局部状态

---

## 四、Git 与 Review

- 提交前必须通过 **lint + typecheck**（建议在 `.husky/` 或 `lint-staged` 中前置）
- **未经我确认不要直接 commit**
- 分支命名：`feature/xxx`、`fix/xxx`、`refactor/xxx`
- Commit 格式：Conventional Commits（详见 `../.claude/rules/git-conventions.md`）
- PR 需说明：改动范围、新增/移除依赖、性能影响、是否需要数据迁移、是否替换了自研组件

---

## 五、设计稿实现工作流

当存在设计上下文时：

1. 通过 MCP 读取设计上下文（Figma / MasterGo / Pixso / 墨刀 / Sketch；摹客用截图/标注）
2. **先看 Antd 是否已覆盖**（Form、Table、Modal、Drawer、Tabs、Steps、Tree、Transfer 等）
3. 检查设计稿用色/间距/圆角能否映射到现有 Token；不能映射时**先补 token**到 `globals.css`
4. 产出简短实现计划（用哪些 Antd 组件、Tailwind 原子类、Token 映射）
5. 分步骤实现（先 RSC，后客户端交互）
6. 执行 `npm run lint` + `npx tsc --noEmit`
7. 总结：用了哪些 Antd 组件、与设计稿的偏差、缺失资源

---

## 六、安全要求

- 不要主动暴露或打印任何密钥、Token、内部 URL
- 禁止读取或修改 `.env*`、`secrets/**`、`*.pem/key/p12/jks` 等敏感文件
- 不要在源码硬编码密钥；用 `process.env.*` 或 `NEXT_PUBLIC_*`（仅前端可见的非敏感配置）
- 不要执行破坏性 shell 命令；与生产相关的操作必须先确认

---

## 七、规则导入

以下规则文件位于仓库根目录 `.claude/rules/`，已按本项目技术栈裁剪。

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
