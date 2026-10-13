import { App } from "antd";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import TagReviewContent, { type GovernanceReviewItem } from "./TagReviewContent";

vi.stubGlobal("ResizeObserver", class {
  observe() {}
  unobserve() {}
  disconnect() {}
});

const reviewItem: GovernanceReviewItem = {
  governance_result_id: "result-1",
  normalized_ref_id: "ref-1",
  asset_id: "asset-1",
  asset_title: "示例政策",
  classification: "industry_policy",
  level: "L1",
  org_scope: "全组织",
  tags: {
    regions: [{ value: "浙江省" }],
    industries: [],
    occupations: [],
    majors: [],
    abilities: [],
    topics: [{ value: "产教融合" }],
    time_ranges: [{ kind: "year_range", start: 2025, end: 2026 }],
  },
  quality_summary: {},
  created_at: null,
};

it("keeps collapsed review fields and submits editable default reasons", async () => {
  let submitted: Record<string, unknown> | null = null;
  vi.stubGlobal("fetch", vi.fn(async (input: string, init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/review-context")) {
      return { ok: true, json: async () => ({ data: {
        rules: { classifications: [{ code: "industry_policy", name: "产教政策" }], levels: [{ code: "L1", name: "L1" }] },
      } }) };
    }
    if (url.endsWith("/review-decisions") && init?.method === "POST") {
      submitted = JSON.parse(String(init.body));
      return { ok: true, json: async () => ({ data: { version_status: "available" } }) };
    }
    if (url.includes("/pending?")) {
      return { ok: true, json: async () => ({ data: [], meta: { total: 0 } }) };
    }
    throw new Error(`Unexpected request: ${url}`);
  }));

  render(<App><TagReviewContent
    initialItems={[reviewItem]}
    initialTotal={1}
    ok
    error={null}
    traceId={null}
    classificationDictionary={{ industry_policy: "产教政策" }}
    levelDictionary={{ L1: "L1" }}
  /></App>);

  fireEvent.click(screen.getByRole("button", { name: /审核$/ }));
  expect(await screen.findByDisplayValue("内容完整，结构清洗，符合质量要求")).toBeInTheDocument();
  expect(screen.getByDisplayValue("审核通过，继续处理")).toBeInTheDocument();
  expect(screen.queryByRole("textbox", { name: "组织范围" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "提交治理结论" }));

  await waitFor(() => expect(submitted).not.toBeNull());
  expect(submitted).toMatchObject({
    org_scope: "全组织",
    quality_review: { disposition: "pass", reason: "内容完整，结构清洗，符合质量要求" },
    review_reason: "审核通过，继续处理",
    tags: {
      regions: [{ value: "浙江省" }],
      time_ranges: [{ kind: "year_range", start: 2025, end: 2026 }],
    },
  });
});

it("deletes a reviewed asset only after exact-title confirmation and reloads the queue", async () => {
  const requests: Array<{ url: string; init?: RequestInit }> = [];
  vi.stubGlobal("fetch", vi.fn(async (input: string, init?: RequestInit) => {
    const url = String(input);
    requests.push({ url, init });
    if (url === "/api/assets/asset-1" && init?.method === "DELETE") {
      return { ok: true, json: async () => ({ data: { deleted: true } }) };
    }
    if (url.includes("/pending?")) {
      return { ok: true, json: async () => ({ data: [], meta: { total: 0 } }) };
    }
    throw new Error(`Unexpected request: ${url}`);
  }));

  render(<App><TagReviewContent
    initialItems={[reviewItem]}
    initialTotal={1}
    ok
    error={null}
    traceId={null}
    classificationDictionary={{ industry_policy: "产教政策" }}
    levelDictionary={{ L1: "L1" }}
  /></App>);

  fireEvent.click(screen.getByRole("button", { name: "删除资产 示例政策" }));
  expect(screen.getByText(/删除不可恢复/)).toBeInTheDocument();
  expect(requests).toHaveLength(0);
  fireEvent.click(screen.getByRole("button", { name: /继\s*续/ }));
  const confirm = screen.getByRole("button", { name: /永\s*久\s*删\s*除/ });
  expect(confirm).toBeDisabled();
  fireEvent.change(screen.getByRole("textbox", { name: "完整资产标题" }), { target: { value: "示例" } });
  expect(confirm).toBeDisabled();
  fireEvent.change(screen.getByRole("textbox", { name: "完整资产标题" }), { target: { value: "示例政策" } });
  fireEvent.click(confirm);

  await waitFor(() => expect(requests).toHaveLength(2));
  expect(requests[0].url).toBe("/api/assets/asset-1");
  expect(requests[0].init?.headers).toMatchObject({ "Idempotency-Key": expect.any(String) });
  expect(requests[1].url).toContain("/api/governance-reviews/pending?page=1&pageSize=20");
  expect(screen.getByText("暂无待治理审核资产")).toBeInTheDocument();
});
