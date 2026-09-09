"use client";

import { useEffect, useMemo, useState, useTransition, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Alert, Button, Empty, Form, Input, Skeleton, Space, Table, Tag } from "antd";
import type { ColumnsType, TablePaginationConfig } from "antd/es/table";
import {
  Award,
  BookOpen,
  BriefcaseBusiness,
  GraduationCap,
  ListChecks,
  Search,
  X,
} from "lucide-react";

import { ApiState } from "@/components/ApiState";
import {
  getApiData,
  type MajorProfile,
  type MajorProfileCourse,
  type MajorProfileItem,
} from "@/lib/api";

export type MajorProfileFilters = {
  major_name?: string;
  major_code?: string;
  education_level?: string;
  institution_name?: string;
};

type Props = {
  rows: MajorProfile[];
  total: number;
  page: number;
  pageSize: number;
  filters: MajorProfileFilters;
  ok: boolean;
  error: string | null;
  traceId: string | null;
};

type DetailState = {
  loading: boolean;
  data: MajorProfile | null;
  error: string | null;
};

const EMPTY_FILTERS: MajorProfileFilters = {
  major_name: undefined,
  major_code: undefined,
  education_level: undefined,
  institution_name: undefined,
};

const COURSE_GROUP_LABELS: Record<string, string> = {
  foundation: "专业基础课程",
  core: "专业核心课程",
  practice_training: "实习实训",
};

export function MajorProfilesTable({
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
  const [details, setDetails] = useState<Record<string, DetailState>>({});
  const [form] = Form.useForm<MajorProfileFilters>();

  useEffect(() => form.setFieldsValue({ ...EMPTY_FILTERS, ...filters }), [filters, form]);

  const replaceQuery = (next: MajorProfileFilters, nextPage = 1, nextPageSize = pageSize) => {
    const search = new URLSearchParams();
    for (const [key, value] of Object.entries(next)) {
      if (value?.trim()) search.set(key, value.trim());
    }
    if (nextPage > 1) search.set("page", String(nextPage));
    if (nextPageSize !== 20) search.set("pageSize", String(nextPageSize));
    startTransition(() => router.replace(`${pathname}${search.size ? `?${search}` : ""}`));
  };

  const loadDetail = (profile: MajorProfile) => {
    if (details[profile.id]) return;
    setDetails((current) => ({
      ...current,
      [profile.id]: { loading: true, data: null, error: null },
    }));
    void getApiData<MajorProfile>(`/api/major-profiles/${profile.id}`, profile).then((result) => {
      setDetails((current) => ({
        ...current,
        [profile.id]: result.ok
          ? { loading: false, data: result.data, error: null }
          : { loading: false, data: null, error: result.error ?? "专业简介详情加载失败" },
      }));
    });
  };

  const columns = useMemo<ColumnsType<MajorProfile>>(
    () => [
      {
        title: "专业名称",
        dataIndex: "major_name",
        width: 250,
        fixed: "left",
        render: (value: string) => <strong>{value || "-"}</strong>,
      },
      {
        title: "专业代码",
        dataIndex: "major_code",
        width: 130,
        render: (value: string | null) => value || "-",
      },
      {
        title: "修业年限",
        dataIndex: "basic_study_duration",
        width: 140,
        render: (value: string | null) => value || "-",
      },
      {
        title: "培养层次",
        dataIndex: "education_level",
        width: 160,
        render: (value: string | null) => value || "-",
      },
      {
        title: "院校名称",
        dataIndex: "institution_name",
        width: 300,
        render: (value: string | null) => value || "-",
      },
    ],
    [],
  );

  const handleTableChange = (pagination: TablePaginationConfig) => {
    replaceQuery(filters, pagination.current ?? 1, pagination.pageSize ?? pageSize);
  };

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
          <Form.Item name="education_level" className="!mb-0">
            <Input allowClear placeholder="培养层次" className="w-36" />
          </Form.Item>
          <Form.Item name="institution_name" className="!mb-0">
            <Input allowClear placeholder="院校名称" className="w-52" />
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

        <Table<MajorProfile>
          rowKey="id"
          size="small"
          columns={columns}
          dataSource={rows}
          loading={pending}
          tableLayout="fixed"
          scroll={{ x: 980 }}
          expandable={{
            onExpand: (expanded, row) => {
              if (expanded) loadDetail(row);
            },
            expandedRowRender: (row) => <MajorProfileDetailPanel state={details[row.id]} />,
          }}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            showTotal: (count) => `共 ${count} 条`,
          }}
          locale={{ emptyText: ok ? "暂无专业简介" : "数据加载失败" }}
          onChange={handleTableChange}
        />
      </section>
    </>
  );
}

function MajorProfileDetailPanel({ state }: { state?: DetailState }) {
  if (!state || state.loading) {
    return <Skeleton active paragraph={{ rows: 4 }} className="px-6 py-3" />;
  }
  if (state.error) {
    return <Alert type="error" showIcon title="专业简介详情加载失败" description={state.error} />;
  }
  if (!state.data) {
    return <Empty description="暂无专业简介详情" image={Empty.PRESENTED_IMAGE_SIMPLE} />;
  }

  const profile = state.data;
  const groupedCourses = groupCourses(profile.courses ?? []);
  return (
    <div
      data-testid="major-profile-detail-panel"
      className="border-line bg-surface grid grid-cols-2 overflow-hidden rounded-sm border"
      style={{ marginLeft: 24 }}
    >
      <DetailSection title="职业面向" icon={<BriefcaseBusiness size={16} />}>
        <ItemTags items={profile.occupations ?? []} />
      </DetailSection>
      <DetailSection title="培养定位" icon={<GraduationCap size={16} />} shaded>
        <p className="m-0 text-sm leading-6 whitespace-pre-wrap">{profile.training_goal || "-"}</p>
      </DetailSection>
      <DetailSection title="能力要求" icon={<ListChecks size={16} />} fullWidth>
        <ItemList items={profile.abilities ?? []} />
      </DetailSection>
      <DetailSection title="课程与实训" icon={<BookOpen size={16} />}>
        {Object.keys(groupedCourses).length > 0 ? (
          <div className="grid gap-4 xl:grid-cols-3">
            {Object.entries(groupedCourses).map(([group, items]) => (
              <div key={group} className="min-w-0">
                <div className="text-text-muted mb-2 text-xs font-medium">
                  {COURSE_GROUP_LABELS[group] ?? group}
                </div>
                <ItemTags items={items} />
              </div>
            ))}
          </div>
        ) : (
          <span className="text-text-muted">-</span>
        )}
      </DetailSection>
      <DetailSection title="证书信息" icon={<Award size={16} />} shaded>
        <ItemTags items={profile.certificates ?? []} />
      </DetailSection>
    </div>
  );
}

function DetailSection({
  title,
  icon,
  children,
  shaded = false,
  fullWidth = false,
}: {
  title: string;
  icon: React.ReactNode;
  children: ReactNode;
  shaded?: boolean;
  fullWidth?: boolean;
}) {
  return (
    <section
      className={`border-line min-w-0 px-5 py-4 ${shaded ? "bg-surface-alt" : "bg-surface"} ${
        fullWidth ? "col-span-2 border-y" : ""
      }`}
    >
      <h4 className="text-text-secondary mb-3 flex items-center gap-2 text-sm font-semibold">
        <span className="text-accent" aria-hidden>
          {icon}
        </span>
        {title}
      </h4>
      <div
        data-testid="major-profile-section-content"
        className="text-text max-h-56 min-w-0 overflow-y-auto pr-1"
      >
        {children}
      </div>
    </section>
  );
}

function ItemTags({ items }: { items: MajorProfileItem[] }) {
  if (items.length === 0) return <span className="text-text-muted">-</span>;
  return (
    <Space size={[4, 4]} wrap className="max-w-full">
      {[...items]
        .sort((a, b) => a.item_index - b.item_index)
        .map((item) => (
          <Tag key={item.id} className="!m-0 max-w-full leading-5 break-words whitespace-normal">
            {item.text}
          </Tag>
        ))}
    </Space>
  );
}

function ItemList({ items }: { items: MajorProfileItem[] }) {
  if (items.length === 0) return <span className="text-text-muted">-</span>;
  return (
    <ol className="m-0 grid list-decimal gap-x-8 gap-y-2 pl-5 text-sm leading-6 xl:grid-cols-2">
      {[...items]
        .sort((a, b) => a.item_index - b.item_index)
        .map((item) => (
          <li key={item.id}>{item.text}</li>
        ))}
    </ol>
  );
}

function groupCourses(courses: MajorProfileCourse[]): Record<string, MajorProfileCourse[]> {
  const groups: Record<string, MajorProfileCourse[]> = {};
  for (const course of [...courses].sort((a, b) => a.item_index - b.item_index)) {
    const group = course.course_group || "foundation";
    (groups[group] ??= []).push(course);
  }
  return groups;
}
