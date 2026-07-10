# Tagging Prompt v2 Golden Fixtures (v1.3 §4.1 契约)

Each `*.json` file is one **input → expected output** pair for the v1.3
tagging profile v2. The suite serves three distinct purposes:

1. **Static structural guards (CI mandatory)** — every fixture is loaded by
   `tests/ai_governance/test_tagging_v2_golden_set.py`, which asserts:
   - Input has a valid `classification` code (present in
     `governance_rules_v2.json.classifications`).
   - Expected output is a valid `StructuredTagBag` per v1.3 §4.1.
   - Each expected tag has non-empty `value` and `evidence_span`; the
     `evidence_span` must appear verbatim in
     `input.normalized_document_excerpt`.
   - `confidence_range` (optional) is a `[min, max]` pair in `[0, 1]`.
2. **Mock-LLM smoke test (CI mandatory)** — same tests feed the expected
   output back through `tag_payload.normalize_to_structured(...)` to prove
   the shape survives the payload contract used by
   `AIGovernanceService.run_tagging_only`.
3. **Real-LLM regression (nightly / manual, `@pytest.mark.integration`)** —
   a separate test module (`test_tagging_v2_golden_llm.py`, to be added)
   will drive the actual LiteLLM tagging profile against these inputs and
   score output tags against the expected set (recall / precision per
   category). That test is **not** part of the default CI suite because
   it needs live LiteLLM credentials.

## Fixture schema

```json
{
  "fixture_id": "industry_policy_beijing_livestream_ecom",
  "purpose": "structural_static + mock_smoke",
  "input": {
    "classification": "industry_policy",
    "normalized_document_excerpt": "……原文摘录，尽量真实……"
  },
  "expected": {
    "tags": {
      "regions": [
        {
          "value": "北京市",
          "confidence": 0.94,
          "evidence_span": "本规划适用于北京市"
        }
      ],
      "industries": [
        {
          "value": "直播电商",
          "confidence": 0.88,
          "evidence_span": "直播电商产业"
        }
      ],
      "occupations": [],
      "majors": [],
      "abilities": [],
      "topics": [
        {
          "value": "数据合规",
          "confidence": 0.72,
          "evidence_span": "数据合规要求"
        }
      ],
      "time_ranges": [{ "kind": "year_range", "start": 2024, "end": 2026 }]
    },
    "confidence_range": [0.65, 0.95]
  },
  "notes": "自由文本，说明构造意图 / 主体范围 vs 举例的判定要点等"
}
```

## Coverage plan

Initial (v1.3 A4 收官):

| classification                      | target count | fixtures shipped |
| ----------------------------------- | ------------ | ---------------- |
| `industry_policy`                   | 5-6          | 起步 3 条（P0）  |
| `industry_report` / `sector_report` | 3-4          | 起步 1 条        |
| `course_textbook`                   | 3-4          | 起步 1 条        |
| `major_profile`                     | 3-4          | 起步 1 条        |
| `job_demand`                        | 3-4          | 起步 1 条        |
| `competency_analysis`               | 3-4          | 起步 1 条        |
| `major_distribution`                | 2-3          | 起步 1 条        |

**Not seed-to-100 immediately** — A4 交付 P0：为每个高频 classification 至少 1 条，
共约 9 条；后续实际治理跑起来后根据 tagging profile v2 输出偏差再补充到 100+。
每次新增或修改一条 fixture 都会自动被 CI 静态守卫覆盖。

## 添加新 fixture 的流程

1. 复制现有一份 `*.json` 作模板。
2. 修改 `fixture_id`、`classification`、`normalized_document_excerpt`。
3. 手动构造预期 `tags` 结构（每个 tag 的 `evidence_span` 必须能在
   `normalized_document_excerpt` 中原样找到）。
4. 运行 `./.venv/bin/pytest tests/ai_governance/test_tagging_v2_golden_set.py`
   验证结构守卫通过。
5. 提交 PR，注明"golden set +1"。
