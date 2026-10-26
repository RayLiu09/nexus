# 职业分类大典基础数据与只读 API

2026-10-26；实现任务包：`docs/task-packages/wk_occupation_dictionary_task_package.md`。

## 数据契约

系统基础表 `occupation_dictionary` 以 `edition + occupation_code` 唯一，独立于资产处理管道、AI 治理和知识索引。首次数据来自 `docs/e2e/中华人民共和国职业分类大典（2022年版）职业名录.xlsx`，仅涵盖该表中的编码；使用同目录同版 PDF 的同编码正文修复内容。所提供 PDF 的封面标注“社会公示稿”，本次数据不声明为最终发布版或全国完整名录。

| 字段 | 说明 |
| --- | --- |
| id | 版本和编码派生的稳定 UUID |
| edition | 版次，当前 2022 |
| occupation_code | 职业编码，如 `2-02-07-11` |
| occupation_category | 职业类别，源表第一列 |
| major_group | 职业大类，对应源表“所属大类(中类)” |
| minor_group | 职业小类，对应源表“所属小类”；当前数据均已补齐 |
| occupation_name | 职业名称，不含编码和 L/S 标记 |
| definition | 职业定义，必填 |
| work_tasks | 工作任务，必填，保留任务项换行 |

内部另保留 `source_file`、`supplement_file`、`source_rows`、`pdf_pages`、`supplemented_fields`、创建/更新时间，不通过列表 API 暴露。按编码合并重复占位行，正式源行存在冲突则拒绝导入；PDF 使用有定义和“主要工作任务”的正文，跳过目录并在下个分类/职业编码边界停止。正文同时修复 Excel 已非空但被截断的名称、定义、任务。补齐后名称、定义、任务任一仍为空者丢弃，报告单独输出。

## 接口

- `GET /v1/occupation-dictionary`：沿用 `require_api_caller` 的 API caller 认证。
- `GET /open/v1/occupation-dictionary`：相同认证与只读查询的公开消费别名，工具名 `query_occupation_dictionary`；资源发现包含本基础表。
- `GET /internal/v1/occupation-dictionary`：沿用 `require_user` 的 Console 用户认证。
- 仅提供读取，不提供创建、编辑、删除接口。

| 参数 | 规则 |
| --- | --- |
| major_group | 可选，最多 256 字符，分类名称或大类编码子串 |
| minor_group | 可选，最多 256 字符，分类名称或小类编码子串 |
| occupation_name | 可选，最多 256 字符，职业名称子串 |
| page | 从 1 开始，最大 10000，默认 1 |
| pageSize | 1–200，默认 20 |

条件去除首尾空白后以 AND 组合，空值不限制，`%`、`_` 按字面字符匹配。先过滤、COUNT 再分页，排序为版次降序、编码升序。

```json
{
  "data": [{
    "id": "<uuid>",
    "edition": 2022,
    "occupation_code": "2-02-07-11",
    "occupation_category": "2 专业技术人员",
    "major_group": "2-02 工程技术人员",
    "minor_group": "2-02-07 机械工程技术人员",
    "occupation_name": "汽车工程技术人员",
    "definition": "<完整职业定义>",
    "work_tasks": "<完整工作任务>"
  }],
  "meta": {"trace_id": "<trace>", "page": 1, "page_size": 20, "total": 1},
  "aggregations": null
}
```

未认证返回现有 401/403 鉴权错误；参数越界返回 422；无匹配返回 200 和空数组。读取记录 `OpenRecordAssetsAccessed` 审计，包含 actor、trace_id、结果总数。导入有新增时记录 `OccupationDictionaryImported`，纯重复导入不新增审计事件。Console 卡片计数来自同表。

## 迁移与导入

`20261026_0122` 创建表和审计枚举值，直接导入包内 `nexus_app/reference_data/occupation_dictionary_2022.json`，部署不依赖原始 Excel/PDF 或解析服务。

```bash
cd nexus-app
uv run alembic upgrade head
# 查看已审阅种子；默认不写库
PYTHONPATH=. uv run python scripts/import_occupation_dictionary.py
# 幂等导入；相同版次/编码且内容一致跳过，已存在内容冲突则报错并回滚
PYTHONPATH=. uv run python scripts/import_occupation_dictionary.py --apply
```

如需从提供的文档重新生成，在仓库根目录运行：

```bash
PYTHONPATH=nexus-app nexus-app/.venv/bin/python nexus-app/scripts/import_occupation_dictionary.py \
  --workbook 'docs/e2e/中华人民共和国职业分类大典（2022年版）职业名录.xlsx' \
  --pdf 'docs/e2e/中华人民共和国职业分类大典（2022年版）.pdf' \
  --seed-output /tmp/occupation_dictionary_2022.json \
  --report-output /tmp/occupation_dictionary_report.json
```

先审阅生成数据和报告，再将确认的种子纳入版本管理。导入由调用方持有事务；版本化种子完整校验后写入，唯一约束防止重复。回滚迁移删除基础表，保留历史审计及枚举值。
