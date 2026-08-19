---
name: talent-demand-report
description: vocational-program-suite 调度的单专业建设子技能，执行单专业《人才需求调研分析报告》。报告围绕“产业—行业—职业—专业”链条，判断目标产业链相关环节、业务领域、岗位群、岗位层级、工作任务、能力要求、培养供给、供需矛盾与培养优化方向。报告生成采用“保存大纲 → 等待确认 → 建报告骨架 → 按 section 草稿逐次写入正文”的机制：大纲和骨架使用 save_artifact，正文长内容使用 begin_artifact_draft / write_artifact_draft / commit_artifact_draft 逐 section 写入。本技能不生成正式职业面向表、正式典型工作任务模型、正式能力矩阵、课程体系图、人才培养方案或课程标准。
---

# 单专业人才需求调研分析报告

## 使用前必读

执行本技能前**必须先读取 `reference.md`**。所有执行细则只在 `reference.md` 维护，本文件只给主干，不重复细节：固定六章大纲与标题排版、禁用词与正文表达、政策/标准/数据源规则、分章写作要点与各章必出表格、图表与图谱数据契约、以及统一的质量门（禁止/验收清单）。

## 定位与边界

交付单专业《人才需求调研分析报告》：围绕“产业—行业—职业—专业”链条，分析专业服务的产业链环节、业务领域、岗位群、岗位层级、典型工作任务、能力要求、培养供给、供需矛盾与优化方向，支撑专业建设、课程与教材更新、实训更新和人才培养方案修订。报告不是行业介绍、政策摘录或岗位统计清单（报告必须回答的核心问题见 `reference.md` 开头）。

本技能**不生成**：正式职业面向表、典型工作任务模型、能力矩阵、课程体系图、人才培养方案、课程标准——这些由下游技能负责。本技能可产出调研版“岗位群—岗位—任务—知识/技能/素养/工具”图谱，但不得表达为上述正式成果。

## 前置条件

当前会话必须已绑定项目容器，且项目基础信息齐全：`industry`、`province`、`city`、`specialtyName`、`educationLevel`。缺失时先补充，不进入报告生成。（`educationLevel` 用于岗位名称与岗位层级校准，校准规则与对照表见 `reference.md` §四三。）

## 必用能力

| 数据任务 | 工具 |
| --- | --- |
| 政策 / 产业 / 区域 / 院校 / 标准 / 紧缺目录检索（优先 2026 及近三年） | `mcp__edu-server-mcp__lightrag_query` / `lightrag_query_data` / `WebSearch` / `WebFetch` |
| 岗位样本、薪资、学历、经验、技能、任务文本查询 | `mcp__edu-server-mcp__postgres_execute_query` |
| 保存待确认大纲 | `save_artifact` |
| 开启报告新版本 / 建报告骨架 / 结束报告生成 | `start_artifact_generation` / `save_artifact` / `end_artifact_generation` |
| 逐节写入正文（begin 必须独占一轮） | `begin_artifact_draft` / `write_artifact_draft` / `commit_artifact_draft` |
| 生成统计图表与交互图谱 option | `build_echarts_option` |

## 主流程

1. 确认项目已绑定、5 个必填输入齐全（尤其 `educationLevel`）。
2. 读取 `reference.md`。
3. 按固定六章生成初始大纲 → `save_artifact(demand_outline)`，**等待用户确认或编辑**。
4. 用户确认大纲后先读回最新 `demand_report`。首次生成调用 `start_artifact_generation`；仅当用户明确要求放弃现有内容并重新生成整份报告时显式传 `regenerate:true`。若最新报告仍为 `generating` 且已有骨架，必须复用原 `recordId` 从首个未完成 section 续写；继续、失败重试和断点恢复禁止再次 start。
5. 按 section 顺序：生成内部证据包 → 写正文 → 出表格/图表/岗位图谱 → **过 `reference.md` §六 全部质量门** → 用草稿三件套逐节写入；**每个 section 开写前先输出一句业务语言的进度提示**（见 `reference.md`「逐章进度提示」），不要静默连续调用几十次草稿工具；一级章 section 也必须写 1-2 段开篇综述，不能只写下级二级节。
6. 职业分析、课程体系、人才培养方案等关键节点，须经教师或专家确认后才作下游正式输入。

## 硬约束提要（完整规则与禁止清单以 `reference.md` 为准）

- 固定六章；每个二级节必设三级标题；三级标题格式只能 `**1. 标题**`——见 §二。
- `demand_outline.sections` 只保存章和节，必须按出现顺序拍平成一维 `{ level, title }[]`；禁止 `subSections`、`children`、`thirdLevels` 等嵌套字段，三级标题留到正文生成——见 §一 / §二。
- 政策优先检索 2026 → 2025 → 2024，正文不出现“十四五”；专业教学标准是标准依据、不是政策，不得进政策汇总表——见 §三。
- 岗位分析紧扣数字化转型与“四新”，按 `educationLevel` 校准岗位层级，必检国/省/市三级新质与紧缺目录——见 §三 / §四。
- “岗位图谱分析”必须生成 graph/tree 图谱并保存规定字段（`graphName` 等）；图谱主节点不含“课程/实训方向”——见 §五。
- 统计分布 / 趋势 / 关系类数据用 `build_echarts_option` 出图（禁止手搓 option，贴进 ```chart 代码块）；图表分章覆盖、第三章至少 3–4 张核心图表，工具支持类型与分章建议见 §五。
- 用户可见文本不得暴露内部编号、工具名、panelType、recordId、字段名或表名，只使用业务阶段名称。
- 每个 section 写入前必须过 `reference.md` §六 全部质量门，任一不合格不得提交。
- 报告骨架中的每个 section 都是可写正文单元：一级章写开篇综述，二级节写完整正文；禁止遗留空正文或“待生成”章节。
