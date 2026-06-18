# 文档解析（Pipeline A）缺陷登记与修复计划

- **状态**：登记中 / 按 1→4 顺序修复
- **日期**：2026-06-18
- **样本资产**：`4abe6b71-9b07-488d-a04f-863fee14ebe7`（《2025 直播电商行业发展白皮书.pdf》v1，唯一可用版本）
- **样本 normalized_ref**：`e17c4a75-b07e-47fe-b3c8-e6d019352250`
- **关联代码**：
  - `nexus-app/nexus_app/pipeline/mineru_converter.py`（MinerU `pdf_info → (blocks, body_markdown)` 1:1 映射）
  - `nexus-app/nexus_app/pipeline/stages.py`（normalize 阶段调用 converter + 写 payload）
  - `nexus-app/nexus_app/normalize/service.py`
  - `nexus-app/nexus_app/image_analysis.py`（VLM 图像描述）
- **关联契约**：
  - `ARCHITECT.md` —「Chunk Locator Contract」、image artifacts 必须落 `parsed/<version_id>/<artifact_id>/images/`
  - `CLAUDE.md` —「md_char_range 必须带外，markdown 字节不变」、normalize 阶段不得在 markdown 中注入锚标记
  - 内存：`feedback_md_char_range_out_of_band.md`

---

## 一、问题清单（按修复顺序）

| #   | 类别                                                      | 命中本样本                               | 严重度 | 影响面                                                        |
| --- | --------------------------------------------------------- | ---------------------------------------- | ------ | ------------------------------------------------------------- |
| 1   | 页眉页脚 / 水印 / 装饰图描述未清洗                        | 是                                       | 高     | 召回噪声、token 浪费、AI 治理输入污染                         |
| 2   | TOC 未独立化 / 未写入 `payload.toc`                       | 本样本未命中（PDF 无目录页），但路径缺失 | 中     | 含目录的 PDF 会在 `body_markdown` 中产生大量"标题+页码"伪片段 |
| 3   | 跨页表格不合并 / 空 table 块未兜底                        | 是                                       | 高     | 表体内容丢失、伪 chunk 入库、问答无法回答表内问题             |
| 4   | 图像 VLM 调用无差异化（QR/Logo 等装饰图被生成英文长描述） | 是                                       | 中     | 单次最多 >1.6KB 噪声入 `body_markdown`                        |

---

## 二、实测证据（基于样本 ref）

### 缺陷 1 · 水印 / QR 描述

`body_markdown` 偏移 1043 起出现 1 处：

```
报告搜一搜

800000+份行业研究报告

长按识别关注公众号

> The image is a QR code (Quick Response Code) — a two-dimensional matrix barcode — with a central logo overlay.
> ... （>1.6 KB 英文 blockquote 描述）
```

- 三行广告文字是 MinerU 把第 4 页广告水印识别为 3 个 `paragraph` 块。
- QR 二维码块由 NEXUS 侧 `image_analyzer` 跑 VLM 生成英文 alt-text，以 markdown blockquote 形式拼回 `body_markdown`，但**未单独存图、未差异化是否值得跑 VLM**。

### 缺陷 2 · TOC 未独立化

- `body_markdown` 中「目录」字样 0 处；典型点引线行 0 行；`payload.toc=[]`。
- 本样本 PDF 无印刷目录页；但 `mineru_converter.convert()` 调用链**完全没有 TOC 提取与字段填充逻辑**，对带目录页的 PDF 等同于把目录行原样塞进 `body_markdown`。

### 缺陷 3 · 跨页表格内容丢失

「表 3-1 2020 年 11 月至 2025 年 12 月直播电商相关政策一览表」实际跨第 50–55 页，MinerU 切出 6 个 `block_type=table` 块：

| 块              | caption                        | image_uris | md_char_range  | content_len |
| --------------- | ------------------------------ | ---------- | -------------- | ----------- |
| `block-p50-166` | 表 3-1 …直播电商相关政策一览表 | 有截图     | [32697, 33075] | 331         |
| `block-p51-167` | —                              | 空         | null           | 0           |
| `block-p52-168` | —                              | 空         | null           | 0           |
| `block-p53-169` | —                              | 空         | null           | 0           |
| `block-p54-170` | —                              | 空         | null           | 0           |
| `block-p55-171` | —                              | 空         | null           | 0           |

- `body_markdown` 中该表只剩 24 行空 `|  |` + 末页 1 行真实内容（`2025.12 | 市场监管总局 | …`）。
- 全文 20 个 table 块里，**14 个**（70%）`caption / image_uris / content` 三项全空，是跨页续页占位。
- 另一处「表 3-1 我国直播电商规范化治理阶段划分及特征」（第 72 页）同样仅 4 行空 pipe + 一段 VLM 给整图生成的英文 blockquote，无任何单元格。

### 缺陷 4 · 图像 VLM 无差异化

- `_handle_visual` 对所有 image / chart 类块默认走 VLM；QR 码与 Logo 类装饰图也产生 >1.6 KB 英文描述。
- 这段描述既不在原文里有出处，也不在治理 / 索引上有价值，纯粹增大 token 与噪声。

---

## 三、根因（按类别）

### 1. 清洗缺口（结构性）

`mineru_converter.convert()` 是无状态 1:1 映射：

```python
body_markdown = "\n\n".join(md_parts)
_annotate_md_ranges(blocks, md_parts)
assert_no_anchor_pollution(body_markdown)
return blocks, body_markdown
```

整条 normalize 流水线**没有**任何环节做：

- 页眉页脚 / 水印 / 装饰图描述的过滤；
- 跨页 footer 高频去重；
- 关键词 / 正则白/黑名单。

### 2. TOC 路径缺失

- `payload.toc` 字段存在但**从未被写入**；
- 没有"识别 TOC 行 → 不入 `body_markdown` → 单独序列化到 `payload.toc`"的步骤；
- MinerU 输出本身有 `outline` / `bookmarks`（PDF metadata 提供时）可作为兜底信号，目前也未读取。

### 3. 跨页表两层根因

a) **MinerU 解析侧**：跨页表续页缺表头，版面/VLM 模型置信度低，抽不到表体；甚至连续页表图截图也未输出。
b) **NEXUS normalize 侧**：缺一个 `block_postprocess`：

- 合并连续 page、同 caption 或 bbox 邻近的 table 块；
- 丢弃 `content` + `image` 双空的 table 块（避免污染 `blocks[]` 与 `md_char_range`）；
- 对"image_only"的合并表保留截图作为兜底，并标记 `parse_quality=image_only` 供下游识别。

### 4. VLM 调用无差异化

`_handle_visual` 不区分图像语义类别（QR / Logo / 装饰条 vs 图表 / 流程图 / 实质截图），全部送 VLM 写描述。

---

## 四、修复计划（顺序与切片）

按 1 → 4 顺序提交，**每个缺陷一个独立 commit + 必要的单元测试**。修复期间保持 `md_char_range` 契约（带外、markdown 字节不被注入）。

### 缺陷 1 · 水印 / 装饰文本清洗（先做）

- 入参：`blocks` + `md_parts` 在 `convert()` 末尾、`_annotate_md_ranges` **之前**执行清洗（保持 1:1）。
- 清洗规则（配置化，落到 `config/normalize_filters.json` 或 `ingest_validate.json` 同一目录）：
  - 关键词命中（默认表：`报告搜一搜`、`扫码`、`长按识别`、`关注公众号`、`800000+份`、`报告下载`…）。
  - 跨页高频 footer（同一行文本在 ≥3 页重复时认定为 footer，整段剔除）。
  - 装饰图 VLM blockquote（命中 QR/Logo 描述特征短语：`This is a QR code`、`logo`、`barcode`…）—此处先按文本特征剔，缺陷 4 再从源头不生成。
- 实现位置：`mineru_converter.py` 新增 `_strip_noise(blocks, md_parts) -> (blocks, md_parts)`。
- 测试：构造含水印段的 `pdf_info` fixture，断言 `body_markdown` 不含水印关键词、`md_char_range` 重排后仍能与 `md_parts[i]` 一致。

### 缺陷 2 · TOC 抽取（第二步）

- 检测：
  - 优先读 MinerU `pdf_info` 中 `outline` / `headings_with_page`（如存在）。
  - 次选启发式：连续 ≥5 行命中 `.{3,}\s*\d+\s*$`（点引线 + 页码）或 `^(第[一二三四五六七八九十]+章|\d+(\.\d+)*)\s+.+\s+\d+\s*$` 的段。
- 命中段从 `md_parts` 移除，整理为 `[{level, title, page}]` 写入 `payload.toc`。
- 实现位置：清洗器之后、`_annotate_md_ranges` 之前。
- 测试：构造含 TOC 的 fixture，断言 `payload.toc` 非空且 `body_markdown` 不再含目录行。

### 缺陷 3 · 跨页表合并（第三步）

- 算法：扫 `blocks[]`，连续若干 `block_type=table` 块若满足
  - 上一块有 caption 且当前块无 caption；
  - 页号连续（diff = 1）；
  - bbox 左右边界相近（差距 ≤ 阈值）；
    则合并 → 单一逻辑 table 块：
  - 合并后 `md_part` 取首块原 markdown + 续块 `content`（若有）；
  - 保留首块 `image_uris`，并把续块 `image_uris` 合并进 `image_uris`（如有）；
  - `bbox` 取并集；`page` 字段改为 `{first, last}` 元组或保留首页。
- 兜底：
  - `content` + `image_uris` + `caption` 三空块 → 丢弃，不入 `blocks[]`、不进 `md_parts[]`。
  - 合并后仍只有 `image_uris` 无文本 → 标 `parse_quality=image_only`，便于下游切块与治理识别。
- 实现位置：`_strip_noise` 之后、TOC 抽取之后、`_annotate_md_ranges` 之前。
- 测试：用样本 ref 的 6 个 table 块构造 fixture，断言合并后 `blocks` 含 1 个 table、`md_char_range` 唯一 / 非空。

### 缺陷 4 · VLM 调用差异化（最后）

- `_handle_visual` 调 VLM 之前先经 `_is_decorative(image_bytes / meta) -> bool`：
  - 命中（QR / 极小图 / 单色 logo / 黑白条形码）→ 不调 VLM、不写 blockquote；可以仍存图但 markdown 中以 `[decorative image: skipped]` 占位（占位文本可配置或留空）。
  - 未命中 → 走原 VLM 描述路径。
- 判别规则：尺寸阈值（< 200×200）、长宽比（≈1:1 + 高频角点检测信号或 MinerU 子类型）、文件名/路径 hint（如 `qr_`, `logo_`）。
- 实现位置：`image_analysis.py` 增加分类入口；`mineru_converter._handle_visual` 调用前置判断。
- 测试：QR fixture → 不调 VLM；图表 fixture → 仍调用 VLM。

---

## 五、跨缺陷不变量

- `md_char_range` 保持带外，且重排后仍满足 `body_markdown[start:end] == md_parts[i]`。
- 不在 markdown 中注入任何锚标记（`feedback_md_char_range_out_of_band.md`）。
- 所有清洗 / 合并 / 丢弃动作必须可观测：写 `parse_artifact` 或 worker 日志，标明丢弃数量与原因。
- 配置化优先：关键词表 / 阈值放配置文件，避免硬编码。

---

## 六、回归与验收

每个缺陷修复后回归本样本 `e17c4a75-…`，期望对比：

| 指标                                                    | 现状 | 缺陷 1 后     | 缺陷 2 后         | 缺陷 3 后           | 缺陷 4 后       |
| ------------------------------------------------------- | ---- | ------------- | ----------------- | ------------------- | --------------- |
| `body_markdown` 含「报告搜一搜」/「长按识别关注公众号」 | 1    | 0             | 0                 | 0                   | 0               |
| `body_markdown` 含 QR VLM blockquote（>1KB）            | 1    | 0（按文本剔） | 0                 | 0                   | 0（源头不生成） |
| `payload.toc` 长度                                      | 0    | 0             | 0（本样本无目录） | 0                   | 0               |
| `blocks[]` 中 type=table 总数                           | 20   | 20            | 20                | ≤ 8（合并 / 丢空）  | 同              |
| `block_type=table` 中 content+image 双空块数            | 14   | 14            | 14                | 0                   | 0               |
| 「表 3-1 …直播电商相关政策一览表」md 中空 pipe 行数     | 24   | 24            | 24                | 0（合并后保留截图） | 0               |

---

## 七、不在本计划范围

- MinerU 模型层升级 / `model_version=vlm` 切换（属外部能力，单独评估）。
- chunk 切块策略（`knowledge_chunk` 端的处理，已在 ARCHITECT.md 中归 Knowledge Pipeline）。
- AI 治理 Prompt / 规则调整。

---

## 八、修复落地与回归（2026-06-18）

四类缺陷顺序落地完成，主要代码位于 `nexus-app/nexus_app/pipeline/mineru_converter.py`，由 `convert()` 内按以下顺序串行：

1. 主循环：MinerU `para_blocks` → `(blocks, md_parts)`。
2. `_strip_noise` —— 缺陷 1：水印 + 装饰图 VLM blockquote 清洗（装饰图正则锚定到 blockquote 段首，避免误伤正常图描述）。
3. `_extract_toc` —— 缺陷 2：检测点引线 / 章节 / 编号三种 TOC 行；连续 ≥3 行命中即抽出到 `payload.toc` 并从 markdown 移除。
4. `_merge_cross_page_tables` —— 缺陷 3 主体：合并连续 table 块（同 caption / 连续页 / bbox 接近）；丢弃 caption+image+content 三空 table 块；剥离 `|  |` 空 pipe 行。
5. `_rescue_multipage_tables_via_pdf` —— 缺陷 3 扩展：跨页表（`page_range` 长度 > 1）走 PDF 渲染逐页 VLM 提取，拼接所有页结果（保留首页 header + separator，去重后续页表头）。依赖 `pypdfium2` + `pillow`（已加入 `nexus-app/pyproject.toml`）；由 `nexus_app/pipeline/stages.py::_make_pdf_renderer` 在 normalize 阶段从 raw PDF 字节构造并注入 `convert()` 的 `pdf_renderer` 参数。
6. `_handle_visual` 内置 —— 缺陷 4：`_is_decorative_visual` 在 VLM 调用前过滤 QR / Logo / 装饰图；只对 `image` / `chart` 生效，`table` 永远走 VLM 救场。被跳过的块打 `decorative=True` / `parse_quality="decorative"`。
7. 缺陷 3 子路径：`_handle_visual` 内对**MinerU HTML 退化**的表（`_table_md_is_useful` 判定假）触发**anchor 截图**的 VLM 救场，结果通过 `_table_md_is_useful` 二次过滤后写回 `content`，并打 `parse_quality="vlm_rescue"`。
8. LiteLLM 表格 prompt 收紧：必须**仅返回**严格的 GitHub-Flavoured Markdown 表，无前言无评论；`max_tokens` 对 `table` block 提升到 4000。

### 样本资产 (`4abe6b71-…`) 回归

| 指标                      |                  修复前 |                                                最终修复后 | 备注                                                   |
| ------------------------- | ----------------------: | --------------------------------------------------------: | ------------------------------------------------------ |
| 「报告搜一搜」            |                       1 |                                                         0 | 清洗器命中                                             |
| 「长按识别关注公众号」    |                       1 |                                                         0 | 清洗器命中                                             |
| QR blockquote (`QR code`) |                       1 |                                                         0 | 收紧正则；装饰图 VLM 在源头被跳过                      |
| 空 `\|  \|` 行            |                    大量 |                                                         0 | merge 步骤剥离                                         |
| `block_type=table` 总数   |                      20 |                                                         6 | 14 个空续页块被合并 / 丢弃                             |
| 表 3-1 政策一览表 content | 331 字符（仅末页 1 行） | **4027 字符 / 22 行完整数据**（2020.11 → 2025.12 全跨度） | `parse_quality=vlm_rescue_pages`，`page_range=[50,55]` |
| 表 3-2 地方政策           |                       0 |                                             **3671 字符** | `vlm_rescue_pages`，`page_range=[58,63]`               |
| 表 4-1 / 4-2 / 4-3        |               0 / 0 / 0 |                                **1688 / 425 / 2579 字符** | 均 `vlm_rescue_pages`                                  |
| 单页表（如 p72 治理阶段） |       caption + 空 pipe |                                         494 字符 markdown | `vlm_rescue`（anchor crop 即可）                       |
| `image` 块 VLM 描述       |                    全有 |                2/3 有完整描述（第 3 个是 QR，正确被跳过） | `decorative=True` 标记                                 |
| `chart` 块 VLM 描述       |                    全有 |  **13/13 全保留完整图表分析**（含轴、图例、数据点、趋势） | 描述质量提升                                           |
| `payload.toc`             |                       0 |                                                         0 | 本 PDF 无目录页，符合预期                              |

### 测试矩阵（pipeline + knowledge 套件 55/55 全绿）

- `tests/pipeline/test_mineru_markdown_stability.py` — golden snapshot 字节不变。
- `tests/pipeline/test_mineru_noise_filter.py` — 缺陷 1 水印 / VLM blockquote 清洗。
- `tests/pipeline/test_mineru_toc_extract.py` — 缺陷 2 TOC 抽取与误判抑制。
- `tests/pipeline/test_mineru_table_merge.py` — 缺陷 3 跨页合并、空行剥离、空块丢弃、image_only 标记。
- `tests/pipeline/test_mineru_table_vlm_rescue.py` — 缺陷 3 anchor crop VLM 救场（退化触发 / 有用不触发）。
- `tests/pipeline/test_mineru_multipage_pdf_rescue.py` — 缺陷 3 多页 PDF 渲染救场（多页触发 / 单页不触发 / 无 renderer 无回归）。
- `tests/pipeline/test_mineru_visual_vlm_gate.py` — 缺陷 4 装饰图差异化。

### 已知边界

- MinerU 服务端 `vlm-transformers` 在本部署上对实际文档（123 页 / 6 页范围）均超时不可用；故方案 3 的兜底选择是「PDF 自渲染 + LiteLLM 表格 prompt」，而非依赖 MinerU vlm。该路径有外部 LLM 调用成本：跨页表越多越慢（样本资产首次重 normalize 耗时 ~327 s，跑了 19 次 VLM 表格调用）。后续可加缓存或并发。
- `pypdfium2` 与 `pillow` 现在是 `nexus-app` 硬依赖。CI / 部署需重新 `uv sync`。

## 九、复审发现：真正的根因是 `_table_html_to_markdown` 正则不识别属性（2026-06-18 下午）

第八节落地后用户复审指出："MinerU pipeline 配 `table_enable` 应该能拿到 HTML，先确认是否真的拿不到再走 VLM 救场"。深入复核后**结论被推翻**：MinerU 实际**正确**返回了结构化表 HTML，是我们的转换层把它弄丢的。

### 9.1 实测数据

| 维度                                                        |              数量 |
| ----------------------------------------------------------- | ----------------: | -------- |
| 样本资产里 MinerU 真实输出的 `<td                           | th>` 单元（全文） | **1079** |
| 当前 `_table_html_to_markdown` 抓到的 `<td>`（buggy regex） |             **4** |
| **单元数据丢失率**                                          |         **99.6%** |
| 样本中 `rowspan>1` 的单元                                   |                60 |
| 样本中 `colspan>1` 的单元                                   |                 1 |
| `<th>` / `<thead>` / `<tbody>`                              |         0 / 0 / 0 |

样本 anchor 页（p50 政策一览表）单块 HTML 就有 **7355 字节，27 个 `<tr>`，108 个 `<td>`，99 个非空 cell**——整张表 21+ 行政策**全在 MinerU 里**。续页（p51-55, p59-63 等）确实是 0 HTML（MinerU 无法续抽），跨页救场仍必须，但**只针对续页**，不该再覆盖 anchor。

### 9.2 配置侧 — 无问题

`nexus_app/mineru.py::MinerUHttpAdapter.parse()` 已显式：

| 字段                                                 | 取值                            |
| ---------------------------------------------------- | ------------------------------- |
| `table_enable`                                       | `"true"` ✓                      |
| `formula_enable`                                     | `"true"` ✓                      |
| `parse_method`                                       | `"auto"`                        |
| `return_md` / `return_middle_json` / `return_images` | 全 `"true"`                     |
| `lang_list`                                          | `["ch"]`                        |
| OCR                                                  | MIME 自动启用（pdf/image/tiff） |

样本 backend=`pipeline`、ocr_enabled=`True`。**所有该开的都开了**。

### 9.3 根因 — Regex 漏掉所有带属性的标签

`nexus_app/pipeline/mineru_converter.py:_table_html_to_markdown` line 183-204：

```python
rows  = re.findall(r"<tr>(.*?)</tr>",  html, re.DOTALL)
cells = re.findall(r"<td>(.*?)</td>",  row,  re.DOTALL)
```

只匹配**裸标签**。MinerU 输出形如：

```html
<tr>
  <td colspan="1" rowspan="1">2020.11</td>
  <td colspan="1" rowspan="1">市场监管总局</td>
  ...
</tr>
```

`<tr>` 凑巧裸 → 行数对（189 行）；`<td colspan=… rowspan=…>` 全 miss → 每行变成空 `| |`。原始症状里那 1 条「2025.12」真实行能漏出来，是因为正好那 4 个 cell 的 `<td>` 没带属性。

### 9.4 VLM 救场的语义重定位

之前以 `_table_md_is_useful=False` 触发救场是因为我们以为"MinerU 没拿到内容"。修 regex 后，**绝大多数表 anchor 都会变成 useful**，VLM anchor 救场会自然停发。但：

- 单页表（如 p72）—— 修 regex 后直接拿全，**不再需要 VLM**。
- 跨页表 —— anchor 用 MinerU markdown 即可；**仅续页**（page_range[0]+1 .. page_range[-1]）需要 VLM 兜底，因为 MinerU 在这些页确实 0 输出。

当前 `_rescue_multipage_tables_via_pdf` 是**整张表都用 VLM 重做**（覆盖 anchor 内容）—— 修 regex 后这反而是**降级**（MinerU 才是 ground truth）。需要改为「保留 anchor 的 MinerU 内容 + 仅对续页跑 VLM + 拼接」。

### 9.5 LLM Prompt / 响应清洗 — 双层加固

第八节做了 prompt 收紧，但用户实际看到的输出仍含：

- 头："当然可以。以下是您提供的表格内容..."
- 尾："说明：表格共 5 列..."、"若需导出为 CSV、Markdown 或 Excel..."、"如需我为您生成... 请告知"

这是中文 LLM 的"helpful assistant"长尾，prompt 单层压不住。需要：

- **A. Prompt 层加强**（仅工程指令）—— 角色限定为 OCR engine、显式列禁止短语（"说明"、"如需"、"当然可以"、"以下是"、"若需"、"可进一步"）、要求最后一行后立即终止。
- **B. 响应后处理**（必加兜底）—— 取第一行 `^\s*\|.*\|\s*$` 到最后一行 `^\s*\|.*\|\s*$`，**只保留 pipe 行 + separator**，其它一律丢。取不出有效表块则视为救场失败，回退到不替换。该后处理应作用于所有接受 VLM 表输出的入口（`_handle_visual` + `_rescue_multipage_tables_via_pdf`）。

### 9.6 合并单元格（colspan / rowspan）

修 regex 后还需处理：

- `colspan>1` —— GFM 不支持，复制内容到展开的多列。
- `rowspan>1` —— 在后续物理行的同一列填充上一行的内容（避免错位）。

样本中只有 1 个 colspan>1 + 60 个 rowspan>1，影响有限但必须处理才能让 markdown 表行宽对齐。

### 9.7 修复优先级与计划

| 优先级 | 项                                                                 | 预期收益                                                       |
| ------ | ------------------------------------------------------------------ | -------------------------------------------------------------- |
| 🔴 P0  | 修 `_table_html_to_markdown` regex 接受属性 + 处理 colspan/rowspan | **单点收回 99% 解析能力**；样本 VLM 调用数有望从 19 次降到个位 |
| 🟡 P1  | LLM 响应后处理（markdown 表块提取）+ prompt 加固                   | 直接消除"说明：..."类长尾                                      |
| 🟡 P1  | 跨页救场策略改为「首页 MinerU + 续页 VLM」                         | 保留 MinerU ground truth；降低 LLM 抖动                        |
| 🟢 P2  | colspan/rowspan 渲染策略细化                                       | 视觉对齐改善（当前样本影响小）                                 |

落地顺序按表 P0 → P1 → 验证。

---

## 十、§9 落地验证发现的新边界 — 跨页 VLM 越界 + 单段 TOC（2026-06-18 晚）

§9 P0+P1 落地并重 normalize 后，用户报告政策表附近的章节标题在 body_markdown 出现 3 次。逐项定位：

### 10.1 三次重复的来源

| 出现位置                   | 原因                                                                                                                                                                                                 |
| -------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 偏移 2388（在文档开头）    | MinerU 把整张 TOC 塞进**单个 paragraph 块**（block-p07-023），§2 的「≥3 连续行」检测不命中，TOC 内容留在了 body_markdown 里                                                                          |
| 偏移 37965（混在政策表内） | 续页救场把 p55 整页发给 VLM；p55 表格只占顶部 1/3（bbox [82,114,510,**281**]），下方还有「二、地方规范…」标题 + 段落 + 脚注 + 页码 -47-，VLM 把它们全部包装成 `\| 标题 \|  \|  \|  \|` 的 4 列填充行 |
| 偏移 38470（正常正文）     | MinerU 在 p55 之后正确识别的 heading + paragraph 块                                                                                                                                                  |

### 10.2 三项修复

| 改动                                                             | 文件                                                    | 作用                                               |
| ---------------------------------------------------------------- | ------------------------------------------------------- | -------------------------------------------------- |
| renderer 增 `bbox` 参数，按 bbox 裁剪后输出 JPEG                 | `nexus_app/pipeline/stages.py::_make_pdf_renderer`      | 续页救场时 VLM 只看表格区域，越界的标题/段落被剪掉 |
| `_merge_cross_page_tables` 保留 `per_page_bboxes` 映射           | `mineru_converter.py::_merge_cross_page_tables`         | 救场环节可按页查得 bbox                            |
| 救场遍历每页时把 bbox 传给 renderer（兼容老 renderer）           | `mineru_converter.py::_rescue_multipage_tables_via_pdf` | 实际启用裁剪                                       |
| sanitiser 新增 `_is_padding_row`：4 列只有 1 列有内容 → 丢弃     | `mineru_converter.py::_sanitise_vlm_table_response`     | 即使裁剪失败也兜底剔除 padding row                 |
| TOC 抽取增加 `_classify_toc_concat_block`：单段落多 TOC 片段识别 | `mineru_converter.py::_extract_toc`                     | 适配 MinerU 把整 TOC 塞进单块的写法                |

### 10.3 样本回归

| 指标                                                               |        §9 修复后 |             §10 修复后 |
| ------------------------------------------------------------------ | ---------------: | ---------------------: |
| 「二、地方规范创新精准落地」出现次数                               |                3 |                  **1** |
| 政策表 content 含「二、地方规范」/「在浙江省」/「十不准」/「-47-」 | 全部包含（污染） |           **全部不含** |
| `payload.toc` 条目数                                               |                0 |                 **39** |
| 政策表 content_len                                                 |   7918（含污染） |           7120（纯净） |
| convert 总耗时                                                     |             213s | 177s（裁剪后图片更小） |

### 10.4 新增测试

- `tests/pipeline/test_mineru_section10_fixes.py` — 12 项：padding row 检测、sanitiser 过滤、merge 保留 per_page_bboxes、rescue 传 bbox 给 renderer、concat TOC 检测与抽取。
- 全 pipeline 套件 66/66 通过。

---

## 十一、Chart/Image VLM 元标签污染 + 表被误分类为图 chart（2026-06-18 深夜）

§10 落地后用户报告 `block-p73-215`（实为「我国直播电商规范化治理阶段划分及特征」对照表）产生大段「Chart Type: Tabular comparison... Axis Labels:... Legend:... Key Data Values:... Trend:...」结构化输出。

### 11.1 根因

| 层     | 问题                                                                                                               |
| ------ | ------------------------------------------------------------------------------------------------------------------ |
| Prompt | 原 chart prompt 主动要 "chart type / axis labels / legend / key data / trends"，模型严格执行，元标签是我们让它加的 |
| 路由   | MinerU 把对照表识别为 `block_type=chart`，走的不是 table 路径，得不到 markdown 表                                  |
| 后处理 | 仅 table 输出有 `_sanitise_vlm_table_response`；image/chart 输出无任何清洗                                         |

样本全文 13 个 chart 块全部带这种结构化输出（差别只在内容详略），陪同的「Trend: Progressive institutionalization…」主观总结也是用户明令不要的"无关信息"。

### 11.2 三层修复

| 改动                                                                                                                                                                                                          | 文件                  | 作用                           |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------- | ------------------------------ |
| **A** — chart/image prompt 全部重写：复用 `_STRICT_OCR_PREFIX`、明确禁止 `Chart Type:` / `Axis Labels:` / `Legend:` / `Key Data:` / `Trend:` / `Summary:` 等结构标签                                          | `image_analysis.py`   | 源头不让模型产元标签           |
| **B** — `_sanitise_vlm_visual_response`：剥头部 chatty 前言；丢弃纯元标签行；对"label: value"行剥标签留 value；折叠多空行                                                                                     | `mineru_converter.py` | 兜底清洗，模型偶发漏话也能消掉 |
| **C** — `_looks_tabular` + chart→table 重路由：检测「Tabular/matrix/grid」+ Rows/Columns 字样或 ≥3 GFM pipe 行，用 table prompt 重跑，成功则 `block_type='table'`、`parse_quality='chart_to_table_recovered'` | `mineru_converter.py` | 救回 MinerU 把表错认为图的情况 |

### 11.3 样本回归

| 指标                                                    |                     §10 修复后 |                                                       §11 修复后 |
| ------------------------------------------------------- | -----------------------------: | ---------------------------------------------------------------: |
| body 含 `Chart Type:`                                   |                             13 |                                                            **0** |
| body 含 `Axis Labels` / `X-axis:` / `Y-axis:`           |                           多处 |                                                            **0** |
| body 含 `Legend:` / `Key Data:` / `Trend:` / `Summary:` |                           多处 |                                                            **0** |
| 13 chart 块平均 content_len                             | ~700 字符（含元标签+主观总结） |                                          **~275 字符**（纯数据） |
| p73-215                                                 |  chart 块，1278 字符元标签噪声 | **重路由为 table 并与 p72-214 跨页合并**，1 个干净的 markdown 表 |
| `convert` 总耗时                                        |                           177s |                                   186s（+1 次 chart→table 调用） |

### 11.4 新增测试

`tests/pipeline/test_mineru_visual_response_sanitiser.py` — 11 项：

- 视觉响应清洗：pure label 行丢弃、`X-axis:` 这类含值标签剥前缀留值、`Y-axis (left):` 这种带括号修饰也命中、chatty 前言剥掉、`-` sentinel 保留、空行折叠。
- `_looks_tabular`：显式关键词 + Rows/Columns 命中、内含 ≥3 pipe 行命中、正常 chart 描述不命中、None/empty 安全。
- 集成：误分类的"chart"实际是 table 时 chart→table 双轮调用 + 块类型提升 + `parse_quality='chart_to_table_recovered'`；真正的 chart 不重路由且元标签被清洗。

pipeline 套件 78/78 全绿。

---

## 历史

- 2026-06-18 上午：基于资产 4abe6b71… 的实测分析触发；登记 4 类缺陷与修复顺序，按 1→4 实施并通过回归。
- 2026-06-18 下午：复审发现 `_table_html_to_markdown` 正则不认属性导致 99.6% 数据丢失，是 table 内容缺失的真正根因；登记第九节，按 P0→P1 落地。
- 2026-06-18 晚：§9 落地后用户复审发现跨页 VLM 越界 + 单段 TOC 两类残留问题；登记第十节并修复，sample 上目标指标全部达成。
- 2026-06-18 深夜：§10 落地后用户报告 chart 块元标签污染 + 表被误分类为 chart；登记第十一节，三层修复（prompt 收紧 / 视觉响应清洗 / chart→table 重路由）落地，sample 上所有元标签清零，p73-215 被正确识别为表。
