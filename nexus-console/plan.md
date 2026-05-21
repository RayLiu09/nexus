# nexus-console 与 prototype-v3.2 偏差分析与重构计划

> 基线：`docs/samples/prototype-v3.2.html`（中保真原型）
> 适用范围：`nexus-console/`
> 编制时间：2026-05-20（基于先前 v3.1 计划全面重写）
> 性质：工程执行计划。原型属于中保真稿；以资深 UI 设计经验为准做合理优化（在「五、原型层 UI 优化建议」中显式列出，落地需经评审）。

---

## 一、为什么要重写

`plan.md` 的上一版以 `prototype-v3.1.html` 为基线，并在阶段 0 做出了几个决定：合并 `/tag-review` 与 `/search`、改为 Indigo `#4f46e5`、govern tabs 5 项、workspace tabs 4 项。

`prototype-v3.2.html` 是**新的中保真基线**，对上述决策做了以下回退或调整：

| 维度        | v3.1 决策（已落地）            | v3.2 基线                                                                 | 处理方式                                                                              |
| ----------- | ------------------------------ | ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| 主色        | Indigo `#4f46e5`               | Royal Blue `#3b6cf4`                                                      | **以设计师评审权限校准为 `#2563eb`（Blue-600）**，详见「四之三 主色调选型与统一原则」 |
| 强调色      | Teal `#0d9488`                 | Teal `#0e8a7a`                                                            | **回到 `#0d9488`（Teal-600）**，理由同上                                              |
| 侧边栏底色  | 浅灰 `--surface-alt`           | 深海军 `#0f172a`，logo 渐变 `#7c9ff5 → #0e8a7a`                           | 全量切换为深色 sidebar                                                                |
| 导航分组    | 5 组                           | 5 组（同）                                                                | 不变                                                                                  |
| 路由数      | 12（合并 tag-review / search） | **14**（恢复 `/tag-review`、`/search` 独立）                              | 新建两个独立路由                                                                      |
| 治理 tabs   | 5（含标签审核）                | 4（待复核 / AI 建议 / 质量校准 / 决策追踪）                               | 移除「标签审核」tab；标签审核重新成顶级页                                             |
| 工作区 tabs | 4（含检索验证）                | 3（我的待办 / 我负责的资产 / 我的草稿）                                   | 移除「检索验证」tab                                                                   |
| 资产详情    | 7 大区块 + anchor-nav          | **5 tabs**（概览 / 版本与 ref / 治理与质量 / 切片与索引 / 血缘与审计）    | 由 anchor-nav 改为顶部 sticky tabs，结构更轻                                          |
| 工作台 hero | 6 metric                       | **4 hero-card** + attention-zone（异常项直接呈现）                        | 信息密度收敛，强调"问题驱动"                                                          |
| 数据源      | 表格视图                       | **卡片网格 + 表格视图切换**                                               | 加视图切换器                                                                          |
| 批次接入    | 单视图                         | provider-card-grid + 最近批次表 + 总览/台账职责区分表                     | 接入仪表盘化                                                                          |
| 原始台账    | metric + 双视图                | search-hero（首屏巨型搜索框）+ metric + 批次/对象 + 选中明细              | 强调"先搜索"                                                                          |
| 资产目录    | 6 metric + 表格                | 4 metric + 域 quick-filter chips + 资产表（左色条）+ 域分布 + 说明        | 简化指标、加左侧色条彩色区分                                                          |
| 规则        | metric + 清单 + 详情           | metric + 可展开规则集卡片 + 发布影响评估面板                              | 规则集用 expandable card 风格，发布前置 publish flow                                  |
| 权限        | 6 metric + 矩阵 + 流           | 3 tabs（用户与角色 / API 调用方 / 审计日志）+ 权限矩阵 heatmap + 脱敏预览 | 改为 tab 划分                                                                         |

> 结论：**v3.2 不是 v3.1 的小修补，而是基线整体翻新**。本计划据此重排路由、tab 结构、视觉 token 与每页骨架。

---

## 二、整体差距总览（基于 v3.2）

| 维度       | nexus-console 现状（commit e2e3da2）                                | v3.2 目标                            | 差距 |
| ---------- | ------------------------------------------------------------------- | ------------------------------------ | ---- |
| 路由数     | 13 个（缺 `/tag-review`、`/search`，多 `/login`）                   | 14 个业务路由                        | 中   |
| 信息架构   | 5 组（与 v3.2 一致）                                                | 5 组                                 | ✅   |
| 主色       | Indigo `#4f46e5`（v3.1 决策）                                       | **奠基蓝 `#2563eb`**（设计师校准）   | 大   |
| 侧边栏     | 浅色（基于 `--surface-alt`）                                        | 深海军 `#0f172a`                     | 大   |
| Topbar     | 面包屑 + 搜索 + 3 pill + Avatar（已具备）                           | 同（内容微调）                       | 小   |
| 资产详情   | 7 大区块 + anchor-nav（v3.1 落地）                                  | 5 tabs（v3.2 收敛）                  | 中   |
| 治理中心   | 5 tabs（含标签审核）                                                | 4 tabs                               | 中   |
| 工作区     | 3 tabs（实际，未合并 search）                                       | 3 tabs（同）                         | ✅   |
| 内联 style | grep 出 **146 处** `style={{`                                       | 走 Tailwind / token / 语义类         | 大   |
| 自研组件   | 平铺在 `components/`：`AssetDetailTabs` `JobPipeline` `StatCard` 等 | 用 Antd 等价物，业务薄壳进 `shared/` | 中   |

---

## 三、路由级差距对照（v3.2）

> 现状路径以 `app/<route>/` 计；行数为 `page.tsx` + 同目录 `_components/*` 的总行数（不含 `_lib`）。

| #   | v3.2 page-id   | 现状路由            | 现状规模 | 完成度 | 主要缺失（按 v3.2）                                                                |
| --- | -------------- | ------------------- | -------- | ------ | ---------------------------------------------------------------------------------- |
| 1   | `workbench`    | `/workbench`        | 586 行   | 55%    | hero-strip → 4 卡 + attention-zone（v3.2 新形态），整体瘦身                        |
| 2   | `datasources`  | `/data-sources`     | 27 行    | 8%     | 4 metric / source-card-grid 默认视图 / 视图切换 / 默认策略 + 治理前置提醒          |
| 3   | `ingest`       | `/ingest`           | 178 行   | 50%    | hero-strip × 4 / provider-card-grid × N / quick-filter chips / 总览 vs 台账 区分卡 |
| 4   | `raw`          | `/raw-ledger`       | 50 行    | 12%    | search-hero / 4 metric / 批次+对象双视图 / 选中明细 definition-grid                |
| 5   | `jobs`         | `/jobs`             | 29 行    | 5%     | 4 tabs / 列表（含 job-pipeline 横管线）/ 选中作业 stage-steps + 失败定位 notice    |
| 6   | `assets`       | `/assets`           | 285 行   | 35%    | 4 metric / 域 quick-filter chips / 资产表（左色条 + quality-ring）/ 域分布 + 说明  |
| 7   | `asset-detail` | `/assets/[assetId]` | 107 行   | 25%    | 顶部 sticky 5-tab；目前 `AssetDetailTabs.tsx` 为 v3.1 anchor-nav，需重构           |
| 8   | `governance`   | `/governance`       | 644 行   | 70%    | 移除「标签审核」tab，恢复 4 tabs；review-card 改为 v3.2 卡片样式                   |
| 9   | `tag-review`   | ❌                  | 0 行     | 0%     | **新建独立页**：bulk-bar + 低置信审核表 + 自动提交历史 + 流程说明                  |
| 10  | `rules`        | `/rules`            | 352 行   | 40%    | metric × 4 / expandable 规则集卡片（含 code-block）/ 发布影响评估面板              |
| 11  | `prompt`       | `/ai-prompts`       | 51 行    | 12%    | profile-card × N（带版本下拉）/ 输出 Schema definition-grid / 版本对比 diff        |
| 12  | `permissions`  | `/iam-audit`        | 83 行    | 25%    | 3 tabs / 主体表 / 权限矩阵 heatmap / API 调用方表 / 审计流（expandable）/ 脱敏预览 |
| 13  | `search`       | ❌                  | 0 行     | 0%     | **新建独立页**：query 构造左侧 / 结果与引用右侧 / 权限测试切换 / 引用链 notice     |
| 14  | `workspace`    | `/my-workspace`     | 143 行   | 50%    | 3 tabs（待办 / 我的资产 / 我的草稿），SLA 分层 + 快捷入口 + 我的最近动作           |

> 路由命名保持现状（`raw-ledger` / `iam-audit` / `ai-prompts` / `my-workspace` / `data-sources`），不强行改名为 v3.2 prototype 用的 `raw` / `permissions` / `prompt` / `workspace` / `datasources`，理由：URL 是对外契约，重命名收益小、回归风险大。

---

## 四、共性偏差与原子组件清单（v3.2）

### 4.1 v3.2 中频繁出现的 UI 原子

| 原子                                        | v3.2 出现场景                            | 现状               | 落地                                                                                                                                              |
| ------------------------------------------- | ---------------------------------------- | ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------- | --------------------- | ------- | --------------------- |
| `hero-strip`（4 卡）                        | workbench、ingest                        | 无                 | Antd `Statistic` × 4 + 自定义语义类 `.hero-card[.warning                                                                                          | .danger                          | .success]`            |
| `metric-grid-4`                             | datasources、raw、rules、assets          | 部分（StatCard）   | Antd `Card` × 4 + `Statistic`，退役 `StatCard.tsx`                                                                                                |
| `summary-strip`                             | governance、asset-detail overview        | `SummaryStrip.tsx` | 保留薄壳，内部用 token + Antd `Tag`/`Statistic`                                                                                                   |
| `attention-zone`                            | workbench                                | 无                 | 自定义语义类 `.attention-item[.danger                                                                                                             | .warning]`，含 dot + 标题 + 操作 |
| `chip-domain-d{1..6}`                       | 全局                                     | `DomainTag.tsx`    | 保留薄壳；token 调整为 v3.2 配色（D1=#3b49df / D2=#6d3bd0 / D3=#0e8a7a / D4=#1d7a3a / D6=#ae2e28，D5 不在 v3.2 prototype 中显式出现，保留 token） |
| `chip-level-l{1..4}`                        | 全局                                     | `Tag` 内联         | 保留 token（已在 v3.1 阶段补齐），薄壳 `LevelChip`                                                                                                |
| `status` 圆点徽标                           | 全局                                     | `StatusLabel.tsx`  | 替换为 Antd `Badge`+`Tag` 组合，业务薄壳 `StatusDot`                                                                                              |
| `funnel-row`                                | workbench                                | 无                 | Antd `Progress strokeColor=brand→accent gradient`，独立 `FunnelRow` 薄壳                                                                          |
| `job-pipeline`（水平管线条）                | jobs 列表行                              | `JobPipeline.tsx`  | 重写为符合 v3.2 视觉的水平 7 段，颜色用 token；薄壳保留                                                                                           |
| `stage-steps`                               | jobs 详情、asset-detail                  | 无                 | Antd `Steps direction="vertical"`，业务包装 `StageSteps`                                                                                          |
| `definition-grid`                           | asset-detail / raw / prompt              | 无                 | Antd `Descriptions column={2}`，全部走它                                                                                                          |
| `compare-row` / `compare-side`              | asset-detail / prompt 版本对比           | 无                 | 自建（2 列 grid + Card 内部 stack），含 `diff-added/changed/removed` 内联 token                                                                   |
| `timeline`                                  | workbench / asset-detail                 | 无                 | Antd `Timeline mode="left"`                                                                                                                       |
| `code-block`                                | rules / asset-detail / permissions audit | 无                 | 语义类 `.code-block`（`#0f172a` bg, `#cbd5e1` text）+ `Typography.Paragraph code`                                                                 |
| `bulk-bar`                                  | governance / tag-review                  | governance 已实现  | 抽取到 `components/shared/BulkBar.tsx`                                                                                                            |
| `notice` / `notice-info                     | warning                                  | danger`            | 几乎每页                                                                                                                                          | 无                               | Antd `Alert type=info | warning | error`，薄壳 `Notice` |
| `review-card`                               | governance 待复核                        | governance 已实现  | 抽取，加 `priority-overdue` / `priority-today` 语义                                                                                               |
| `quality-ring`                              | assets 表行 / asset-detail               | 无                 | 自建 SVG 或 conic-gradient 圆环；薄壳 `QualityRing`                                                                                               |
| `provider-card`（含 file-upload 虚线变体）  | ingest                                   | 无                 | 自建语义类，区分 `enabled / scheduled / partial_failed / idle`                                                                                    |
| `source-card`                               | datasources 卡片视图                     | 无                 | 自建语义类                                                                                                                                        |
| `quick-filters` chips                       | ingest                                   | 无                 | 自建语义类；Antd `Segmented` 也可候选（视觉差异需评审）                                                                                           |
| `heatmap`（权限矩阵）                       | permissions                              | 无                 | 自建；4 列固定，单元格 `.can/.review/.cant`                                                                                                       |
| `mask-preview`                              | permissions                              | 无                 | 2 列卡 + 状态色头部                                                                                                                               |
| `simple-list` / `kanban-item`               | workbench / rules                        | 无                 | 语义类 + Tailwind                                                                                                                                 |
| `audit-stream` / `audit-item`（expandable） | permissions / workbench                  | 无                 | 自建语义类                                                                                                                                        |
| `search-hero`                               | raw-ledger                               | 无                 | Antd `Input.Search size="large"` 居中容器                                                                                                         |
| `wizard-steps`                              | drawer 内（新建 provider）               | 无                 | Antd `Steps` 横向，按需引入                                                                                                                       |
| `tag-cloud`                                 | asset-detail                             | 无                 | flex-wrap 标签集合                                                                                                                                |
| `small-chart`（横条带数值）                 | assets 域分布、asset-detail 质量维度     | 无                 | 自建 3 列 grid（label / 进度条 / 数值）                                                                                                           |
| `expandable card`                           | rules                                    | 无                 | 自建（基于 Antd `Card` + 自管开合状态）                                                                                                           |

### 4.2 视觉系统偏差

- **主色调**：从 v3.1 的 Indigo `#4f46e5` 切换为 **奠基蓝 `#2563eb`（Tailwind Blue-600）**，辅色 **数据流青 `#0d9488`（Teal-600）**。详见下文「4.3 主色调选型与统一原则」。
- **侧边栏**：深色 `#0f172a`（slate-900），active 项 `rgba(37,99,235,0.16)` + 左 3px `#60a5fa`。
- **logo 渐变**：从原型的 `#7c9ff5 → #0e8a7a`（跨色相，与品牌脱节）校准为 **`#2563eb → #0d9488`**，与品牌主色对齐。
- 内联 `style={{}}`：grep 命中 **146 处**。逐页迁移到 Tailwind utility / token / 语义类。
- Topbar 视觉：v3.2 用 `rgba(255,255,255,0.92)` + `backdrop-filter: blur(12px)`；目前已大致一致，复核细节。

### 4.3 主色调选型与统一原则

> 基于 NEXUS 产品定位（企业级数据与知识资产治理平台、长会话密集数据、AI 辅助而非主角、教育+企业 B 端用户）做选型，作为整个控制台视觉一致性的单一真源。

#### 4.3.1 选色四轴

| 轴                  | 要求                                                                               |
| ------------------- | ---------------------------------------------------------------------------------- |
| 信任与权威感        | 蓝色家族（金融、政企、SaaS 平台主流），非 marketing 蓝、非过度年轻化               |
| 与 AI 的距离        | 略带智能感即可；AI 是辅助方，视觉不抢治理主调；远离纯紫（OpenAI/Anthropic 标签色） |
| 与暗色 sidebar 协同 | sidebar `#0f172a`（slate-900），主色 active 态在深色上需读得出                     |
| 与域色/语义色协同   | 不撞 D1 `#3b49df`（蓝紫）/ D2 `#6d3bd0`（紫）；不与 info `#3b82f6` 重合            |

#### 4.3.2 决策

**主色：`#2563eb` 奠基蓝（Tailwind Blue-600）**
**辅色：`#0d9488` 数据流青（Tailwind Teal-600）**

否决路径：

- ❌ 原型 `#3b6cf4`：饱和度偏高，与 D1 `#3b49df` 在密集表格中区分度不足；非 Tailwind 标准刻度，派生 50-900 色阶需手调。
- ❌ v3.1 `#4f46e5`（Indigo）：偏 AI/Tech 站点视觉（Linear、Vercel 风），治理权威感弱；与 D2 紫色域家族过近。

#### 4.3.3 完整 Token 体系（写入 `globals.css`）

```css
/* ── 品牌主色：奠基蓝 ─────────────────────────────── */
--brand-50: #eff6ff; /* selected bg / alert info bg / brand-soft */
--brand-100: #dbeafe;
--brand-200: #bfdbfe;
--brand-300: #93c5fd;
--brand-400: #60a5fa; /* sidebar active 左条（深底上需提亮一档） */
--brand-500: #3b82f6;
--brand-600: #2563eb; /* 主色（按钮、链接、active tab） */
--brand-700: #1d4ed8; /* hover / pressed */
--brand-800: #1e40af;
--brand-900: #1e3a8a;

--brand: var(--brand-600);
--brand-strong: var(--brand-700);
--brand-soft: var(--brand-50);

/* ── 辅色：数据流青（pipeline、数据流向、AI 建议）── */
--accent: #0d9488; /* teal-600 */
--accent-strong: #0f766e;
--accent-soft: #ccfbf1;
--accent-bg: #f0fdfa;

/* ── 品牌渐变（logo、漏斗条、强调元素）─────────── */
--brand-gradient: linear-gradient(135deg, #2563eb 0%, #0d9488 100%);

/* ── 侧边栏 active 态（蓝色 + 16% 透明叠加于 slate-900）── */
/* nav-item.active background: rgba(37, 99, 235, 0.16) */
/* nav-item.active 左条：var(--brand-400) */
```

`providers.tsx` 同步：

```ts
theme: {
  token: {
    colorPrimary: '#2563eb',
    colorInfo:    '#3b82f6',   // brand-500，比主色浅一档，避免冲突
    colorLink:    '#2563eb',
  },
  components: {
    Menu: {
      itemSelectedBg:    'rgba(37, 99, 235, 0.10)',
      itemSelectedColor: '#2563eb',
      itemHoverBg:       'rgba(37, 99, 235, 0.06)',
    },
  },
}
```

#### 4.3.4 视觉层级使用规则（保持一致性的关键）

| 元素                        | 用色                                        |
| --------------------------- | ------------------------------------------- |
| 主按钮 / 主操作             | `--brand-600` 实心                          |
| 次按钮 / 链接 / 导航 active | `--brand-600` 文字 + 透明/soft 底           |
| 选中 tab / 选中行 / focus   | `--brand-50` 底 + `--brand-600` 文字/边     |
| 表格 `table-link`           | `--brand-600` 文字                          |
| 漏斗 / 管线进度条 / 渐变    | `--brand-gradient`                          |
| jobs pipeline 当前阶段      | `--brand-600` + pulse 动画                  |
| `Alert type=info` / notice  | `--brand-50` 底 + `--brand-600` 描边        |
| AI 建议徽标 / 智能标签      | `--accent`（teal）                          |
| 数据流向箭头 / 血缘 code    | `--accent`                                  |
| 侧边栏 brand-mark 渐变      | `--brand-gradient`                          |
| 侧边栏 active 高亮          | `rgba(37,99,235,0.16)` + 左条 `--brand-400` |

#### 4.3.5 一致性禁止项

- ❌ 主色和 info 同时出现在同一信息块（视觉冗余）
- ❌ 主色 + 紫色 D2 域同行表格里同强度展示（色相打架，D2 应保持 chip 弱化形式）
- ❌ 自定义非 token 蓝（如 `#2c5cdc`、`#3060e0`、`#3b6cf4`）
- ❌ logo 渐变跨大色相（蓝→青跨度过大），统一使用 `--brand-gradient`
- ❌ 在某一页面引入蓝色之外的"页面强调色"破坏整体一致性

#### 4.3.6 与 v3.2 原型的偏差校准（落地时）

| 原型 token                    | 校准后                                              | 理由                                |
| ----------------------------- | --------------------------------------------------- | ----------------------------------- |
| `--primary: #3b6cf4`          | `--brand-600: #2563eb`                              | 与 D1 区分度更强，Tailwind 标准刻度 |
| `--primary-soft: #edf2fe`     | `--brand-50: #eff6ff`                               | Tailwind 标准刻度                   |
| `--primary-hover: #3060e0`    | `--brand-700: #1d4ed8`                              | 标准 hover 一档                     |
| logo 渐变 `#7c9ff5 → #0e8a7a` | `linear-gradient(135deg, #2563eb 0%, #0d9488 100%)` | 与品牌主色一致，避免脱节            |
| `--accent: #0e8a7a`           | `--accent: #0d9488`                                 | Tailwind Teal-600                   |
| sidebar active bg             | `rgba(37,99,235,0.16)`                              | 主色对齐                            |
| sidebar active 左条 `#7c9ff5` | `var(--brand-400)`（即 `#60a5fa`）                  | Token 化，深底上更亮                |

### 4.4 工程基础债

| 项                           | 状态                                                   |
| ---------------------------- | ------------------------------------------------------ |
| TanStack Query 接入          | 未接入；`app/rules/page.tsx` 仍是手写 `fetch+useState` |
| Antd `Form` + Zod 表单       | 未落地（drawer 表单尚未实现）                          |
| `react-error-boundary` 边界  | 已安装，未在路由壳/模块包裹                            |
| Loading / Empty / Error 三态 | 仅部分页面具备                                         |
| URL 状态同步                 | 表格 search/filter/page 未与 query string 同步         |
| ESLint 已知 error            | 2 处，集中在 `app/rules/page.tsx`                      |
| 内联 style 计数              | 146                                                    |

---

## 五、原型层 UI 优化建议（落地前需评审）

> v3.2 是中保真原型，作为资深 UI 设计审视，提出以下合理化建议。**未经评审不强推。**

| #   | 问题                                                                                                                                               | 建议                                                                                                      | 影响   |
| --- | -------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- | ------ | ---- | ----------------------------------------------------------- | --- |
| 1   | hero-card / metric-card 在 1180px 以下会从 4→2 跳变，单卡变得过宽                                                                                  | 在 1024-1280px 区间引入 3 列断点，整体平滑                                                                | 小     |
| 2   | 资产列表用 `border-left:3px solid <domain>` 表示数据域，但行选中态视觉与之冲突                                                                     | 选中行改用浅 brand-50 整行底色 + 左条由 chip 表达，避免双信号                                             | 小     |
| 3   | `quality-ring` 用 `conic-gradient` 呈现，弧形读数依赖记忆                                                                                          | 圆环中心数字 + 下方 `quality_level` 文字（pass / partial / poor）双重表达                                 | 小     |
| 4   | governance review-card 卡片右上的两个按钮（裁定 / 改派）布局过紧，移动端会换行                                                                     | 主按钮保留，改派改为右上角 `MoreOutlined` overflow menu，避免双主按钮                                     | 中     |
| 5   | sticky `tab-nav`（asset-detail 详情页）在 `top:68px`，与 topbar `56px` 不一致                                                                      | 统一为 `top:var(--topbar-h)` 即 56px，并加 8px 视觉缓冲                                                   | 小     |
| 6   | 时间显示混用相对/绝对（"2 分钟前" / "今日 09:18" / "2026-05-15"）                                                                                  | 统一规则：≤1h 相对，1h-24h 显示 "今日 HH:mm"，跨日绝对 + hover tooltip 显示 ISO + trace_id                | 小     |
| 7   | sidebar 深色（`#0f172a`）与 page bg `#f8fafb` 对比强，国内 SaaS 习惯偏中性灰底                                                                     | 维持深色但允许浅色变体（用户偏好），通过 prefers-color-scheme 或显式 toggle                               | 大     |
| 8   | brand-mark 渐变 `#7c9ff5 → #0e8a7a`（蓝→青）跨色相                                                                                                 | **已校准**：使用 `--brand-gradient`（`#2563eb → #0d9488`），与品牌主色对齐，详见 4.3.6                    | ✅     |
| 9   | `data-source` 默认是卡片网格，缺少"按状态分组"或排序入口                                                                                           | 卡片网格保留，加排序下拉（最近批次时间 / 状态 / 责任人）                                                  | 小     |
| 10  | `search-hero` 在 `raw-ledger` 顶部居中，中保真为占位输入框                                                                                         | 实现时支持 `Cmd/Ctrl+K` 焦点回流；输入历史下拉                                                            | 中     |
| 11  | `attention-zone` 三种 tone（danger / warning / info）但 prototype 只用了前两种                                                                     | 显式补上 `info` 形态（如系统提醒：定时任务完成）                                                          | 小     |
| 12  | `permissions` heatmap 单元格颜色（can/review/cant）易与状态色混用                                                                                  | 加角标图标（✓ / ⚑ / —）辅助色盲场景                                                                       | 中     |
| 13  | bulk-bar 在 governance 与 tag-review 重复定义                                                                                                      | 抽 `BulkBar` 共享组件，行为统一（清空、计数、批量按钮 props 化）                                          | 小     |
| 14  | `provider-card` 状态点和 chip 之间没有视觉层级，长 chip 会换行                                                                                     | 状态从 chip 提升为 card-top 角标（与名称对齐），chip 仅留 D/L/source_type/content_type                    | 小     |
| 15  | 整页 `onclick="navigateTo('xxx')"` 的内联跳转，缺少 hover 高亮                                                                                     | 实现时统一加 `:hover { box-shadow }` 与 `cursor:pointer`，避免可点不可视                                  | 小     |
| 16  | `code-block` 颜色与 sidebar 同为 `#0f172a`，深色一致但缺少代码语法高亮                                                                             | 引入 `react-syntax-highlighter` 或 Antd `Typography.Paragraph code` + 简单 token 高亮（DSL 关键字）       | 中     |
| 17  | 无障碍：纯图标 chip / 状态点缺 `aria-label`                                                                                                        | 所有圆点徽标补语义文本（视觉隐藏），通过 Antd `Tag` + `aria-label`                                        | 小     |
| 18  | drawer-overlay 没有焦点陷阱回退                                                                                                                    | 用 Antd `Drawer`（自带焦点管理）替换原型的 div                                                            | 小     |
| 19  | "业务专家"等中文角色名直接出现在 UI；未来 i18n 风险                                                                                                | 文案改用 i18n key（同 `i18n.md` 规则），先建 `zh-CN.json`                                                 | 中     |
| 20  | 移动端 (<960px) 内 `topbar-pill:first-child` 直接 `display:none`                                                                                   | 改为 overflow chip（点击后展开为 popover），避免信息丢失                                                  | 小     |
| 21  | 卡片体系过度分化：`.card` `.profile-card` `.review-card` `.source-card` `.provider-card` `.hero-card` `.metric-card` `.audit-item` 共 **8 种变体** | 收敛为 `<Card variant="default                                                                            | metric | hero | interactive">`，其余通过 composition 实现，长期维护成本骤降 | 大  |
| 22  | `quality-ring` 仅靠 conic-gradient 颜色 + 数字传达，色盲与读屏用户无可读 fallback                                                                  | 圆环中心数字下方加 `quality_level`（pass / partial / poor）文字，并补 `aria-label="质量分 92，等级 pass"` | 中     |
| 23  | sidebar `nav-section-title` 透明度 `0.40` 在深底上对比度接近 AA 下限                                                                               | 提到 `0.60`；保持 `letter-spacing: 0.10em` 与 `font-weight: 700`，可读性更稳                              | 小     |
| 24  | governance review-card 同时挂 D + L + 状态 + 优先级 + 置信度 + SLA 共 **5+ 徽标**，一行视觉过载                                                    | 同行徽标硬上限 3 个，超出折叠为 hover popover；按「徽标语义优先级矩阵」（阶段 -1 A6）选取保留项           | 中     |
| 25  | "一键采纳高置信建议" / "批量重试" / "切换激活版本" 等高 blast-radius 操作仅 toast 即完成，缺 undo                                                  | 危险动作分级：confirm dialog（不可逆）/ two-step / undo toast 10s（默认）/ time-locked，统一在阶段 -1 A3  | 中     |

---

## 六、阶段化执行计划

### 阶段 -1 — UX 基础规范（1 天，与阶段 0 并行）

> 资深 UI/UX 视角的二次审视产物。v3.2 中保真稿在「四态、a11y、危险动作、微文案、卡片体系」上有结构性盲区，按原型 1:1 落地会得到「看起来对、用起来累」的控制台。本阶段先沉淀基础规范，作为阶段 2 每个 PR 的输入。

| 子项                      | 产出                                                                                                                                                                         | 落地位置                                                                      |
| ------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| **A1 四态规范**           | Loading（Skeleton）/ Empty（Empty + 主 CTA）/ Error（Result + retry + trace_id）/ Forbidden（MaskedCell"内容受限"）的统一样式 + token                                        | `components/shared/{Loading,Empty,ErrorState,MaskedCell}.tsx` + `globals.css` |
| **A2 a11y 基线**          | 所有颜色信号补 icon/text 双通道（D1-D6 / L1-L4 / heatmap / priority）；`--focus-ring: 0 0 0 3px rgba(37,99,235,0.40)`；键盘可达自查清单 + AA 对比度                          | `globals.css` 补 token；`docs/a11y-checklist.md`                              |
| **A3 危险动作清单**       | 全站 destructive 操作枚举 + 每个的 UX 模式（confirm dialog / two-step / undo toast 10s / time-locked），含"采纳建议、批量重试、规则发布、撤销标签、Prompt 切换、caller 撤销" | `docs/ux-destructive-actions.md`                                              |
| **A4 微文案与术语模板**   | 错误信息四要素模板（What / Why / Next / trace_id）；空队列 CTA 模板（描述 + 主操作）；术语小卡（assetize / normalize / normalized_ref / org_scope 等首次出现处 hover 解释）  | `i18n/zh-CN.json` 起步 + `components/shared/TermTip.tsx`                      |
| **A5 卡片体系收敛**       | 用 `<Card variant="default \| metric \| hero \| interactive">` 替代 8 种 `.xxx-card` 语义类；其余形态通过 composition 实现                                                   | `components/shared/Card.tsx`，迁移指南写入 plan                               |
| **A6 徽标语义优先级矩阵** | 一行徽标硬上限 3 个；优先级顺序：状态 > 优先级 > 分级 L > 域 D > 置信度 > SLA；超出折叠 hover popover                                                                        | `docs/ux-badge-priority.md`                                                   |
| **A7 时间统一规则**       | ≤1h 相对（"5 分钟前"）/ 1h-24h "今日 HH:mm" / 跨日绝对 `YYYY-MM-DD HH:mm`；hover tooltip 显示 ISO + trace_id                                                                 | `lib/format-time.ts` 工具函数                                                 |
| **A8 卡片视觉权重 3 级**  | Primary（p24 + shadow-md，主任务区）/ Secondary（p20 + shadow-sm，辅助区）/ Tertiary（p16 + no-shadow，列表项）。workbench 等多卡页面强制使用                                | `globals.css` `.card.{primary\|secondary\|tertiary}`                          |
| **A9 移动端策略决策**     | 显式决策：是否支持 <960px。若支持，重做 topbar pill / sidebar drawer；若不支持，<960px 显示"请使用桌面端"的友好引导                                                          | 评审决策 + 实现                                                               |

**验收**：以上 9 项全部产出文档/组件/token；阶段 2 任何 P2.\* PR 引用 `docs/*` 路径作为依据。

### 阶段 0 — Baseline 重置（0.5 天）

> 目标：让仓库视觉与 v3.2 对齐，作为后续每页骨架填充的稳定基线。

- [ ] `app/globals.css`（详见 4.3.3 完整 token 体系）：
  - `--brand` 替换为 `#2563eb`（Blue-600）、`--brand-strong` `#1d4ed8`、`--brand-soft` `#eff6ff`；同步 `--brand-50..900` 整套 Tailwind Blue 刻度；
  - `--accent` 替换为 `#0d9488`（Teal-600）、`--accent-strong` `#0f766e`、`--accent-soft` `#ccfbf1`；
  - 新增 `--brand-gradient: linear-gradient(135deg, #2563eb 0%, #0d9488 100%)`；
  - 域色 token 校准：D1 `#3b49df` / D2 `#6d3bd0` / D3 `#0e8a7a` / D4 `#1d7a3a` / D6 `#ae2e28`（D5 暂保留 v3.1 的 `#ea580c`，待 SPEC 确认）；
  - 新增 v3.2 共享类：`.hero-strip` `.metric-grid-4/6` `.summary-strip` `.attention-zone` `.attention-item.{danger|warning|info}` `.funnel-row` `.notice.{info|warning|danger}` `.code-block` `.timeline` `.kanban-item` `.simple-list` `.bulk-bar` `.review-card.{priority-overdue|priority-today}` `.quality-ring` `.small-chart` `.heatmap-cell.{can|review|cant}` `.mask-cell` `.provider-card.file-upload` `.source-card` `.audit-item` `.expandable` `.diff-{added|changed|removed}`。
- [ ] `app/providers.tsx`（详见 4.3.3）：
  - `theme.token.colorPrimary` 切到 `#2563eb`；
  - `colorInfo` 设为 `#3b82f6`（Blue-500，比主色浅一档以避免冲突）；
  - `colorLink` 与主色一致 `#2563eb`；
  - `components.Menu.itemSelectedBg` 切到 `rgba(37,99,235,0.10)`、`itemSelectedColor` `#2563eb`、`itemHoverBg` `rgba(37,99,235,0.06)`。
- [ ] `components/Sidebar.tsx` + 配套 CSS：
  - 底色 `#0f172a`（slate-900），文字 `rgba(226,232,240,0.78)`；
  - active 项 `background: rgba(37,99,235,0.16)`，左 3px `var(--brand-400)`（即 `#60a5fa`，深底上更亮）；
  - brand-mark 32×32 圆角 10、渐变使用 `var(--brand-gradient)`、白字 N。
- [ ] `Topbar.tsx`：核对 `backdrop-filter: blur(12px)` 与右侧三 pill 顺序（环境 / 角色 / 组织）。
- [ ] 新增空壳路由 `/tag-review` 与 `/search`（占位 + PageHeader），确保导航激活态正确。
- [ ] `lib/navigation.ts` 增加两条：
  - 「资产与治理」组追加 `{ href: "/tag-review", label: "标签审核", icon: "#", badge: 12, badgeTone: "warning" }`；
  - 「访问与审计」组追加 `{ href: "/search", label: "检索验证", icon: "?" }`。

**验收**：`npm run lint` & `npx tsc --noEmit` & `npm run build` 通过；视觉与 v3.2 sidebar / topbar 高度一致；两条新路由可访问、导航高亮正确。

### 阶段 1 — 共享原子组件落地（1.5 天）

> 目标：在 `components/shared/` 下沉淀 v3.2 反复用到的薄壳，避免每页重复实现。

- [ ] `components/shared/HeroCard.tsx`（含 tone 变体：default / warning / danger / success）
- [ ] `components/shared/MetricCard.tsx`（替代 `StatCard.tsx`）
- [ ] `components/shared/SummaryStrip.tsx`（已有，重写为基于 v3.2 token）
- [ ] `components/shared/AttentionItem.tsx`
- [ ] `components/shared/FunnelRow.tsx`
- [ ] `components/shared/Notice.tsx`（薄壳 Antd `Alert`，type 映射）
- [ ] `components/shared/StatusDot.tsx`（替代 `StatusLabel.tsx`）
- [ ] `components/shared/DomainChip.tsx` / `LevelChip.tsx`（替代 `DomainTag.tsx` / `ConfidenceBadge.tsx`）
- [ ] `components/shared/QualityRing.tsx`
- [ ] `components/shared/CodeBlock.tsx`
- [ ] `components/shared/StageSteps.tsx`（基于 Antd `Steps`）
- [ ] `components/shared/JobPipelineBar.tsx`（重写 `JobPipeline.tsx`）
- [ ] `components/shared/BulkBar.tsx`（从 governance 抽取）
- [ ] `components/shared/SmallChart.tsx`
- [ ] `components/shared/CompareRow.tsx`（v3.2 `compare-row`/`compare-side`）

**退役清单（按页面触及顺序删）**：`Badge.tsx` / `Tabs.tsx` / `EmptyState.tsx` / `StatCard.tsx` / `ProgressBar.tsx` / `ConfidenceBadge.tsx` / `DomainTag.tsx` / `StatusLabel.tsx` / `JobPipeline.tsx`。`AssetDetailTabs.tsx` 在 P2.7 重写资产详情时整体替换。

### 阶段 2 — 页面骨架填充（13-16 天）

> 优先级按"业务价值 + 现状缺口"排序。每页一个 PR，禁止跨页捆绑。

| 优先级 | 页面                  | v3.2 关键产出                                                                                                            | 主要 Antd / 自定义                                                                 | 预计 |
| ------ | --------------------- | ------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------- | ---- |
| P2.1   | `/governance`         | 移除「标签审核」tab，回到 4 tabs；review-card 左条 priority；`bulk-bar` 抽到 shared                                      | `Tabs` / `Table` / `Tag` / `Checkbox` / `Drawer` + shared.BulkBar                  | 1.5d |
| P2.2   | `/tag-review` ⭐ 新建 | 待审核表 + 自动提交历史 + 流程说明                                                                                       | `Table` / `Checkbox` / shared.BulkBar / shared.Notice / shared.SmallChart          | 1d   |
| P2.3   | `/workbench`          | hero-strip × 4 / attention-zone / 主链路漏斗 / 最近活动 timeline / 批次进度看板 / 决策待办 / 三 column 运行状态          | shared.HeroCard / shared.AttentionItem / shared.FunnelRow / Antd Timeline          | 2d   |
| P2.4   | `/assets`             | 4 metric / 域 quick-filter chips / 资产表（左色条 + quality-ring）/ 域分布 small-chart / 目录页说明                      | shared.MetricCard / shared.QualityRing / shared.SmallChart / shared.Notice         | 1.5d |
| P2.5   | `/data-sources`       | 4 metric / source-card-grid（默认）/ 表格视图切换 / 默认接入策略 + 治理前置提醒                                          | shared.MetricCard / Antd Card grid / Antd Table / shared.Notice                    | 1.5d |
| P2.6   | `/ingest`             | hero-strip × 4 / provider-card-grid（含 file-upload 虚线变体）/ 最近批次表（含小图表进度）/ 总览 vs 台账 区分卡          | shared.HeroCard / Antd Table / shared.Notice + 自建 ProviderCard                   | 1.5d |
| P2.7   | `/assets/[assetId]`   | sticky 顶部 5-tab：概览 / 版本与 ref / 治理与质量 / 切片与索引 / 血缘与审计；移除 anchor-nav；`AssetDetailTabs.tsx` 重写 | Antd Tabs sticky / Descriptions / Timeline / Steps / shared.CompareRow / CodeBlock | 2d   |
| P2.8   | `/jobs`               | 4 tabs（全部 / 运行中 / 失败 / 已完成）/ 列表（含 job-pipeline 横管线）/ 选中作业 stage-steps + 失败定位 notice          | Antd Tabs / Table / shared.JobPipelineBar / shared.StageSteps / shared.Notice      | 1.5d |
| P2.9   | `/raw-ledger`         | search-hero 巨型搜索 / 4 metric / 批次视图 + 对象视图 / 选中明细 definition-grid                                         | Antd Input.Search / Table / Descriptions / shared.MetricCard                       | 1d   |
| P2.10  | `/rules`              | 移除 JSON textarea；4 metric + expandable 规则集卡片（含 code-block）+ 发布影响评估面板                                  | shared.MetricCard / shared.CodeBlock / shared.Notice + Antd Steps（发布流）        | 2d   |
| P2.11  | `/ai-prompts`         | profile-card × N（带版本下拉）/ 输出 Schema definition-grid / 版本对比 diff                                              | Antd Select / Descriptions / shared.CompareRow + diff-{added/changed/removed}      | 1d   |
| P2.12  | `/iam-audit`          | 3 tabs（用户与角色 / API 调用方 / 审计日志）/ heatmap / mask-preview                                                     | Antd Tabs / Table / 自建 Heatmap / 自建 MaskCell                                   | 1.5d |
| P2.13  | `/search` ⭐ 新建     | 左：query 构造 + 权限切换；右：结果与引用 + 引用链 notice                                                                | Antd Input / Select / shared.Notice                                                | 1d   |
| P2.14  | `/my-workspace`       | 3 tabs；SLA 分层（超时 / 今日 / 正常）+ 快捷入口 + 我的最近动作                                                          | Antd Tabs / Table / shared.StatusDot                                               | 1d   |

**总计**：≈ 16 天单人。

### 阶段 3 — 数据层与状态机（5-7 天，与阶段 2 后段并行）

- [ ] 安装 `@tanstack/react-query` + `@tanstack/react-query-devtools`，在 `Providers` 中注入 `QueryClientProvider`。
- [ ] 改写 `app/rules/page.tsx`：消除手写 `fetch + useState`，修当前 2 处 ESLint error。
- [ ] 治理列表 / 资产列表 / 作业列表迁移到 `useQuery`，URL 状态同步（`?status=running&domain=D4&page=2`）。
- [ ] Antd `Form` + Zod resolver 重写 drawer 表单（新建 Provider、规则编辑、Prompt 编辑）。
- [ ] 引入 `react-error-boundary`：每个 `app/<route>/page.tsx` 包 `<ErrorBoundary FallbackComponent>`，模块卡片级别再包一层。
- [ ] 三态规范化：`Skeleton`（loading）/ `Empty`（empty）/ `Result status="error" + Button`（error）。
- [ ] 全局 toast：保留现有 `App.useApp()` 出口，给关键变更操作（规则发布、Prompt 切换、批量裁定）补一致文案。

### 阶段 4 — 视觉与样式收尾（3 天，与阶段 2 并行收尾）

- [ ] 用 grep + 工具检查清除 146 处内联 `style={{}}`（仅保留运行时计算值，且通过 CSS 变量传递）。
- [ ] 统一 sticky tab 距顶（`top:var(--topbar-h)`）。
- [ ] 退役自研组件最终清理：删除 `components/Badge.tsx` 等清单项；保留 `PageHeader.tsx`、`AppShell.tsx`。
- [ ] `globals.css` 抽取重复语义类，避免散落硬编码。

---

## 七、验收门槛

每个 P2.\* PR 合并前必须满足：

1. `npm run lint` 0 error；
2. `npx tsc --noEmit` 通过；
3. `npm run build` 通过；
4. 视觉对照 v3.2 prototype 对应 page-id 区块，关键骨架（hero-strip / metric-grid / tab 数 / 表列 / 详情区块）完全一致；
5. 该页 **四态**（Loading / Empty / Error / Forbidden）均有处理，附四态截图入 PR；
6. 无新增内联 `style={{}}`（运行时值除外）；
7. 该页所触及的自研组件（旧 `components/*.tsx`）已替换或在 PR 描述中说明保留原因；
8. 任何写入操作（规则发布、Prompt 切换、批量裁定、新建 caller 等）有审计 toast + idempotency 注释；
9. **a11y**：键盘可达 + AA 对比度 + 颜色信号已配 icon/text 双通道 + 圆点徽标补 `aria-label`；
10. **危险动作**匹配「阶段 -1 A3 危险动作清单」中规定的 UX 模式；
11. **徽标密度**：单行徽标 ≤ 3，超出折叠 hover popover（参见 A6）；
12. **微文案**：错误信息按 A4 四要素模板（What / Why / Next / trace_id）；空状态附主 CTA；
13. **响应式**：在 1024px / 1280px / 1440px 三档自查，或显式声明断点策略；
14. **设计 review**：≥ 1 名非纯工程 reviewer（产品/设计）通过；
15. **开工前 30 分钟自检**回答 3 问：本页主任务是谁、移走 30% 内容是否还能用、四态/移动端长啥样。

---

## 八、风险与回滚

| 风险                                                    | 缓解                                                                        |
| ------------------------------------------------------- | --------------------------------------------------------------------------- |
| 新建 `/tag-review` 与 `/search` 后端 API 未就绪         | 先以 mock data + `lib/console-data.ts` 静态数据交付 UI，再接 API；UI 不阻塞 |
| `AssetDetailTabs.tsx` 重写涉及 5 tab 数据合并，回归面广 | P2.7 拆为两个 PR：先骨架（5 tab + 占位）后逐 tab 接数据                     |
| 主色切换影响视觉回归                                    | 阶段 0 单独 PR，先发 staging；保留 v3.1 token 一周作回滚保险                |
| Antd 6 minor 升级偶发样式漂移                           | 锁定 `^6.4.x`；CI 内增加视觉冒烟（Playwright `toHaveScreenshot`，P3）       |
| 内联 style 大批量清理引入新样式 bug                     | 按页清理，每页 PR 内 diff 不超 +200 行，便于回滚                            |

---

## 九、待办清单（与本文档保持同步）

### 阶段 -1（UX 基础规范）

- [ ] A1 四态规范：Loading / Empty / Error / Forbidden 组件 + token
- [ ] A2 a11y 基线：colorblind 双通道、`--focus-ring`、键盘自查清单、AA 对比度
- [ ] A3 危险动作清单 + UX 模式映射（`docs/ux-destructive-actions.md`）
- [ ] A4 微文案与术语模板（错误四要素 + 空队列 CTA + 术语小卡 `TermTip`）
- [ ] A5 卡片体系收敛：`<Card variant>` 替代 8 种 .xxx-card
- [ ] A6 徽标语义优先级矩阵（单行 ≤ 3，超出折叠）
- [ ] A7 时间统一规则 + `lib/format-time.ts`
- [ ] A8 卡片视觉权重 3 级（primary / secondary / tertiary）
- [ ] A9 移动端策略决策（支持 or 显式不支持）

### 阶段 0

- [ ] `globals.css` 主色 / 辅色 / 域色 token 切换到 v3.2
- [ ] `providers.tsx` ConfigProvider 同步
- [ ] Sidebar 深色 + brand-mark 渐变重写
- [ ] `lib/navigation.ts` 补 `/tag-review` 与 `/search`
- [ ] 新建 `/tag-review` 与 `/search` 占位路由

### 阶段 1

- [ ] 落地 15 个 `components/shared/*` 原子组件
- [ ] 退役旧自研：Badge/Tabs/EmptyState/StatCard/ProgressBar/ConfidenceBadge/DomainTag/StatusLabel/JobPipeline

### 阶段 2

- [ ] P2.1 `/governance`（恢复 4 tabs，移除标签审核 tab）
- [ ] P2.2 `/tag-review`（独立页）
- [ ] P2.3 `/workbench`
- [ ] P2.4 `/assets`
- [ ] P2.5 `/data-sources`
- [ ] P2.6 `/ingest`
- [ ] P2.7 `/assets/[assetId]`（5 tabs sticky，重写 AssetDetailTabs）
- [ ] P2.8 `/jobs`
- [ ] P2.9 `/raw-ledger`
- [ ] P2.10 `/rules`
- [ ] P2.11 `/ai-prompts`
- [ ] P2.12 `/iam-audit`
- [ ] P2.13 `/search`（独立页）
- [ ] P2.14 `/my-workspace`（保持 3 tabs）

### 阶段 3

- [ ] 接入 TanStack Query
- [ ] 改写 `app/rules/page.tsx`，修 2 处 ESLint error
- [ ] Antd Form + Zod 表单
- [ ] react-error-boundary 模块边界
- [ ] 三态 Skeleton / Empty / Result
- [ ] URL 状态同步

### 阶段 4

- [ ] 清除 146 处内联 `style={{}}`
- [ ] 统一 sticky tab 顶距
- [ ] 删除已退役旧组件文件

---

## 十、与原契约的关系

- `nexus-console/CLAUDE.md`：保留为前端工程契约，本计划的视觉/组件选择与之一致（Antd 6 + Tailwind v4 + Token，禁止 CSS-in-JS / 内联 style）。
- 仓库根 `CLAUDE.md` / `ARCHITECT.md` / `SPEC.md` / `WORKFLOWS.md`：本计划不改变后端契约。**`nexus-console` 不调用后端不存在的接口**；缺失字段以 `lib/console-data.ts` mock 走通 UI，并在 PR 中明确列出 mock 项。
- `WORKFLOWS.md` Review Gate：每个 P2.\* PR 视为一个 Review Gate，需满足"七、验收门槛"。
