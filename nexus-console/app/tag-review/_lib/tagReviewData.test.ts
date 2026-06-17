import { describe, expect, it } from "vitest";
import type { AIGovernanceRun } from "@/lib/api";
import { toTagReviewData } from "./tagReviewData";

function run(overrides: Partial<AIGovernanceRun>): AIGovernanceRun {
  return {
    id: "run-1",
    normalized_ref_id: "ref-1",
    profile_id: "profile-1",
    model_alias: "model",
    prompt_version: "multi-stage/1",
    ai_output: null,
    quality_summary: null,
    validation_status: "schema_valid",
    adoption_status: "auto_adopted",
    validation_error: null,
    created_at: "2026-06-16T09:15:35.933365Z",
    updated_at: "2026-06-16T09:16:44.765430Z",
    ...overrides,
  };
}

describe("toTagReviewData", () => {
  it("extracts committed tags from multi-stage fixed-dimension tagging output", () => {
    const data = toTagReviewData([
      run({
        ai_output: {
          tags: [],
          confidence: 0.94,
          _stages: {
            tagging: {
              tags: {
                professional_domain: [
                  { value: "电子商务", criteria: "跨境电商行业报告" },
                  { value: "国际贸易", criteria: "出口贸易数据" },
                ],
                education_level: [{ value: "高等教育", criteria: "行业研究学习" }],
              },
              confidence: 0.9,
            },
          },
        },
        quality_summary: { confidence: 0.94 },
      }),
    ]);

    expect(data.drafts).toEqual([]);
    expect(data.committed).toHaveLength(1);
    expect(data.committed[0].tags).toEqual(["电子商务", "国际贸易", "高等教育"]);
  });

  it("does not turn stage metadata or ingest channel hints into committed tags", () => {
    const data = toTagReviewData([
      run({
        ai_output: {
          tags: [],
          confidence: 0.94,
          _stages: {
            tagging: {
              tags: {
                professional_domain: [
                  { value: "电子商务", criteria: "跨境电商行业报告" },
                  { value: "#tagging", criteria: "展示 token，不是业务标签" },
                  { value: "doubao-seed-2-0-lite-260215", criteria: "模型别名" },
                ],
                data_source_type: [
                  { value: "文件上传", criteria: "source_type_hint=file_upload" },
                  { value: "第三方行业研究机构", criteria: "AMZ123 出品" },
                ],
              },
              confidence: 0.9,
              _task_type: "tagging",
              _model_alias: "doubao-seed-2-0-lite-260215",
            },
          },
        },
      }),
    ]);

    expect(data.committed).toHaveLength(1);
    expect(data.committed[0].tags).toEqual(["电子商务", "第三方行业研究机构"]);
  });
});
