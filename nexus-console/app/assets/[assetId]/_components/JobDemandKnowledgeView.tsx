"use client";

/**
 * B9.2 — Job-demand record asset knowledge view.
 *
 * Layout (per design §9.2):
 * - Dataset summary card (counts + source channel)
 * - Filter bar (city / industry / enterprise_size / employment_type)
 * - Records table (paginated, expandable row → record detail)
 * - Extracted-item drawer (skills / tools / certificates / literacy)
 * - Quality issues list (from dataset.quality_summary)
 *
 * All API calls go through `lib/api.ts::getApiData`. No direct fetch. No
 * inline styles for static layout (only run-time computed values via the
 * Antd component API).
 */

import { useEffect, useMemo, useState } from "react";
import {
  Alert, Badge, Button, Card, Drawer, Empty, Input, Select, Skeleton,
  Statistic, Table, Tag, Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  getApiData,
  type JobDemandDataset,
  type JobDemandRecord,
  type JobDemandRequirementItem,
} from "@/lib/api";

type Props = { normalizedRefId: string };

type DatasetListEnvelope = JobDemandDataset[];
type RecordListEnvelope = JobDemandRecord[];
type ItemListEnvelope = JobDemandRequirementItem[];


export function JobDemandKnowledgeView({ normalizedRefId }: Props) {
  // ── Dataset (one per ref; B4 writer enforces it) ──────────────────────
  const [datasetState, setDatasetState] = useState<{
    loading: boolean;
    dataset: JobDemandDataset | null;
    error: string | null;
  }>({ loading: true, dataset: null, error: null });

  useEffect(() => {
    let active = true;
    setDatasetState({ loading: true, dataset: null, error: null });
    getApiData<DatasetListEnvelope>(
      "/open/v1/record-assets/job-demand-datasets",
      [],
      { normalized_ref_id: normalizedRefId, page_size: "1" },
    ).then((res) => {
      if (!active) return;
      if (!res.ok) {
        setDatasetState({ loading: false, dataset: null, error: res.error });
        return;
      }
      setDatasetState({
        loading: false,
        dataset: res.data[0] ?? null,
        error: null,
      });
    });
    return () => { active = false; };
  }, [normalizedRefId]);

  if (datasetState.loading) {
    return <Skeleton active paragraph={{ rows: 6 }} />;
  }
  if (datasetState.error) {
    return (
      <Alert
        type="error" showIcon
        title="加载岗位需求数据集失败"
        description={datasetState.error}
      />
    );
  }
  if (!datasetState.dataset) {
    return (
      <Empty
        description="该 ref 没有关联的岗位需求数据集"
        image={Empty.PRESENTED_IMAGE_SIMPLE}
      />
    );
  }
  return <Loaded dataset={datasetState.dataset} />;
}

// ---------------------------------------------------------------------------
// Loaded view (separated so React unmounts the filter / table state cleanly
// when the dataset is refetched, e.g. via parent re-render).
// ---------------------------------------------------------------------------


function Loaded({ dataset }: { dataset: JobDemandDataset }) {
  return (
    <div className="flex flex-col gap-4">
      <DatasetSummary dataset={dataset} />
      <RecordsSection dataset={dataset} />
      <QualityIssues quality={dataset.quality_summary} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Dataset summary card
// ---------------------------------------------------------------------------


function DatasetSummary({ dataset }: { dataset: JobDemandDataset }) {
  const validCount = Math.max(
    0, dataset.record_count - (dataset.invalid_count ?? 0),
  );
  return (
    <Card title="数据集概要" size="small">
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <Statistic title="记录总数" value={dataset.record_count} />
        <Statistic
          title="有效记录"
          value={validCount}
          valueStyle={{ color: "var(--success-600)" }}
        />
        <Statistic
          title="重复记录"
          value={dataset.duplicate_count}
          valueStyle={{ color: "var(--warning-600)" }}
        />
        <Statistic
          title="无效记录"
          value={dataset.invalid_count}
          valueStyle={{ color: "var(--danger-600)" }}
        />
      </div>
      <div className="text-muted mt-3 flex flex-wrap gap-x-6 gap-y-1 text-sm">
        <span>专业：{dataset.major_name ?? "—"}</span>
        <span>默认行业：{dataset.industry_name ?? "—"}</span>
        <span>来源渠道：{dataset.source_channel}</span>
        <span>Schema：{dataset.schema_version}</span>
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Records section — filter + paginated table + expandable row
// ---------------------------------------------------------------------------


type RecordFilters = {
  city: string;
  industry_name: string;
  enterprise_size: string;
  employment_type: string;
};


function RecordsSection({ dataset }: { dataset: JobDemandDataset }) {
  const [filters, setFilters] = useState<RecordFilters>({
    city: "", industry_name: "", enterprise_size: "", employment_type: "",
  });
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [state, setState] = useState<{
    loading: boolean;
    records: JobDemandRecord[];
    total: number;
    error: string | null;
  }>({ loading: true, records: [], total: 0, error: null });

  // Pull whichever filters are non-empty into the query string. The
  // backend treats missing params as "no filter" so we don't have to
  // wrap each in undefined-checking.
  const queryParams = useMemo(() => {
    const params: Record<string, string> = {
      page: String(page), page_size: String(pageSize),
    };
    for (const [k, v] of Object.entries(filters)) {
      const trimmed = v.trim();
      if (trimmed) params[k] = trimmed;
    }
    return params;
  }, [filters, page, pageSize]);

  useEffect(() => {
    let active = true;
    setState((prev) => ({ ...prev, loading: true, error: null }));
    getApiData<RecordListEnvelope>(
      `/open/v1/record-assets/job-demand-datasets/${dataset.id}/records`,
      [],
      queryParams,
    ).then((res) => {
      if (!active) return;
      if (!res.ok) {
        setState({ loading: false, records: [], total: 0, error: res.error });
        return;
      }
      setState({
        loading: false,
        records: res.data,
        total: res.total ?? res.data.length,
        error: null,
      });
    });
    return () => { active = false; };
  }, [dataset.id, queryParams]);

  const columns: ColumnsType<JobDemandRecord> = useMemo(() => [
    {
      title: "岗位", dataIndex: "job_title", key: "job_title",
      render: (text: string | null) => text || <span className="text-muted">—</span>,
    },
    { title: "公司", dataIndex: "company_name", key: "company" },
    { title: "城市", dataIndex: "city", key: "city" },
    { title: "薪资", dataIndex: "salary_text", key: "salary" },
    { title: "学历", dataIndex: "education_requirement", key: "edu" },
    { title: "经验", dataIndex: "experience_requirement", key: "exp" },
    { title: "企业规模", dataIndex: "enterprise_size", key: "size" },
    { title: "行业", dataIndex: "industry_name", key: "industry" },
  ], []);

  return (
    <Card
      title="岗位记录"
      size="small"
      extra={<span className="text-muted text-sm">共 {state.total} 条</span>}
    >
      <FilterBar filters={filters} onChange={(next) => { setFilters(next); setPage(1); }} />
      {state.error ? (
        <Alert
          type="error" showIcon title="加载记录失败" description={state.error}
          className="!mt-3"
        />
      ) : null}
      <Table<JobDemandRecord>
        size="small"
        rowKey="id"
        loading={state.loading}
        columns={columns}
        dataSource={state.records}
        pagination={{
          current: page, pageSize, total: state.total,
          showSizeChanger: true,
          pageSizeOptions: [10, 20, 50, 100],
          onChange: (p, ps) => { setPage(p); setPageSize(ps); },
        }}
        expandable={{
          expandedRowRender: (record) => <RecordDetail record={record} />,
        }}
        locale={{ emptyText: <Empty description="无匹配记录" image={Empty.PRESENTED_IMAGE_SIMPLE} /> }}
      />
    </Card>
  );
}


function FilterBar({
  filters, onChange,
}: { filters: RecordFilters; onChange: (next: RecordFilters) => void }) {
  return (
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
      <Input.Search
        placeholder="城市" allowClear value={filters.city}
        onChange={(e) => onChange({ ...filters, city: e.target.value })}
        aria-label="按城市筛选岗位记录"
      />
      <Input.Search
        placeholder="行业" allowClear value={filters.industry_name}
        onChange={(e) => onChange({ ...filters, industry_name: e.target.value })}
        aria-label="按行业筛选岗位记录"
      />
      <Input.Search
        placeholder="企业规模（原文匹配）" allowClear
        value={filters.enterprise_size}
        onChange={(e) => onChange({ ...filters, enterprise_size: e.target.value })}
        aria-label="按企业规模筛选岗位记录"
      />
      <Select
        placeholder="雇佣类型" allowClear value={filters.employment_type || undefined}
        onChange={(v) => onChange({ ...filters, employment_type: v ?? "" })}
        options={[
          { value: "全职", label: "全职" },
          { value: "兼职", label: "兼职" },
          { value: "实习", label: "实习" },
          { value: "校园招聘", label: "校园招聘" },
        ]}
        aria-label="按雇佣类型筛选岗位记录"
      />
    </div>
  );
}


// ---------------------------------------------------------------------------
// Expanded record detail — extracted items + raw description
// ---------------------------------------------------------------------------


function RecordDetail({ record }: { record: JobDemandRecord }) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  return (
    <div className="flex flex-col gap-3">
      {record.job_description ? (
        <section>
          <Typography.Text strong>岗位描述</Typography.Text>
          <Typography.Paragraph className="text-sm whitespace-pre-wrap !mb-0 !mt-1">
            {record.job_description}
          </Typography.Paragraph>
        </section>
      ) : null}
      {record.job_skill_text ? (
        <section>
          <Typography.Text strong>岗位技能说明</Typography.Text>
          <Typography.Paragraph className="text-sm whitespace-pre-wrap !mb-0 !mt-1">
            {record.job_skill_text}
          </Typography.Paragraph>
        </section>
      ) : null}
      <div>
        <Button size="small" onClick={() => setDrawerOpen(true)}>
          查看抽取项
        </Button>
      </div>
      <ExtractedItemsDrawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        recordId={record.id}
        recordTitle={record.job_title}
      />
    </div>
  );
}


function ExtractedItemsDrawer({
  open, onClose, recordId, recordTitle,
}: {
  open: boolean; onClose: () => void;
  recordId: string; recordTitle: string;
}) {
  const [state, setState] = useState<{
    loading: boolean;
    items: JobDemandRequirementItem[];
    error: string | null;
  }>({ loading: false, items: [], error: null });

  useEffect(() => {
    if (!open) return;
    let active = true;
    setState({ loading: true, items: [], error: null });
    getApiData<ItemListEnvelope>(
      `/open/v1/record-assets/job-demand-records/${recordId}/requirement-items`,
      [],
    ).then((res) => {
      if (!active) return;
      if (!res.ok) {
        setState({ loading: false, items: [], error: res.error });
        return;
      }
      setState({ loading: false, items: res.data, error: null });
    });
    return () => { active = false; };
  }, [open, recordId]);

  return (
    <Drawer
      title={`抽取项 · ${recordTitle}`}
      width={520}
      onClose={onClose}
      open={open}
      destroyOnHidden
    >
      {state.loading ? <Skeleton active /> : null}
      {state.error ? (
        <Alert
          type="error" showIcon title="加载失败" description={state.error}
        />
      ) : null}
      {!state.loading && !state.error && state.items.length === 0 ? (
        <Empty description="该记录暂无抽取项（B5 LLM 尚未运行或全部被拒绝）" />
      ) : null}
      {!state.loading && state.items.length > 0 ? (
        <ItemsByType items={state.items} />
      ) : null}
    </Drawer>
  );
}


function ItemsByType({ items }: { items: JobDemandRequirementItem[] }) {
  const grouped = useMemo(() => {
    const map = new Map<string, JobDemandRequirementItem[]>();
    for (const it of items) {
      const list = map.get(it.item_type) ?? [];
      list.push(it);
      map.set(it.item_type, list);
    }
    return Array.from(map.entries());
  }, [items]);
  const labels: Record<string, string> = {
    professional_skill: "职业技能",
    tool: "工具",
    certificate: "证书",
    professional_literacy: "职业素养",
    work_task_candidate: "候选工作任务",
  };
  return (
    <div className="flex flex-col gap-4">
      {grouped.map(([type, list]) => (
        <section key={type}>
          <Typography.Text strong>
            {labels[type] ?? type} <Badge count={list.length} showZero={false} />
          </Typography.Text>
          <div className="mt-2 flex flex-wrap gap-2">
            {list.map((item) => (
              <Tag
                key={item.id}
                color={item.confidence >= 0.85 ? "blue" : "default"}
                title={item.raw_text ?? undefined}
              >
                {item.item_name}
                <span className="ml-1 text-xs opacity-70">
                  {(item.confidence * 100).toFixed(0)}%
                </span>
              </Tag>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}


// ---------------------------------------------------------------------------
// Quality issues list
// ---------------------------------------------------------------------------


function QualityIssues({ quality }: { quality: Record<string, unknown> }) {
  const entries = useMemo(
    () => Object.entries(quality).filter(([, v]) => v !== false && v != null),
    [quality],
  );
  if (entries.length === 0) {
    return null;  // hide card entirely when no issues
  }
  return (
    <Card title="质量问题" size="small">
      <ul className="m-0 list-none pl-0">
        {entries.map(([key, val]) => (
          <li key={key} className="text-sm py-1">
            <Tag color="warning" className="mr-2">{key}</Tag>
            <span>{String(val)}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}
