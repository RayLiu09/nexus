"use client";

import { useCallback, useState, useTransition } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Button, Input, Select, Table, Tabs, Tag, Tooltip } from "antd";
import type { ColumnsType } from "antd/es/table";
import { Search, X } from "lucide-react";

import { ApiState } from "@/components/ApiState";
import type { EcommerceDemoBase, EcommerceDemoBaseAggregate } from "@/lib/api";
import { NationalDemoBaseDistribution } from "./NationalDemoBaseDistribution";

export type EcommerceDemoBaseFilters = {
  q?: string;
  batch?: string;
  province_code?: string;
  recognized_year?: number;
};

type Props = {
  rows: EcommerceDemoBase[];
  total: number | null;
  page: number;
  pageSize: number;
  level: "national" | "provincial";
  filters: EcommerceDemoBaseFilters;
  aggregate: EcommerceDemoBaseAggregate | null;
  ok: boolean;
  error: string | null;
  traceId: string | null;
};

const BATCHES = [
  { value: "first", label: "首批" },
  { value: "second", label: "第二批" },
  { value: "supplement", label: "增补" },
];

function queryString(
  level: Props["level"],
  filters: EcommerceDemoBaseFilters,
  page = 1,
  pageSize = 20,
) {
  const search = new URLSearchParams({ level });
  if (filters.q?.trim()) search.set("q", filters.q.trim());
  if (level === "national" && filters.batch) search.set("batch", filters.batch);
  if (filters.province_code) search.set("province_code", filters.province_code);
  if (filters.recognized_year) search.set("recognized_year", String(filters.recognized_year));
  if (page > 1) search.set("page", String(page));
  if (pageSize !== 20) search.set("pageSize", String(pageSize));
  return search.toString();
}

export function EcommerceDemoBasesView(props: Props) {
  const { level, aggregate, filters } = props;
  const router = useRouter();
  const pathname = usePathname();
  const [pending, startTransition] = useTransition();
  // The route keys this component by submitted URL parameters. Navigation and
  // browser history therefore restore the corresponding draft controls.
  const [draft, setDraft] = useState<EcommerceDemoBaseFilters>(filters);
  const navigate = useCallback(
    (next: EcommerceDemoBaseFilters, nextPage = 1, nextPageSize = props.pageSize) => {
      startTransition(() =>
        router.push(`${pathname}?${queryString(level, next, nextPage, nextPageSize)}`, {
          scroll: false,
        }),
      );
    },
    [level, pathname, props.pageSize, router],
  );
  const selectProvince = useCallback(
    (code?: string) => {
      navigate({ ...filters, province_code: code === filters.province_code ? undefined : code });
    },
    [filters, navigate],
  );

  const columns: ColumnsType<EcommerceDemoBase> = [
    {
      title: "序号",
      width: 72,
      align: "center",
      render: (_value, _row, index) => (props.page - 1) * props.pageSize + index + 1,
    },
    {
      title: "基地名称",
      dataIndex: "title",
      width: 360,
      render: (title: string, row) =>
        row.source_url ? (
          <a
            href={row.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="font-medium"
          >
            {title}
          </a>
        ) : (
          <span className="font-medium">{title}</span>
        ),
    },
    {
      title: "省份",
      dataIndex: "province_name",
      width: 120,
      render: (value: string | null) => value || "-",
    },
    ...(level === "national"
      ? [
          {
            title: "批次",
            dataIndex: "batch_name",
            width: 100,
            render: (value: string | null) => <Tag color="blue">{value || "-"}</Tag>,
          },
        ]
      : []),
    { title: "认定年月", dataIndex: "recognized_period", width: 125 },
    ...(level === "provincial"
      ? [
          {
            title: "来源发布时间",
            dataIndex: "source_publish_at",
            width: 155,
            render: (value: string | null) =>
              value
                ? new Intl.DateTimeFormat("zh-CN", {
                    timeZone: "Asia/Shanghai",
                    year: "numeric",
                    month: "2-digit",
                    day: "2-digit",
                  }).format(new Date(value))
                : "-",
          },
        ]
      : []),
    {
      title: "操作",
      width: 130,
      render: (_value: unknown, row: EcommerceDemoBase) =>
        row.source_url ? (
          <a href={row.source_url} target="_blank" rel="noopener noreferrer">
            查看原文
          </a>
        ) : (
          <Tooltip title="来源未开放链接">
            <span className="text-text-muted">来源未开放链接</span>
          </Tooltip>
        ),
    },
  ];

  return (
    <div className="flex min-w-0 flex-col gap-5" aria-busy={pending}>
      <ApiState
        ok={props.ok}
        error={props.error}
        traceId={props.traceId}
        onRetry={() => router.refresh()}
      />
      <Tabs
        activeKey={level}
        items={[
          { key: "national", label: "国家" },
          { key: "provincial", label: "省份" },
        ]}
        onChange={(value) =>
          startTransition(() =>
            router.push(
              `${pathname}?${queryString(value === "provincial" ? "provincial" : "national", {}, 1, props.pageSize)}`,
              { scroll: false },
            ),
          )
        }
      />
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-text text-base font-semibold">
          {level === "national" ? "国家电子商务示范基地" : "省级电子商务示范基地"}
        </h2>
        {aggregate && (
          <span className="text-text-muted text-sm">
            已收录 {aggregate.coverage.imported_total.toLocaleString("zh-CN")} 条 · 覆盖{" "}
            {aggregate.filter_options.provinces.length} 个省级地区
          </span>
        )}
      </div>
      {level === "national" && aggregate && (
        <>
          <div className="flex flex-wrap items-center gap-2" aria-label="批次筛选">
            <Button
              type={!filters.batch ? "primary" : "default"}
              onClick={() => navigate({ ...filters, batch: undefined })}
            >
              整体情况
            </Button>
            {BATCHES.map((batch) => (
              <Button
                key={batch.value}
                type={filters.batch === batch.value ? "primary" : "default"}
                onClick={() => navigate({ ...filters, batch: batch.value })}
              >
                {batch.label}（
                {aggregate.batch_counts.find((item) => item.code === batch.value)?.count ?? 0}）
              </Button>
            ))}
            <span className="text-text-secondary ml-auto text-sm" role="status">
              当前条件：<strong className="text-blue-700">{aggregate.matched_total}</strong> 个基地
            </span>
          </div>
          <NationalDemoBaseDistribution
            aggregate={aggregate}
            selectedProvince={filters.province_code}
            onProvinceSelect={selectProvince}
          />
        </>
      )}
      <section className="border-line bg-surface min-w-0 border-y">
        <form
          className="border-line flex flex-wrap items-center justify-end gap-2 border-b px-4 py-3"
          onSubmit={(event) => {
            event.preventDefault();
            navigate(draft);
          }}
        >
          <Input
            className="w-60 max-w-full"
            aria-label="基地名称"
            placeholder="基地名称"
            value={draft.q ?? ""}
            onChange={(event) => setDraft((old) => ({ ...old, q: event.target.value }))}
          />
          <Select
            className="w-36"
            aria-label="省份"
            allowClear
            placeholder="全部省份"
            value={draft.province_code}
            options={aggregate?.filter_options.provinces.map((item) => ({
              value: item.province_code,
              label: item.province_name,
            }))}
            onChange={(value: string | undefined) =>
              setDraft((old) => ({ ...old, province_code: value }))
            }
          />
          <Select
            className="w-32"
            aria-label="认定年份"
            allowClear
            placeholder="认定年份"
            value={draft.recognized_year}
            options={aggregate?.filter_options.recognized_years.map((year) => ({
              value: year,
              label: `${year}年`,
            }))}
            onChange={(value: number | undefined) =>
              setDraft((old) => ({ ...old, recognized_year: value }))
            }
          />
          <Button type="primary" htmlType="submit" icon={<Search size={15} />} loading={pending}>
            检索
          </Button>
          <Button
            icon={<X size={15} />}
            onClick={() => {
              setDraft({});
              navigate({});
            }}
          >
            重置
          </Button>
        </form>
        <Table<EcommerceDemoBase>
          rowKey="id"
          columns={columns}
          dataSource={props.rows}
          loading={pending}
          scroll={{ x: level === "national" ? 1010 : 1060 }}
          pagination={
            props.total === null
              ? false
              : {
                  current: props.page,
                  pageSize: props.pageSize,
                  total: props.total,
                  showSizeChanger: true,
                  pageSizeOptions: [20, 50, 100],
                  showTotal: (count) => `共 ${count} 条`,
                  onChange: (page, size) =>
                    navigate(filters, size === props.pageSize ? page : 1, size),
                }
          }
          locale={{
            emptyText: !props.ok
              ? "数据加载失败，请重试"
              : aggregate?.coverage.imported_total === 0
                ? "暂无电子商务示范基地数据"
                : "未找到匹配基地",
          }}
        />
      </section>
    </div>
  );
}
