"use client";

import { useState, useTransition } from "react";
import { usePathname, useRouter } from "next/navigation";
import {
  Alert,
  Button,
  Descriptions,
  Drawer,
  Form,
  Input,
  InputNumber,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from "antd";
import type { ColumnsType, TablePaginationConfig } from "antd/es/table";
import { CheckCircle2, FileSearch, RefreshCw, Search, X } from "lucide-react";

import { ApiState } from "@/components/ApiState";
import {
  patchApiData,
  postApiData,
  type TeachingStandardCourse,
  type TeachingStandardLibrary,
} from "@/lib/api";

export type StandardCourseFilters = {
  libraryId?: string;
  course_name?: string;
  major_code?: string;
  major_name?: string;
  education_level?: string;
  course_type?: string;
};

type Props = {
  rows: TeachingStandardCourse[];
  total: number;
  page: number;
  pageSize: number;
  filters: StandardCourseFilters;
  ok: boolean;
  error: string | null;
  traceId: string | null;
};

type DraftRange = { min: number | null; max: number | null; unit: "学时" };
type CourseDraft = {
  suggested_total_hours?: number | null;
  suggested_practice_hours?: number | null;
  suggested_hours_range?: DraftRange | null;
};

const COURSE_TYPE_LABELS: Record<TeachingStandardCourse["course_type"], string> = {
  foundation: "专业基础课",
  core: "专业核心课",
  extension: "专业拓展课",
};

const COURSE_TYPE_COLORS: Record<TeachingStandardCourse["course_type"], string> = {
  foundation: "blue",
  core: "green",
  extension: "gold",
};

function empty(value: string | null | undefined): string {
  return value?.trim() || "-";
}

function TagList({ values }: { values: string[] }) {
  if (values.length === 0) return <span className="text-text-muted">-</span>;
  return (
    <Space size={[4, 6]} wrap>
      {values.map((value) => (
        <Tag key={value}>{value}</Tag>
      ))}
    </Space>
  );
}

function ExpandedCourse({ course }: { course: TeachingStandardCourse }) {
  return (
    <Descriptions
      size="small"
      bordered
      column={2}
      styles={{
        label: { width: 150, fontWeight: 600 },
        content: { minWidth: 260, whiteSpace: "pre-wrap", lineHeight: 1.7 },
      }}
      items={[
        {
          key: "task",
          label: "典型工作任务",
          children: empty(course.typical_work_task_description),
          span: 2,
        },
        {
          key: "content",
          label: "主要教学内容与要求",
          children: empty(course.teaching_content_requirement),
          span: 2,
        },
        {
          key: "knowledge",
          label: "知识标签",
          children: <TagList values={course.knowledge_tags} />,
        },
        { key: "skill", label: "技能标签", children: <TagList values={course.skill_tags} /> },
        { key: "tool", label: "工具标签", children: <TagList values={course.tool_tags} /> },
        { key: "literacy", label: "素养标签", children: <TagList values={course.literacy_tags} /> },
      ]}
    />
  );
}

export function StandardCourseLibraryTable({
  rows: incomingRows,
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
  const [rowOverrides, setRowOverrides] = useState<Record<string, TeachingStandardCourse>>({});
  const [activeLibraryIds, setActiveLibraryIds] = useState<Set<string>>(new Set());
  const [drafts, setDrafts] = useState<Record<string, CourseDraft>>({});
  const [savingId, setSavingId] = useState<string | null>(null);
  const [activatingLibraryId, setActivatingLibraryId] = useState<string | null>(null);
  const [evidenceCourse, setEvidenceCourse] = useState<TeachingStandardCourse | null>(null);
  const [form] = Form.useForm<StandardCourseFilters>();
  const [messageApi, messageContext] = message.useMessage();

  const rows = incomingRows.map((row) => {
    const current = rowOverrides[row.id] ?? row;
    return activeLibraryIds.has(row.library_id)
      ? { ...current, library_status: "active" as const }
      : current;
  });

  const replaceQuery = (next: StandardCourseFilters, nextPage = 1, nextPageSize = pageSize) => {
    const search = new URLSearchParams();
    for (const [key, value] of Object.entries(next)) {
      if (value?.trim()) search.set(key, value.trim());
    }
    if (nextPage > 1) search.set("page", String(nextPage));
    if (nextPageSize !== 20) search.set("pageSize", String(nextPageSize));
    startTransition(() => router.replace(`${pathname}${search.size ? `?${search}` : ""}`));
  };

  const setDraftField = <K extends keyof CourseDraft>(
    courseId: string,
    key: K,
    value: CourseDraft[K],
  ) => {
    setDrafts((current) => ({
      ...current,
      [courseId]: { ...current[courseId], [key]: value },
    }));
  };

  const updateRange = (
    course: TeachingStandardCourse,
    key: "min" | "max",
    value: number | null,
  ) => {
    const existing = drafts[course.id]?.suggested_hours_range;
    const base = existing === undefined ? course.suggested_hours_range : existing;
    const next: DraftRange = {
      min: base?.min ?? null,
      max: base?.max ?? null,
      unit: "学时",
      [key]: value,
    };
    setDraftField(
      course.id,
      "suggested_hours_range",
      next.min === null && next.max === null ? null : next,
    );
  };

  const saveCourse = async (course: TeachingStandardCourse) => {
    const draft = drafts[course.id];
    if (!draft) return;
    if (draft.suggested_hours_range) {
      const { min, max } = draft.suggested_hours_range;
      if (min === null || max === null) {
        messageApi.error("建议学时区间的最小值和最大值必须同时填写");
        return;
      }
      if (min > max) {
        messageApi.error("建议学时区间的最小值不能大于最大值");
        return;
      }
    }
    const payload: Record<string, unknown> = { ...draft };
    setSavingId(course.id);
    try {
      const result = await patchApiData<TeachingStandardCourse>(
        `/api/teaching-standard-courses/${encodeURIComponent(course.id)}`,
        payload,
      );
      setRowOverrides((current) => ({ ...current, [course.id]: result.data }));
      setDrafts((current) => {
        const next = { ...current };
        delete next[course.id];
        return next;
      });
      messageApi.success(`已更新“${course.course_name}”的建议学时`);
    } catch (saveError) {
      messageApi.error(saveError instanceof Error ? saveError.message : "更新失败");
    } finally {
      setSavingId(null);
    }
  };

  const activateLibrary = async (course: TeachingStandardCourse) => {
    setActivatingLibraryId(course.library_id);
    try {
      await postApiData<TeachingStandardLibrary & { changed: boolean }>(
        `/api/teaching-standard-libraries/${encodeURIComponent(course.library_id)}/activate`,
        {},
      );
      setActiveLibraryIds((current) => new Set(current).add(course.library_id));
      messageApi.success(
        `已激活“${course.major_name ?? course.course_name}”专业教学标准及整套课程库`,
      );
    } catch (activateError) {
      messageApi.error(activateError instanceof Error ? activateError.message : "激活失败");
    } finally {
      setActivatingLibraryId(null);
    }
  };

  const columns: ColumnsType<TeachingStandardCourse> = [
    {
      title: "课程唯一编号",
      dataIndex: "course_id",
      width: 190,
      fixed: "left",
      ellipsis: true,
    },
    {
      title: "课程名称",
      dataIndex: "course_name",
      width: 200,
      fixed: "left",
      render: (value: string) => <strong>{value}</strong>,
    },
    { title: "专业代码", dataIndex: "major_code", width: 105, render: empty },
    { title: "专业名称", dataIndex: "major_name", width: 150, render: empty },
    { title: "培养层次", dataIndex: "educational_level", width: 170, render: empty },
    {
      title: "课程类型",
      dataIndex: "course_type",
      width: 120,
      render: (value: TeachingStandardCourse["course_type"]) => (
        <Tag color={COURSE_TYPE_COLORS[value]}>{COURSE_TYPE_LABELS[value]}</Tag>
      ),
    },
    {
      title: "建议总学时",
      width: 120,
      align: "center",
      render: (_, course) => {
        const locked = course.library_status !== "review";
        return (
          <InputNumber
            aria-label={`${course.course_name}建议总学时`}
            min={0}
            precision={0}
            controls
            disabled={locked}
            className="!w-[92px]"
            value={drafts[course.id]?.suggested_total_hours ?? course.suggested_total_hours}
            onChange={(value) => setDraftField(course.id, "suggested_total_hours", value)}
          />
        );
      },
    },
    {
      title: "建议实践学时",
      width: 132,
      align: "center",
      render: (_, course) => {
        const locked = course.library_status !== "review";
        return (
          <InputNumber
            aria-label={`${course.course_name}建议实践学时`}
            min={0}
            precision={0}
            controls
            disabled={locked}
            className="!w-[92px]"
            value={drafts[course.id]?.suggested_practice_hours ?? course.suggested_practice_hours}
            onChange={(value) => setDraftField(course.id, "suggested_practice_hours", value)}
          />
        );
      },
    },
    {
      title: "建议学时区间",
      width: 220,
      align: "center",
      render: (_, course) => {
        const locked = course.library_status !== "review";
        const range = drafts[course.id]?.suggested_hours_range ?? course.suggested_hours_range;
        return (
          <Space.Compact>
            <InputNumber
              aria-label={`${course.course_name}建议最小学时`}
              min={0}
              precision={0}
              controls={false}
              disabled={locked}
              className="!w-[82px]"
              value={range?.min ?? null}
              placeholder="最小"
              onChange={(value) => updateRange(course, "min", value)}
            />
            <span className="border-line bg-surface-subtle text-text-muted inline-flex w-8 items-center justify-center border-y text-xs">
              至
            </span>
            <InputNumber
              aria-label={`${course.course_name}建议最大学时`}
              min={0}
              precision={0}
              controls={false}
              disabled={locked}
              className="!w-[82px]"
              value={range?.max ?? null}
              placeholder="最大"
              onChange={(value) => updateRange(course, "max", value)}
            />
          </Space.Compact>
        );
      },
    },
    {
      title: "操作",
      key: "actions",
      width: 230,
      fixed: "right",
      render: (_, course) => {
        const locked = course.library_status !== "review";
        const lockReason =
          course.library_status === "active"
            ? "所属专业教学标准已激活，不可直接修改或重复激活"
            : "所属专业教学标准已废止";
        return (
          <Space size={2}>
            <Tooltip title={locked ? lockReason : undefined}>
              <span>
                <Button
                  type="link"
                  size="small"
                  icon={<RefreshCw size={14} />}
                  disabled={locked || !drafts[course.id]}
                  loading={savingId === course.id}
                  onClick={() => saveCourse(course)}
                >
                  更新
                </Button>
              </span>
            </Tooltip>
            <Popconfirm
              title="激活整套专业教学标准？"
              description={`将激活“${course.major_name ?? "当前专业"}”的专业教学标准及其全部课程记录。`}
              okText="确认激活"
              cancelText="取消"
              disabled={locked}
              onConfirm={() => activateLibrary(course)}
            >
              <Tooltip title={locked ? lockReason : "激活所属专业教学标准及整套课程库"}>
                <span>
                  <Button
                    type="link"
                    size="small"
                    icon={<CheckCircle2 size={14} />}
                    disabled={locked}
                    loading={activatingLibraryId === course.library_id}
                  >
                    激活
                  </Button>
                </span>
              </Tooltip>
            </Popconfirm>
            <Button
              type="link"
              size="small"
              icon={<FileSearch size={14} />}
              onClick={() => setEvidenceCourse(course)}
            >
              血缘追溯
            </Button>
          </Space>
        );
      },
    },
  ];

  const handleTableChange = (pagination: TablePaginationConfig) => {
    replaceQuery(filters, pagination.current ?? 1, pagination.pageSize ?? pageSize);
  };

  return (
    <>
      {messageContext}
      <ApiState ok={ok} error={error} traceId={traceId} />
      {filters.libraryId ? (
        <Alert
          type="info"
          showIcon
          className="!mb-3"
          title="当前仅显示所选专业教学标准的课程"
          action={
            <Button size="small" onClick={() => replaceQuery({})}>
              查看全部课程
            </Button>
          }
        />
      ) : null}
      <section className="border-line bg-surface border-y">
        <Form
          form={form}
          layout="inline"
          initialValues={filters}
          className="border-line flex gap-2 border-b px-4 py-3"
          onFinish={(values) => replaceQuery({ ...values, libraryId: filters.libraryId })}
        >
          <Form.Item name="course_name" className="!mb-0">
            <Input allowClear placeholder="课程名称" className="w-44" />
          </Form.Item>
          <Form.Item name="major_code" className="!mb-0">
            <Input allowClear placeholder="专业代码" className="w-32" />
          </Form.Item>
          <Form.Item name="major_name" className="!mb-0">
            <Input allowClear placeholder="专业名称" className="w-40" />
          </Form.Item>
          <Form.Item name="education_level" className="!mb-0">
            <Input allowClear placeholder="培养层次" className="w-44" />
          </Form.Item>
          <Form.Item name="course_type" className="!mb-0">
            <Select
              allowClear
              placeholder="课程类型"
              className="w-36"
              options={Object.entries(COURSE_TYPE_LABELS).map(([value, label]) => ({
                value,
                label,
              }))}
            />
          </Form.Item>
          <Form.Item className="!mb-0">
            <Space size={8}>
              <Button htmlType="submit" type="primary" icon={<Search size={15} />}>
                查询
              </Button>
              <Button
                icon={<X size={15} />}
                onClick={() => {
                  form.setFieldsValue({
                    course_name: undefined,
                    major_code: undefined,
                    major_name: undefined,
                    education_level: undefined,
                    course_type: undefined,
                  });
                  replaceQuery(filters.libraryId ? { libraryId: filters.libraryId } : {});
                }}
              >
                重置
              </Button>
            </Space>
          </Form.Item>
        </Form>

        <Table<TeachingStandardCourse>
          rowKey="id"
          size="small"
          columns={columns}
          dataSource={rows}
          loading={pending}
          scroll={{ x: 1830 }}
          expandable={{
            expandedRowRender: (course) => <ExpandedCourse course={course} />,
            rowExpandable: () => true,
            columnWidth: 42,
          }}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            showTotal: (count) => `共 ${count} 条`,
          }}
          locale={{ emptyText: ok ? "暂无标准课程" : "数据加载失败" }}
          onChange={handleTableChange}
        />
      </section>

      <Drawer
        open={evidenceCourse !== null}
        size={640}
        title={evidenceCourse ? `${evidenceCourse.course_name} · 血缘追溯` : "血缘追溯"}
        destroyOnHidden
        onClose={() => setEvidenceCourse(null)}
      >
        {evidenceCourse ? (
          <Space orientation="vertical" size={20} className="w-full">
            <Descriptions
              size="small"
              bordered
              column={1}
              styles={{
                label: { width: 112, minWidth: 112, whiteSpace: "nowrap", fontWeight: 600 },
                content: { whiteSpace: "pre-wrap", lineHeight: 1.6, wordBreak: "break-word" },
              }}
              items={[
                {
                  key: "basis",
                  label: "学时设置依据",
                  children: empty(evidenceCourse.hours_setting_basis),
                },
                {
                  key: "keywords",
                  label: "匹配关键字",
                  children: empty(evidenceCourse.match_keywords),
                },
                {
                  key: "standard",
                  label: "来源标准",
                  children: empty(evidenceCourse.source_standard),
                },
                {
                  key: "section",
                  label: "来源章节",
                  children: empty(evidenceCourse.source_section),
                },
                { key: "page", label: "来源页码", children: empty(evidenceCourse.source_page) },
              ]}
            />
            <div>
              <Typography.Title level={5}>匹配文本</Typography.Title>
              <Typography.Paragraph className="bg-surface-subtle border-line rounded-sm border p-3 !whitespace-pre-wrap">
                {empty(evidenceCourse.match_text)}
              </Typography.Paragraph>
            </div>
            <div>
              <Typography.Title level={5}>证据绑定</Typography.Title>
              <div className="border-line divide-line divide-y overflow-hidden rounded-sm border">
                {evidenceCourse.evidence_bindings.length > 0 ? (
                  evidenceCourse.evidence_bindings.map((binding, index) => (
                    <div key={index} className="p-3">
                      <strong>证据 {index + 1}</strong>
                      <pre className="bg-surface-subtle mt-2 max-h-72 overflow-auto rounded-sm p-3 text-xs leading-6 whitespace-pre-wrap">
                        {JSON.stringify(binding, null, 2)}
                      </pre>
                    </div>
                  ))
                ) : (
                  <div className="text-text-muted px-3 py-6 text-center text-sm">暂无证据绑定</div>
                )}
              </div>
            </div>
          </Space>
        ) : null}
      </Drawer>
    </>
  );
}
