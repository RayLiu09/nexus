"use client";

import { useCallback } from "react";
import Link from "next/link";
import { useRouter, usePathname } from "next/navigation";
import { Table, Tag, Select, Button, Alert, Card } from "antd";
import { SaveOutlined } from "@ant-design/icons";
import type { ColumnsType, TablePaginationConfig } from "antd/es/table";
import type { FilterValue, SorterResult } from "antd/es/table/interface";
import { ApiState } from "@/components/ApiState";
import { StatusLabel } from "@/components/StatusLabel";
import { formatTime } from "@/lib/format-time";
import type { AssetWithMeta, AssetSummary, AssetStats, DomainDistItem } from "../_lib/types";
import { toAssetStats, toDomainDistItems } from "../_lib/types";
import { AssetsSummary } from "./AssetsSummary";
import { DomainDistribution } from "./DomainDistribution";
import { DEFAULT_PAGE_SIZE } from "@/lib/pagination";

const DOMAIN_COLOR_KEY: Record<string, string> = {
  D1: "geekblue", D2: "cyan", D3: "green",
  D4: "gold", D5: "orange", D6: "magenta",
};

const LEVEL_COLOR_KEY: Record<string, string> = {
  L1: "success", L2: "processing", L3: "warning", L4: "error",
};

const EMPTY_STATS: AssetStats = {
  available: 0,
  reviewRequired: 0,
  currentNormalizedRefs: 0,
  staleIndex: 0,
  l3l4: 0,
  autoAdoptionRate: 0,
};

interface AssetsContentProps {
  assets: AssetWithMeta[];
  /** Pre-computed aggregate from /v1/assets/summary. */
  summary: AssetSummary | null;
  totalCount: number;
  currentPage: number;
  pageSize: number;
  ok: boolean;
  error: string | null;
  traceId: string | null;
}

export function AssetsContent({
  assets,
  summary,
  totalCount,
  currentPage,
  pageSize,
  ok,
  error,
  traceId,
}: AssetsContentProps) {
  const router = useRouter();
  const pathname = usePathname();

  const stats = summary ? toAssetStats(summary) : EMPTY_STATS;
  const domainDist: DomainDistItem[] = summary ? toDomainDistItems(summary) : [];

  const handleTableChange = useCallback(
    (
      pagination: TablePaginationConfig,
      _filters: Record<string, FilterValue | null>,
      _sorter: SorterResult<AssetWithMeta> | SorterResult<AssetWithMeta>[],
    ) => {
      const params = new URLSearchParams();
      if (pagination.current && pagination.current > 1) {
        params.set("page", String(pagination.current));
      }
      if (pagination.pageSize && pagination.pageSize !== DEFAULT_PAGE_SIZE) {
        params.set("pageSize", String(pagination.pageSize));
      }
      const qs = params.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname);
    },
    [router, pathname],
  );

  const columns: ColumnsType<AssetWithMeta> = [
    {
      title: "资产",
      dataIndex: "title",
      width: 280,
      fixed: "left",
      render: (title: string, r) => (
        <div>
          <Link
            href={`/assets/${r.id}`}
            className="font-semibold"
            style={{ color: "var(--brand)" }}
          >
            {title}
          </Link>
          <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>
            <code>{r.id.slice(0, 18)}…</code>
          </div>
        </div>
      ),
    },
    {
      title: "当前版本",
      width: 160,
      render: (_, r) => (
        <span style={{ fontSize: 13 }}>
          {r.current_version_no ? (
            <code>{r.current_version_no}</code>
          ) : (
            <span style={{ color: "var(--text-muted)" }}>-</span>
          )}
        </span>
      ),
    },
    {
      title: "标准化引用",
      width: 200,
      render: (_, r) =>
        r.current_normalized_ref_id ? (
          <code style={{ fontSize: 12 }}>{r.current_normalized_ref_id.slice(0, 22)}…</code>
        ) : (
          <span style={{ color: "var(--text-muted)" }}>-</span>
        ),
    },
    {
      title: "域 / 分级",
      width: 140,
      render: (_, r) => (
        <span>
          {r.domain && <Tag color={DOMAIN_COLOR_KEY[r.domain] ?? "default"}>{r.domain}</Tag>}
          {r.level && <Tag color={LEVEL_COLOR_KEY[r.level] ?? "default"}>{r.level}</Tag>}
        </span>
      ),
    },
    {
      title: "质量",
      dataIndex: "quality_score",
      width: 80,
      align: "center" as const,
      render: (s?: number) =>
        s != null ? <strong className="text-num">{s}</strong> : <span style={{ color: "var(--text-muted)" }}>-</span>,
    },
    { title: "治理", width: 160, render: (_, r) => r.governance_status ? <StatusLabel value={r.governance_status} /> : <span style={{ color: "var(--text-muted)" }}>-</span> },
    { title: "索引", width: 110, render: (_, r) => r.index_status ? <StatusLabel value={r.index_status} /> : <span style={{ color: "var(--text-muted)" }}>-</span> },
    {
      title: "组织范围",
      width: 180,
      render: (_, r) =>
        r.org_scope?.length ? (
          r.org_scope.join(" / ")
        ) : (
          <span style={{ color: "var(--text-muted)" }}>-</span>
        ),
    },
    {
      title: "状态",
      width: 130,
      render: (_, r) => <StatusLabel value={r.status} />,
    },
    {
      title: "更新时间",
      dataIndex: "updated_at",
      width: 150,
      render: (t: string) => {
        const ft = formatTime(t);
        return (
          <time dateTime={ft.iso} title={ft.iso} style={{ fontSize: 12, color: "var(--text-muted)" }}>
            {ft.display}
          </time>
        );
      },
    },
  ];

  return (
    <>
      <ApiState ok={ok} error={error} traceId={traceId} />

      <AssetsSummary stats={stats} />

      <div className="assets-toolbar">
        <Select
          defaultValue="all-domain"
          options={[
            { value: "all-domain", label: "全部数据域" },
            { value: "D1", label: "D1 教学资源" },
            { value: "D2", label: "D2 人才培养" },
            { value: "D3", label: "D3 科研数据" },
            { value: "D4", label: "D4 产教融合" },
            { value: "D5", label: "D5 政策法规" },
            { value: "D6", label: "D6 综合管理" },
          ]}
          style={{ width: 160 }}
        />
        <Select
          defaultValue="all-level"
          options={[
            { value: "all-level", label: "全部分级" },
            { value: "L1", label: "L1 公开" },
            { value: "L2", label: "L2 内部" },
            { value: "L3", label: "L3 机密" },
            { value: "L4", label: "L4 受控" },
          ]}
          style={{ width: 130 }}
        />
        <Select
          defaultValue="visible"
          options={[
            { value: "visible", label: "available + review_required" },
            { value: "all", label: "全部状态" },
            { value: "archived", label: "归档" },
          ]}
          style={{ width: 240 }}
        />
        <Button icon={<SaveOutlined />}>保存视图</Button>
      </div>

      <div className="assets-layout">
        <Card variant="borderless" style={{ minWidth: 0 }}>
          <Table
            rowKey="id"
            dataSource={assets}
            columns={columns}
            size="middle"
            pagination={{
              current: currentPage,
              pageSize,
              total: totalCount,
              showSizeChanger: true,
              showTotal: (total, range) => `${range[0]}-${range[1]} / ${total} 项`,
              pageSizeOptions: ["10", "20", "50"],
            }}
            onChange={handleTableChange}
            scroll={{ x: 1280 }}
            locale={{ emptyText: "暂无资产" }}
          />
        </Card>

        <div className="assets-side">
          <DomainDistribution items={domainDist} />

          <Card title="目录页解释" size="small">
            <Alert
              type="info"
              showIcon={false}
              banner
              message={
                <span style={{ fontSize: 12 }}>
                  <strong>current version</strong> 来自 read model，不在 asset 表上存储反向指针。
                </span>
              }
              style={{ marginBottom: 8 }}
            />
            <Alert
              type="info"
              showIcon={false}
              banner
              message={
                <span style={{ fontSize: 12 }}>
                  <strong>current normalized ref</strong> 只表示当前可读标准化引用，不与 version
                  双向绑定。
                </span>
              }
              style={{ marginBottom: 8 }}
            />
            <Alert
              type="warning"
              showIcon={false}
              banner
              message={
                <span style={{ fontSize: 12 }}>
                  <strong>stale index</strong> 表示需要重建索引，不等于资产不可读。
                </span>
              }
            />
          </Card>
        </div>
      </div>
    </>
  );
}
