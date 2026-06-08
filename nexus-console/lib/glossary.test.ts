import { describe, it, expect } from "vitest";
import { glossary } from "./glossary";

describe("glossary", () => {
  it("contains at least 20 business terms", () => {
    const keys = Object.keys(glossary);
    expect(keys.length).toBeGreaterThanOrEqual(20);
  });

  it.each(Object.entries(glossary))(
    "%s has a non-empty definition string",
    (_, definition) => {
      expect(typeof definition).toBe("string");
      expect(definition.length).toBeGreaterThan(10);
    },
  );

  it("has no duplicate definitions", () => {
    const values = Object.values(glossary);
    const unique = new Set(values);
    expect(unique.size).toBe(values.length);
  });

  it("covers core domains: asset, pipeline, governance, AI, permission, search", () => {
    const domains = {
      asset: ["asset", "asset_version", "normalized_asset_ref", "normalized_document", "current_version"],
      pipeline: ["pipeline_a", "pipeline_b", "ingest_validate", "assetize", "parse", "normalize"],
      governance: ["governance_result", "quality_summary", "decision_trail", "rule_set", "review_required", "available", "archived"],
      ai: ["ai_prompt_profile", "litellm_alias"],
      permission: ["org_scope", "rbac", "l1", "l2", "l3", "l4"],
      search: ["trace_id", "qa_answer_generated", "search_query_executed"],
    };

    for (const keys of Object.values(domains)) {
      for (const key of keys) {
        expect(glossary[key]).toBeDefined();
      }
    }
  });

  it("has no empty or whitespace-only definitions", () => {
    for (const value of Object.values(glossary)) {
      expect(value.trim()).not.toBe("");
    }
  });
});
