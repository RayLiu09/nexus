import { describe, expect, it } from "vitest";
import { extractGovernanceTags } from "./governance-tags";

describe("extractGovernanceTags", () => {
  it("extracts fixed-dimension multi-stage tags and ignores stage metadata", () => {
    expect(
      extractGovernanceTags({
        tags: [],
        _stages: {
          tagging: {
            tags: {
              professional_domain: [
                { value: "电子商务", criteria: "跨境电商行业报告" },
                { value: "#tagging", criteria: "stage token" },
                { value: "doubao-seed-2-0-lite-260215", criteria: "model alias" },
              ],
              data_source_type: [
                { value: "文件上传", criteria: "ingest channel" },
                { value: "第三方行业研究机构", criteria: "AMZ123 出品" },
              ],
            },
            _task_type: "tagging",
            _model_alias: "doubao-seed-2-0-lite-260215",
          },
        },
      }),
    ).toEqual(["电子商务", "第三方行业研究机构"]);
  });
});
