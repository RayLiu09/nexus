"use client";

import { useCallback } from "react";
import Link from "next/link";
import { useRouter, usePathname } from "next/navigation";
import { Table, Tag, Select, Button, Card } from "antd";
import { SaveOutlined } from "@ant-design/icons";
import type { ColumnsType, TablePaginationConfig } from "antd/es/table";
import type { FilterValue, SorterResult } from "antd/es/table/interface";
import { ApiState } from "@/components/ApiState";
import { StatusLabel } from "@/components/StatusLabel";
import { CopyableShortId } from "@/components/shared/CopyableShortId";
import { formatTime } from "@/lib/format-time";
import type { AssetWithMeta, AssetSummary, AssetStats } from "../_lib/types";
import {
  DOMAIN_OPTIONS,
  canonicalDomain,
  domainLabel,
  toAssetStats,
} from "../_lib/types";
import { AssetsSummary } from "./AssetsSummary";
import { DEFAULT_PAGE_SIZE } from "@/lib/pagination";

type AssetCatalogFilters = {
  domain?: string;
  level?: string;
  status?: string;
};

const FILTER_UNCHANGED = Symbol("filter-unchanged");

type AssetCatalogFilterPatch = {
  domain?: string | typeof FILTER_UNCHANGED;
  level?: string | typeof FILTER_UNCHANGED;
  status?: string | typeof FILTER_UNCHANGED;
};

const DOMAIN_COLORS = [
  "geekblue",
  "cyan",
  "green",
  "gold",
  "orange",
  "magenta",
  "purple",
  "blue",
  "lime",
  "volcano",
  "default",
];

function domainColor(domain: string | null | undefined): string {
  if (!domain) return "default";
  let hash = 0;
  for (const ch of domain) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return DOMAIN_COLORS[hash % DOMAIN_COLORS.length];
}

const LEVEL_COLOR_KEY: Record<string, string> = {
  L1: "success",
  L2: "processing",
  L3: "warning",
  L4: "error",
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
  filters: AssetCatalogFilters;
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
  filters,
  ok,
  error,
  traceId,
}: AssetsContentProps) {
  const router = useRouter();
  const pathname = usePathname();

  const stats = summary ? toAssetStats(summary) : EMPTY_STATS;

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
      if (filters.domain) params.set("domain", filters.domain);
      if (filters.level) params.set("level", filters.level);
      if (filters.status) params.set("status", filters.status);
      const qs = params.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname);
    },
    [filters.domain, filters.level, filters.status, router, pathname],
  );

  const updateFilters = useCallback(
    (next: AssetCatalogFilterPatch) => {
      const params = new URLSearchParams();
      const nextDomain = next.domain === FILTER_UNCHANGED ? filters.domain : next.domain;
      const nextLevel = next.level === FILTER_UNCHANGED ? filters.level : next.level;
      const nextStatus = next.status === FILTER_UNCHANGED ? filters.status : next.status;
      if (nextDomain) params.set("domain", nextDomain);
      if (nextLevel) params.set("level", nextLevel);
      if (nextStatus) params.set("status", nextStatus);
      if (pageSize !== DEFAULT_PAGE_SIZE) {
        params.set("pageSize", String(pageSize));
      }
      const qs = params.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname);
    },
    [filters.domain, filters.level, filters.status, pageSize, pathname, router],
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
          <div style={{ marginTop: 2 }}>
            <CopyableShortId value={r.id} className="text-secondary font-mono text-[11px]" />
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
          <CopyableShortId
            value={r.current_normalized_ref_id}
            className="text-secondary font-mono text-xs"
          />
        ) : (
          <span style={{ color: "var(--text-muted)" }}>-</span>
        ),
    },
    {
      title: "域 / 分级",
      width: 140,
      render: (_, r) => {
        const domain = canonicalDomain(r.domain);
        return (
          <span>
            {domain && (
              <Tag color={domainColor(domain)}>{domainLabel(domain, r.domain_name)}</Tag>
            )}
            {r.level && <Tag color={LEVEL_COLOR_KEY[r.level] ?? "default"}>{r.level}</Tag>}
          </span>
        );
      },
    },
    {
      title: "质量",
      dataIndex: "quality_score",
      width: 80,
      align: "center" as const,
      render: (s?: number) =>
        s != null ? (
          <strong className="text-num">{s}</strong>
        ) : (
          <span style={{ color: "var(--text-muted)" }}>-</span>
        ),
    },
    {
      title: "治理",
      width: 160,
      render: (_, r) =>
        r.governance_status ? (
          <StatusLabel value={r.governance_status} />
        ) : (
          <span style={{ color: "var(--text-muted)" }}>-</span>
        ),
    },
    {
      title: "索引",
      width: 110,
      render: (_, r) =>
        r.index_status ? (
          <StatusLabel value={r.index_status} />
        ) : (
          <span style={{ color: "var(--text-muted)" }}>-</span>
        ),
    },
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
          <time
            dateTime={ft.iso}
            title={ft.iso}
            style={{ fontSize: 12, color: "var(--text-muted)" }}
          >
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
          value={filters.domain ?? "all-domain"}
          options={[{ value: "all-domain", label: "全部数据域" }, ...DOMAIN_OPTIONS]}
          onChange={(value) => updateFilters({
            domain: value === "all-domain" ? undefined : value,
            level: FILTER_UNCHANGED,
            status: FILTER_UNCHANGED,
          })}
          style={{ width: 180 }}
        />
        <Select
          value={filters.level ?? "all-level"}
          options={[
            { value: "all-level", label: "全部分级" },
            { value: "L1", label: "L1 公开" },
            { value: "L2", label: "L2 内部" },
            { value: "L3", label: "L3 机密" },
            { value: "L4", label: "L4 受控" },
          ]}
          onChange={(value) => updateFilters({
            domain: FILTER_UNCHANGED,
            level: value === "all-level" ? undefined : value,
            status: FILTER_UNCHANGED,
          })}
          style={{ width: 130 }}
        />
        <Select
          value={filters.status ?? "visible"}
          options={[
            { value: "visible", label: "available + review_required" },
            { value: "all", label: "全部状态" },
            { value: "archived", label: "归档" },
          ]}
          onChange={(value) => updateFilters({
            domain: FILTER_UNCHANGED,
            level: FILTER_UNCHANGED,
            status: value === "all" ? undefined : value,
          })}
          style={{ width: 240 }}
        />
        <Button icon={<SaveOutlined />}>保存视图</Button>
      </div>

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
    </>
  );
}
