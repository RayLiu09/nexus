"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { App, Button, Form, Input, Modal, Select, Space, Table, Tag, Tooltip, Typography } from "antd";
import { PlusOutlined, CopyOutlined, KeyOutlined, EditOutlined } from "@ant-design/icons";
import type { ColumnsType, TablePaginationConfig } from "antd/es/table";
import type { FilterValue, SorterResult } from "antd/es/table/interface";

import type { ApiCaller } from "@/lib/api";
import { postApiData, patchApiData, deleteApiData, shortId } from "@/lib/api";
import { StatusLabel } from "@/components/StatusLabel";
import { EmptyState } from "@/components/shared/EmptyState";
import { ConfirmButton } from "@/components/shared/ConfirmButton";
import { ApiState } from "@/components/ApiState";
import { formatTime } from "@/lib/format-time";
import { DEFAULT_PAGE_SIZE } from "@/lib/pagination";

interface ApiCallersContentProps {
  callers: ApiCaller[];
  totalCount: number;
  currentPage: number;
  pageSize: number;
  ok: boolean;
  error: string | null;
  traceId: string | null;
}

interface CreateFormValues {
  name: string;
  permission_scope: string[];
  expiry: string;
}

interface EditFormValues {
  permission_scope: string[];
  expiry: string;
}

interface CreatedCaller {
  id: string;
  caller_key: string | null;
  name: string;
  caller_key_plaintext: string;
}

const PERMISSION_OPTIONS = [
  { label: "search", value: "search" },
  { label: "qa", value: "qa" },
  { label: "ingest", value: "ingest" },
  { label: "read:asset", value: "read:asset" },
  { label: "read:knowledge", value: "read:knowledge" },
];

const EXPIRY_OPTIONS = [
  { label: "1 天", value: "1d" },
  { label: "7 天", value: "7d" },
  { label: "30 天", value: "30d" },
  { label: "90 天", value: "90d" },
  { label: "6 个月", value: "6m" },
  { label: "1 年", value: "1y" },
  { label: "2 年", value: "2y" },
  { label: "永不过期", value: "never" },
];

/** Convert an expiry duration key to an ISO datetime string, or null for "never". */
function resolveExpiry(value: string): string | null {
  if (value === "never") return null;
  const match = value.match(/^(\d+)([dmy])$/);
  if (!match) return null;
  const num = parseInt(match[1], 10);
  const unit = match[2];
  const d = new Date();
  if (unit === "d") d.setDate(d.getDate() + num);
  else if (unit === "m") d.setMonth(d.getMonth() + num);
  else if (unit === "y") d.setFullYear(d.getFullYear() + num);
  return d.toISOString();
}

// Sentinel value: keep current expiry unchanged (edit form only).
const KEEP_EXPIRY = "__keep__";
const EDIT_EXPIRY_OPTIONS = [
  { label: "保持当前", value: KEEP_EXPIRY },
  ...EXPIRY_OPTIONS,
];

export function ApiCallersContent({
  callers: initialCallers,
  totalCount,
  currentPage,
  pageSize,
  ok,
  error,
  traceId,
}: ApiCallersContentProps) {
  const { message } = App.useApp();
  const router = useRouter();
  const pathname = usePathname();
  const [callers, setCallers] = useState<ApiCaller[]>(initialCallers);
  const [createOpen, setCreateOpen] = useState(false);
  const [createLoading, setCreateLoading] = useState(false);
  const [createdCaller, setCreatedCaller] = useState<CreatedCaller | null>(null);
  const [form] = Form.useForm<CreateFormValues>();
  const [editOpen, setEditOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<ApiCaller | null>(null);
  const [editLoading, setEditLoading] = useState(false);
  const [editForm] = Form.useForm<EditFormValues>();

  /** Mask caller_key: show "nx-" prefix + last 4 chars, middle hidden. */
  function maskKey(key: string | null): string {
    if (!key) return "-";
    // caller_key now always stores a display-safe masked value like "nx-****abcd"
    return key;
  }

  const handleTableChange = useCallback(
    (
      pagination: TablePaginationConfig,
      _filters: Record<string, FilterValue | null>,
      _sorter: SorterResult<ApiCaller> | SorterResult<ApiCaller>[],
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

  const handleCreate = useCallback(async (values: CreateFormValues) => {
    setCreateLoading(true);
    try {
      const result = await postApiData<{
        id: string;
        caller_key: string | null;
        caller_key_hash: string | null;
        caller_key_plaintext: string | null;
        name: string;
        permission_scope: string[];
        expired_at: string | null;
        revoked_at: string | null;
        created_at: string;
        updated_at: string;
      }>("/api/api-callers", {
        name: values.name,
        permission_scope: values.permission_scope,
        expired_at: resolveExpiry(values.expiry),
      });

      if (!result.data.caller_key_plaintext) {
        message.error("后端未返回明文密钥，请重试");
        return;
      }

      setCreatedCaller({
        id: result.data.id,
        caller_key: result.data.caller_key,
        name: result.data.name,
        caller_key_plaintext: result.data.caller_key_plaintext,
      });

      // Add to list
      setCallers((prev) => [
        {
          id: result.data.id,
          caller_key: result.data.caller_key,
          caller_key_hash: result.data.caller_key_hash,
          name: result.data.name,
          org_scope: [],
          permission_scope: result.data.permission_scope,
          owner_user_id: null,
          expired_at: result.data.expired_at,
          revoked_at: result.data.revoked_at,
          created_at: result.data.created_at,
          updated_at: result.data.updated_at,
        },
        ...prev,
      ]);

      form.resetFields();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "创建失败");
    } finally {
      setCreateLoading(false);
    }
  }, [form, message]);

  const handleRevoke = useCallback(async (caller: ApiCaller) => {
    await deleteApiData(`/api/api-callers/${caller.id}`);
    setCallers((prev) => prev.map((c) =>
      c.id === caller.id ? { ...c, revoked_at: new Date().toISOString() } : c,
    ));
    message.success(`已吊销 ${caller.name}`);
  }, [message]);

  const handleEditOpen = useCallback((caller: ApiCaller) => {
    setEditTarget(caller);
    setEditOpen(true);
  }, []);

  // Set form values after Modal renders so the Form element is connected.
  useEffect(() => {
    if (editOpen && editTarget) {
      editForm.setFieldsValue({
        permission_scope: editTarget.permission_scope,
        expiry: KEEP_EXPIRY,
      });
    }
  }, [editOpen, editTarget, editForm]);

  const handleEdit = useCallback(async (values: EditFormValues) => {
    if (!editTarget) return;
    setEditLoading(true);
    try {
      const body: Record<string, unknown> = {
        permission_scope: values.permission_scope,
      };
      if (values.expiry !== KEEP_EXPIRY) {
        body.expired_at = resolveExpiry(values.expiry);
      }
      const result = await patchApiData<ApiCaller>(`/api/api-callers/${editTarget.id}`, body);
      setCallers((prev) => prev.map((c) =>
        c.id === editTarget.id
          ? {
              ...c,
              permission_scope: values.permission_scope,
              expired_at: result.data?.expired_at ?? c.expired_at,
            }
          : c,
      ));
      message.success(`已更新 ${editTarget.name} 的调用权限`);
      setEditOpen(false);
      setEditTarget(null);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "更新失败");
    } finally {
      setEditLoading(false);
    }
  }, [editTarget, message]);

  const handleCopyToken = useCallback(async () => {
    if (!createdCaller?.caller_key_plaintext) return;
    try {
      await navigator.clipboard.writeText(createdCaller.caller_key_plaintext);
      message.success("Token 已复制到剪贴板");
    } catch {
      message.error("复制失败，请手动选择文本");
    }
  }, [createdCaller, message]);

  const columns: ColumnsType<ApiCaller> = [
    {
      title: "名称",
      dataIndex: "name",
      key: "name",
      render: (name: string) => (
        <Space>
          <KeyOutlined style={{ color: "var(--text-muted)" }} />
          <span style={{ fontWeight: 500 }}>{name}</span>
        </Space>
      ),
    },
    {
      title: "密钥",
      dataIndex: "caller_key",
      key: "caller_key",
      width: 160,
      render: (v: string | null) => (
        <Typography.Text style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}>
          {maskKey(v)}
        </Typography.Text>
      ),
    },
    {
      title: "权限范围",
      dataIndex: "permission_scope",
      key: "permission_scope",
      render: (scopes: string[]) => (
        <Space size={4} wrap>
          {scopes.length > 0
            ? scopes.map((s) => <Tag key={s}>{s}</Tag>)
            : <Typography.Text type="secondary">-</Typography.Text>}
        </Space>
      ),
    },
    {
      title: "组织范围",
      dataIndex: "org_scope",
      key: "org_scope",
      render: (scopes: string[]) => (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {scopes.length > 0 ? scopes.map(shortId).join(", ") : "全部组织"}
        </Typography.Text>
      ),
    },
    {
      title: "状态",
      key: "status",
      width: 100,
      render: (_: unknown, record: ApiCaller) => (
        <StatusLabel value={record.revoked_at ? "revoked" : "active"} />
      ),
    },
    {
      title: "创建时间",
      dataIndex: "created_at",
      key: "created_at",
      width: 160,
      render: (v: string) => {
        const ft = formatTime(v);
        return (
          <time dateTime={ft.iso} title={ft.iso} style={{ fontSize: 12, color: "var(--text-muted)" }}>
            {ft.display}
          </time>
        );
      },
    },
    {
      title: "过期时间",
      dataIndex: "expired_at",
      key: "expired_at",
      width: 160,
      render: (v: string | null) => {
        if (!v) return <Typography.Text type="secondary">永不过期</Typography.Text>;
        const ft = formatTime(v);
        return (
          <time dateTime={ft.iso} title={ft.iso} style={{ fontSize: 12, color: "var(--text-muted)" }}>
            {ft.display}
          </time>
        );
      },
    },
    {
      title: "操作",
      key: "actions",
      width: 130,
      render: (_: unknown, record: ApiCaller) =>
        !record.revoked_at ? (
          <Space size={0}>
            <Button
              type="link"
              size="small"
              icon={<EditOutlined />}
              onClick={() => handleEditOpen(record)}
            >
              编辑
            </Button>
            <ConfirmButton
              title="吊销 API Caller"
              description={
                <>
                  确定要吊销 <strong>{record.name}</strong> 的 API 凭证吗？
                  <br />
                  吊销后，使用该凭证的所有请求将立即失效，且不可恢复。
                </>
              }
              confirmWord={record.name}
              confirmLabel="确认吊销"
              severity="danger"
              danger
              buttonProps={{ size: "small", type: "link" }}
              onConfirm={() => handleRevoke(record)}
            >
              吊销
            </ConfirmButton>
          </Space>
        ) : null,
    },
  ];

  return (
    <>
      <ApiState ok={ok} error={error} traceId={traceId} />

      <div style={{ marginBottom: 16, display: "flex", justifyContent: "flex-end" }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
          创建 API Caller
        </Button>
      </div>

      {callers.length === 0 ? (
        <EmptyState title="暂无 API 调用方" hint="创建一个 API Caller 来开始使用" />
      ) : (
        <Table
          columns={columns}
          dataSource={callers}
          rowKey="id"
          pagination={{
            current: currentPage,
            pageSize,
            total: totalCount,
            showSizeChanger: true,
            showTotal: (total, range) => `${range[0]}-${range[1]} / ${total} 项`,
            pageSizeOptions: ["10", "20", "50"],
          }}
          onChange={handleTableChange}
        />
      )}

      {/* Create Modal */}
      <Modal
        title="创建 API Caller"
        open={createOpen}
        onCancel={() => {
          setCreateOpen(false);
          setCreatedCaller(null);
          form.resetFields();
        }}
        footer={createdCaller ? [
          <Button key="close" onClick={() => {
            setCreateOpen(false);
            setCreatedCaller(null);
          }}>
            关闭
          </Button>,
        ] : undefined}
        destroyOnHidden
      >
        {createdCaller ? (
          <Space orientation="vertical" size="middle" className="w-full">
            <Typography.Text>
              API Caller <strong>{createdCaller.name}</strong> 创建成功。
              请立即复制以下 Token，<strong>关闭后将无法再次查看</strong>。
            </Typography.Text>

            <div style={{
              background: "var(--surface-alt)",
              border: "1px solid var(--line)",
              borderRadius: "var(--radius-md)",
              padding: 12,
              position: "relative",
            }}>
              <code style={{
                fontSize: 11,
                fontFamily: "var(--font-mono)",
                wordBreak: "break-all",
                display: "block",
                paddingRight: 32,
              }}>
                {createdCaller.caller_key_plaintext}
              </code>
              <Tooltip title="复制 Token">
                <Button
                  size="small"
                  type="text"
                  icon={<CopyOutlined />}
                  onClick={handleCopyToken}
                  style={{ position: "absolute", top: 8, right: 8 }}
                />
              </Tooltip>
            </div>

            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              Caller Key: <code>{createdCaller.caller_key}</code>
            </Typography.Text>
          </Space>
        ) : (
          <Form form={form} layout="vertical" onFinish={handleCreate}>
            <Form.Item
              name="name"
              label="名称"
              rules={[{ required: true, message: "请输入 API Caller 名称" }]}
            >
              <Input placeholder="例如：数据分析平台、报表系统" />
            </Form.Item>

            <Form.Item
              name="permission_scope"
              label="权限范围"
              rules={[{ required: true, message: "请选择至少一个权限" }]}
            >
              <Select
                mode="multiple"
                options={PERMISSION_OPTIONS}
                placeholder="选择 API 调用方可访问的接口范围"
              />
            </Form.Item>

            <Form.Item
              name="expiry"
              label="过期时间"
              initialValue="never"
              rules={[{ required: true, message: "请选择过期时间" }]}
            >
              <Select options={EXPIRY_OPTIONS} placeholder="选择凭证有效期" />
            </Form.Item>

            <Button type="primary" htmlType="submit" block loading={createLoading}>
              创建
            </Button>
          </Form>
        )}
      </Modal>

      {/* Edit Modal */}
      <Modal
        title={`编辑 ${editTarget?.name ?? ""}`}
        open={editOpen}
        onCancel={() => {
          setEditOpen(false);
          setEditTarget(null);
        }}
        footer={null}
        destroyOnHidden
      >
        <Form form={editForm} layout="vertical" onFinish={handleEdit}>
          <Form.Item
            name="permission_scope"
            label="权限范围"
            rules={[{ required: true, message: "请选择至少一个权限" }]}
          >
            <Select
              mode="multiple"
              options={PERMISSION_OPTIONS}
              placeholder="选择 API 调用方可访问的接口范围"
            />
          </Form.Item>

          <Form.Item
            name="expiry"
            label="过期时间"
            rules={[{ required: true, message: "请选择过期时间" }]}
          >
            <Select options={EDIT_EXPIRY_OPTIONS} placeholder="选择凭证有效期" />
          </Form.Item>

          <Button type="primary" htmlType="submit" block loading={editLoading}>
            保存
          </Button>
        </Form>
      </Modal>
    </>
  );
}
