import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const { getApiData, content } = vi.hoisted(() => ({ getApiData: vi.fn(), content: vi.fn() }));
vi.mock("@/lib/api", () => ({ getApiData }));
vi.mock("./_components/IamAuditContent", () => ({
  IamAuditContent: (props: unknown) => {
    content(props);
    return null;
  },
}));
import IamAuditPage from "./page";

describe("audit log page data contract", () => {
  it("loads a filtered backend page and full event choices with Token refresh excluded", async () => {
    getApiData.mockResolvedValue({
      data: [],
      total: 125,
      ok: true,
      error: null,
      traceId: "trace-1",
    });
    render(
      await IamAuditPage({
        searchParams: Promise.resolve({
          event: "VersionStatusChanged",
          page: "3",
          pageSize: "50",
        }),
      }),
    );
    expect(screen.getByRole("heading", { name: "审计日志" })).toBeInTheDocument();
    expect(getApiData).toHaveBeenCalledWith("/internal/v1/audit-logs", [], {
      event_type: "VersionStatusChanged",
      page: "3",
      pageSize: "50",
      exclude_token_refresh: "true",
    });
    expect(getApiData).toHaveBeenCalledWith("/internal/v1/audit-logs/event-types", [], {
      exclude_token_refresh: "true",
    });
    expect(content).toHaveBeenCalledWith(
      expect.objectContaining({
        eventType: "VersionStatusChanged",
        currentPage: 3,
        pageSize: 50,
        totalCount: 125,
      }),
    );
  });

  it("shows API errors instead of presenting a failed load as an empty success", async () => {
    getApiData.mockResolvedValue({
      data: [],
      total: null,
      ok: false,
      error: "audit unavailable",
      traceId: "trace-failed",
    });
    render(await IamAuditPage({ searchParams: Promise.resolve({}) }));
    expect(screen.getByText(/audit unavailable/)).toBeInTheDocument();
  });
});
