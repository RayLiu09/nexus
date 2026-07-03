# 职业院校教材与企业实训任务书类资产知识加工优化设计方案

## 1. 背景

`course_textbook` 教材类资产已经纳入 AI 治理规则体系，并通过 `textbook_kb` 进入 NEXUS 知识加工链路。当前实现对教材类资产主要采用通用 `semantic_repack` 生成 `knowledge_chunk`，并允许 Evidence Graph 基于语义 chunks 构建。

但职业院校教材存在明显子类型差异：

- 理论知识型教材：以概念、定义、原理、机制、制度、知识点关系为主。
- 实训操作型 / 任务型教材：以项目、任务、任务背景、任务分析、操作步骤、数据采集表、实训产物和任务思考为主。
- 混合型教材：同一教材内同时包含理论章节和实训任务章节。

因此，教材类资产不应统一默认导向 Evidence Graph。理论知识型教材适合构建 Evidence Graph；任务型教材更适合提炼为树形任务大纲，并将任务节点投影为统一 `knowledge_chunk`，支撑检索、QA、原文定位和后续索引。

同一套 Task Outline 能力也需要兼容企业实训任务书类数据资产。NEXUS v8.0 样本清单中存在“企业真实任务书 / D4-6 实训指导书”类资产，这类数据不一定是完整教材，也不一定具备出版社、目录、章节、项目等教材特征，但通常天然具有任务名称、背景、要求、资源和任务步骤。其知识消费方式同样不是 Evidence Graph，而是任务操作指导结构化表达。

典型样本：

- `c62de38a-2070-40fb-beb6-26798898982d`
- 文件名：`47411-A0电子商务数据分析实践（初级）.pdf`
- 资产形态：电子商务数据分析实训操作教材。
- 推荐加工方式：任务树 / 任务大纲 + 任务感知 chunks。
- 不推荐默认加工方式：完整 Evidence Graph。

企业实训任务书样例：

```text
任务名称：数据行列的转换
背景名称：数据行列的转换
背景内容：贵州清韵企业计划对去年各月销售数据进行分析，需要全面、准确整理销售数据。
要求：对店铺去年各月销售数据进行行列转换。
资源：数据行列的转换-原始数据.xlsx
任务步骤：
1. 在 Power BI Desktop 中导入“数据行列的转换-原始数据”工作表，点击“转换数据”。
2. 在 Power Query 编辑器“转换”选项卡下单击“转置”。
3. 选中第一列，单击“将第一行用作标题”。
4. 在“应用的步骤”中删除“更改的类型”，完成数据行列转换。
```

该类资产应被加工为单任务或多任务 Task Outline，并投影为统一 `knowledge_chunk`，而不是另建企业任务书专用 chunk 表。

## 2. 设计目标

本方案目标是优化 `course_textbook` 教材类资产的知识加工策略，并在领域模型和 chunk metadata 上兼容后续企业任务实现书 / 企业实训任务书类资产。当前实施优先覆盖教材类资产；企业任务实现书类资产暂不落地，仅预留扩展边界。

核心目标：

1. 为教材类资产增加子类型识别：`theory_knowledge`、`training_operation`、`hybrid`、`unknown`。
2. 理论知识型教材继续支持语义 chunks + Evidence Graph。
3. 任务型教材构建任务树 / 任务大纲，表达项目、任务、任务章节、操作步骤、任务产物等结构。
4. 任务树节点必须投影为统一 `knowledge_chunk`，不另起一套 chunk 存储。
5. `knowledge_chunk` 继续作为检索、QA、索引、原文定位和 Evidence Graph 候选选择的统一底座。
6. 任务树作为领域主数据，`knowledge_chunk` 作为检索投影，两者通过 `outline_node_id`、`normalized_ref_id`、`source_block_ids` 和 `locator` 关联。
7. Evidence Graph 构建增加准入策略，任务操作指导类资产默认不推荐构图。
8. Task Outline profile 应抽象为跨资产类型能力，不绑定死在 `course_textbook`，以便后续接入企业任务实现书 / 企业实训任务书。

## 3. 非目标

本方案不做以下事情：

- 不替代现有 `knowledge_chunk` 表。
- 不为任务型教材建立独立的 task_chunk 存储底座。
- 不为企业实训任务书建立独立的 training_task_chunk 存储底座。
- 当前阶段不实现企业任务实现书 / 企业实训任务书的分类、抽取、入库、Console 展示和重建流程。
- 不改变 `normalized_asset_ref` 作为知识加工输入的架构约束。
- 不从 raw file、MinerU raw output 或局部页面直接构建知识模型。
- 不要求本阶段立即实现完整人工维护工作台。
- 不要求本阶段立即实现对外公开任务树 API。
- 不要求本阶段立即扩展大量 `chunk_type` 枚举。

## 4. 总体架构

教材类知识加工总体流程，并预留企业实训任务书扩展点：

```text
normalized_asset_ref(document/record-like-document)
  -> content profile detection
      -> course_textbook subtype detection
      -> enterprise_training_task detection (reserved)
  -> processing profile routing
      -> theory_knowledge
          -> semantic chunks
          -> Evidence Graph candidate selection
          -> Evidence Graph
      -> training_operation
          -> task outline extraction
          -> task-aware chunk projection
          -> task retrieval / QA
      -> enterprise_training_task (reserved)
          -> task outline extraction
          -> task-aware chunk projection
      -> hybrid
          -> chapter-level subtype routing
          -> theory chapters: graph path
          -> task chapters: task outline path
  -> unified knowledge_chunk
  -> index adapter / search / QA / source preview
```

核心关系：

```text
normalized_asset_ref
  -> task_outline_profile
  -> task_outline_node
  -> knowledge_chunk
       chunk_metadata.outline_node_id
       chunk_metadata.task_profile
       chunk_metadata.textbook_subtype
       source_block_ids
       locator
```

原则：

- `task_outline_node` 是任务操作指导类资产的领域结构源。
- `knowledge_chunk` 是所有教材知识加工路径的统一检索底座。
- 任务树不能替代 chunks。
- chunks 不应承担完整树结构主数据职责。
- 高价值任务树节点需要投影为 chunks。

## 5. 教材子类型识别

### 5.1 子类型枚举

| 子类型 | 说明 | 推荐知识加工方式 |
|---|---|---|
| `theory_knowledge` | 以概念、定义、原理、分类、机制、制度、知识点关系为主 | 语义 chunks + Evidence Graph |
| `training_operation` | 以项目、任务、任务背景、任务分析、操作步骤、实训表单、任务产物为主 | 任务树 / 任务大纲 + 任务感知 chunks |
| `hybrid` | 理论章节和任务章节混合存在 | 章节级分流，理论章节走 Graph，任务章节走 Task Outline |
| `unknown` | 特征不足或解析质量不足，无法可靠判定 | 先生成基础 semantic chunks，进入复核或等待人工选择加工方式 |

### 5.2 识别输出

建议在教材 profile 中保存：

```json
{
  "textbook_subtype": "training_operation",
  "subtype_confidence": 0.91,
  "processing_profile": "task_outline",
  "evidence_graph_admission": "not_recommended",
  "subtype_evidence": [
    "目录和正文包含大量项目/任务结构",
    "正文包含任务目标、任务背景、任务分析、任务实施、操作步骤",
    "存在多张数据采集表和实训产物表"
  ]
}
```

### 5.3 识别规则

| 特征 | 倾向子类型 |
|---|---|
| 大量出现“项目、任务、任务目标、任务背景、任务分析、任务实施、操作步骤、任务思考、实践训练” | `training_operation` |
| 大量出现“概念、定义、原理、机制、分类、影响因素、知识点、理论基础” | `theory_knowledge` |
| 章节中既有理论讲解又有完整任务结构 | `hybrid` |
| 表格多为数据采集表、记录表、填报表、检查表、实训表 | `training_operation` |
| 图表多为理论框架、关系模型、指标体系 | `theory_knowledge` |
| 目录缺失、正文解析不完整、结构不清 | `unknown` 或 `review_required` |

## 6. 企业任务实现书 / 企业实训任务书兼容预留

本章节是扩展设计，不进入当前实现范围。

企业任务实现书 / 企业实训任务书不是教材子类型，但属于同一类“任务操作指导型内容”。它通常没有完整教材的目录、章节、出版社、版权页等结构，但任务边界更清晰，常见字段包括：

| 字段 | 说明 | 映射到 Task Outline |
|---|---|---|
| 任务名称 / 标题 | 例如“数据行列的转换” | `task.title` |
| 背景名称 | 常与任务名称一致，也可能是场景标题 | `task_section.section_type = task_background` 的标题 |
| 背景内容 | 企业场景、业务问题、任务缘由 | `task_background.content` |
| 要求 | 任务目标、完成要求、验收标准 | `task_objective` 或 `assessment` |
| 资源 | 数据文件、工具、附件、模板 | `task_artifact`，`artifact_type = source_resource` |
| 任务步骤 | 顺序操作指令 | `operation_step` |
| 输出物 | 若源文档显式给出报告、表格、模型等 | `task_artifact`，`artifact_type = deliverable` |

### 6.1 企业任务书 profile（预留）

建议识别为：

```json
{
  "task_profile": "enterprise_training_task",
  "processing_profile": "task_outline",
  "subtype_confidence": 0.95,
  "evidence_graph_admission": "not_recommended",
  "subtype_evidence": [
    "源内容包含任务名称、背景内容、要求、资源、任务步骤",
    "正文以顺序操作指导为主",
    "缺少理论概念关系和完整教材目录结构"
  ]
}
```

### 6.2 企业任务书节点示例（预留）

```json
{
  "node_type": "task",
  "title": "数据行列的转换",
  "summary": "贵州清韵企业需要整理去年各月销售数据，完成销售数据行列转换，为后续分析奠定基础。",
  "source_block_ids": ["block-task-001"],
  "metadata": {
    "task_profile": "enterprise_training_task",
    "business_context": "贵州特色产品销售数据分析",
    "tools": ["Power BI Desktop", "Power Query"],
    "source_resources": ["数据行列的转换-原始数据.xlsx"]
  }
}
```

背景节点：

```json
{
  "node_type": "task_section",
  "section_type": "task_background",
  "title": "数据行列的转换",
  "content": "在快速发展的商业环境中，数据分析已成为企业决策不可或缺的一部分。贵州清韵计划对去年各月销售数据进行分析，需要全面、准确整理销售数据。",
  "source_block_ids": ["block-task-002"]
}
```

要求节点：

```json
{
  "node_type": "task_section",
  "section_type": "task_objective",
  "title": "要求",
  "content": "对店铺去年各月销售数据进行行列转换。",
  "source_block_ids": ["block-task-003"]
}
```

资源节点：

```json
{
  "node_type": "task_artifact",
  "artifact_type": "source_resource",
  "title": "数据行列的转换-原始数据.xlsx",
  "description": "用于 Power BI Desktop 导入和行列转换的原始销售数据工作表。",
  "source_block_ids": ["block-task-004"]
}
```

操作步骤节点：

```json
{
  "node_type": "operation_step",
  "section_type": "operation_steps",
  "step_no": 2,
  "title": "执行转置",
  "instruction": "在 Power Query 编辑器中的“转换”选项卡下单击“转置”命令。",
  "tools": ["Power Query"],
  "inputs": ["数据行列的转换-原始数据.xlsx"],
  "outputs": ["已转置的数据表"],
  "source_block_ids": ["block-task-006"]
}
```

### 6.3 企业任务书 chunk 投影示例（预留）

企业任务书同样投影到统一 `knowledge_chunk`：

```json
{
  "knowledge_type_code": "textbook_kb",
  "chunk_type": "semantic_block",
  "chunking_strategy": "semantic_repack",
  "content": "操作步骤 2：在 Power Query 编辑器中的“转换”选项卡下单击“转置”命令。",
  "source_block_ids": ["block-task-006"],
  "chunk_metadata": {
    "semantic_variant": "task_outline_repack",
    "domain_model": "task_outline.v1",
    "task_profile": "enterprise_training_task",
    "outline_node_id": "node-step-002",
    "task_title": "数据行列的转换",
    "node_type": "operation_step",
    "section_type": "operation_steps",
    "step_no": 2,
    "tools": ["Power Query"],
    "anchor_role": "operation_step",
    "graph_candidate": false
  }
}
```

说明：

- `knowledge_type_code` 短期可继续复用 `textbook_kb`，因为企业实训任务书在业务分类中属于 D4-6 实训指导书 / 课程资源邻域。
- 如果后续需要更精细知识类型，可新增 `training_task_kb`，但底层仍写入同一 `knowledge_chunk`。
- 企业任务书通常是单任务资产，不强制要求 project/module 层级。
- 当前实现暂不启用 `enterprise_training_task` 的自动识别、任务树持久化、chunks 投影和 Console 视图，仅保证 `task_outline` 模型命名和 metadata 字段能够兼容该扩展。

## 7. 任务操作指导类领域模型

任务型教材和企业实训任务书的核心领域模型都是树形任务大纲。二者差异主要在层级深度：

- 任务型教材通常是 `book -> project -> task -> section/step/artifact`。
- 企业实训任务书通常是 `task -> section/step/artifact`。

推荐结构：

```text
教材 / 实训任务书
  -> 工作领域 / 项目 / 模块
      -> 任务
          -> 任务目标
          -> 任务背景
          -> 任务分析
          -> 知识准备 / 知识回顾
          -> 任务实施 / 操作步骤
              -> 步骤 1
              -> 步骤 2
              -> 步骤 3
          -> 任务产物 / 表单 / 输出物
          -> 任务思考 / 训练题
          -> 评价要点 / 检查点
```

对于单任务企业任务书，可以省略工作领域 / 项目 / 模块层：

```text
任务：数据行列的转换
  -> 任务背景
  -> 要求
  -> 资源
  -> 操作步骤
      -> 步骤 1 导入数据
      -> 步骤 2 转置
      -> 步骤 3 将第一行用作标题
      -> 步骤 4 删除更改的类型
```

### 7.1 节点类型

| `node_type` | 说明 |
|---|---|
| `book` | 教材根节点 |
| `project` | 项目、工作领域、模块、单元 |
| `task` | 任务 |
| `task_section` | 任务下的结构化章节，如背景、目标、分析、知识准备 |
| `operation_step` | 操作步骤 |
| `task_artifact` | 表格、模板、报告、输出文件、源数据、检查表等任务产物或资源 |
| `assessment` | 任务思考、练习、评价项 |

### 7.2 任务章节类型

| `section_type` | 说明 |
|---|---|
| `task_objective` | 任务目标、学习目标、能力目标 |
| `task_background` | 任务背景、场景描述 |
| `task_analysis` | 任务分析、需求分析 |
| `knowledge_prepare` | 知识准备、知识回顾、知识链接 |
| `operation_steps` | 操作步骤、任务实施 |
| `task_artifact` | 任务产物、数据采集表、模板表 |
| `source_resource` | 原始数据、附件、素材、工具文件 |
| `task_reflection` | 任务思考、拓展训练 |
| `assessment` | 检查点、评价要点 |

### 7.3 任务节点示例

```json
{
  "node_type": "task",
  "title": "任务一 市场数据采集",
  "task_code": "project_1_task_1",
  "summary": "围绕市场数据采集场景，完成采集渠道、采集指标和采集表设计。",
  "learning_objectives": [
    "能够根据需求确定数据采集渠道",
    "能够根据需求明确数据采集指标",
    "能够遵守电子商务法进行合法合规采集"
  ],
  "source_block_ids": ["block-p11-081", "block-p11-082"],
  "locator": {
    "page_start": 11,
    "page_end": 12,
    "blocks": []
  }
}
```

### 7.4 操作步骤示例

```json
{
  "node_type": "operation_step",
  "section_type": "operation_steps",
  "step_no": 3,
  "title": "制作关键词搜索指数月均值数据采集表",
  "instruction": "根据关键词搜索指数数据，按月份填写整体日均值和移动日均值。",
  "tools": ["Excel"],
  "inputs": ["关键词搜索指数"],
  "outputs": ["关键词搜索指数月均值数据采集表"],
  "related_artifact_node_ids": ["node-artifact-fig-1-1"],
  "source_block_ids": ["block-p14-132", "block-p14-135"]
}
```

### 7.5 任务产物示例

```json
{
  "node_type": "task_artifact",
  "artifact_type": "data_collection_table",
  "title": "智能门锁竞争数据采集表",
  "description": "用于采集商品名称、链接、价格、月销量等竞品商品销售数据。",
  "fields": ["商品名称", "链接", "价格", "月销量"],
  "source_block_ids": ["block-p15-159"]
}
```

## 8. 建议存储结构

### 8.1 `task_outline_profile`

用于保存任务操作指导类资产 profile。教材和企业实训任务书均可使用该表。

| 字段 | 说明 |
|---|---|
| `id` | 主键 |
| `normalized_ref_id` | 关联 `normalized_asset_ref.id` |
| `asset_version_id` | 资产版本 |
| `asset_profile` | `course_textbook` / `enterprise_training_task` / 其他任务操作指导类 profile |
| `title` | 教材标题或任务书标题 |
| `textbook_subtype` | 教材子类型；非教材任务书可为空 |
| `task_profile` | `textbook_training_operation` / `enterprise_training_task` |
| `subtype_confidence` | 子类型或任务 profile 识别置信度 |
| `processing_profile` | `evidence_graph` / `task_outline` / `hybrid` / `semantic_only` |
| `evidence_graph_admission` | `recommended` / `not_recommended` / `chapter_selective` / `unknown` |
| `source_block_ids` | 类型判断证据 blocks |
| `metadata` | 扩展字段，如课程方向、适用层次、章节数量、企业场景、工具等 |

### 8.2 `task_outline_node`

用于保存任务树节点。教材任务树和企业实训任务书任务树均落在此表。

| 字段 | 说明 |
|---|---|
| `id` | 主键 |
| `normalized_ref_id` | 归一化资产 |
| `profile_id` | 教材 profile |
| `parent_id` | 父节点 |
| `node_type` | 节点类型 |
| `section_type` | 任务章节类型 |
| `title` | 标题 |
| `content` | 正文 |
| `summary` | 摘要 |
| `order_no` | 同级顺序 |
| `depth` | 树深度 |
| `source_block_ids` | 来源 blocks |
| `locator` | 原文定位 |
| `metadata` | 工具、输入、输出、能力点、表字段等 |

### 8.3 是否需要单独任务 chunk 表

不需要。

任务操作指导类资产的 chunks 必须继续写入统一 `knowledge_chunk`。任务树表是领域主数据，`knowledge_chunk` 是检索投影。

```text
task_outline_node
  -> emits
knowledge_chunk
```

如果后续需要在代码层避免与教材强绑定，建议领域模块命名为 `task_outline`，而不是 `course_textbook_task_outline`。教材只是该 profile 的一种来源。

## 9. 与 `knowledge_chunk` 的兼容设计

### 9.1 统一底座原则

所有教材子类型和企业实训任务书最终都应产出统一 `knowledge_chunk`：

```text
theory_knowledge
  -> semantic units
  -> knowledge_chunk
  -> Evidence Graph

training_operation
  -> task outline nodes
  -> knowledge_chunk
  -> task retrieval / QA

enterprise_training_task
  -> task outline nodes
  -> knowledge_chunk
  -> task retrieval / QA

hybrid
  -> chapter-level semantic units / task nodes
  -> knowledge_chunk
  -> selective Evidence Graph / task retrieval
```

### 9.2 任务操作指导类 chunk 映射

短期建议不新增大量 `chunk_type`。继续使用：

```text
chunk_type = semantic_block
knowledge_type_code = textbook_kb
```

差异通过以下字段表达：

| 字段 | 建议 |
|---|---|
| `chunking_strategy` | 后续可新增 `task_outline_repack`；短期可仍用 `semantic_repack`，在 metadata 标注 `semantic_variant` |
| `chunk_metadata.domain_model` | `task_outline.v1` |
| `chunk_metadata.task_profile` | `textbook_training_operation` / `enterprise_training_task` |
| `chunk_metadata.textbook_subtype` | 教材子类型；企业实训任务书可为空 |
| `chunk_metadata.outline_node_id` | 对应任务树节点 |
| `chunk_metadata.project_title` | 所属项目 |
| `chunk_metadata.task_title` | 所属任务 |
| `chunk_metadata.node_type` | `task` / `task_section` / `operation_step` / `task_artifact` |
| `chunk_metadata.section_type` | `task_background` / `task_analysis` / `operation_steps` 等 |
| `chunk_metadata.anchor_role` | `task_overview` / `operation_step` / `task_artifact` 等 |

### 9.3 chunk 示例：任务背景

```json
{
  "normalized_ref_id": "be6079d7-4ac8-43c3-b182-3558bb7344de",
  "knowledge_type_code": "textbook_kb",
  "chunk_type": "semantic_block",
  "chunking_strategy": "semantic_repack",
  "content": "任务背景：随着数字经济的发展，企业越来越重视电商数据分析...",
  "source_block_ids": ["block-p12-090", "block-p12-091"],
  "locator": {
    "page_start": 12,
    "page_end": 12,
    "blocks": []
  },
  "chunk_metadata": {
    "semantic_variant": "task_outline_repack",
    "domain_model": "task_outline.v1",
    "task_profile": "textbook_training_operation",
    "textbook_subtype": "training_operation",
    "outline_node_id": "node-task-bg-001",
    "project_title": "项目一 基础数据采集",
    "task_title": "任务一 市场数据采集",
    "node_type": "task_section",
    "section_type": "task_background",
    "anchor_role": "task_background"
  }
}
```

### 9.4 chunk 示例：操作步骤

```json
{
  "normalized_ref_id": "be6079d7-4ac8-43c3-b182-3558bb7344de",
  "knowledge_type_code": "textbook_kb",
  "chunk_type": "semantic_block",
  "chunking_strategy": "semantic_repack",
  "content": "操作步骤 3：制作关键词搜索指数月均值数据采集表。根据关键词搜索指数数据，按月份填写整体日均值和移动日均值。",
  "source_block_ids": ["block-p14-132", "block-p14-135"],
  "locator": {
    "page_start": 14,
    "page_end": 14,
    "blocks": [
      {
        "block_id": "block-p14-135",
        "page": 14,
        "bbox": [55, 72, 468, 264]
      }
    ]
  },
  "chunk_metadata": {
    "semantic_variant": "task_outline_repack",
    "domain_model": "task_outline.v1",
    "task_profile": "textbook_training_operation",
    "textbook_subtype": "training_operation",
    "outline_node_id": "node-step-003",
    "project_title": "项目一 基础数据采集",
    "task_title": "任务一 市场数据采集",
    "node_type": "operation_step",
    "section_type": "operation_steps",
    "step_no": 3,
    "tools": ["Excel"],
    "outputs": ["关键词搜索指数月均值数据采集表"],
    "related_artifact_node_ids": ["node-artifact-fig-1-1"],
    "anchor_role": "operation_step"
  }
}
```

### 9.5 chunk 示例：任务产物

```json
{
  "normalized_ref_id": "be6079d7-4ac8-43c3-b182-3558bb7344de",
  "knowledge_type_code": "textbook_kb",
  "chunk_type": "semantic_block",
  "chunking_strategy": "semantic_repack",
  "content": "任务产物：智能门锁竞争数据采集表。字段包括商品名称、链接、价格、月销量，用于采集竞品商品销售数据。",
  "source_block_ids": ["block-p15-159"],
  "locator": {
    "page_start": 15,
    "page_end": 15,
    "blocks": [
      {
        "block_id": "block-p15-159",
        "page": 15,
        "bbox": [163, 574, 360, 661]
      }
    ]
  },
  "chunk_metadata": {
    "semantic_variant": "task_outline_repack",
    "domain_model": "task_outline.v1",
    "task_profile": "textbook_training_operation",
    "textbook_subtype": "training_operation",
    "outline_node_id": "node-artifact-fig-1-2",
    "project_title": "项目一 基础数据采集",
    "task_title": "任务一 市场数据采集",
    "node_type": "task_artifact",
    "artifact_type": "data_collection_table",
    "fields": ["商品名称", "链接", "价格", "月销量"],
    "anchor_role": "task_artifact"
  }
}
```

## 10. 哪些任务树节点需要投影 chunks

| 节点类型 | 是否生成 chunk | 说明 |
|---|---:|---|
| `project` / `module` | 可生成 | 生成项目概览 chunk，支持项目级检索 |
| `task` | 必须生成 | 任务是任务操作指导类资产核心检索入口 |
| `task_objective` | 必须生成 | 对应学习目标和能力目标 |
| `task_background` | 必须生成 | 对应任务场景 |
| `task_analysis` | 必须生成 | 对应任务逻辑和需求分析 |
| `knowledge_prepare` | 必须生成 | 对应前置知识 |
| `operation_step` | 必须生成 | 任务操作指导类资产最重要的检索单元 |
| `task_artifact` | 必须生成 | 表格、模板、输出物是关键产物 |
| `task_reflection` | 可生成 | 思考题、练习题具有教学检索价值 |
| `assessment` | 可生成 | 评价项、检查点可用于教学质检 |
| 目录、版权页、附录、装饰图 | 不生成 | 属于导航或噪声，不应进入检索知识块 |

## 11. Evidence Graph 准入策略

教材和企业实训任务书的 Evidence Graph 构建不应只判断是否存在 chunks，还应判断内容 profile、教材子类型和章节加工 profile。

### 11.1 资产级准入

| 内容 profile | Evidence Graph 策略 |
|---|---|
| `course_textbook / theory_knowledge` | 推荐构建 |
| `course_textbook / training_operation` | 默认不推荐构建；推荐构建任务大纲 |
| `course_textbook / hybrid` | 允许按章节选择性构建 |
| `enterprise_training_task` | 默认不推荐构建；推荐构建任务大纲 |
| `unknown` | 不自动构建，提示先完成类型识别或人工选择 |

### 11.2 chunk 级准入

理论型 chunk：

```json
{
  "graph_candidate": true,
  "section_processing_profile": "evidence_graph"
}
```

任务操作指导类 chunk：

```json
{
  "graph_candidate": false,
  "section_processing_profile": "task_outline"
}
```

混合型教材可以在章节级设置：

```text
理论章节 -> graph_candidate = true
任务章节 -> graph_candidate = false
```

### 11.3 Console 提示

任务型教材或企业实训任务书进入 Evidence Graph 视图时，建议提示：

```text
该资产识别为“任务操作指导类内容”，更适合构建任务大纲。
Evidence Graph 不作为推荐加工方式。
```

按钮策略：

| 场景 | Evidence Graph | Task Outline |
|---|---|---|
| 理论知识型 | 可用 / 推荐 | 可选 |
| 实训操作型 | 默认弱化或需确认 | 可用 / 推荐 |
| 企业实训任务书 | 默认弱化或需确认 | 可用 / 推荐 |
| 混合型 | 可按章节选择 | 可用 |
| unknown | 需先识别类型 | 需先识别类型 |

## 12. 任务树抽取流程

建议任务操作指导类资产加工流程：

```text
normalized_document.blocks
  -> heading/key-label normalization
  -> content profile detection
  -> textbook subtype detection when applicable
  -> task section candidate detection
  -> task scope grouping
  -> task outline node extraction
  -> table/image/artifact binding
  -> source locator binding
  -> quality validation
  -> persist outline domain tables
  -> project outline nodes to knowledge_chunk
```

对于企业任务书这类短文本或结构化文本，也可从 `normalized_record` / `record_body` 投影为任务树；但治理和知识加工输入仍必须是 `normalized_asset_ref`，不能绕过 normalized contract。

### 12.1 heading / key-label normalization

任务型教材中，MinerU 可能把短标题识别为 paragraph。企业任务书中也常见 `背景名称：`、`背景内容：`、`要求：`、`资源：`、`任务步骤：` 这类 key-label 结构。知识加工阶段需要统一归一为任务结构边界。

教材短标题示例：

- `编写说明`
- `前言`
- `任务目标`
- `任务背景`
- `任务分析`
- `任务实施`
- `任务思考`

企业任务书 key-label 示例：

- `背景名称：`
- `背景内容：`
- `要求：`
- `资源：`
- `任务步骤：`

这些结构都应作为任务节点或任务章节边界，避免把背景、要求和步骤混成一个普通段落。

### 12.2 任务范围聚合

聚合规则：

```text
任务 X 起点
  -> 下一个任务 X+1
  -> 或下一个项目 / 模块
  -> 或文档结束
```

任务内再按短标题划分 section。

企业任务书如果只有一个任务，则整个资产可作为一个 task 范围；如果存在多个 `任务名称` 或编号任务，则按任务名称切分。

### 12.3 表格 / 图片 / 资源 / 任务产物绑定

表格、图片、附件资源不应作为孤立信息处理。对于数据采集表、填报表、记录表、检查表、原始数据文件、Power BI 文件、Excel 模板等，应绑定到所在任务和操作步骤。

示例：

```text
图1-1 关键词搜索指数月均值数据采集表
  -> 项目一 基础数据采集
  -> 任务一 市场数据采集
  -> 操作步骤：制作关键词搜索指数月均值数据采集表

图1-2 智能门锁竞争数据采集表
  -> 项目一 基础数据采集
  -> 任务一 市场数据采集
  -> 任务产物：竞品数据采集表

数据行列的转换-原始数据.xlsx
  -> 任务：数据行列的转换
  -> 资源：原始销售数据工作表
  -> 步骤 1：导入数据
```

## 13. 质量评价

任务操作指导类资产的质量评价应区别于理论型教材。

| 指标 | 说明 |
|---|---|
| `task_coverage` | 识别出的任务数 / 目录或正文任务数 |
| `section_coverage` | 任务背景、目标、分析、步骤等结构覆盖率 |
| `step_order_validity` | 操作步骤顺序是否完整 |
| `artifact_binding_rate` | 表格、模板、输出物是否绑定到任务 |
| `resource_binding_rate` | 原始数据、附件、工具文件是否绑定到任务或步骤 |
| `locator_coverage` | 节点是否具备原文定位 |
| `chunk_projection_coverage` | 高价值任务节点是否投影为 chunks |
| `noise_ratio` | 版权页、目录、页眉页脚等噪声比例 |
| `orphan_block_ratio` | 未归属任务的大块正文比例 |

建议准入阈值：

```text
task_coverage >= 0.8
locator_coverage >= 0.95
artifact_binding_rate >= 0.7
resource_binding_rate >= 0.7 when resources exist
chunk_projection_coverage >= 0.9
noise_ratio <= 0.05
```

不满足时：

- 任务大纲状态进入 `review_required`。
- 不阻断 normalized asset 本身治理状态。
- 不自动对外索引低质量任务树。
- Console 提示需要人工校正或重新构建。

## 14. 检索与 QA 使用方式

### 14.1 基础召回

检索仍然以 `knowledge_chunk` 为统一入口：

```text
query
  -> vector/text search over knowledge_chunk
  -> return chunk_id / normalized_ref_id / locator / source_block_ids
```

### 14.2 结构补全

如果命中 chunk 携带 `chunk_metadata.outline_node_id`，可以回查任务树：

```text
knowledge_chunk.chunk_metadata.outline_node_id
  -> task_outline_node
  -> parent task
  -> parent project
  -> sibling operation steps
  -> related task artifacts
```

这样可以从单一命中补全任务上下文。

示例问题：

```text
智能门锁竞争数据采集表怎么填写？
```

理想返回：

```text
命中任务：项目一 基础数据采集 / 任务一 市场数据采集
命中节点：任务产物 / 图1-2 智能门锁竞争数据采集表
相关字段：商品名称、链接、价格、月销量
相关步骤：制作竞品数据采集表
原文定位：page 15, block-p15-159
```

## 15. 人工维护策略

任务操作指导类资产的人工维护应以任务树为主，不直接把 `knowledge_chunk` 当作人工维护主数据。

推荐流程：

```text
人工编辑 task_outline_node
  -> 标记相关 projected chunks stale
  -> 重建受影响节点对应 chunks
  -> 更新索引状态
```

原则：

- 用户维护任务标题、任务章节、步骤、产物时，更新任务树。
- chunks 是任务树的检索投影，由系统重建。
- 避免用户直接修改 chunk 内容导致任务树和 chunks 漂移。

## 16. 与现有 NEXUS 架构的关系

| 现有对象 | 本方案关系 |
|---|---|
| `normalized_asset_ref` | 仍是知识加工输入，不从 raw 或 MinerU raw 直接加工 |
| `knowledge_chunk` | 统一知识块底座，任务型教材和企业实训任务书都必须写入 |
| `index_manifest` | 后续索引仍以 chunks 为输入 |
| `knowledge_graph_build` | 只消费适合构图的 chunks |
| `task_outline_profile` | 新增任务大纲 profile 领域表，兼容教材和企业任务书 |
| `task_outline_node` | 新增任务树领域表，兼容教材和企业任务书 |
| `governance_result` | 不直接保存任务树，只保存治理决策和质量结果 |

## 17. 分阶段落地计划

### 阶段一：子类型识别与任务树最小模型

目标：

- 新增教材子类型识别。
- 新增 `task_outline_profile`。
- 新增 `task_outline_node`。
- 对任务型教材抽取项目 / 任务 / 任务章节基础树。
- Evidence Graph 对 `training_operation` 默认不推荐。
- 在表结构和 metadata 字段上预留 `enterprise_training_task`，但不启用对应抽取流程。

验收：

- `c62de38a-2070-40fb-beb6-26798898982d` 可识别为 `training_operation`。
- 可生成项目、任务、任务背景、任务分析、操作步骤、任务产物节点。
- 每个节点具备 `source_block_ids` 和 locator。
- schema / metadata 设计允许后续填充 `task_profile = enterprise_training_task`，但当前不会自动生成企业任务书任务树。

### 阶段二：任务感知 chunks

目标：

- 将任务树高价值节点投影到统一 `knowledge_chunk`。
- chunk metadata 增加 `outline_node_id`、`task_title`、`section_type`、`anchor_role`。
- 保留当前 `chunk_type=semantic_block` 以兼容现有链路。
- 任务操作指导类 chunks 不进入默认 Evidence Graph 候选。

验收：

- 任务背景、任务分析、操作步骤、任务产物均有 chunks。
- 版权页、目录、附录、装饰图等不进入 chunks。
- 检索命中 chunk 后可回查任务树上下文。

### 阶段三：Console 展示与人工维护

目标：

- 资产详情知识块 tab 增加任务大纲视图。
- 支持任务树定位原文。
- 支持任务节点人工修正。
- 修正后可重建相关 chunks。

验收：

- 用户可以按项目/任务浏览教材。
- 用户可以定位任务节点原文。
- 用户修改任务节点后，相关 chunks 标记 stale 并可重建。

### 阶段四：混合型教材章节级分流

目标：

- 对 `hybrid` 教材做章节级 profile。
- 理论章节可进入 Evidence Graph。
- 任务章节进入 Task Outline。

验收：

- 同一教材内可同时存在 graph-ready chunks 和 task-outline chunks。
- Evidence Graph 只消费 graph-ready chunks。

### 阶段五：企业任务实现书扩展预留落地

目标：

- 启用 `enterprise_training_task` profile 识别。
- 支持企业任务实现书 / 企业实训任务书的 key-label normalization。
- 支持单任务资产抽取任务、背景、要求、资源和操作步骤。
- 将企业任务书任务树投影到统一 `knowledge_chunk`。

验收：

- “数据行列的转换”类企业任务书可识别为 `enterprise_training_task`。
- 可生成任务、任务背景、要求、资源、操作步骤节点。
- 资源文件和操作步骤具备 `source_block_ids` 和 locator。
- 企业任务书 chunks 不进入默认 Evidence Graph 候选。

## 18. 对样本资产的期望结果

对 `c62de38a-2070-40fb-beb6-26798898982d` 的理想结构：

```text
电子商务数据分析实践（初级）
  编写说明
  前言
  项目一 基础数据采集
    任务一 市场数据采集
      任务目标
      任务背景
      任务分析
      知识准备
      任务实施 / 操作步骤
        步骤 1 确定采集渠道
        步骤 2 明确采集指标
        步骤 3 制作关键词搜索指数月均值数据采集表
      任务产物
        图1-1 关键词搜索指数月均值数据采集表
        图1-2 智能门锁竞争数据采集表
      任务思考
    任务二 运营数据采集
      ...
  项目二 数据分类与处理
    ...
```

期望检索行为：

```text
用户问题：智能门锁竞争数据采集表怎么填写？

召回：
  - 任务：项目一 / 任务一 市场数据采集
  - 节点：任务产物 / 图1-2 智能门锁竞争数据采集表
  - 字段：商品名称、链接、价格、月销量
  - 原文：page 15, block-p15-159
```

对企业任务书“数据行列的转换”的理想结构：

```text
任务：数据行列的转换
  任务背景
    背景名称：数据行列的转换
    背景内容：贵州清韵计划对去年各月销售数据进行分析，需要整理销售数据。
  要求
    对店铺去年各月销售数据进行行列转换。
  资源
    数据行列的转换-原始数据.xlsx
  操作步骤
    步骤 1 导入“数据行列的转换-原始数据”工作表并点击“转换数据”
    步骤 2 在 Power Query 编辑器中执行“转置”
    步骤 3 将第一行用作标题
    步骤 4 删除“更改的类型”
```

期望检索行为：

```text
用户问题：Power BI 中如何完成数据行列转换？

召回：
  - 任务：数据行列的转换
  - 资源：数据行列的转换-原始数据.xlsx
  - 工具：Power BI Desktop / Power Query
  - 步骤：导入数据 -> 转置 -> 将第一行用作标题 -> 删除更改的类型
  - 原文定位：任务步骤对应 source_block_ids / locator
```

## 19. 关键设计结论

1. `course_textbook` 需要按教材子类型选择知识加工路径。
2. 企业实训任务书虽然不是教材子类型，但属于任务操作指导类资产，应复用 Task Outline profile。
3. 理论知识型教材适合 Evidence Graph。
4. 任务型教材和企业实训任务书适合 Task Outline / Task Tree。
5. 混合型教材需要章节级分流。
6. 任务树是领域模型，`knowledge_chunk` 是统一检索底座。
7. 任务操作指导类资产也必须生成 `knowledge_chunk`，不建立独立 task_chunk 或 training_task_chunk 底座。
8. 任务树节点通过 `outline_node_id` 投影到 chunks。
9. Evidence Graph 只消费适合构图的 chunks，任务操作指导类 chunks 默认不进入 Graph 候选。
10. 人工维护以任务树为主，维护后重建相关 chunks 和索引。
11. 所有知识加工结果必须保持 `normalized_ref_id`、`source_block_ids`、`locator` 的原文追溯能力。
