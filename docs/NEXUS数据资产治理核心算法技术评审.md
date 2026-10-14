# NEXUS 数据资产治理核心算法技术方案 v2.0

## 技术方案评审材料 · 01 / 15

## 一、技术讨论范围

**目标**：评审 NEXUS 如何将异构原始数据转换为可治理、可检索、可追溯、可复核的数据与知识资产，并冻结算法边界、阈值和技术选型。

| 评审域 | 本次讨论内容 | 不可破坏的边界 |
|---|---|---|
| 解析与清洗 | PDF/Office/HTML/Markdown/结构记录路由；噪声、低价值、低信息密度和去重 | 原始对象保留；删除/合并必须可解释、可回放 |
| 标准化 | `normalized_document` / `normalized_record` 建模、字段归一与领域校验 | 治理只通过 `normalized_asset_ref` 读取标准化数据 |
| AI 治理 | 分类、分级、标签、结果复核、四维质量评估和状态准入 | AI 只产生候选；Schema、白名单、脱敏、规则、置信度和状态机不可跳过 |
| 知识构建 | 分类型 RAG 切块、领域模型、块质量和 Evidence-grounded KG | `knowledge_chunk` 归 NEXUS 所有；事实必须绑定 chunk/block/locator 证据 |
| 检索 | 传统向量 RAG 与 NEXUS 场景化智能检索对比 | 权限/治理过滤先于返回；外部 Web 证据不伪装成 NEXUS 资产 |

**v2.0 组件原则**：生产中文主链 = **现有规则 + HanLPAdapter + 领域词典 + BGE + LiteLLM**；结构化质量 = **Pydantic/领域验证器 + 可选 Pandera/Great Expectations**。NLP 只做带 offset 的注释、特征和候选，不直接删除证据或改写正式治理结果。

> 状态口径：**现行** = 代码/契约已落地；**v2.0 增强** = 本次建议，需任务包和 Review Gate；**可选** = 达到规模/多语言触发条件后引入。

---

# 数据资产端到端处理流程

## 技术方案评审材料 · 02 / 15

## 二、端到端算法地图

```text
数据源（文件/NAS/爬虫/API/结构记录）
  -> ingest_validate：MIME/magic bytes、大小、URL 安全、幂等键
  -> assetize：Asset + AssetVersion + raw_object（原始留存）
  -> parse：MinerU/Trafilatura/Markdown/OpenPyXL，输出 block/page/bbox/table/image
  -> clean：硬规则降噪 + 结构恢复 + NLP 软判别（v2.0）
  -> normalize：normalized_document / normalized_record
  -> normalized_asset_ref：身份、内容、governance、quality、lineage
  -> AI governance：分类/分级/标签/组织范围 + 质量审核
  -> rule guardrails + state machine
       +--> disabled / review_required / failed
       `--> available（同一资产最多一个 available 版本）
  -> 独立 Knowledge Pipeline
       +--> 领域结构化投影
       +--> knowledge_chunk -> embedding/pgvector -> rerank
       `--> Evidence-grounded KG
  -> 权限/治理过滤 -> 智能检索/QA -> 引用与审计
```

**六个全链路不变式**

1. `assetize` 与 `normalize` 是两个独立阶段，不得混同。
2. Raw、原始 JSON、MinerU 原始输出不是合法治理输入。
3. `governance_result.target = normalized_asset_ref`，不是 `asset_version`。
4. 清洗不改变原始留存；每个删除、合并、救场动作记录 rule/model version 和 reason。
5. Chunk、领域事实和 KG 共享 `normalized_ref_id`，但可独立重建、审计和回滚。
6. 失败保留 `trace_id`、stage、reason、retry semantics；降级不得伪装为算法成功。

---

# 多格式文档解析技术路由

## 技术方案评审材料 · 03 / 15

## 三、解析、清洗与去重（1/3）

| 数据类型 | 现行/建议主路由 | 核心输出 | 选择依据与备选方案 |
|---|---|---|---|
| 扫描 PDF/图片/TIFF | MinerU `pipeline`，OCR 自动开启；复杂版式显式升级 `vlm` | block/page/bbox/text/table/image URI | 中文 OCR、表格和版面统一；不用 HanLP 替代 OCR。可选 PaddleOCR/Docling 必须以表格和 locator 黄金集对比 |
| 数字 PDF | MinerU `pipeline`；表格结构损坏时页渲染 + VLM 救场 | 正文、标题、表格、图片和页定位 | 保留视觉证据和跨页表；PyMuPDF/pdfplumber 可作文本型快路实验，但不能降低追溯率 |
| DOC/DOCX/PPT/PPTX | MinerU `pipeline`，按 MIME 路由 | 层级文本、表格、图片和幻灯片顺序 | 与 PDF 形成统一 block 契约；若精确样式/批注成为需求，评测 `python-docx/python-pptx + LibreOffice` 专用路由 |
| XLS/XLSX/CSV | Pipeline B 结构解析；XLSX 用 OpenPyXL，领域 profile 映射 | sheet/row/cell + 字段映射 + 原行定位 | 表数据必须按行列处理，不先转纯文本；可选 Pandera/GE 做批量 Schema/分布验证 |
| 爬虫 HTML | Firecrawl `onlyMainContent` + Trafilatura -> Markdown/block | 正文、section、URL、DOM 来源与字符定位 | 对 CMS/新闻页去导航成熟；动态渲染由 Firecrawl 负责，不用通用 NLP 猜测 DOM |
| 上传 HTML | MinerU-HTML | 统一 document block | 与文件 Pipeline 一致；爬虫 HTML 不重复走 MinerU-HTML |
| Markdown/TXT | 轻量 Markdown adapter，保留 heading/list/code/table | block + `md_char_range` | 已有显式结构，无需重型文档 AI；对 GFM 表格做结构校验 |
| JSON/API 记录 | Pipeline B + domain profile + Pydantic | `normalized_record` + dataset/record lineage | 不转自然语言后再解析；未知 profile 不猜测字段语义 |

**入口判定顺序（v2.0）**：`magic bytes -> MIME -> 扩展名交叉校验 -> 安全/解压限制 -> pipeline_type`。扩展名与 MIME 冲突时隔离或人审，不默默改路由。

**选型不只看文字准确率**：必须同时测 `block F1`、表格 cell F1、阅读顺序、locator 覆盖率、图片回指率、P95 耗时、资源峰值和许可证/模型供应链。

---

# 低效数据全分类与清理算法

## 技术方案评审材料 · 04 / 15

## 三、解析、清洗与去重（2/3）

> 下表是 NEXUS 当前数据范围内的完整低效数据分类；“删除”仅指不进入 normalized 正文/检索候选，raw 仍保留。

| 类型 | 核心判定算法 | 处理策略 |
|---|---|---|
| 不安全/不可访问 | URL 安全校验；前 2,000 字的登录、账号+密码、CAPTCHA/人机验证联合模式 | 入口拒绝，记 reason |
| 页面壳/聚合页 | 首页、栏目、搜索结果、GitHub 会话壳/源码查看页的 URL+正文特征 | 入口拒绝 |
| 内容不足/语言不符 | Firecrawl `<300` 字、WebSearch `<200` 字、无汉字；v2.0 用语言识别比例代替“任一汉字” | 拒绝或多语言人审 |
| 低价值活动/人物新闻 | 活动标记命中 `>=2`；人物型标题+记者/通讯员/“（完）”；政策条款、文号、统计量化证据反向放行 | 高置信拒绝；冲突进复核 |
| 导航/页眉页脚 | `第 N 页`、`Page N of M`、`- N -`、站点导航的正则+跨页重复率 | 删除块；记规则版本 |
| 目录/索引 | 连续目录行 `>=3`，或单块目录片段 `>=4`；点线+页码、章节序号模式 | 抽取到 `toc[]`，正文候选删除 |
| 出版/管理元数据 | ISBN/CIP/版权/定价/责编；出版词 `>=3`，或 `>=2` 且含 URL/ISBN/版权 | 转 document metadata，不作检索正文 |
| 水印/推广/站点模板 | 配置词典 + 跨文档高频段 + DOM/bbox 位置；v2.0 增加 5-gram MinHash 模板发现 | 高置信删除，候选标记 template |
| 装饰视觉/QR/Logo | 空 caption/text；短标签+空正文且 bbox 面积 `<=2,500`；QR-only VLM 描述 | 删除或 `decorative`；table 永不按装饰图跳过 |
| OCR/编码损坏 | replacement-char 比例、非语言符号率、连续乱码、词法异常；与页图 VLM 复核 | 重试 OCR/VLM；无法恢复则 parse_quality 阻断 |
| 空洞/纯符号/孤立片段 | 空文本、纯标点/数字；去空白 `<4` 字符；chunk `<=12` 记 near-empty | 非结构块删除；比例进质量报告 |
| 低信息密度 | `实词/全部 token`、领域实体/句、数值证据/句、唯一 n-gram 率；现行低信息块 `<=4` 或最多 8 个符号 | 不单凭短就删；标记 `weak_value` 或合并上下文 |
| Prompt/练习/学习目标 | “请/思考/问题/练习/课后”短问句；heading 含“学习目标” | 教材中保留为 context/weak evidence，不得单独支撑答案 |
| 占位/示例/纯序号记录 | `.../……/-/无/N/A/TBD`、纯序号、“示例/样例”、必填主题为空 | 不落正式记录，计 `placeholder_row_dropped` |
| 类型/范围/关系异常 | 日期、金额、地区、枚举、外键、代码正则、跨 sheet 关系和单位维度 | 保留原值/trace + quality flag；关键关系失败则 blocking |
| 表格/层级结构损坏 | 缺表头、列数漂移、重复表头、跨页不连续、大表未拆 | 跨页合并/VLM 救场；无法恢复进人审/重建 |
| 精确重复/近重复/过时版本 | SHA-256、业务键、MinHash/SimHash/BGE 候选、时间/来源/效力对比 | 精确重复幂等；近重复只提示；过时版本归档不删除 |

**v2.0 软判别模型（需标注集校准）**

```text
density = (实词 + 领域实体 + 数值证据 + 引用/关系) / (tokens + ε)
P_inefficient = calibrate(
  char/language/corruption + structure/template/duplicate
  + lexical/entity/evidence features + BGE prototype similarities
)
```

`P>=0.90` 且无政策/统计/法律/人工白名单证据时才自动剔除；`0.50<=P<0.90` 标记 `weak_value/review`；`P<0.50` 保留。噪声是“内容本身不可用”，低价值是“对当前领域任务贡献弱”，两者必须分开标注和评测。

---

# 完整清洗流程与去重模型

## 技术方案评审材料 · 05 / 15

## 三、解析、清洗与去重（3/3）

**完整清洗流程（v2.0）**

```text
raw + parse blocks
 -> L0 安全/准入：URL、MIME、登录墙、内容量、语言
 -> L1 结构修复：阅读顺序、跨页表、重复表头、图表 VLM 救场
 -> L2 硬噪声：页脚、目录、出版信息、QR、空/纯符号块
 -> L3 HanLPAdapter（v2.0）：分句、POS、NER、依存、领域词典，保留 char offsets
 -> L4 软判别：低价值/低密度/模板/乱码特征 + 可校准分类器
 -> L5 语义检查：BGE 主题/近重复；中间置信冲突交 LiteLLM/人审
 -> 删除 / 转 metadata / 保留 / weak_value / review
 -> 重建 body_markdown -> md_char_range -> normalized payload
 -> 输出每条 rule/model/dictionary version、reason、before/after count
```

HanLP 失败时回退 `RuleOnlyAnalyzer`，标记 `nlp_status=degraded`；不得因 NLP 不可用而中断确定性规则链，也不得默默标记 NLP 检查通过。

**四层去重模型**

| 层 | 算法/键 | 正式决策 |
|---|---|---|
| 请求幂等 | `(data_source_id, idempotency_key)` | 返回已有批次 |
| 原始内容 | `SHA-256(raw bytes)` | 同源同 checksum 跳过；跨源保留 lineage |
| 业务身份 | `(data_source_id, source_object_key)`；领域自然键/指纹 | 同身份内容变化创建新版本，原 `available` 原子归档 |
| 近重复候选（v2.0） | NFKC+脱模板 -> 5-gram MinHash/LSH 候选 -> BGE cosine -> 元数据冲突校验 | 只生成 `duplicate_candidate`，不自动合并 |

```text
candidate if Jaccard_est >= Tj AND cosine >= Ts
auto-link prohibited when version/date/region/issuer/legal_effect differs
```

**技术取舍**：SHA/业务键精确、便宜、可审计，但找不到轻微改写；MinHash 适合大规模字面候选，不理解语义；BGE 可发现改写，但会把不同地区/时间/效力的文件误并。因此“MinHash+BGE”仅降低人工候选集，不替代身份和版本规则。

---

# 原始数据标准化建模

## 技术方案评审材料 · 06 / 15

## 四、标准化结构与规则

```text
normalized_asset_ref
  identity : id, version_id, source_type, content_type, normalized_type
  content  : title, language, object_uri -> normalized_document | normalized_record
  control  : governance, quality, status
  lineage  : raw checksum, parse_artifact, block/image URI, schema/config/model version

normalized_document
  body_markdown + blocks[block_id,type,page,bbox,content,image_uri,md_char_range]
  + document_metadata + toc + parse_quality

normalized_record
  dataset metadata + schema/profile version
  + records[row_id, canonical fields, source row locator, quality_flags]
```

**标准化次序**：契约解析 -> 规则生成基础 payload -> LiteLLM 仅补允许且当前为空的字段 -> Pydantic required/type/format -> 领域验证 -> 失败回退规则结果 -> 仍不满足则 `NormalizeContractError`。

| 对象 | 归一规则 |
|---|---|
| 文本 | Unicode NFKC、trim、空白折叠；原文证据和 char offset 不改写 |
| 枚举/标签 | 仅允许注册表 code；未知值标 flag/复核，不自动扩枚举 |
| 日期/数值/单位 | 受控解析、量纲检查、标准单位；同时保留 raw value |
| 地区/机构/专业/岗位 | 领域词典 + HanLP NER 生成 canonical candidate；标准码/别名表决定，无证据不推断 |
| 标题/摘要 | 优先结构标题；LLM 摘要失败回退确定性正文截取 |
| 行记录 | 字段别名映射、必填、类型、范围、唯一性、跨列/跨 sheet 关系 |

**v2.0 结构质量分工**：Pydantic 负责单对象契约和 API 一致性；领域验证器负责专业布点/岗位/能力/画像等业务关系；Pandera 适合 Worker 内 DataFrame 批校验；Great Expectations 仅在需要跨批次分布、数据档案和专职数据工程运营时引入，P0 不为其建独立服务。

---

# AI 治理：分类、分级与数据打标

## 技术方案评审材料 · 07 / 15

## 五、AI 治理算法（1/2）

```text
normalized_asset_ref
 -> 规则/领域 Schema 产生硬证据
 -> HanLP+词典产生实体/术语/敏感候选（v2.0）
 -> L3/L4 脱敏/私有模型策略
 -> LiteLLM + 版本化 Prompt 产生结构化候选
 -> Pydantic Schema + 字段白名单
 -> 分类/分级/标签注册表 + evidence_refs
 -> 结果质量审核 -> 置信度/规则/人审 -> 状态机
```

**1. 分类算法**

- 先以领域结构证据生成 candidate mask：如 `job_demand` 要有可枚举岗位，`major_profile` 要有专业身份+培养/课程等至少两类证据，`industry_policy` 要有发布主体/文号/条款/正式措施。
- HanLP NER+领域词典统计专业、课程、岗位、机构、政策、时间、指标密度，作为可解释特征，不单独定类。
- LiteLLM 在 mask 内输出 `classification + confidence + reasons + evidence_refs`；类别必须存在于注册表。
- v2.0 校准分：`Pclass = calibrate(LLM_confidence, schema_evidence, term/entity evidence, conflict flags)`；用黄金集做 temperature/isotonic calibration，不直接把 LLM 自报分当概率。

**2. 分级算法**

- 导入源默认 L1/L2；类别默认 level 只是先验，不是敏感性证据。
- 检测个人信息、密钥/凭据、商业秘密、精确个人定位等高敏例外；规则命中必须带 exact evidence span。
- 规则与 AI 不一致取更严等级并进人审；L3/L4 必须显式审批、规则证据、脱敏和审计。

**3. 数据打标算法**

```text
候选 = 分类可用 tag dimension
       ∩ （词典精确命中 + HanLP 实体/术语 + LLM 语义候选）
接纳 = registry valid AND applicable_to(classification)
     AND evidence span exists AND confidence >= dimension threshold
```

高置信标签自动提交并写 audit；低置信/同义冲突/新术语进人审队列。`metadata_enrich` 标签目标是 normalized asset，不是 chunk。

---

# AI 结果审核与数据质量模型

## 技术方案评审材料 · 08 / 15

## 五、AI 治理算法（2/2）

**AI 分类/分级/标签结果的七项审核**

| 审核 | 算法 | 失败路由 |
|---|---|---|
| Schema | Pydantic 类型、必填、枚举、分数范围 | reject AI output |
| 白名单 | 输出字段必须在 scenario allowlist | reject + audit |
| 注册表 | classification/level/tag code 存在且标签适用当前分类 | reject/review |
| 证据 | `evidence_refs` 属于同一 normalized ref，span 可回指且文本相符 | blocking 或 warning，按规则严重度 |
| 相互一致 | 分类-分级、分类-标签、标签间互斥/依赖、org scope 和领域 Schema | conflict -> `review_required` |
| 敏感/策略 | 脱敏策略、模型出域策略、L3/L4 审批条件 | `POLICY_BLOCKED` 或人审 |
| 置信度/校准 | `<0.50` 隔离；`0.50-0.85` 人审；`>=0.85` 仍需质量通过 | disabled / review / 继续准入 |

**v2.0 数据质量模型：客观指标主分 + AI 语义补分 + blocking veto**

```text
D = 0.30*C + 0.25*A + 0.25*K + 0.20*U
dimension = α*deterministic + β*NLP + γ*AI_semantic
任一 severity=blocking 检查 fail => 不得 available，无论 D 多高
```

| 维度 | 可执行算法 | 建议融合（规则/NLP/AI） |
|---|---|---:|
| 完整性 C | `100 * Σ(w_i*valid_i)/Σw_i`；`valid` 要求非空、非占位、类型正确、关系/证据齐全 | 85/10/5 |
| 准确性 A | Schema/注册码命中率、数值单位合法率、实体规范码命中率、证据可定位率、异常值反比 | 55/25/20 |
| 一致性 K | `100*(1-加权冲突数/加权检查数)`；代码-名称、别名、单位、地域、时间、跨 sheet、标签-分类、版本唯一性 | 65/20/15 |
| 可用性 U | 解析成功率、噪声反比、句完整率、locator/图片可访问率、chunk/index readiness、检索黄金集效果 | 75/20/5 |

`D>=80` 为 pass，`60<=D<80` 为 warning，`D<60` 为 fail；但正式 `available` 还要求置信度 `>=0.85`、无 blocking、taxonomy 合法、分级无审批要求、必填治理字段齐全和 available 版本唯一。

**必须修复的现状**：`no_conflicting_signals`、`level_matches_classification`、`tags_match_classification`、`no_parse_errors`、`images_accessible` 不得再固定 pass；未注册 evaluator 在 v2.0 应配置加载失败或 fail-closed。Parse/image 检查应读 ParseArtifact/MinIO，不交给 HanLP。

---

# 分类型 RAG 语义块构建

## 技术方案评审材料 · 09 / 15

## 六、RAG 切块与领域知识建模（1/4）

| 数据类型 | 主切块策略 | 强边界/输出单元 | v2.0 NLP 增强 |
|---|---|---|---|
| 政策/报告/通用文档 | `semantic_repack` | heading/section、paragraph、table、chart/image | HanLP 分句+实体连续性；BGE 主题边界 |
| 教材正文 | `semantic_repack` + Task Outline | project/task/step/artifact；练习作 weak evidence | 依存/指代避免把任务步骤断裂 |
| 行记录表 | `row_decompose` | dataset overview + 一行一块，字段名:值 | 只做实体/术语标注，不改变行原子性 |
| 矩阵/交叉表 | 整表或按受控维度拆分 | 表头+维度+单元格证据 | NLP 不猜表结构；必须由 table schema 驱动 |
| 专业画像/培养方案 | domain decompose | 目标、规格、岗位、能力、课程字段块 | 实体规范化和跨句关系候选 |
| 专业/课程标准 | 领域表投影 + 叙事补充 | 职业域/任务/能力，或模块/内容/技能/知识 | 依存关系只产生候选，表格证据决定正式边 |
| QA | `qa_pair` | question + answer + evidence | 问句意图/实体用于标签和检索 |
| 流程/指标/案例 | `process_step` / `indicator` / `case_section` | 步骤、指标口径、案例阶段 | 时序词、指标实体、事件候选 |

**统一 Chunk 契约**

```text
identity  : normalized_ref_id, knowledge_type_code, chunk_type, chunk_index
content   : 可独立检索的语义文本
evidence  : source_block_ids, locator, md_char_range/md_spans, heading_path
role      : body/table_overview/table_row/chart/image/metric_image/equation/...
build     : strategy/config/NLP/dictionary/embedding version + embedding_status
```

**路由顺序**：治理确认的主知识类型 -> domain strategy registry -> 结构化投影 -> 叙事语义补充。能由表行、章节、步骤、Outline 确定的边界不交给纯字符窗口或 LLM。

---

# 领域知识模型结构与建模算法

## 技术方案评审材料 · 10 / 15

## 六、RAG 切块与领域知识建模（2/4）

| 领域模型 | 结构 | 建模算法/硬约束 |
|---|---|---|
| 政策/行业报告 | `Document -> Section -> Block -> Metric/Evidence` | heading 树+文号/发布主体/日期+指标单位；数值必须回指表/图/原句 |
| 岗位需求 | `Dataset -> JobRecord -> RequirementItem` | 公司+岗位+城市+源行指纹；薪资/日期/经验/学历受控解析；占位/重复分 flag |
| 专业布点 | `Dataset -> Year + Province + Major(code,name) -> Count` | 至少 year/province/major_name/major_code 且 `count>=0`；代码-名称和行政区划一致 |
| 职业能力 | `Analysis -> Task -> WorkContent -> Ability(P/G/S/D)` | profile 与 analysis model 一致；ability code regex；ability 必须连 task，指定类型还必须连 work content |
| 专业画像 | `Institution + Major -> Career/Goal/Ability/Course` | 学校身份必须有标题/正文/验证元数据证据；培养目标、职业面向、课程等完整性验证 |
| 人才培养方案 | `Plan -> Major -> Goal/Specification -> Position-Skill/LearningDomain -> Course` | 仅从 normalized document 投影；课程为 plan-local；只有证据化岗位-技能才构图 |
| 专业教学标准 | `Major -> OccupationalDomain -> TypicalWorkTask -> SkillKnowledgeRequirement` | 专业名/代码归一；工作任务与能力要求必须有表格/section 证据 |
| 课程标准 | `Course -> Module -> CourseContent -> {SkillRequirement, KnowledgeRequirement}` | 受控表头别名+学时/课时结构锚；Course 名仅从标题归一，不从正文猜测 |
| 实训教材 Task Outline | `Profile -> Project -> Task -> Step -> Artifact` | heading/编号/操作词构树；父子层级和 source block 绑定；高价值节点投影 chunk |
| 通用证据图 | `Entity -> Fact/Edge -> Evidence` | 规则提取强结构，HanLP/依存生成候选，LLM 补跨句语义；共现不等于关系 |

**四层分工**：资产语义层管版本/治理/权限；领域事实层支持精确查询；Chunk 层支持语义召回；关联图层支持跨块关系。不构建一个同时承担主数据、检索和抽取候选的“大图谱”。

---

# HanLP + BGE 混合语义切块算法

## 技术方案评审材料 · 11 / 15

## 六、RAG 切块与领域知识建模（3/4）

```text
normalized blocks
 -> 硬结构边界：heading/table row/list/outline/media/code/equation
 -> HanLPAdapter：sentence spans + POS + NER + dependency（原文 offsets）
 -> 领域词典：机构/专业/岗位/课程/技能/政策别名
 -> BGE：相邻句语义相似度与主题跃迁
 -> 边界打分 + min/target/hard-max 约束下的动态规划
 -> 补充 heading/caption/attribution
 -> 继承 block_id/md_spans/locator/heading_path
 -> 文档内精确去重 -> KnowledgeChunk
```

**候选切点分数（v2.0）**

```text
B(k) = w1*(1-cos(e_k,e_k+1))           # 主题跃迁
     + w2*structure_boundary            # heading/list/section
     + w3*entity_topic_shift            # 主体/专业/岗位变化
     + w4*terminal_punctuation
     - w5*pronoun_or_dependency_link     # 指代/依存续接
```

**Chunk 区间代价**

```text
J(i,j) = λ1*length_penalty(i,j)
       + λ2*semantic_dispersion(i,j)
       + λ3*broken_structure(i,j)
       + λ4*dangling_reference(i,j)
       - λ5*B(j)
DP[j] = min_i(DP[i] + J(i,j))
```

- 强边界不可跨越；表行、QA、任务步骤优先保持原子性。
- 长文本按“段落 -> HanLP 句子 -> 列表项 -> 表行”拆分，不按固定字符生硬截断。
- 现行质量报告 `hard_max=2,500`、`p95_warn=1,500` 只是监测基线；v2.0 的 target/hard-max 需用中文 token 分布和检索黄金集冻结。
- HanLP 只输出 offset annotation，不改写 `body_markdown`；分句失败回退现行标点/结构规则。

**为什么不用 spaCy/NLTK 替代**：spaCy 的 Pipeline/Matcher/offset 工程化优秀，适合未来多语言或已有 spaCy 模型团队，但中文领域模型还需二次适配；NLTK 适合英文离线统计/基线，不适合中文生产主链。同时引入三套会带来 tokenizer、offset、模型和运维重复。

---

# RAG 语义块构建质量评估

## 技术方案评审材料 · 12 / 15

## 六、RAG 切块与领域知识建模（4/4）

**质量不用单一总分掩盖追溯和边界阻断缺陷：先硬门禁，再内在质量，最后检索外在效果。**

| 硬检查（现行） | Warning / Block |
|---|---|
| `missing_locator_ratio` | `>5% / >20%` |
| `missing_heading_path_ratio`（文档） | `>20% / >50%` |
| `over_hard_max_ratio` | `>0 / >5%` |
| `near_empty_ratio`（`len<=12`） | `>2% / >10%` |
| `low_information_ratio` | `>5% / >15%` |
| 残留 TOC/页脚/版权，大表未拆，embedding pending | 任一命中告警并定位 chunk |

**v2.0 内在质量分**

```text
I = 0.20*provenance_coverage
  + 0.15*sentence_boundary_integrity
  + 0.15*semantic_cohesion
  + 0.10*self_containment
  + 0.10*(1-noise_ratio)
  + 0.10*size_fitness
  + 0.10*structure_atomicity
  + 0.10*index_readiness
```

- `semantic_cohesion` = 块内句向量与 centroid 的平均 cosine；过高且跨块重复则反查过度重叠。
- `self_containment` = 无悬空指代/无标题上下文缺失/关键实体与谓词齐全的句比例，HanLP 只提供特征。
- `structure_atomicity` 检查表行、QA、步骤、指标口径是否被错拆/错并。

**外在检索效果分（黄金问题集）**

```text
R = 0.25*Recall@5 + 0.15*nDCG@10
  + 0.20*answer_context_recall + 0.20*citation_precision
  + 0.10*section_context_hit_rate
  + 0.10*(1-no_answer_false_positive_rate)
```

**决策**：硬检查 block -> 不用于公共 QA，生成重建/人审建议；报告本身不改资产状态。v2.0 阈值建议用当前策略 vs HanLP+BGE 策略的 paired bootstrap 置信区间决定，不根据单次 demo。记录类 chunk 允许 locator 为空，但必须有源 row identity。

---

# Evidence-grounded KG 构建算法

## 技术方案评审材料 · 13 / 15

## 七、事实选取、归一化与合并

```text
完整 normalized_ref chunk 范围（不用 Top-K/单页构图）
 -> 候选过滤：空/噪声/装饰/非图谱 Outline
 -> 上下文单元：body 按 heading/连续性分组，table_row/media 一块一单元
 -> 候选生成：规则强结构 > HanLP NER/依存 > LiteLLM 跨句语义
 -> Schema/证据/显著性/置信度门禁
 -> 实体/谓词/字面量/单位/时间归一
 -> fact/edge 去重合并 -> evidence 持久化
```

**候选契约**

```text
subject(type,name) --predicate--> object(type,name) | object_literal
+ fact_type + qualifiers + confidence
+ source_chunk_id/evidence_chunk_ids + exact evidence_text
```

**事实显著性分（现行基线）**

```text
S = 0.25 + 0.24*core - 0.18*low_value
  + 0.18*strong_predicate - 0.16*weak_predicate
  + 0.08*entity_object + min(0.16,literal_len/500)
  + 0.18*multi_chunk_evidence + 0.12*context_link
  + 0.08*valid_context_role + 0.18*(confidence-0.70)
  - 0.18*generic_entity
```

`S<0.45`、弱 `MENTIONS`、低显著通用实体、单证据块候选过密（同源块 `>8`）拒绝；正式持久化还要求 confidence `>=0.70`、exact evidence 存在、evidence chunk 属于同一 normalized ref。

**归一与合并**

- 实体：NFKC/空白/编号标题清理 -> 领域词典/标准码/别名映射 -> `entity_type + canonical_name` 节点键。HanLP 识别边界，词典决定 canonical value。
- 谓词：同义关系映射到受控谓词，如“同比增长 -> HAS_GROWTH_RATE”；未知谓词不直接入库。
- 量值：保留 raw literal，同时归一 value/unit/time/region qualifier；维度冲突不合并。
- 事实键：normalized subject/predicate/object/literal/语义 qualifier；重复候选取最大置信度并合并 qualifier，evidence 按 `(fact,edge,chunk,evidence_text)` 去重。

**技术取舍**：HanLP 依存便宜、可解释，但跨句/隐含关系弱；LiteLLM 抽取更强，但成本高且可幻觉。因此使用级联候选生成，所有路径共用同一证据门禁。

---

# 传统 RAG 与 NEXUS 智能检索对比

## 技术方案评审材料 · 14 / 15

## 八、技术路径与取舍

**传统单路向量 RAG**

```text
query -> embedding -> pgvector cosine
      -> score = 1-cosine_distance >= threshold
      -> score DESC -> Top-K chunks -> LLM
```

**NEXUS 智能检索**

```text
query
 -> 意图分类 + subject route guard（confidence<0.60 -> unknown）
 -> 参数抽取（专业/岗位/年份/地区/KB/outline）
 -> 场景工具计划
      scenario_1 政策/报告 -> semantic chunks + section summary
      scenario_2 岗位/能力/布点 -> structured SQL / domain graph
      scenario_3 专业信息/教学标准 -> 领域事实或 chunks；显式请求才返回 graph
      scenario_4 教材 -> chunks + outline/section + evidence graph
      scenario_5 跨资产模板 -> P0 占位
 -> 权限/治理/范围过滤 -> 证据上下文 -> Composer -> 引用/审计
```

| 维度 | 传统向量 RAG | NEXUS 智能检索 |
|---|---|---|
| 决策单元 | query-chunk 相似度 | 意图、参数、领域工具、结构范围、chunk/section/graph |
| 数据通路 | 单一向量索引 | pgvector + 结构化 SQL + 领域/证据图 + Outline context |
| 精确问题 | 用语义相似猜数据 | 统计/枚举优先领域表，语义召回补叙事证据 |
| 范围与证据 | threshold+Top-K | 显式 outline 不越界、弱证据标记、章节扩展、引用回指 |
| 成本 | 低延迟、易评测 | LLM/工具编排延迟更高，需路由/工具/证据分层评测 |
| 失败模式 | 召回不全、相似但无答案 | 误路由、参数错、工具编排失败、延迟放大 |

**当前边界必须如实呈现**

- pgvector adapter 默认阈值 `0.70`；智能语义工具未显式指定时为 `0.50`。
- 框架支持原 query + 3-5 个扩展 query，但默认 executor 未注入 `expansion_provider`；`expand_queries=true` 仍回退原 query，记 `provider_not_configured`。
- P0 多 query 只按 chunk_id 去重取 max score，没有 RRF/多路 rerank；接线前后必须对比 Recall@K、nDCG@K、误扩展率、P95 延迟和成本。
- 本地无证据时仅 scenario_1/4 允许 request-scoped WebSearch；外部结果不持久化、不治理、不索引。

---

# v2.0 组件选型、实现路径与评审决策

## 技术方案评审材料 · 15 / 15

**最终选型**

| 能力 | 选型 | 优势 | 代价/不选择的替代 |
|---|---|---|---|
| 中文 NLP | `HanLPAdapter + 领域词典`，提供 `RuleOnlyAnalyzer` 降级 | 中文分句/NER/POS/依存统一，offset 可用于证据 | 模型内存/延迟上升；不同时引入 spaCy/NLTK 制造重复 tokenizer/Pipeline |
| 语义 | 已有 `bge-large-zh-v1.5` + `bge-reranker-large` | 中文近重复候选、主题边界、检索共用模型底座 | 向量不作正式身份/事实决策 |
| 语义例外 | 既有 LiteLLM + 版本化 Prompt | 处理跨句、隐含分类/关系和中间置信冲突 | 成本/幻觉；必须 Schema+证据+规则门禁 |
| 结构质量 | Pydantic + 领域验证器；批数据可选 Pandera | 与现有 Python/Worker 契约相容，对象和表校验分工清晰 | GE 只在需数据档案/跨批次运营时引入，避免 P0 平台化过度 |
| 近重复 | SHA/业务键 + MinHash/LSH 候选 + BGE 复核 | 兼顾吞吐和改写发现 | 不自动合并，避免不同版本/效力误合并 |

**实现路径**

1. **Phase A，黄金集与适配层**：标注噪声/低价值、句界、实体、关系、近重复、Chunk QA；定义 `NlpAnalyzer` 契约，冻结 char-offset、model/dictionary version 和降级语义。
2. **Phase B，shadow mode**：HanLP 注释只写评测日志/派生 artifact，不删数据、不改分数/状态；测 F1、误删率、P95、内存和降级率。
3. **Phase C，低风险接入**：先用于 hard-max 分句、实体候选和 MinHash 脱模板；与现行 `semantic_repack` 做 A/B，不改治理准入。
4. **Phase D，质量增强**：实现一致性/可用性 evaluator，未知 check fail-closed；Pandera 仅接入需批校验的 Pipeline B profile。
5. **Phase E，受控自动化**：只有经校准阈值达标的高置信软判别才自动生效；保留 reason/evidence/version/audit 和一键回退 RuleOnly。

**评审需冻结**：HanLP 具体模型/许可证/部署形态；黄金集与误删率上限；MinHash/BGE 候选阈值；中文 target/hard-max；四维指标权重；未知 evaluator fail-closed 策略；NLP annotation 先运行时还是经 Data Model Gate 持久化。

**验收底线**：追溯/引用/KG 事实证据覆盖 100%；权限泄漏和未授权 L3/L4 外发为 0；不产生重复有效对象；NLP 降级可用；新策略在 Recall/nDCG/引用准确率上显著不劣且误删率满足冻结阈值。

**主要实现依据**：`ARCHITECT.md`、`SPEC.md`、`config/governance_rules_v2.json`、`pipeline/mineru_converter.py`、`crawler/quality_gate.py`、`normalize/service.py`、`structured_parse/*`、`domain_normalize/*`、`ai_governance/quality_scorer.py`、`governance/decision_service.py`、`knowledge/semantic_repack.py`、`knowledge/chunking_strategies/*`、`scripts/chunk_quality_report.py`、`evidence_graph/*`、`index/pgvector_search.py`、`retrieval/*`。
