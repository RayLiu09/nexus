import { App } from "antd";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { DocumentTagSearch } from "./DocumentTagSearch";

describe("DocumentTagSearch", () => {
  it("trims the three fields on Enter and clears both draft and applied values on reset", async () => {
    const onSearch = vi.fn();
    const user = userEvent.setup();
    render(
      <App>
        <DocumentTagSearch
          filters={{ region: "重庆市", industry: "电子商务", content_tag: "数字" }}
          pending={false}
          onSearch={onSearch}
        />
      </App>,
    );

    const region = screen.getByRole("textbox", { name: "区域" });
    fireEvent.change(region, { target: { value: "  成都市  " } });
    await user.click(region);
    await user.keyboard("{Enter}");
    expect(onSearch).toHaveBeenLastCalledWith({
      region: "成都市",
      industry: "电子商务",
      content_tag: "数字",
    });

    await user.click(screen.getByRole("button", { name: /重\s*置/ }));
    expect(onSearch).toHaveBeenLastCalledWith({});
    expect(region).toHaveValue("");
  });
});
