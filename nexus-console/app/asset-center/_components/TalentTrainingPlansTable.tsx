"use client";

import { useEffect, useMemo, useState, useTransition } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Button, Drawer, Form, Input, Space, Table, Tag } from "antd";
import type { ColumnsType, TablePaginationConfig } from "antd/es/table";
import { BookOpen, Network, Search, X } from "lucide-react";

import { ApiState } from "@/components/ApiState";
import type {
  TalentTrainingPlanCareerFact,
  TalentTrainingPlanCareerSummary,
  TalentTrainingPlanSummary,
} from "@/lib/api";
import {
  TalentTrainingPlanGraphView,
  type TalentTrainingPlanGraphKind,
} from "./TalentTrainingPlanGraphView";

export type TalentTrainingPlanFilters = {
  major_name?: string;
  major_code?: string;
  institution_name?: string;
  education_level?: string;
};

type Props = {
  rows: TalentTrainingPlanSummary[];
  total: number;
  page: number;
  pageSize: number;
  filters: TalentTrainingPlanFilters;
  ok: boolean;
  error: string | null;
  traceId: string | null;
};

type GraphSelection = {
  plan: TalentTrainingPlanSummary;
  kind: TalentTrainingPlanGraphKind;
};

const EMPTY_FILTERS: TalentTrainingPlanFilters = {
  major_name: undefined,
  major_code: undefined,
  institution_name: undefined,
  education_level: undefined,
};

const EMPTY_CAREER_SUMMARY: TalentTrainingPlanCareerSummary = {
  major_categories: [],
  major_classes: [],
  industries: [],
  occupations: [],
  positions: [],
};

function factLabel(fact: TalentTrainingPlanCareerFact, normalizeLayout: boolean): string {
  let name = fact.name.trim();
  if (normalizeLayout) {
    name = name
      .replace(/(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])/g, "")
      .replace(/\s+([（()）])/g, "$1")
      .replace(/([（(])\s+/g, "$1");
  }
  return `${name}${fact.code ? ` (${fact.code})` : ""}`;
}

function renderFacts(values: TalentTrainingPlanCareerFact[], normalizeLayout = true) {
  if (values.length === 0) return <span className="text-text-muted">-</span>;
  return (
    <Space size={[4, 4]} wrap className="max-w-full">
      {values.map((value) => (
        <Tag
          key={`${value.name}:${value.code ?? ""}`}
          className="!m-0 max-w-full leading-5 break-words whitespace-normal"
        >
          {factLabel(value, normalizeLayout)}
        </Tag>
      ))}
    </Space>
  );
}

export function TalentTrainingPlansTable({
  rows,
  total,
  page,
  pageSize,
  filters,
  ok,
  error,
  traceId,
}: Props) {
  const router = useRouter();
  const pathname = usePathname();
  const [pending, startTransition] = useTransition();
  const [graphSelection, setGraphSelection] = useState<GraphSelection | null>(null);
  const [form] = Form.useForm<TalentTrainingPlanFilters>();

  useEffect(() => form.setFieldsValue({ ...EMPTY_FILTERS, ...filters }), [filters, form]);

  const replaceQuery = (next: TalentTrainingPlanFilters, nextPage = 1, nextPageSize = pageSize) => {
    const search = new URLSearchParams();
    for (const [key, value] of Object.entries(next)) {
      if (value?.trim()) search.set(key, value.trim());
    }
    if (nextPage > 1) search.set("page", String(nextPage));
    if (nextPageSize !== 20) search.set("pageSize", String(nextPageSize));
    startTransition(() => router.replace(`${pathname}${search.size ? `?${search}` : ""}`));
  };

  const columns = useMemo<ColumnsType<TalentTrainingPlanSummary>>(
    () => [
      {
        title: "专业名称",
        dataIndex: "major_name",
        width: 190,
        fixed: "left",
        render: (value: string | null) => <strong>{value || "-"}</strong>,
      },
      {
        title: "专业代码",
        dataIndex: "major_code",
        width: 112,
        render: (value: string | null) => value || "-",
      },
      {
        title: "修业年限",
        dataIndex: "study_duration",
        width: 110,
        align: "center",
        render: (value: string | null) => value || "-",
      },
      {
        title: "培养层次",
        dataIndex: "education_level",
        width: 150,
        render: (value: string | null) => value || "-",
      },
      {
        title: "院校名称",
        dataIndex: "institution_name",
        width: 240,
        render: (value: string | null) => value || "-",
      },
      {
        title: "操作",
        key: "actions",
        width: 270,
        fixed: "right",
        render: (_, row) => (
          <Space size={4}>
            <Button
              type="link"
              size="small"
              icon={<BookOpen size={14} />}
              onClick={() => setGraphSelection({ plan: row, kind: "course" })}
            >
              课程知识图谱
            </Button>
            <Button
              type="link"
              size="small"
              icon={<Network size={14} />}
              onClick={() => setGraphSelection({ plan: row, kind: "position" })}
            >
              岗位能力图谱
            </Button>
          </Space>
        ),
      },
    ],
    [],
  );

  const handleTableChange = (pagination: TablePaginationConfig) => {
    replaceQuery(filters, pagination.current ?? 1, pagination.pageSize ?? pageSize);
  };

  const graphTitle = graphSelection
    ? `${graphSelection.plan.major_name ?? "人才培养方案"} · ${
        graphSelection.kind === "course" ? "课程知识图谱" : "岗位能力图谱"
      }`
    : "人才培养方案图谱";

  return (
    <>
      <ApiState ok={ok} error={error} traceId={traceId} />
      <section className="border-line bg-surface border-y">
        <Form
          form={form}
          layout="inline"
          initialValues={filters}
          className="border-line flex gap-2 border-b px-4 py-3"
          onFinish={(values) => replaceQuery(values)}
        >
          <Form.Item name="major_name" className="!mb-0">
            <Input allowClear placeholder="专业名称" className="w-44" />
          </Form.Item>
          <Form.Item name="major_code" className="!mb-0">
            <Input allowClear placeholder="专业代码" className="w-32" />
          </Form.Item>
          <Form.Item name="institution_name" className="!mb-0">
            <Input allowClear placeholder="院校名称" className="w-52" />
          </Form.Item>
          <Form.Item name="education_level" className="!mb-0">
            <Input allowClear placeholder="培养层次" className="w-40" />
          </Form.Item>
          <Form.Item className="!mb-0">
            <Space size={8}>
              <Button htmlType="submit" type="primary" icon={<Search size={15} />}>
                查询
              </Button>
              <Button
                icon={<X size={15} />}
                onClick={() => {
                  form.setFieldsValue(EMPTY_FILTERS);
                  replaceQuery({});
                }}
              >
                重置
              </Button>
            </Space>
          </Form.Item>
        </Form>

        <Table<TalentTrainingPlanSummary>
          rowKey="id"
          size="small"
          columns={columns}
          dataSource={rows}
          loading={pending}
          tableLayout="fixed"
          scroll={{ x: 1100 }}
          expandable={{
            expandedRowRender: (row) => (
              <CareerOrientationPanel
                summary={row.career_orientation_summary ?? EMPTY_CAREER_SUMMARY}
              />
            ),
          }}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            showTotal: (count) => `共 ${count} 条`,
          }}
          locale={{ emptyText: ok ? "暂无人才培养方案" : "数据加载失败" }}
          onChange={handleTableChange}
        />
      </section>

      <Drawer
        open={graphSelection !== null}
        size="min(1120px, 82vw)"
        title={graphTitle}
        destroyOnHidden
        onClose={() => setGraphSelection(null)}
      >
        {graphSelection ? (
          <TalentTrainingPlanGraphView
            key={`${graphSelection.plan.id}:${graphSelection.kind}`}
            planId={graphSelection.plan.id}
            kind={graphSelection.kind}
          />
        ) : null}
      </Drawer>
    </>
  );
}

function CareerOrientationPanel({ summary }: { summary: TalentTrainingPlanCareerSummary }) {
  return (
    <div
      data-testid="career-orientation-panel"
      className="border-line bg-surface grid grid-cols-[minmax(0,0.72fr)_minmax(0,1.28fr)] overflow-hidden rounded-sm border"
      style={{ marginLeft: 24 }}
    >
      <section aria-labelledby="professional-belonging-heading" className="min-w-0 px-5 py-4">
        <h4
          id="professional-belonging-heading"
          className="text-text-secondary mb-3 flex items-center gap-2 text-sm font-semibold"
        >
          <span className="bg-domain-d2 h-4 w-1 rounded-sm" aria-hidden />
          专业归属
        </h4>
        <dl className="grid grid-cols-2 gap-x-5">
          <CareerFactField label="专业大类（代码）" values={summary.major_categories} />
          <CareerFactField label="专业类（代码）" values={summary.major_classes} />
        </dl>
      </section>

      <section
        aria-labelledby="career-orientation-heading"
        className="border-line bg-surface-alt min-w-0 border-l px-5 py-4"
      >
        <h4
          id="career-orientation-heading"
          className="text-text-secondary mb-3 flex items-center gap-2 text-sm font-semibold"
        >
          <span className="bg-domain-d3 h-4 w-1 rounded-sm" aria-hidden />
          职业面向
        </h4>
        <dl className="grid grid-cols-[minmax(0,0.85fr)_minmax(0,1fr)_minmax(0,1.5fr)] gap-x-5">
          <CareerFactField label="所属行业" values={summary.industries} />
          <CareerFactField label="职业类别" values={summary.occupations} />
          <CareerFactField label="岗位名称" values={summary.positions} normalizeLayout={false} />
        </dl>
      </section>
    </div>
  );
}

function CareerFactField({
  label,
  values,
  normalizeLayout = true,
}: {
  label: string;
  values: TalentTrainingPlanCareerFact[];
  normalizeLayout?: boolean;
}) {
  return (
    <div className="min-w-0">
      <dt className="text-text-muted text-xs font-medium">{label}</dt>
      <dd className="text-text mt-2 min-w-0 text-sm">{renderFacts(values, normalizeLayout)}</dd>
    </div>
  );
}
