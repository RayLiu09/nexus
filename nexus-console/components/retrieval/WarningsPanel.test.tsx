import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { WarningsPanel } from "./WarningsPanel";

describe("WarningsPanel", () => {
  it("renders empty-state message when no warnings", () => {
    render(<WarningsPanel warnings={[]} />);
    expect(screen.getByText("本次执行未产生告警")).toBeInTheDocument();
  });

  it("shows the Chinese label for a registered code", () => {
    render(<WarningsPanel warnings={["weighted_rerank_applied"]} />);
    expect(screen.getByText("WEIGHTED 已重排")).toBeInTheDocument();
    // The full description also appears inline (not only in the tooltip).
    expect(screen.getByText(/PR-13 WEIGHTED combine op 已生效/)).toBeInTheDocument();
  });

  it("falls back to the raw code when the code is unknown", () => {
    render(<WarningsPanel warnings={["some_future_code_we_have_not_registered"]} />);
    expect(screen.getByText("some_future_code_we_have_not_registered")).toBeInTheDocument();
    expect(screen.getByText(/未在词典中登记的告警码/)).toBeInTheDocument();
  });

  it("shows label + inline detail suffix when the code carries `:` extras", () => {
    render(<WarningsPanel warnings={["tag_filter_resolver_error:regions:bucket_out_of_domain"]} />);
    expect(screen.getByText("resolver 抛错")).toBeInTheDocument();
    // The `:regions:bucket_out_of_domain` slice should surface verbatim
    // so operators can still grep logs by raw substring.
    expect(screen.getByText(":regions:bucket_out_of_domain")).toBeInTheDocument();
  });

  it("renders one item per warning even when the same code appears twice", () => {
    render(<WarningsPanel warnings={["optional_bucket_empty", "optional_bucket_empty"]} />);
    const labels = screen.getAllByText("可选桶未命中");
    expect(labels).toHaveLength(2);
  });

  it("renders a header count reflecting the raw warnings list length", () => {
    render(
      <WarningsPanel
        warnings={["weighted_rerank_applied", "optional_bucket_empty", "tag_asset_index_not_ready"]}
      />,
    );
    expect(screen.getByText(/告警与提示 \(3\)/)).toBeInTheDocument();
  });
});
