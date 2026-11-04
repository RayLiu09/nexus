import { describe, expect, it, vi } from "vitest";
import { IamAuditContent } from "./IamAuditContent";
import type { AuditLog } from "@/lib/api";
import { renderWithProviders, screen } from "@/test-utils/test-renderer";

const replace = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({
  usePathname: () => "/iam-audit",
  useRouter: () => ({ replace }),
}));
vi.stubGlobal(
  "ResizeObserver",
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  },
);

const row: AuditLog = {
  id: "audit-1",
  event_type: "VersionStatusChanged",
  target_type: "asset_version",
  target_id: "version-1",
  target_name: "电子商务人才需求报告",
  actor_type: "user",
  actor_id: "admin-1",
  actor_name: "数据管理员张三",
  trace_id: "trace-1",
  summary: { from_status: "processing", to_status: "available" },
  created_at: "2026-01-01T08:00:00Z",
  updated_at: "2026-01-01T08:00:00Z",
};

const baseProps = {
  audits: [row],
  eventTypes: ["AssetDeleted", "VersionStatusChanged"],
  totalCount: 120,
  currentPage: 1,
  pageSize: 50,
};

describe("administrator audit log list", () => {
  it("shows the six required columns, resolved names and old retained events", () => {
    renderWithProviders(<IamAuditContent {...baseProps} />);
    for (const name of ["事件类型", "操作目标类型", "目标名称", "操作者", "摘要", "操作时间"]) {
      expect(screen.getByRole("columnheader", { name })).toBeInTheDocument();
    }
    expect(screen.getByText("资产版本")).toBeInTheDocument();
    expect(screen.getByText("电子商务人才需求报告")).toBeInTheDocument();
    expect(screen.getByText("数据管理员张三")).toBeInTheDocument();
    expect(screen.getByText("原状态：processing；新状态：available")).toBeInTheDocument();
    expect(document.querySelector("time")?.getAttribute("dateTime")).toContain("2026-01-01");
    expect(screen.getByText("共 120 条审计日志")).toBeInTheDocument();
    expect(screen.queryByText("API 调用方")).not.toBeInTheDocument();
  });

  it("displays recorded executors and missing attribution as unrecorded", () => {
    renderWithProviders(
      <IamAuditContent
        {...baseProps}
        audits={[
          {
            ...row,
            id: "system",
            actor_type: "worker",
            actor_id: "worker-private-id",
            actor_name: null,
          },
          {
            ...row,
            id: "scheduler",
            actor_type: "system",
            actor_id: "crawler-scheduler",
            actor_name: "crawler-scheduler",
          },
          {
            ...row,
            id: "unknown",
            actor_type: null,
            actor_id: null,
            actor_name: null,
            target_name: null,
          },
          { ...row, id: "removed-user", actor_id: "removed-user-full-id", actor_name: null },
        ]}
      />,
    );
    expect(screen.queryByText("system")).not.toBeInTheDocument();
    expect(screen.getByText("worker-private-id")).toBeInTheDocument();
    expect(screen.getByText("crawler-scheduler")).toBeInTheDocument();
    expect(screen.getByText("未记录")).toBeInTheDocument();
    expect(screen.getByText("version-1")).toBeInTheDocument();
    expect(screen.getByText("removed-user-full-id")).toBeInTheDocument();
  });

  it("changes event type from a later page and keeps page size", async () => {
    const { user } = renderWithProviders(
      <IamAuditContent
        {...baseProps}
        audits={[]}
        currentPage={3}
        eventType="VersionStatusChanged"
      />,
    );
    await user.click(screen.getByRole("combobox", { name: "事件类型" }));
    await user.click(screen.getByTitle("AssetDeleted"));
    expect(replace).toHaveBeenLastCalledWith("/iam-audit?event_type=AssetDeleted&pageSize=50");
  });

  it("preserves the event filter while navigating across backend pages", async () => {
    const { user } = renderWithProviders(
      <IamAuditContent {...baseProps} eventType="VersionStatusChanged" />,
    );
    await user.click(screen.getByRole("listitem", { name: "2" }));
    expect(replace).toHaveBeenLastCalledWith(
      "/iam-audit?event_type=VersionStatusChanged&page=2&pageSize=50",
    );
  });

  it("clears the event filter and resets the page", async () => {
    const { user, container } = renderWithProviders(
      <IamAuditContent
        {...baseProps}
        audits={[]}
        currentPage={3}
        eventType="VersionStatusChanged"
      />,
    );
    const clear = container.querySelector(".ant-select-clear");
    expect(clear).not.toBeNull();
    await user.click(clear!);
    expect(replace).toHaveBeenLastCalledWith("/iam-audit?pageSize=50");
    expect(screen.getByText("暂无审计日志")).toBeInTheDocument();
  });
});
