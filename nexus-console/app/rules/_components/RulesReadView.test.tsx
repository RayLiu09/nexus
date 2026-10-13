import { App } from "antd";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import rules from "../../../../config/governance_rules_v2.json";
import { extractTagDimensions } from "../_lib/tagDimensions";
import { RulesReadView } from "./RulesReadView";

vi.stubGlobal("ResizeObserver", class {
  observe() {}
  unobserve() {}
  disconnect() {}
});

it("renders configured tag dimensions and expandable classification criteria", () => {
  render(<App><RulesReadView
    classifications={[]}
    levels={[]}
    tagDimensions={extractTagDimensions(rules as Record<string, unknown>)}
    dimensions={[]}
    thresholds={null}
    autoAdoptThreshold={null}
  /></App>);

  expect(screen.getByText("数据标签（tag_dimensions）")).toBeInTheDocument();
  expect(screen.getByText("学历层次")).toBeInTheDocument();
  expect(screen.getByText("高职")).toBeInTheDocument();

  const professionalRow = screen.getByRole("row", { name: /专业领域/ });
  fireEvent.click(within(professionalRow).getByRole("button"));
  expect(screen.getByText("产业政策")).toBeInTheDocument();
});
