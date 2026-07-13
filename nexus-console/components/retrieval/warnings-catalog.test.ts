import { describe, expect, it } from "vitest";

import { TONE_TO_TAG_COLOR, WARNING_CATALOG, extractCode, lookupWarning } from "./warnings-catalog";

describe("warnings-catalog", () => {
  describe("extractCode", () => {
    it("returns the raw string when no colon is present", () => {
      expect(extractCode("optional_bucket_empty")).toBe("optional_bucket_empty");
    });

    it("returns the head token when the code carries an inline detail", () => {
      expect(extractCode("tag_filter_resolver_error:regions:bucket_out_of_domain")).toBe(
        "tag_filter_resolver_error",
      );
    });

    it("handles an empty string safely", () => {
      expect(extractCode("")).toBe("");
    });
  });

  describe("lookupWarning", () => {
    it("returns the entry for a known code", () => {
      const entry = lookupWarning("weighted_rerank_applied");
      expect(entry).not.toBeNull();
      expect(entry?.tone).toBe("info");
      expect(entry?.category).toBe("rerank");
      // Backend-facing contract: any change to `label` needs a design pass;
      // this assertion catches accidental blank / missing labels.
      expect(entry?.label.length).toBeGreaterThan(0);
    });

    it("looks up the head token when the raw code has inline detail", () => {
      const entry = lookupWarning("tag_filter_resolver_error:regions:invalid");
      expect(entry).not.toBeNull();
      expect(entry?.category).toBe("fallback");
    });

    it("returns null for an unknown code", () => {
      expect(lookupWarning("some_future_code_we_have_not_registered")).toBeNull();
    });
  });

  describe("catalog invariants", () => {
    it("covers the retrieval resolver's warning codes", () => {
      // These codes appear in nexus_app/retrieval/tag_resolver.py.  Any
      // rename on the backend must land here as a deliberate registry
      // update — the test exists to make that visible in review.
      const required = [
        "tag_asset_index_not_ready",
        "embedding_lag_bypass",
        "hnsw_query_failed",
        "l4_no_embedding_client",
        "l4_no_query_vectors",
        "l4_embedding_call_failed",
        "layer_l3_not_implemented",
        "layer_l5_chunk_fallback_out_of_scope",
        "optional_bucket_empty",
        "target_ids_truncated",
      ] as const;
      for (const code of required) {
        if (!WARNING_CATALOG[code]) {
          throw new Error(`missing catalog entry: ${code}`);
        }
        expect(WARNING_CATALOG[code]).toBeDefined();
      }
    });

    it("covers the rerank engine's warning codes", () => {
      const required = [
        "weighted_rerank_applied",
        "weighted_rerank_disabled_by_config",
        "weighted_rerank_skipped_no_target_scores",
        "weighted_rerank_suppressed_by_order_by",
        "unstructured_rerank_applied",
        "unstructured_rerank_disabled_by_config",
        "unstructured_rerank_skipped_no_target_scores",
        "unstructured_rerank_skipped_outline_anchor",
        "unstructured_rerank_skipped_single_item",
        "unstructured_rerank_skipped_zero_weights",
      ] as const;
      for (const code of required) {
        if (!WARNING_CATALOG[code]) {
          throw new Error(`missing catalog entry: ${code}`);
        }
        expect(WARNING_CATALOG[code]).toBeDefined();
      }
    });

    it("maps every tone to an Antd Tag color", () => {
      const tones = new Set(Object.values(WARNING_CATALOG).map((v) => v.tone));
      for (const tone of tones) {
        expect(TONE_TO_TAG_COLOR[tone]).toBeTruthy();
      }
    });

    it("all entries have non-empty label + description", () => {
      for (const [code, entry] of Object.entries(WARNING_CATALOG)) {
        if (!entry.label) throw new Error(`blank label for ${code}`);
        if (!entry.description) throw new Error(`blank description for ${code}`);
        expect(entry.label.length).toBeGreaterThan(0);
        expect(entry.description.length).toBeGreaterThan(0);
      }
    });
  });
});
