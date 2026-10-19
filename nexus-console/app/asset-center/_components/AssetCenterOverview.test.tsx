import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AssetCenterOverview } from "./AssetCenterOverview";

describe("AssetCenterOverview", () => {
  it("renders four visible domains and their business resource links", () => {
    render(
      <AssetCenterOverview
        counts={{
          "major/standard-course-library": 128,
          "market/industrial-parks": 0,
          "teaching-resources/course-textbooks": 7,
        }}
      />,
    );

    expect(screen.getAllByRole("article")).toHaveLength(4);
    expect(screen.getByLabelText("资产中心领域")).toContainElement(
      screen.getAllByRole("article")[0],
    );
    expect(screen.getByRole("heading", { name: "产业数据" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "专业数据" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "市场数据" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "教材数据" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "用户行为数据" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /证书数据/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /教育政策/ })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "标准课程库，128 条" })).toHaveAttribute(
      "href",
      "/asset-center/major/standard-course-library",
    );
    expect(screen.getByRole("link", { name: "市场岗位，数量暂不可用" })).toHaveAttribute(
      "href",
      "/asset-center/market/job-demands",
    );
    expect(screen.getByRole("link", { name: "产业园区，0 条" })).toHaveAttribute(
      "href",
      "/asset-center/market/industrial-parks",
    );
    expect(screen.getByRole("link", { name: "课程教材，7 条" })).toHaveAttribute(
      "href",
      "/asset-center/teaching-resources/course-textbooks",
    );
    expect(screen.queryByText("产业画像")).not.toBeInTheDocument();
    expect(screen.queryByText(/进入产业数据/)).not.toBeInTheDocument();
  });

  it("does not present API failures as zero counts", () => {
    render(<AssetCenterOverview counts={null} />);

    expect(screen.getByRole("link", { name: "产教政策，数量暂不可用" })).toBeInTheDocument();
    expect(screen.getAllByText("--").length).toBeGreaterThan(0);
  });

  it("keeps resource links usable while counts are loading", () => {
    render(<AssetCenterOverview counts={null} loading />);

    expect(screen.getAllByRole("article")).toHaveLength(4);
    expect(screen.getByRole("link", { name: "产教政策，数量加载中" })).toHaveAttribute(
      "href",
      "/asset-center/policy/industry-policies",
    );
    expect(screen.getAllByText("加载中").length).toBeGreaterThan(0);
    expect(screen.queryByRole("link", { name: /数量暂不可用/ })).not.toBeInTheDocument();
  });
});
