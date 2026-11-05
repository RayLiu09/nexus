# 岗位采集计划自由输入验证

日期：2026-11-05。对应[任务包](../task-packages/wk_job_collection_free_input_task_package.md)。
单 Agent；未提交、推送或创建真实上游采集任务。

## 最终行为

- 岗位框保留目录建议，支持自由输入及中英文逗号分隔。自动去除空项、两端空白和重复名称。
  1–30 个岗位、每项最多 120 字符；前端表单和后端适配器均校验，超过 30 不能保存。
- 类别改为 AutoComplete，自定义文字或留空均可。非空文字通过已有计划 JSON 的
  `professional_category` 保存，去除两端空白、最多 128 字符；缺省/null/纯空白省略，
  无需迁移。分类匹配目录时过滤建议，清空/自定义时提供全部建议；不清除已输入的岗位。
- 创建、编辑、复制共享表单；后端创建/编辑移除目录成员限制。目录仍是只读建议，
  自定义输入不新增字典记录。建议超过 30 项时快捷操作显示“选前 30 项”。
- 每计划最多 5 区域、岗位与区域最多 100 组合及原页数选择不变。专业类别只属于计划信息，
  不传给上游；仍以 keyword/region/pageLimit 展开组合。

## 验证证据

| 检查 | 结果 |
| --- | --- |
| data_sync 模块、计划 API、Catalog API 回归 | 109 passed |
| DataSyncContent 前端测试 | 15 passed |
| TypeScript | passed |
| 定向 ESLint：DataSyncContent.tsx | 0 errors / 0 warnings |
| Playwright 桌面/手机输入验收 | 4 passed，17.5 秒 |
| 本机现有管理员只读 Schema 检查 | HTTP 200，keywords maxItems=30，professional_category 为可选字段 |
| 本机未删除的现有计划超过 30 岗位数量 | 0；检查只输出数量，不输出计划或凭证 |
| git diff --check | passed |

后端测试覆盖自定义岗位、类别 trim/空值/长度、30/31 岗位边界、100 组合限制、
计划创建/编辑/清空/读取、相同幂等键空类别等价、操作者和 trace 审计。模拟上游的组合
请求精确断言没有 professional_category 字段，其他 Provider 与运行控制回归通过。

前端覆盖类别非必填、未入目录岗位、编辑/复制回显、自定义类别保存、清空类别、31 项拦截。
浏览器实际验证了中英文逗号、空白和去重、切换类别保留岗位、无尾逗号的最后岗位在点击
创建时提交、30 项成功与 31 项阻止、无专业类别提交。浏览器的所有写请求均被模拟。

本地 API 已重启并只读确认新 Schema；Worker、爬虫调度、数据同步运行继续关闭。
前端可在 `/data-sync` 刷新查看。

## Review Gate 自检

- **API Contract**：复用现有内部计划入口，岗位仍是数组，专业类别是可选 JSON 字段；
  新上限 30 在返回 Schema 中可见，无新增业务 API 或表结构。旧计划无需补类别；
  其他环境若有超过 30 岗位的历史计划，需要调整到新上限后再保存/执行。
- **Permission/Audit**：原管理员校验、计划状态/非终态运行保护、更新与创建审计/幂等沿用，
  自定义文本不执行代码、不传递凭证、不改变资产处理路径。
- **Frontend UX**：输入/选取/清空/编辑/复制一致，数量和长度错误明确；
  Prototype、SPEC、ARCHITECT、readme 及上游合同已同步。

实现与自动验证完成；依 WORKFLOWS.md，合并前仍需相应负责人的人工 Review Gate。
