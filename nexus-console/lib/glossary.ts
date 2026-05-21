/**
 * A4 微文案 — 业务术语词库
 *
 * 唯一真源：在控制台首次出现某术语处包 <TermTip term="...">。
 * 新增/调整术语只在此文件维护。
 */

export const glossary: Record<string, string> = {
  // 资产域
  asset: "资产：业务可识别的最小数据/知识单元，每个 asset 同一时间只有一个 available 版本。",
  asset_version: "资产版本：asset 的某次内容快照；version 之间不双向绑定 normalized_ref。",
  normalized_asset_ref: "标准化引用：标准化后的资产指针，是治理与索引的目标对象，不是 raw 文件。",
  normalized_document: "标准化文档：document 类型 normalized_asset_ref 的内容载体（schema-v1）。",
  normalized_record: "标准化记录：record 类型 normalized_asset_ref 的内容载体。",
  current_version:
    "当前版本：来自 read model 的派生视图，asset 表上不存反向指针；同一资产仅一个 available。",

  // 流水线
  pipeline_a: "Pipeline A（document）：ingest_validate → assetize → parse → normalize。",
  pipeline_b: "Pipeline B（record）：ingest_validate → assetize → normalize（不调用 MinerU）。",
  ingest_validate: "接入验证：MIME / checksum / 病毒扫描三段校验。",
  assetize: "资产化：创建 asset 与 asset_version 的锚点；与 normalize 是不同阶段。",
  parse: "解析：MinerU 自动选 model_version + OCR，输出 parse_artifact。",
  normalize: "标准化：LLM 语义抽取 + 规则兜底，产出 normalized_asset_ref。",
  metadata_enrich: "标签生成：基于 normalized asset 生成标签草稿，高置信自动提交，低置信入审核。",

  // 治理
  governance_result:
    "治理结果：以 normalized_asset_ref 为 target，含 quality_summary 与 decision_trail。",
  quality_summary: "质量摘要：完整性 / 结构性 / 可读性 / 安全性 四维加权综合分。",
  decision_trail: "决策追踪：候选值、规则命中、最终值串成的可追溯链。",
  rule_set: "规则集：版本化的规则容器；publish 走 Validate → Preview Impact → Confirm 三段。",
  review_required: "待复核：未通过质量、规则或权限校验，未进入索引。",
  available: "可用：满足质量、分级、组织范围与唯一性，可被授权用户访问且可索引。",
  archived: "已归档：被新版本替换的历史版本；只读不索引。",

  // AI
  ai_prompt_profile:
    "Prompt 资产：NEXUS 自有的 Prompt 模板 + 输出 Schema + 评分权重；密钥归 LiteLLM。",
  litellm_alias: "LiteLLM alias：模型别名，NEXUS 仅引用，不直接配置底层供应商。",

  // 权限
  org_scope: "组织范围：资源可见的组织子集；规则可收窄不可放大。",
  rbac: "基于角色的访问控制：P0 模型，搭配 org_scope 过滤；ABAC 留扩展点。",
  l1: "L1 公开：可对所有授权角色开放。",
  l2: "L2 内部：限本组织或合作组织。",
  l3: "L3 受限：需审批与脱敏策略。",
  l4: "L4 例外：必须显式审批，默认不出网，仅私有 alias 可调用非脱敏内容。",

  // 检索
  trace_id: "请求追踪 ID：每次写入或检索都会生成，用于审计与售后定位。",
  qa_answer_generated: "QAAnswerGenerated：仅记录引用 chunk_ids，不留答案明文。",
  search_query_executed: "SearchQueryExecuted：记录 query_hash 与 hit_ref_ids，不留 query 明文。",
};
