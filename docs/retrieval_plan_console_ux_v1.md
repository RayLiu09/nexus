# NEXUS 检索计划 Console 友好呈现设计 v1.0

- **状态**：v1.3 R3 前置设计（对应 v1.3 §5.3 `friendly_view` 契约与 §9 二区改版）
- **日期**：2026-07-10
- **配套文档**：
  - `docs/knowledge_retrieval_result_enhancement_v1.3.md`（v1.3 主设计）
  - `docs/tag_filter_reliability_matrix_v1.md`（tag_filter 稳定性设计）
- **面向**：Console 前端 + `retrieval/orchestrator.py`
- **目的**：定义 `RetrievalPlan.friendly_view` 数据契约与 `SearchPlayground` 二区渲染契约，让业务用户看得懂检索的"意图理解 / 执行计划 / 结果证据"

---

## 1. 背景

当前 `nexus-console/app/search/_components/SearchPlayground.tsx` 是对话式 UI，**不展示** `retrieval_intent` / `retrieval_plan`。若直接把原始 JSON 抛给用户，会有三类问题：

1. 业务用户读不懂 `sub_queries` / `tag_filters` / `depends_on` 等工程字段。
2. 复杂场景（"某省产业布局 → 专业建设方案"）产生 6+ 个 sub_query，无结构化视图让用户迷失。
3. Console 无法反过来影响 planner（用户想"排除举例范围""只查最近 3 年"没有入口）。

同时对齐 v1.3 §9 —— 但原三区结构（对话主区 / 执行步骤区 / 辅助分析区）分割过细。R3 决策：**改为二区**：一区聚焦业务用户可读的完整对话流；一区作为工程/审计视角的折叠抽屉。

---

## 2. 设计目标

- **业务用户可读**：中文自然语言表达，隐藏 `tag_type` code、`match_strategy` 表达式、单复数命名分岔等工程细节。
- **过程可见**：每 sub_query 从"待执行 → 执行中 → 完成/降级/失败"状态可视，无花哨 DAG 图。
- **证据可回溯**：sub_query 卡片可展开看命中数、匹配层分布、来源。
- **可交互**：用户可"重跑单节点""跳过某维度""重新识别意图""编辑问题"。
- **降级友好**：降级、断链、举例误判等提示以显式 warning 形式展现，不隐藏。
- **无花哨 DAG**：依赖关系用"来自 X（岗位分析）"式自然语言表达（Q3 决策）。DAG 图形化留后续 M-D 观察后再定。

---

## 3. Console 单一对话流结构（R3-c 决策）

**R3-c 决策**：取消右侧辅助分析抽屉；所有内容一律呈现在**单一对话流**里，按时间顺序自上而下排列。工程/调试细节（原始 JSON / trace_id / 匹配层分布图 / source_refs 详情）按需通过**卡片内嵌折叠**展开，不再独立分区。

```
┌───────────────────────────────────────────────────────────┐
│  对话流（单一区，面向业务用户）                            │
│                                                           │
│  ┌─────────────────────────────────────────────────────┐  │
│  │ 用户问题输入                                        │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                           │
│  ┌─────────────────────────────────────────────────────┐  │
│  │ 意图卡：意图理解 + 识别到的约束 + 置信度徽章        │  │
│  │   └─ [展开详情]（可选，inline 显示原始 intent JSON） │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                           │
│  ┌─────────────────────────────────────────────────────┐  │
│  │ 执行步骤卡片 ① 查询北京市直播电商产业政策           │  │
│  │   数据来源 · 过滤条件 · 状态徽章 · 结果摘要         │  │
│  │   └─ [展开详情]（inline 显示 source_refs、warnings） │  │
│  └─────────────────────────────────────────────────────┘  │
│  ┌─────────────────────────────────────────────────────┐  │
│  │ 执行步骤卡片 ② 分析北京市直播电商岗位需求           │  │
│  │   ...                                                │  │
│  └─────────────────────────────────────────────────────┘  │
│  ┌─────────────────────────────────────────────────────┐  │
│  │ 执行步骤卡片 ③ … ④ … ⑤ …                            │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                           │
│  ┌─────────────────────────────────────────────────────┐  │
│  │ 最终 Markdown 汇总（evidence_chain 结构）           │  │
│  │   └─ 底部小 footer：trace_id · [导出证据]           │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                           │
│  ┌─────────────────────────────────────────────────────┐  │
│  │ 追加问题 / 澄清                                     │  │
│  └─────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────┘
```

**单一区职责**：

| 层次                 | 内容                                                                              | 目标用户                                |
| -------------------- | --------------------------------------------------------------------------------- | --------------------------------------- |
| **对话流（唯一区）** | 用户问题、意图卡、执行步骤卡片列表、Markdown 汇总、追加问题、底部 trace 小 footer | 业务用户为主；工程/审计按需 inline 展开 |

**关键 UX 原则**：

- **不再有独立辅助分析区/抽屉/侧栏**——工程细节按需通过卡片内嵌"展开详情"折叠区呈现。
- 执行步骤卡片按 `sub_query_cards` 顺序列出，随 SSE 事件流更新状态徽章 / 结果摘要。
- **每张卡片**（意图卡、执行步骤卡）都可点击"展开详情"→ **在卡片自身高度内**展开显示对应的原始数据（意图卡展开原始 intent JSON；步骤卡展开 source_refs、原始 sub_query JSON、`match_layer_distribution` 分布小图、warnings 详情）；再次点击收起。
- `trace_id` 显示在 Markdown 汇总底部一个**小 footer**（8-10px 字号灰色文字），工程/审计需要时可复制，业务用户可忽略。
- 追加问题在同一对话内延续。
- **零右滑动画、零侧栏、零 modal**——保持一列滚动的对话式体验。

---

## 4. 后端数据契约

### 4.1 `RetrievalPlan.friendly_view: FriendlyRetrievalPlanView`

由 orchestrator 生成，前端只渲染、不派生。**这是新增字段，不替换现有 `RetrievalPlan` 结构**——工程侧、审计侧仍走原始字段。

```typescript
interface FriendlyRetrievalPlanView {
  // 顶部意图卡数据
  intent_summary: IntentSummary;

  // 执行步骤卡片列表（顺序 = 期望展示顺序）
  sub_query_cards: SubQueryCard[];

  // 顶部摘要条
  overall: OverallSummary;
}

interface IntentSummary {
  // 一句话陈述用户问题的理解
  natural_language: string;
  // 例：「查询北京市直播电商产业规划，涉及岗位需求、教材与专业布点」

  // 涉及的业务领域中文名（非 code）
  business_domains_display: string[];
  // 例：["产业政策", "岗位需求", "专业布点"]

  // 识别到的约束（cross_asset_tags 的中文映射）
  identified_constraints: DisplayConstraint[];

  // 未识别的关键词
  unresolved_terms: string[];
  // 例：["职业院校"] —— 在 UI 中以灰色标签展示

  confidence: number; // 0-1
  confidence_level: "high" | "medium" | "low";
  // high >= 0.8; medium 0.6-0.8; low < 0.6 —— 用于配色

  // 若置信度低，返回澄清建议列表
  clarification_suggestions?: string[];
}

interface DisplayConstraint {
  label: string; // "地区"（tag_type 中文名）
  value: string; // "北京市"（tag_value 原文）
  confidence: number; // 0-1
  source_display: string; // "从问题中识别" | "从上游岗位分析反哺" | "从追加问题补充"
}

interface SubQueryCard {
  // 内部 id（与 RetrievalPlan.sub_queries[*].query_id 一致）
  query_id: string;

  // 展示编号（① ② ③ …）
  display_index: string;

  // 卡片标题（面向用户）
  title: string;
  // 例：「查询北京市直播电商相关岗位」

  // 目的（中文，非 purpose code）
  purpose_display: string;
  // 例："岗位需求分析"

  // 数据通道中文
  channel_display: string;
  // 例："结构化数据" | "文档知识"

  // 领域中文
  domain_display: string;
  // 例："岗位需求" | "产业政策"

  // 依赖关系用自然语言表达（Q3 决策：不画图，只文字）
  depends_on_display: string[];
  // 例：["需要先完成 ① 岗位分析"]

  // 过滤条件（不暴露 tag_type code、match_strategy 表达式）
  filter_summary: DisplayFilter[];

  // 状态
  status: SubQueryStatus;
  status_display: string; // 中文
  degraded_reasons: string[]; // 若 degraded，说明降级原因

  // 完成后填充
  result_summary?: SubQueryResult;

  // 可用交互
  actions_available: SubQueryAction[];
}

type SubQueryStatus =
  | "pending" // 待执行
  | "running" // 执行中
  | "completed" // 已完成
  | "blocked" // 被上游阻塞
  | "degraded" // 降级完成（部分维度未生效）
  | "failed" // 失败
  | "skipped"; // 用户主动跳过

interface DisplayFilter {
  label: string; // "地区" / "行业" / "职业" / ...
  values: string[]; // ["北京市"]
  match_strategy_display: string;
  // 例："精确匹配" / "精确或语义匹配" / "语义匹配"

  is_optional: boolean;
  // true → UI 显示"可选（未识别时跳过）"

  is_from_binding?: boolean;
  // true → UI 显示"来自 ① 岗位分析"

  binding_source_display?: string;
  // 例："来自 ① 岗位分析"
}

interface SubQueryResult {
  hit_count: number;
  hit_count_display: string; // "8 条证据" / "156 条记录"
  duration_ms: number;
  duration_display: string; // "620 ms"

  // 匹配层分布用中文表达
  match_layer_summary: string;
  // 例："精确匹配 60% / 归一化 25% / 语义 15%"

  evidence_strength: "strong" | "medium" | "weak";
  evidence_strength_display: string;
  // 例："证据强度：强"

  // warnings 以 badge 展示
  warnings: string[];
  // 例：["行业维度部分走语义匹配"]
}

type SubQueryAction =
  | "rerun" // 重跑本节点
  | "cancel" // 取消
  | "skip" // 跳过（若 optional）
  | "view_details" // 查看证据详情（打开侧栏）
  | "view_raw"; // 查看原始 sub_query JSON

interface OverallSummary {
  total_sub_queries: number;
  max_depth: number; // DAG 深度
  estimated_duration_ms: number | null; // 允许 null
  combine_summary: string;
  // 例："所有维度均需匹配（AND）" / "任一维度匹配即可（OR）"
}
```

### 4.2 生成时机

- **意图识别完成后**：生成 `friendly_view.intent_summary`，emit 事件 `intent_recognized`。
- **计划生成完成后**：生成 `sub_query_cards`（所有 status="pending"），emit `plan_generated`。
- **每 sub_query 状态变化时**：更新对应卡片 `status` + `result_summary`，emit `sub_query_updated`。
- **全部完成后**：emit `summary_ready` 附带最终 Markdown。

### 4.3 生成规则（orchestrator 侧）

**中文映射源**：

- `tag_type` → 中文 label：读 `tag_taxonomy.TAG_TAXONOMY_V1_3.types[*].name`（region → "地区"）。
- `domain` → 中文 label：读 `retrieval/domain_registry.py` 中新增字段 `QueryProfile.display_name`。
- `match_strategy` → 中文：内置映射表（`l1|l1.5` → "精确匹配"、`l1|l1.5|l4` → "精确或语义匹配"、`l4` → "语义匹配"）。
- `purpose` → 中文：内置映射表（`background_evidence` → "政策背景依据"、`aggregation` → "统计聚合"、`ability_expansion` → "能力扩展"等）。
- `channel` → 中文：`structured` → "结构化数据"、`unstructured` → "文档知识"、`hybrid` → "混合"。

**depends_on 语句拼装**：

- 单一依赖：`需要先完成 ① 岗位分析`。
- 多依赖：`需要先完成 ① 岗位分析和 ② 能力分析`。

**binding 描述**：

- 若 filter 的 tag 值来自 binding_map，`is_from_binding=true` 且 `binding_source_display="来自 ① 岗位分析"`。
- UI 中该 filter 展示为"职业（来自 ① 岗位分析）：直播运营、短视频运营 · 语义匹配"。

**status_display 表**：

| status      | 中文               |
| ----------- | ------------------ |
| `pending`   | 等待执行           |
| `running`   | 执行中             |
| `completed` | 已完成             |
| `blocked`   | 等待前置节点完成   |
| `degraded`  | 已完成（部分降级） |
| `failed`    | 失败               |
| `skipped`   | 已跳过             |

**degraded_reasons 表**（对齐 tag_filter reliability matrix §2 warning 语义）：

| warning code                | UI 展示                            |
| --------------------------- | ---------------------------------- |
| `intent_produced_no_tags`   | "问题维度未识别，走全文兜底"       |
| `binding_resolution_failed` | "从上游结果反哺失败，该维度已跳过" |
| `optional_filter_skipped`   | "'能力'维度未识别，已跳过"         |
| `target_ids_truncated`      | "命中过多，已截断到 Top 10000"     |
| `embedding_lag_bypass`      | "语义索引未就绪，已降级为精确匹配" |
| `tag_asset_index_not_ready` | "跨资产索引未就绪，走全文兜底"     |

---

## 5. SSE 事件契约

后端 `orchestrator.emit_events()` 按检索流生命周期推送。每事件带 `event_seq`（严格递增）以支持断连重连增量拉取。

```
data: {"event_seq": 1, "event": "intent_started"}
data: {"event_seq": 2, "event": "intent_recognized",
       "friendly_view": {"intent_summary": {...}}}
data: {"event_seq": 3, "event": "plan_started"}
data: {"event_seq": 4, "event": "plan_generated",
       "friendly_view": {"intent_summary": {...},
                         "sub_query_cards": [...全量, 均 pending...],
                         "overall": {...}}}
data: {"event_seq": 5, "event": "sub_query_updated",
       "query_id": "q_policy",
       "card_delta": {"status": "running"}}
data: {"event_seq": 6, "event": "sub_query_updated",
       "query_id": "q_policy",
       "card_delta": {"status": "completed",
                      "result_summary": {...}}}
data: {"event_seq": 7, "event": "sub_query_updated",
       "query_id": "q_ability",
       "card_delta": {"status": "degraded",
                      "degraded_reasons": ["optional_filter_skipped"]}}
data: {"event_seq": 8, "event": "summary_ready",
       "markdown": "...",
       "source_refs": [...]}
data: {"event_seq": 9, "event": "done"}
```

**契约要点**：

- `card_delta` 只带**变化字段**（不重发全量卡片）。
- 前端维护本地卡片 map，按 `query_id` 应用 delta。
- 断连重连时前端携带最后收到的 `event_seq`，后端按 `event_seq > N` 补发（保留最近 300 秒的事件缓存）。
- 断连超过缓存窗口 → fallback 到轮询完整 `RetrievalContextPack`。

---

## 6. 卡片渲染示意

以复杂场景"北京市直播电商产业布局 → 电子商务专业建设方案"为例：

```
┌─────────────────────────────────────────────────────────────┐
│ 我理解你要查询的是：                                        │
│  「北京市直播电商产业规划，涉及岗位需求、教材与专业布点」   │
│                                                             │
│ 涉及领域：产业政策 · 岗位需求 · 专业布点                    │
│                                                             │
│ 识别到的约束：                                              │
│  [地区: 北京市 (94%)]  [行业: 直播电商 (90%)]                │
│  [时间: 2024-2026]     ⚠️ 未识别: "职业院校"                 │
│                                                             │
│ 意图置信度：高 ✓        [编辑问题] [重新识别]                │
└─────────────────────────────────────────────────────────────┘

将分成 5 个步骤检索（预计需要 6-10 秒）· 所有维度均需匹配（AND）：

┌─────────────────────────────────────────────────────────────┐
│ ① 查询北京市直播电商产业政策                                │
│    数据来源：产业政策文档                                   │
│    过滤：地区=北京市（精确匹配） · 行业=直播电商（精确匹配）│
│                                                             │
│    ✓ 已完成 · 8 条证据 · 400ms · 证据强度：强               │
│                                        [查看证据] [重跑]    │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ ② 分析北京市直播电商岗位需求                                │
│    数据来源：结构化数据（岗位需求）                         │
│    过滤：地区=北京市 · 行业=直播电商（精确或语义匹配）      │
│    按 岗位 分组 · 取 Top 10                                 │
│                                                             │
│    ✓ 已完成 · 156 条记录 · 620ms · 证据强度：强             │
│    ⚠️ 行业维度部分走语义匹配（精确 60% / 归一化 25% / 语义 15%）│
│                                        [查看证据] [重跑]    │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ ③ 展开岗位对应的能力项  (需要先完成 ② 岗位分析)             │
│    数据来源：结构化数据（职业能力分析）                     │
│    过滤：职业（来自 ② 岗位分析）=直播运营, 短视频运营 · 语义匹配 │
│                                                             │
│    ⏳ 执行中                                                │
│                                        [查看进度] [取消]    │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ ④ 查询北京市专业布点                                        │
│    数据来源：结构化数据（专业布点）                         │
│    过滤：地区=北京市（精确匹配）                             │
│    按 专业, 年份 分组                                       │
│                                                             │
│    ✓ 已完成 · 32 条记录 · 180ms · 证据强度：强              │
│                                        [查看证据]           │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ ⑤ 查询支撑能力项的教材内容  (需要先完成 ③ 能力扩展)         │
│    数据来源：文档知识（课程教材）                           │
│    过滤：能力（来自 ③ 能力扩展） · 语义匹配                 │
│                                                             │
│    ⏸ 等待前置节点完成                                      │
└─────────────────────────────────────────────────────────────┘

──────────────────  以下为最终汇总  ──────────────────

[渲染后端返回的 evidence_chain Markdown]
```

**关键呈现规则**：

- 依赖关系用"（需要先完成 ② 岗位分析）"直接写在卡片标题旁，**不画箭头**（Q3 决策）。
- filter 值中"来自 ② 岗位分析"式标签替代 `binding_map` 表达式。
- warning 用 ⚠️ 图标 + 一行说明，不折叠。
- 匹配层分布用中文百分比表达，替代 L1/L1.5/L4 code。

---

## 7. 前端组件设计

**组件树**（React + Antd 5，遵循 `nexus-console/CLAUDE.md`）：

```
<SearchPlayground>              现有组件，改为渲染单一对话流
├─ <QueryInput>                  用户问题输入
├─ <ConversationStream>          单一对话流（v1.3 R3-c 决策）
│  ├─ <IntentSummaryCard>        意图卡
│  │  ├─ <ConstraintChip>*       识别到的约束（chip）
│  │  ├─ <UnresolvedTermChip>*
│  │  └─ <InlineDetailsCollapse> "展开详情" 折叠区：<RawIntentJson>
│  ├─ <ExecutionCards>           执行步骤卡片列表
│  │  └─ <SubQueryCard>*         单个 sub_query 卡片
│  │     ├─ <FilterSummaryChip>*
│  │     ├─ <StatusBadge>
│  │     ├─ <ResultSummary>?     完成后显示
│  │     └─ <InlineDetailsCollapse> "展开详情" 折叠区：
│  │        ├─ <SourceRefsList>  该 sub_query 命中的 source_refs
│  │        ├─ <MatchLayerBar>   匹配层分布小图
│  │        ├─ <WarningsList>    warnings 详情
│  │        └─ <RawSubQueryJson> 原始 sub_query JSON
│  ├─ <SummaryMarkdown>          最终 Markdown 汇总（evidence_chain 结构）
│  ├─ <TraceFooter>              底部小 footer：trace_id · [导出证据]
│  └─ <FollowupInput>            追加问题
```

**关键组件契约**：

- **零抽屉、零侧栏、零 modal**——所有工程/审计细节走 `<InlineDetailsCollapse>` 在卡片自身高度内展开。
- `SubQueryCard.props`：`card: SubQueryCard`（`FriendlyRetrievalPlanView.sub_query_cards[i]`）+ `onAction: (action, query_id) => void`。
- `<InlineDetailsCollapse>`：Antd `<Collapse>` 或自研折叠组件；默认关闭；点击标题切换；展开动画在卡片自身高度内完成，不推动下方卡片布局跳动（用 `absolute` 定位 + 撑高卡片）。
- 状态变化通过 SSE 增量更新卡片；使用 React `useReducer` 管理 `Map<query_id, SubQueryCard>`。
- 断连自动 fallback 到轮询，界面无缝切换（用户不感知）。

**类型定义位置**：

- 后端：`nexus-app/nexus_app/retrieval/schemas.py`（`FriendlyRetrievalPlanView` 等 Pydantic）。
- 前端：`nexus-console/app/search/_lib/friendlyPlanTypes.ts`（TypeScript 类型，从后端 schema 派生保持一致）。
- **契约**：schema 变更走 v1.3 主文档更新流程；两侧类型定义需同步。

---

## 8. 交互动作

### 用户在意图卡上可做

- **重新识别**：重新触发 `IntentRecognitionService`（保留原问题）。
- **编辑问题**：回到 QueryInput 修改并重新提交。
- **补充约束**（P1）：手动追加未识别的维度（例如手动指定"限定近 3 年"）。

### 用户在 sub_query 卡片上可做

- **展开详情**（内嵌折叠）：在卡片自身高度内展开 source_refs 列表、匹配层分布小图、warnings 详情、原始 sub_query JSON；再次点击收起。
- **重跑**：重新执行该 sub_query（用于降级或失败后的重试）。
- **取消**（仅 running 状态）：中止当前节点。
- **跳过**（仅 optional 且 pending 状态）：跳过该节点，不影响其他分支。

### 用户在汇总下方可做

- **追加问题**：延续对话，将新问题作为下一轮检索（保留历史上下文）。
- **导出**（P1）：将本轮 Markdown 结果 + source_refs 导出。

---

## 9. 落地节奏

| 阶段                  | 交付物                                                                                                                                                   | 前置                                                |
| --------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------- |
| **M-C P0**            | 后端 orchestrator 生成 `friendly_view`；前端 `SearchPlayground` 单一对话流改造 + `IntentSummaryCard` + `SubQueryCard` 渲染（同步完成后一次呈现，无 SSE） | M-B 完成（tag_asset_index 落地 + DAG orchestrator） |
| **M-C P1**            | SSE 事件流后端 emit + 前端 EventSource 订阅；卡片状态增量更新；断连 fallback 到轮询                                                                      | M-C P0                                              |
| **M-C P2**            | 每卡片 `<InlineDetailsCollapse>` 内嵌折叠详情；用户交互（跳过某维度 / 重跑单节点 / 手动补充约束）                                                        | M-C P1                                              |
| **M-D**（观察后决定） | DAG 拓扑图形化（若用户反馈自然语言表达仍不够直观）                                                                                                       | M-C P2                                              |

---

## 10. 与 v1.3 主文档的关系

- **v1.3 §5.3**：新增 `RetrievalPlan.friendly_view` 字段作为契约（引用本文档细节）。
- **v1.3 §10**（原 §9）：R3-c 决策改为**单一对话流**（取消 R3-b 的二区抽屉方案）；执行步骤内嵌为对话流的时间线卡片；工程/审计细节按需通过卡片 `<InlineDetailsCollapse>` 展开。
- **v1.3 §12.2 P1**：Console 相关工作项拆分到本设计的 M-C P0/P1/P2 三层。
- **v1.3 §16.7**（新增）：R3 修订说明段追加本设计要点；R3-c 决策以本文档为准。

---

## 11. 待确认（后续讨论项）

1. **意图澄清入口的位置**：当 `confidence_level=low` 时，是内联展示澄清建议（意图卡下方）还是弹出对话框？倾向内联。
2. **卡片"重跑"是否允许在 `completed` 状态触发**：允许则用户可"不满意结果重跑"；不允许则仅 failed/degraded 可重跑。倾向允许（业务用户可能不满意结果想重试）。
3. **意图卡的"编辑问题"**：编辑后是否清空所有历史卡片？还是保留作为对话线索？倾向"作为新一轮问题追加，历史保留"。
4. **卡片"展开详情"是否需要权限**：调试信息（trace_id / raw JSON）是否所有 caller 都能看？还是仅"admin"角色？倾向所有 caller 可见（对齐 v1.0 §10 权限 P0 暂不启用）。
5. **卡片编号形式**：①②③ 圆圈数字 vs 1./2./3. 阿拉伯 vs 无编号。倾向圆圈数字（视觉清晰、"来自 ② 岗位分析"更自然）。
6. **多轮对话历史**：追加问题时，前一轮的意图卡与 sub_query 卡片是否折叠？倾向"折叠为一行摘要，可点击展开"。
7. **`<InlineDetailsCollapse>` 展开时的滚动行为**：展开后是否自动 `scrollIntoView` 把展开区滚到可视区顶部？倾向自动滚（避免用户看不到刚展开的内容）。

---

## 12. 结论

本设计通过 `FriendlyRetrievalPlanView` 契约把 v1.3 的复杂 tag_filter / binding_map / depends_on 结构翻译为业务用户可读的中文卡片列表；通过**单一对话流 + 卡片内嵌折叠**（R3-c 决策）在一个滚动区内呈现"意图理解 → 执行步骤进度 → 最终汇总"，工程/审计细节按需卡片内展开，不分割独立区/抽屉/侧栏。通过 SSE 事件契约支持"意图 → 计划 → 执行 → 汇总"全流程增量呈现。落地按 M-C 三阶段推进，与 tag_filter 稳定性设计（`docs/tag_filter_reliability_matrix_v1.md`）配套构成 v1.3-P1 前后端整体交付图。
