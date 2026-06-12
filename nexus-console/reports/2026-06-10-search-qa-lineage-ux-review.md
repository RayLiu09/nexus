# Search / QA 溯源 UX 架构评审

> 生成时间：2026-06-10
> 评审工具：frontend-craft / fec-frontend-code-review

---

## 1. 目标与约束

**目标**：让操作员能从一条搜索命中或 QA 引用出发，快速核实 chunk 对应的原始文件位置；满足法务/财务/审计场景的溯源合规要求。

**已明确约束**：
- Antd 6 优先，Tailwind v4 补充，不引入新样式体系
- 默认 Server Component；`'use client'` 仅在有交互时使用
- 不引入 TanStack Query（P1 按需），沿用 `lib/api.ts` 模式
- 不在 P0 引入 PDF.js 等重型渲染器

---

## 2. 当前差距

| 能力 | 现状 | 影响 |
|------|------|------|
| 类型定义 | `SearchChunk` / `QaSource` 缺少 `locator`、`source_block_ids`、`raw_object_uri`、`data_source_id`、`answer_confidence` | TS 严格模式下新字段全部不可访问 |
| 结果行渲染 | `SearchResultList` 和 `QaResult` 为 inline 函数，无可复用边界 | 难以独立测试或在 Asset Detail 复用 |
| 溯源入口 | 无任何跳转链接；`normalized_ref_id` 仅以 mono 文本展示 | 操作员无法从结果页导航到资产详情 |
| 定位信息 | `locator` 字段未展示 | 页码/块级定位完全丢失 |
| 置信度 | `answer_confidence` 未展示 | QA 模式下无法判断答案可信程度 |
| 原始文件 | `raw_object_uri` 未利用 | 无法查看原始文档 |
| Asset Detail | 血缘标签页无 chunk 视图、无 Markdown 内容渲染、无"跳转到原始文件" | 溯源链路在 Asset 侧断裂 |

---

## 3. 信息架构

溯源信息按密度分三层展示，避免一次铺开压垮操作员：

```
Layer 1 — 结果行（始终可见）
  score | doc_name | 页码 chip | asset 链接图标

Layer 2 — 展开面板 / Drawer（按需打开）
  完整 content | locator 细节 | block 列表 | 查看原始文件 按钮

Layer 3 — 跳转页面（强意图导航）
  Asset Detail > 血缘追溯标签 → 新增 Chunk 视图
  raw_object_uri presigned URL → 浏览器新标签打开原始文件
```

选择 Drawer 而不是独立页面承载 Layer 2 的原因：操作员通常需要对比多条 chunk；Drawer 不破坏结果列表的上下文，关闭后焦点自动回到触发行，符合 a11y 要求。

---

## 4. 组件分解

### 4.1 目标目录结构

```
app/search/
├── _lib/
│   └── searchTypes.ts          # 补全 ChunkProvenance、LocatorInfo、AnswerConfidence 类型
├── _components/
│   ├── SearchPlayground.tsx    # 保留；精简 inline 子组件，改为导入
│   ├── SearchResultList.tsx    # 抽出（现为 inline 函数）
│   ├── QaResultPanel.tsx       # 抽出（现为 inline 函数）
│   ├── ChunkCard.tsx           # NEW — 单条 chunk 展示行（search + QA 复用）
│   ├── ChunkDetailDrawer.tsx   # NEW — chunk 详情抽屉（'use client'）
│   ├── LocatorChip.tsx         # NEW — 页码/跨页提示 chip（纯展示）
│   ├── AssetLink.tsx           # NEW — 跳转 Asset Detail 图标按钮
│   └── AnswerConfidenceBadge.tsx # NEW — QA 答案置信度展示（复用 ConfidenceBadge 逻辑）

components/
├── ConfidenceBadge.tsx         # 已有；AnswerConfidenceBadge 复用其 tier() 逻辑
└── StatusLabel.tsx             # 不变

app/assets/[assetId]/_components/
└── LineageTab.tsx              # P1 扩展：新增 ChunkListSection 子组件
```

### 4.2 各组件职责

| 组件 | 层级 | 职责 | 交互 |
|------|------|------|------|
| `ChunkCard` | 业务展示 | 渲染单条 chunk 的 Layer 1 信息（score、doc_name、LocatorChip、AssetLink、content 截断） | 点击展开 → 触发 Drawer |
| `ChunkDetailDrawer` | 业务交互 | 展示 Layer 2：完整 content、locator 细节、block 列表、"查看原始文件"按钮 | Antd Drawer；'use client' |
| `LocatorChip` | 通用展示 | 将 `locator` 对象转为人类可读 chip（"第3页"、"p3–p5 跨页"、"-"） | 无，纯展示 |
| `AssetLink` | 通用展示 | 以图标按钮形式跳转 `/assets/[assetId]`；`aria-label="查看资产详情"` | `<Link>` target="_blank" |
| `AnswerConfidenceBadge` | 业务展示 | 重用 `ConfidenceBadge` 的三级颜色逻辑；score < 0.5 额外渲染 Antd `Tooltip` 说明"证据较弱" | Tooltip hover |
| `SearchResultList` | 容器 | 负责列表编排（Antd `List`），将 `SearchChunk[]` 分发给 `ChunkCard` | 无 |
| `QaResultPanel` | 容器 | 展示答案区 + `AnswerConfidenceBadge` + 来源列表（`ChunkCard`） | 无 |

---

## 5. 页面流程（ASCII 线框）

### 5.1 搜索结果行

```
┌─────────────────────────────────────────────────────────────────┐
│  ● 0.923  │  教材开发流程梳理.pdf  │ [第3页]  │ [↗资产]         │
│  内容截断预览，最多 3 行，点击"展开"显示全部…                    │
│  [展开详情]                                                      │
└─────────────────────────────────────────────────────────────────┘

图例：
  ● 0.923   — Antd Tag color="blue"（score）
  [第3页]   — LocatorChip（Antd Tag color="default"）
  [↗资产]   — AssetLink（lucide-react ExternalLink 图标，aria-label）
  [展开详情] — 按钮，触发 ChunkDetailDrawer
```

### 5.2 ChunkDetailDrawer

```
┌──────────────────────────────────────────────────────┐ ✕
│  chunk 详情                                          │
│  ─────────────────────────────────────────────       │
│  原文档      教材开发流程梳理.pdf                     │
│  资产 ID     [↗ a4f2...] (AssetLink)                 │
│  页面定位    第3页（p3）                              │
│  跨页        否                                       │
│  Block IDs   blk_001、blk_002（若非 null）            │
│  ─────────────────────────────────────────────       │
│  完整内容                                            │
│  ┌────────────────────────────────────────────────┐  │
│  │ 光合作用的暗反应阶段发生在叶绿体基质中…        │  │
│  └────────────────────────────────────────────────┘  │
│                                                       │
│  [查看原始文件 ↗]   （presigned URL，新标签）         │
└───────────────────────────────────────────────────────┘
```

### 5.3 QA 答案区

```
┌────────────────────────────────────────────────────────┐
│  AI 回答                    [置信度 中等 71%] [⚠提示]  │
│  光合作用的暗反应（卡尔文循环）发生在叶绿体基质中…      │
└────────────────────────────────────────────────────────┘
┌────────────────────────────────────────────────────────┐
│  引用源（3条）  KB: textbook_kb                        │
│  ┌──────────────────────────────────────────────────┐  │
│  │ ● 0.86 │ 教材开发流程梳理.pdf │ [第3页] │ [↗] │  │  │
│  │ 暗反应阶段发生在叶绿体基质中，该过程…             │  │
│  │ [展开详情]                                        │  │
│  └──────────────────────────────────────────────────┘  │
│  （其余来源同上）                                       │
└────────────────────────────────────────────────────────┘

图例：
  [⚠提示] — answer_confidence < 0.5 时显示 Antd Tooltip "来源证据较弱，建议人工核查"
```

### 5.4 Asset Detail — P1 Chunk 视图（LineageTab 扩展）

```
血缘追溯标签
  ├── 处理链路（现有 Steps）
  ├── 链路明细（现有表格）
  └── 关联 Chunks（NEW，P1）
      ┌──────────────────────────────────────────────┐
      │  chunk_id  │  页码    │  score   │  block数  │
      │  abc123    │  第3页   │  0.921   │  2       │
      │  def456    │  p4–p5   │  0.874   │  3       │
      └──────────────────────────────────────────────┘
```

---

## 6. "查看原始文件"策略（分阶段）

### P0 — MinIO Presigned URL（新标签打开）

- 后端在 `/open/v1/search` / `/open/v1/qa` 响应中已返回 `raw_object_uri`（MinIO key）。
- 控制台代理路由 `GET /api/assets/[assetId]/raw-download` 生成 presigned URL（有效期 15 分钟）；前端点击"查看原始文件"时调用该路由，获得 URL 后 `window.open(url, '_blank')`。
- 优点：零新依赖，浏览器原生处理 PDF/Office/图片；缺点：无法高亮 bbox，无法滚动到指定页。
- 对于 `raw_object_uri: null` 或 presigned 请求失败的情况，按钮降级为禁用状态，Tooltip 说明"原始文件不可访问"。

### P1 — Markdown 内容渲染 + block 锚点定位

- `normalized_document` 已有 `body_markdown`（通过 `normalized_asset_ref.object_uri` 可取）；Asset Detail 新增"内容预览"区，使用 `react-markdown`（按需 `next/dynamic`，ssr:false）渲染。
- 通过 `source_block_ids` 对应锚点，用 `scrollIntoView` 定位并高亮目标 block。
- 适用于 Pipeline A 文档类资产，对 Pipeline B record 类不适用（record 无 markdown，以 JSON 表格展示代替）。

### P2 — PDF.js + bbox overlay

- 仅当运营场景中大量扫描件 / 图像型 PDF 需要精确定位时引入。
- `locator.bbox_union` 在 `next/dynamic` 懒加载的 `<PdfViewer>` 中绘制高亮矩形。
- 引入前需评估包体积（~1MB gzip）与 P0 presigned 方案的覆盖差距。**P0 不引入。**

---

## 7. Locator 可视化规则

```typescript
// LocatorChip 的渲染逻辑（伪代码）
function formatLocator(locator: LocatorInfo | null): string {
  if (!locator) return "-";                                  // record 类型或尚未索引
  const { page_start, page_end } = locator;
  if (page_start === page_end) return `第${page_start}页`;
  return `p${page_start}–p${page_end} 跨页`;
}
```

- 单页：`第3页` — Antd `Tag` color="default"
- 跨页：`p3–p5 跨页` — Antd `Tag` color="orange"（警示色，表示定位精度降低）
- `locator: null`：`-`（灰色 Tag 或仅文本）；在 Drawer 中补充说明"该 chunk 来自记录类型资产，无页码定位"

---

## 8. 类型定义更新

`app/search/_lib/searchTypes.ts` 需补全：

```typescript
export interface LocatorInfo {
  page_start: number;
  page_end: number;
  bbox_union: [number, number, number, number] | null;
  blocks: { block_id: string; page: number; bbox: [number, number, number, number] }[];
}

export interface SearchChunk {
  chunk_id: string;
  nexus_chunk_id?: string;
  normalized_ref_id?: string;
  version_id?: string;
  asset_id?: string;
  content: string;
  score: number;
  source: SearchChunkSource;
  // 新增字段
  locator: LocatorInfo | null;
  source_block_ids: string[] | null;
  raw_object_uri?: string;
  data_source_id?: string;
}

export interface QaSource extends SearchChunk {}  // QA 来源字段与 chunk 对齐

export interface QaResponse {
  question: string;
  kb: string | null;
  caller_id: string;
  answer: string;
  answer_confidence: number | null;  // 新增
  sources: QaSource[];
}
```

**注意**：去除 `[k: string]: unknown` 索引签名（现在两个接口都有），在 `strict: true` 下改为精确字段定义，避免类型洞。

---

## 9. 状态与数据流

```
SearchPlayground (useState — 'use client')
├── 查询参数：mode、query、kb、topK、threshold  (组件内 state)
├── 结果：searchData / qaData                   (组件内 state)
└── UI：loading、error                          (组件内 state)

ChunkDetailDrawer (useState — 'use client')
├── isOpen                                      (组件内 state)
├── selectedChunk                               (由 ChunkCard onOpenDetail 回调注入)
└── rawFileUrl                                  (按需请求，useState + fetchPresignedUrl())
    fetchPresignedUrl() → GET /api/assets/[assetId]/raw-download
    三态：idle | loading | url | error
```

不需要全局 store（Zustand）；数据流是单向的，状态范围足够局部。

---

## 10. A11y 要求

| 场景 | 要求 |
|------|------|
| ChunkCard 展开按钮 | `aria-expanded`、`aria-controls="chunk-detail-{chunk_id}"` |
| AssetLink 图标按钮 | `aria-label="查看资产 {asset_id} 详情"`；`rel="noopener noreferrer"` |
| ChunkDetailDrawer | Antd Drawer 自带焦点陷阱；关闭时焦点回到触发行按钮 |
| LocatorChip | 文本内容已可读，无需额外 aria；图标若有需补 aria-hidden |
| AnswerConfidenceBadge Tooltip | `<Tooltip>` 下包裹的触发元素需有 `tabIndex` 保证键盘可触达 |
| Chunk List | 使用 `<List>` 时确保 `role="list"` 语义正确（Antd 默认符合） |

---

## 11. 分阶段计划

### P0（本迭代，最小可用）

目标：让操作员能看到定位信息并跳转到原始文件。

- [ ] 补全 `searchTypes.ts` 类型定义，消除 `[k: string]: unknown`
- [ ] 将 `SearchResultList`、`QaResult` 从 `SearchPlayground.tsx` 内联函数抽取为独立文件
- [ ] 实现 `ChunkCard`：展示 score、doc_name、LocatorChip、AssetLink、content 截断
- [ ] 实现 `LocatorChip`：单页/跨页格式化
- [ ] 实现 `AssetLink`：icon 按钮跳转 `/assets/[asset_id]`
- [ ] 实现 `ChunkDetailDrawer`：完整 content + locator 细节 + "查看原始文件"按钮（调用 presigned URL 路由）
- [ ] 实现 `AnswerConfidenceBadge`（复用 `ConfidenceBadge` 颜色逻辑）；QA 答案区展示置信度
- [ ] 后端联调：确认 presigned URL 代理路由入参（`raw_object_uri` 还是 `asset_id`）
- [ ] `locator: null` / `raw_object_uri: undefined` 降级态覆盖

验收标准：从搜索结果行，3 步以内可打开原始文件；`locator` 有值时页码可见；QA 答案顶部展示置信度颜色标记。

### P1（下迭代）

- [ ] Asset Detail `LineageTab` 新增 Chunk 列表分区（关联 chunk 数量、页码、score）
- [ ] 后端提供按 `normalized_ref_id` 查询 chunk 列表的接口
- [ ] Markdown 内容预览区（`next/dynamic`，ssr:false；仅 document 类型）
- [ ] block 锚点高亮（`source_block_ids` → 对应 DOM 节点滚动）
- [ ] graph_extract chunk 的"提取来源 block"与"支撑 block"区分展示（仅在 Drawer 内，不在列表行）

### P2（按业务需要）

- [ ] PDF.js + bbox overlay（懒加载，仅在 presigned URL 打开失败或需要精确定位时推荐）
- [ ] chunk 列表虚拟化（当单资产 chunk 数 > 100 时）

---

## 12. 风险与注意事项

1. **类型洞**：现有 `[k: string]: unknown` 索引签名在 `strict: true` 下会静默通过非法字段访问。P0 必须一并清除。

2. **presigned URL 有效期**：15 分钟适合操作员当场核查；若操作员将 URL 保存后稍晚访问会失效。建议 Drawer 内说明"链接15分钟内有效"，并提供"重新获取"按钮。

3. **record 类型 chunk**：`locator` 为 null 是正常状态（Pipeline B），不应展示报错；LocatorChip 需区分"无定位数据"和"加载失败"两种空态。

4. **SearchPlayground.tsx 文件规模**：当前 374 行，抽取后主文件降到 ~120 行，符合约 300 行内的规范目标。

5. **graph_extract 多 block 证据**：属于 chunk_metadata 内的扩展字段，不在 P0 主路径中。P1 仅在 Drawer 内展示，不影响列表行密度。

6. **后端 API 路由确认**：`raw_object_uri` 是 MinIO key（非可直接访问 URL）；控制台代理路由需要持有 MinIO 凭据（与 `nexus-app` 内部服务通信），不暴露到浏览器。需与后端确认接口形式后再实现。

---

## 13. 开放问题

1. `raw_object_uri` 的生成权由 `nexus-app` 还是 `nexus-console` API 层持有 MinIO 凭据？
2. Asset Detail 的"关联 chunk"需要后端新增接口（按 `normalized_ref_id` 分页查询 chunk），还是搜索端有可用替代？
3. graph_extract 类 chunk 的 `primary_block_ids` / `evidence_block_ids` 字段在 API 响应中位置（`chunk_metadata` JSONB 还是顶层字段）？P1 展示前需确认。
4. QA `answer_confidence` 为 `null` 时（搜索模式无此字段）是否需要展示空态，还是仅在 `> 0` 时渲染徽标？
