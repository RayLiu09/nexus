# RAG 语义块构建实施计划

- **状态**：待实施（pending）
- **日期**：2026-06-22
- **关联设计**：`docs/blocks_to_rag_chunks_optimization.md`（§15 优化方案）
- **关联代码**：
  - `nexus-app/nexus_app/knowledge/services.py::run_knowledge_pipeline`
  - `nexus-app/nexus_app/knowledge/chunk_builder.py::_aggregate_locator`（已实现 locator 聚合骨架）
  - `nexus-app/nexus_app/models.py::KnowledgeChunk.locator / source_block_ids`
  - `nexus-console/app/assets/[assetId]/_components/SourcePreviewSection.tsx`（已支持 markdown 预览）

---

## 一、目标

把 `normalized_ref.blocks`（版面单元）转换成 `KnowledgeChunk`（RAG 语义单元）时，**每个 chunk 必须携带可回到源文档的位置定位**，使下游能在 chunk 预览模式中：

1. 高亮 chunk 在源文档 markdown 中的字符范围（`md_char_range` span）。
2. 跳转到 chunk 所在 PDF 页（`page_start` / `page_end`），按 bbox 在页面截图上画框。
3. 列出 chunk 由哪些原始 blocks 派生（`source_block_ids`）。
4. 显示 chunk 所处的章节路径（`heading_path`），让用户知道"我在文档哪里"。

---

## 二、Chunk 位置定位契约（强制字段）

### 2.1 数据结构

`KnowledgeChunk` 表已具备的字段（**沿用，不新增列**）：

| 字段               | 类型             | 用途                                      |
| ------------------ | ---------------- | ----------------------------------------- |
| `source_block_ids` | `JSON list[str]` | chunk 由哪些原始 blocks 派生（N→1，必填） |
| `locator`          | `JSON dict`      | 聚合后的物理位置（必填，contract 见下）   |
| `chunk_metadata`   | `JSON dict`      | 其他 chunk 级元数据（可选）               |

`locator` 的 schema 升级为：

```jsonc
{
  // 已有字段（chunk_builder._aggregate_locator 已经产出）
  "page_start": 50, // 起始页（0-based 或 1-based 与现状保持一致）
  "page_end": 50, // 结束页（跨页时不等于 page_start）
  "bbox_union": [82, 234, 510, 723], // 所有源 block bbox 的并集（PDF 点坐标）
  "blocks": [
    // 每个源 block 的 page + bbox 明细
    { "block_id": "block-p50-166", "page": 50, "bbox": [82, 234, 510, 723] },
  ],

  // 新增字段（本方案要求）
  "md_char_range": [22634, 29763], // chunk 内容在 body_markdown 中的字符范围。
  // 对合并/拆分类 chunk 是合成范围（见 §三）
  "md_spans": [
    // 合并/拆分类 chunk 的分段范围数组
    { "start": 22634, "end": 22713, "block_id": "block-p50-166" },
    { "start": 22730, "end": 22890, "block_id": "block-p51-167" },
  ],
  "heading_path": [
    // 章节路径（叶子最后）
    { "level": 1, "title": "第三章 直播电商行业规范化治理" },
    { "level": 2, "title": "第一节 国家政策框架日趋完善" },
    { "level": 3, "title": "一、国家层面" },
  ],
  "caption": "表 3-1 2020 年 11 月至 2025 年 12 月直播电商相关政策一览表", // 图表 chunk 才有
  "row_index": 7, // table-row chunk 才有（0-based）
  "row_total": 47, // table-row chunk 才有
  "anchor_role": "body", // body / table_row / table_overview / chart / image / figure_attribution
}
```

字段 **必填要求**：

| chunk 来源                              | page_start | page_end |   bbox_union    |   blocks   |   md_char_range   | md_spans | heading_path |
| --------------------------------------- | :--------: | :------: | :-------------: | :--------: | :---------------: | :------: | :----------: |
| 单 block 派生                           |     ✓      |    ✓     |        ✓        |     ✓      |         ✓         |    —     |      ✓       |
| 多 block 合并                           |     ✓      |    ✓     |    ✓（并集）    |     ✓      |    ✓（minmax）    |    ✓     |      ✓       |
| 大 table 行拆分                         |     ✓      |    ✓     | ✓（行 y-slice） | ✓（=父表） | ✓（行 md 子范围） |    —     |      ✓       |
| 跨 block 派生但无版面对应（如全文摘要） |     ✓      |    ✓     |        —        |     ✓      |         —         |    —     |      ✓       |

**契约不变量**：

- `body_markdown[md_char_range[0]:md_char_range[1]]` 必须能定位到一段连续 / 半连续文本（拆分行除外）。
- `bbox_union` 必须覆盖 `blocks[*].bbox` 的并集。
- `page_start ≤ page_end`，且二者都在 `[0, pdf_info.page_count)` 范围内。
- `heading_path` 至少含一条（无任何 heading 上下文时为 `[]`，但仍保留字段以便序列化稳定）。

### 2.2 与 `body_markdown` 的对齐

不修改 `body_markdown`、不在其中注入锚点（遵循 `feedback_md_char_range_out_of_band` 内存规则）。

预览模式靠：

- **markdown 视图**：用 `md_char_range` 在 `SourcePreviewSection` 中包一层 `<mark>`。
- **PDF/页面图视图**：用 `page_*` + `bbox_*` 在页面截图上画矩形高亮（`pypdfium2` 已是 P0 依赖，渲染 PDF 页可服务端跑或前端用 PDF.js）。

---

## 三、blocks → 语义 chunk 的算子如何产 locator

5 个算子（来自 `blocks_to_rag_chunks_optimization.md` §三.1）各自的 locator 产出规则：

### 3.1 `extract_document_metadata`（不产 chunk）

- 把命中的 metadata blocks 标 `role=document_metadata`，不产 chunk 候选。
- 写入 `normalized_ref.document_metadata`，并记录 `source_block_ids`（让前端能从 metadata 反查源 block）。

### 3.2 `drop_navigational`（不产 chunk）

- heading 块不独立成 chunk；但保留 heading 文本作为后续 chunk 的 `heading_path` 上下文。
- TOC 块（§12 已抽到 `payload.toc`）已不产 chunk。

### 3.3 `attach_attribution`（产融合 chunk）

合并规则：`数据来源：xxx` / `图 1-2`等附属短段 → 合入紧邻的 chart/image/table chunk。

locator 处理：

```python
parent_chunk.source_block_ids.append(attribution_block.block_id)
parent_chunk.locator["blocks"].append({...attribution block bbox...})
parent_chunk.locator["bbox_union"] = bbox_union(parent + attribution)
parent_chunk.locator["page_end"] = max(parent.page_end, attribution.page)
parent_chunk.locator["md_spans"].append({
    "start": attribution.md_char_range[0],
    "end":   attribution.md_char_range[1],
    "block_id": attribution.block_id,
})
parent_chunk.locator["md_char_range"] = [
    min(span.start for span in md_spans),
    max(span.end for span in md_spans),
]
```

### 3.4 `merge_continuation`（产合并 chunk）

跨段同主题论证合并：

- 取被合并 blocks 的 `source_block_ids` 并集；
- `bbox_union` = blocks 的 bbox 并集；
- `page_start` = min(page)，`page_end` = max(page)；
- `md_char_range` = minmax(blocks[*].md_char_range)；
- `md_spans` 列出每个被合块的子范围，便于前端逐段高亮。

### 3.5 `decompose_atomic`（产行级 chunk + 概览 chunk）

对大 table 块按行拆分。挑战：MinerU 给的是**整表**的 bbox，没有每行 bbox。

**行级 chunk locator 派生**：

```python
parent_bbox  = table_block.bbox                  # [x0, y0, x1, y1]
parent_pages = table_block.per_page_bboxes       # {50: bbox, 51: bbox, ...}（§13 已加）
parent_md_range = table_block.md_char_range       # 整表在 body_markdown 中的范围
md_lines     = body_markdown[parent_md_range[0]:parent_md_range[1]].splitlines()
data_rows    = [(i, line) for i, line in enumerate(md_lines) if is_data_row(line)]

# 1. md_char_range per row: exact, since each row is its own markdown line
row_md_start = parent_md_range[0] + sum(len(l)+1 for l, _ in md_lines[:row_line_idx])
row_md_end   = row_md_start + len(row_line)

# 2. page mapping: hit the per_page_bboxes interval containing this row's y
#    fallback approach: distribute rows uniformly across pages by row count
#    refined approach: when we have per_page_bboxes + rows-per-page hint from
#    MinerU's per-page table block, route exactly
row_page = pick_page_for_row(row_line_idx, total_rows, parent_pages)

# 3. bbox y-slice within row_page
page_bbox = parent_pages.get(row_page, parent_bbox)
y0_page, y1_page = page_bbox[1], page_bbox[3]
rows_on_page = sum(1 for r in data_rows if pick_page_for_row(...) == row_page)
row_position_in_page = (row_line_idx among rows on this page)
row_y_slice = y0_page + (y1_page - y0_page) * row_position_in_page / rows_on_page
row_bbox = [page_bbox[0], row_y_slice, page_bbox[2], row_y_slice + row_height]
```

行级 chunk 的最终 locator：

```jsonc
{
  "page_start": row_page,
  "page_end":   row_page,
  "bbox_union": row_bbox,                       // 估算，标 anchor_role=table_row 提示精度有限
  "blocks": [{"block_id": parent_table.block_id, "page": row_page, "bbox": row_bbox}],
  "md_char_range": [row_md_start, row_md_end],  // 精确
  "heading_path": <parent heading_path>,
  "caption": parent_table.caption,
  "row_index": row_line_idx_in_data_rows,
  "row_total": total_data_rows,
  "anchor_role": "table_row"
}
```

**source_block_ids 始终包含父表 block_id**，便于回溯：

```python
chunk.source_block_ids = [parent_table.block_id]
```

**概览 chunk locator**：与父表整体相同（page_start = parent.page_start，bbox_union = parent.bbox，anchor_role=`table_overview`）。

### 3.6 `enrich_context`（不产新 chunk，丰富已产 chunk）

- 注入 `heading_path`：从当前 chunk 向前回溯，取最近的 h1/h2/h3 链。
- 注入 `caption`：当 chunk 来自 chart/image/table 时。
- 注入 in-vector context prefix（可选，§16 待决策项 #3）：
  ```
  [第三章 第一节 → 表 3-1 政策一览表 | 行 7/47] 2021.04 | 国家网信办 | ...
  ```
  该前缀**只入 embedding，不污染 chunk.content**（chunk.content 保留原文；前缀作为 embedding 阶段的 `content_for_embedding` 单独构建）。

---

## 四、Chunk 预览 API 与前端

### 4.1 后端 API

新增 internal 端点（控制台调用）：

```
GET  /internal/v1/knowledge-chunks/{chunk_id}/preview
→ {
    "chunk_id": "...",
    "normalized_ref_id": "...",
    "content": "<chunk 原文>",
    "anchor_role": "table_row",
    "heading_path": [...],
    "caption": "...",
    "row_index": 7, "row_total": 47,
    "locator": { md_char_range, md_spans, page_start, page_end, bbox_union, blocks },
    "source_blocks": [
      {"block_id": "block-p50-166",
       "type": "table",
       "page": 50,
       "bbox": [82, 234, 510, 723],
       "preview_uri": "/internal/v1/normalized-refs/.../page-image/50?bbox=82,234,510,723"}
    ],
    "body_markdown_excerpt": "<md_char_range 附近 ±N 字符的预览>"
  }

GET  /internal/v1/normalized-refs/{ref_id}/page-image/{page_idx}?bbox=x0,y0,x1,y1
→ image/jpeg  (PDF 页渲染图，可选画高亮框)
```

`page-image` 用现有 `pypdfium2` 渲染器（`stages._make_pdf_renderer` 已有，复用），可加 PIL 画框：

```python
def render_page_with_highlight(pdf, page_idx, bbox=None):
    page = pdf[page_idx]
    pil = page.render(scale=2).to_pil()
    if bbox:
        from PIL import ImageDraw
        draw = ImageDraw.Draw(pil)
        draw.rectangle([x*2 for x in bbox], outline="red", width=3)
    return jpeg(pil)
```

### 4.2 前端 chunk 预览 UI

**新页面 / 抽屉**：`/assets/[assetId]?chunk={chunkId}` 或资产详情页右侧抽屉。

布局（参考已有 `SourcePreviewSection`）：

```
┌──────────────────────────────────────────────────────────────┐
│  [≡] 章节路径： 第三章 / 第一节 / 表 3-1 政策一览表 → 行 7/47  │
├────────────────────────┬─────────────────────────────────────┤
│                        │                                     │
│   Markdown 视图         │   PDF 页视图                         │
│   （body_markdown 滚到  │   （page 50，bbox 高亮框）            │
│    md_char_range，      │                                     │
│    <mark> 高亮）        │                                     │
│                        │                                     │
├────────────────────────┴─────────────────────────────────────┤
│  Chunk 原文（chunk.content）：                                │
│  2021.04 | 国家网信办等七部门 | 《网络直播营销管理办法（试行）》 │
│  | 直播营销平台应当建立健全...                                  │
├──────────────────────────────────────────────────────────────┤
│  源 blocks：                                                  │
│    • block-p50-166 (table, p.50, bbox=...)  [跳转]            │
└──────────────────────────────────────────────────────────────┘
```

- **左：markdown 视图** — 复用 `SourcePreviewSection`，新增 `highlightRange={chunk.locator.md_char_range}` prop，渲染时把命中字符包 `<mark>`，自动滚到位置。
- **右：PDF 页视图** — 调 `/page-image/{page_idx}?bbox=...` 显示图（含红框），翻页器支持跨页 chunk。
- **底**：chunk 原文 + 源 block 列表（点击逐 block 跳转 markdown）。

API 与组件已具备的基础：

- `pypdfium2 + Pillow`（`pyproject.toml` 中已有，§13 引入）。
- `SourcePreviewSection.tsx` 已渲染 body_markdown。
- 资产详情页 tabs 已有"原文预览"。

新加：

- 资产详情新增 tab "知识块"，列 chunks（按章节分组），点击展开预览。
- 预览组件 `ChunkPreviewDrawer.tsx`。

---

## 五、实施切片（按依赖排序）

### 切片 0 —— 数据 schema 增量（最小）

- 不动 `KnowledgeChunk` 表结构。
- 升级 `chunk.locator` schema 为 §二.1 形态，向前兼容（旧 chunk 没有新增字段时按 fallback 处理）。
- 在 `chunk_metadata` 里维持 `anchor_role` 字段（不进入 locator 命名空间，避免歧义）。
- 工作量：~1 天。

### 切片 1 —— `document_metadata` 抽取 + ref 新列

- `nexus-app/alembic/versions/...add_document_metadata.py`：`ALTER TABLE normalized_asset_ref ADD COLUMN document_metadata JSON NULL`。
- `nexus_app/normalize/document_metadata_extractor.py`：从 blocks 抽取（rule-based v1）。
- `stages.run_normalize_document` 末尾调用 extractor 写入。
- 命中的 blocks 在 `chunk_metadata` 上打 `role=document_metadata`，转换层据此跳过。
- 工作量：~2 天（含单测）。

### 切片 2 —— 语义重组层骨架（5 个算子，不含 table 拆分）

- 新模块 `nexus_app/knowledge/semantic_repack.py`：
  - `drop_navigational(blocks) → blocks`
  - `attach_attribution(blocks) → blocks`（合并）
  - `merge_continuation(blocks) → blocks`（按 heading 父节点 + 续段信号合并）
  - `enrich_context(chunks) → chunks`（注入 heading_path / caption）
- 改 `run_knowledge_pipeline`：`blocks → semantic_repack → KT chunking_strategy → chunks`。
- chunk_builder.\_aggregate_locator 扩展为 §三 的契约（md_spans / heading_path / anchor_role）。
- 测试：用样本资产 blocks 跑一遍，断言 chunk 数量符合预期、locator 字段完整。
- 工作量：~3 天。

### 切片 3 —— `decompose_atomic` 大 table 行拆分

- `semantic_repack.decompose_atomic(blocks) → blocks`（拆 markdown table → 行级伪 blocks + 概览伪 block）。
- 行级 chunk locator 派生算法（§三.5）。
- 路由：industry_research_kb / structured_record_table 默认启用；其他 KT 通过 KT 配置 `decompose_table=true` 开启。
- 测试：样本表 3-1（47 行）拆出 48 chunks（47 行 + 1 概览），每个 chunk locator 通过契约校验。
- 工作量：~3 天。

### 切片 4 —— 后端 chunk 预览 API

- `nexus_api/api/internal/normalized_refs.py` 增 `/page-image/{page_idx}?bbox=...` 端点。
- `nexus_api/api/internal/knowledge_chunks.py` 增 `/preview` 端点。
- pypdfium2 + PIL 渲染并画框（复用 `_make_pdf_renderer`）。
- 测试：调样本资产某 chunk_id 的 preview，断言返回结构 + image bytes 非空。
- 工作量：~2 天。

### 切片 5 —— 前端 chunk 预览 UI

- 资产详情页新增 "知识块" tab：列 chunks（按 heading_path 分组），分页/筛选（按 KT）。
- 新组件 `ChunkPreviewDrawer.tsx`：左右双栏（markdown 高亮 + PDF 页带框）。
- 复用 `SourcePreviewSection` 加 `highlightRange` 支持。
- 工作量：~3 天。

### 切片 6 —— 重 normalize 样本验证

- 触发样本资产 4abe6b71 重 normalize（含 §13 索引）。
- 验收清单：
  - chunks 数量从 1 → ~150–300（heading 不入、attribution 合并、表行拆开）。
  - 每个 chunk 含完整 locator。
  - 控制台资产详情"知识块" tab 可看 / 可预览 / 可定位。
- 工作量：~1 天（含改 bug 缓冲）。

### 切片 7 —— chunks 表治理阶段 1（partial index）

- 与 §15.2 阶段 1 同步：`CREATE INDEX ... WHERE embedding_status='pending'`。
- 不影响 §17 本身，独立运维准备。
- 工作量：~0.5 天。

**总工时估算：~14.5 工作日**，可按切片并行。

---

## 六、测试矩阵

| 维度           |            切片 1            |                    2                    |                     3                     |           4           |      5      |      6       |
| -------------- | :--------------------------: | :-------------------------------------: | :---------------------------------------: | :-------------------: | :---------: | :----------: |
| 单元测试       |        extractor 规则        |               5 算子各自                |           表拆分 + locator 派生           |     API contract      |  组件渲染   |      —       |
| 集成测试       |       normalize stage        |       run_knowledge_pipeline e2e        |                   同 2                    |           —           |      —      | 样本资产 e2e |
| 契约不变量校验 | document_metadata 字段必填集 | locator 必填集 + body_markdown 字节稳定 | 同 2 + 行 md_char_range 与父表 range 一致 | page-image 输出可解码 | a11y / 焦点 |      —       |
| 回归           |      normalize 全套不变      |         knowledge_pipeline 全套         |                  KT 测试                  |     API 现有契约      | 资产详情页  |     全栈     |

---

## 七、关键风险与缓解

| 风险                                         | 影响                          | 缓解                                                                                                              |
| -------------------------------------------- | ----------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| 行级 bbox 派生不精确（无 per-row bbox 数据） | 预览框位置漂移                | UI 标注 `anchor_role=table_row` 时显示"近似定位"；同时 markdown 高亮精确（md_char_range 精确）                    |
| heading_path 抽取错失（多种章节编号方式）    | 检索时上下文不完整            | v1 用启发式（# 数 + 章节关键词），v2 补 LLM 兜底；保留 `heading_path=[]` 不阻塞                                   |
| 重 normalize 旧资产巨量回填                  | DB 负载激增                   | 灰度：先重跑试点 ref，监控 chunk 数量与查询延时；表治理阶段 1 准备好后再大批回填                                  |
| RAGFlow 端旧 chunk 与新 chunk 共存           | 同 doc 多次索引、检索结果重复 | 重 normalize 前先撤旧 doc（`run_index_submit` 前清除该 ref 的 IndexManifest + RAGFlow doc）                       |
| document_metadata 与 chunk_metadata 边界违反 | 文档级信息冗余到每 chunk      | code review 守住；chunk_metadata 禁止出现 title/authors/publish_date/keywords/abstract 等 ref 级字段（lint 规则） |

---

## 八、与已有约束的对齐

| 约束                                                       | 落地                                                                                                                                                  |
| ---------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ARCHITECT.md` Chunk Locator Contract                      | locator schema 是该契约的超集；保留 `blocks[]` / `bbox_union` 不变                                                                                    |
| `feedback_md_char_range_out_of_band`                       | body_markdown 不被改写；md_char_range 仅作为 chunk 上的查询索引                                                                                       |
| Knowledge Pipeline 独立于 Asset Pipeline                   | semantic_repack 全在 Knowledge Pipeline 内；不动 normalize                                                                                            |
| `governance_result` 不可变                                 | 与本方案无交叉                                                                                                                                        |
| AI 输出不替代规则状态                                      | extract_document_metadata v1 纯规则；v2 LLM 兜底也只做"字段抽取"，不改任何治理决策                                                                    |
| `feedback_ingest_validate_thresholds` 类约束（阈值入配置） | `attach_attribution` 的关键词、`decompose_atomic` 的最小行数等阈值入 `config/governance_rules_v2.json` 的 KT 字段或独立 `config/semantic_repack.json` |

---

## 九、待决策项

| #   | 决策点                                                                | 选项                                                                       |
| --- | --------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| 1   | 切片 0–6 是一次性 PR 还是分多 PR                                      | 推荐：切片 1 + 2 + 4 + 5 是一波（含 API + UI），3 单独，6 验证；7 治理独立 |
| 2   | 行级 bbox 精确化是否值得为之扩展 MinerU 调用（要求返回 per-row bbox） | v1 用估算 + 标注；v2 评估精度差再决定                                      |
| 3   | in-vector context prefix（heading_path + caption）是否默认开启        | 推荐默认开启，可在 KT 配置 `embed_prefix=false` 关闭                       |
| 4   | document_metadata 抽取失败时 chunk 是否仍然产出                       | 产出，但 heading_path / caption 可为空                                     |
| 5   | chunk 预览 API 是否需要鉴权                                           | 复用 internal 现有 JWT 即可，不另开放                                      |
| 6   | 重 normalize 历史资产是脚本一键还是 worker 增量                       | 推荐 worker 增量（按 ref 加 retag queue），保护 DB                         |

---

## 十、不在本计划范围

- chunk 召回质量评测（RAG eval 体系单独立项）。
- 跨文档实体关系抽取（KG KT 范围）。
- 向量库替换 / RAGFlow 升级（架构层）。
- chunks 表治理阶段 2 / 3（见 `docs/blocks_to_rag_chunks_optimization.md` §三.2，按规模触发）。

---

## 历史

- 2026-06-22：基于 §14 blocks 分析 + §15 优化方案，制定本实施计划。
