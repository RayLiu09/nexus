# Pipeline B Wave 3 任务包 — normalized_record v2

- **依据**：
  - 实施计划 §三 B3（`docs/pipeline_b_implementation_plan.md`）
  - 设计 §八 normalized_record 与领域表边界 + §5.0 dual-view 契约
    （`docs/pipeline_b_job_occupation_structured_data_design.md`）
  - 合同冻结 §5.0（payload 字段 schema）
    （`docs/pipeline_b_contract_freeze.md`）
- **状态**：B2 总评已通过；**B3 已交付，待人工总评**（代码与测试已落地，未提交）
- **本期目标**：将 `normalized_record` payload 显式升级到 `normalized-record.v2`，承载 B2 已写入的 profile / record_body / domain_profile，并为 B5 预留 `body_markdown` / `body_markdown_meta` 占位。
- **不在范围**：领域表（B4 / B6）、知识单元加工与 `body_markdown` LLM 渲染（B5）、超大 `record_body` 外置 MinIO、PG 列结构变更。
- **依赖**：B1 / B2 全部子切片 ✅

---

## 1. 最小变更策略

B3 不发 Alembic migration、不动 `normalized_record` PG 列；仅升级 payload schema 与写入函数。原因：

- B2 已把 `profile` / `record_body` / `domain_profile` 写入 `normalized_record.payload`（JSONB），结构变化不需要列迁移。
- B4 / B6 才会定义领域表的真正 PG schema，B3 不重复设计。
- `_persist_normalized_ref.metadata_summary` 已能承载 profile 摘要，无需新列。

变更点收敛到 3 处：

| 文件                                             | 类型 | 变更要点                                                                                                                                                                                                                      |
| ------------------------------------------------ | ---- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `nexus_app/pipeline/normalized_record_schema.py` | 新增 | `NORMALIZED_RECORD_SCHEMA_VERSION = "normalized-record.v2"` + `NORMALIZED_DOCUMENT_SCHEMA_VERSION = "normalized-document-v1"`；集中常量避免字面量散落                                                                         |
| `nexus_app/pipeline/stages.py`                   | 修改 | `_build_normalized_record`：payload 顶层新增 `domain_profile` + `body_markdown: None` + `body_markdown_meta: None`；缺省 `profile_dict` 仍能产出兼容 payload；`_persist_normalized_ref` 按 `normalized_type` 选择 schema 常量 |
| `tests/test_normalized_record_v2.py`             | 新增 | 21 个测试覆盖常量、profile 路径、JSON 兼容路径、样本 1 端到端 schema_version                                                                                                                                                  |

---

## 2. 交付项

### 2.1 schema 常量模块

```python
# nexus_app/pipeline/normalized_record_schema.py
NORMALIZED_RECORD_SCHEMA_VERSION: str = "normalized-record.v2"
NORMALIZED_DOCUMENT_SCHEMA_VERSION: str = "normalized-document-v1"
```

- B7 governance、B9 console、未来的 schema-version 比对均从此模块导入。
- 升级 schema 仅需在此处改一行 + 测试常量；下游不必逐文件搜串。

### 2.2 `_build_normalized_record` v2 升级

payload 顶层结构（v2）：

```
{
  "schema_version": "normalized-record.v2",
  "title": ...,
  "language": ...,
  "source_type": "record",
  "content_type": ...,
  "metadata": { ... , "profile": {...}?, "domain_profile": "..."? },
  "domain_profile": "job_demand.v1" | "ability_analysis.pgsd.v1" | None,   # 新增顶层
  "record_body": { ... },                                                  # B1/B2 已写入
  "body_markdown": None,                                                   # B5 渲染
  "body_markdown_meta": None,                                              # B5 元数据
  "governance": {...},
  "quality": {...},
  "lineage": {...}
}
```

- profile_dict 为 None 时：
  - `domain_profile` 缺省（不写入顶层）
  - `body_markdown` / `body_markdown_meta` 仍写 None
  - metadata 不注入 profile
  - 完全向后兼容 JSON 原始路径
- profile_dict 存在时：domain_profile 同时镜像到 metadata.profile.domain_profile（便于 search 索引）

### 2.3 `_persist_normalized_ref` 按类型选择 schema_version

```python
default_schema = (
    NORMALIZED_RECORD_SCHEMA_VERSION
    if normalized_type == NormalizedAssetType.RECORD
    else NORMALIZED_DOCUMENT_SCHEMA_VERSION
)
schema_version = payload.get("schema_version", default_schema)
```

确保：

- record 资产默认走 v2；document 资产保持 v1（Pipeline A 不动）
- payload 自带 schema_version 时尊重 payload（B5/B7 升级可平滑）

---

## 3. 测试覆盖（21 用例）

`tests/test_normalized_record_v2.py`：

- **TestSchemaConstants (3)** — 常量值锁定 / 与 document v1 分离
- **TestBuildNormalizedRecordWithProfile (6)** — profile_dict 完整时的字段写入、metadata 镜像、占位字段、governance/quality/lineage 完整性
- **TestBuildNormalizedRecordWithoutProfile (5)** — JSON 原始路径向后兼容、不污染顶层、不破坏 lineage
- **TestPersistedSchemaVersion (6)** — 样本 1 端到端 \_persist_normalized_ref 后 `payload.schema_version == "normalized-record.v2"`；document 路径仍为 v1；payload 自带 schema_version 时尊重

全套件回归：**670 passed + 1 skipped**，0 regression。

---

## 4. 验收标准（Acceptance）

- 样本 1 经 B1+B2+B3：normalized_record.payload.schema_version == "normalized-record.v2"，profile/domain_profile/quality/lineage 字段非空
- profile_dict 缺省时 payload 仍能落地（兼容旧 JSON 路径）
- `governance_result.target = normalized_asset_ref` 仍成立（未改链路）
- 完整套件无 regression

## 5. 风险与回退

- **风险**：下游若硬编码 "normalized-record-v1"（dash 形式）会失配。
  - **缓解**：grep 整库无遗漏；新增常量模块即为单一来源；schema-version 比对调用点已迁移到该常量。
- **回退**：只需将常量改回 "normalized-record-v1" + 移除顶层 `domain_profile` / `body_markdown*` 字段；无 migration 需要回滚。

## 6. 下一步

- B3 人工总评（Data Model Gate，仅 payload schema 层面）
- 通过后并行启动 B4（岗位需求领域表）与 B6（能力分析领域表）：均消费 v2 payload
- B5 渲染 `body_markdown` 时复用占位字段，无需再次升级 payload
