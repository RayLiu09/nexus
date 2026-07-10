# 主体 vs 举例 Golden Fixtures

Each `*.json` file freezes one **text → 主体范围 / 举例范围** annotation.
Purpose: measure whether tagging prompt v2 correctly follows the v1.3 R2
"主体范围 vs 举例范围" instruction (see
`docs/knowledge_retrieval_result_enhancement_v1.3.md §16.6`).

## Fixture schema

```json
{
  "fixture_id": "policy_beijing_scope_zhejiang_example",
  "classification": "industry_policy",
  "text": "……原文摘录……",
  "expected": {
    "scope": {
      "regions": ["北京市"],
      "industries": ["直播电商"],
      "occupations": [],
      "majors": []
    },
    "example": {
      "regions": ["浙江省"],
      "industries": [],
      "occupations": [],
      "majors": []
    }
  },
  "notes": "主体判断的依据（发文机关 / 适用范围 / 统计范围 / 直接讨论对象）与举例判断的依据（'以…为例' / '参考' / '对比' 等）"
}
```

## 用途

1. **静态守卫（CI 常驻）**：
   `tests/ai_governance/test_scope_vs_example_golden_set.py` 加载所有
   fixture，校验 shape 合规、`scope` 与 `example` 值集合无交集、
   `classification` 存在于治理规则、每个字符串在原文 `text` 中原样出现。
2. **真 LLM 评测（`@pytest.mark.integration`，nightly / 手动）**：
   同一批 fixture 会被驱动到 tagging profile v2，
   计算 **主体准确率**、**举例漏出率**（把举例误识别为主体的比例）、
   **主体召回率**——目标 v1.3 R3 §14 Q16：主体准确率 ≥ 0.80、
   举例漏出率 ≤ 0.15。

## Coverage plan

初始 P0（A4）：每 classification 至少 1-2 条，共 ~10 条起步；
随着 LLM 输出偏差反馈逐步扩充到 30+。

| classification       | count | 备注                         |
| -------------------- | ----- | ---------------------------- |
| `industry_policy`    | 2     | 覆盖"适用范围" vs "对标案例" |
| `industry_report`    | 2     | 覆盖"统计范围" vs "借鉴经验" |
| `course_textbook`    | 1     | 覆盖"面向专业" vs "教学案例" |
| `major_profile`      | 1     | 通常无举例，做正样本         |
| `job_demand`         | 1     | 覆盖"采集范围"主体           |
| `major_distribution` | 1     | 覆盖"统计范围"主体           |
