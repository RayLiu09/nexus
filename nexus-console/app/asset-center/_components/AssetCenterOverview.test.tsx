import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AssetCenterOverview } from "./AssetCenterOverview";

describe("AssetCenterOverview", () => {
  it("renders the five approved domains and business resource links", () => {
    render(
      <AssetCenterOverview
        counts={{
          "major/standard-course-library": 128,
          "market/industrial-parks": 0,
        }}
      />,
    );

    expect(screen.getAllByRole("article")).toHaveLength(5);
    expect(screen.getByRole("heading", { name: "产业政策数据" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "专业数据" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "市场数据" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "教材资源数据" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "用户行为数据" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "标准课程库，128 条" })).toHaveAttribute(
      "href",
      "/asset-center/major/standard-course-library",
    );
    expect(screen.getByRole("link", { name: "产业园区数据，0 条" })).toHaveAttribute(
      "href",
      "/asset-center/market/industrial-parks",
    );
    expect(screen.queryByText("产业画像")).not.toBeInTheDocument();
    expect(screen.queryByText(/进入产业政策数据/)).not.toBeInTheDocument();
  });

  it("does not present API failures as zero counts", () => {
    render(<AssetCenterOverview counts={null} />);

    expect(screen.getByRole("link", { name: "产业政策，数量暂不可用" })).toBeInTheDocument();
    expect(screen.getAllByText("--").length).toBeGreaterThan(0);
  });
});
