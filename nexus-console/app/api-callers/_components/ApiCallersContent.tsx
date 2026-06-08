"use client";

import { useCallback, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { App, Button, Form, Input, Modal, Select, Space, Table, Tag, Tooltip, Typography } from "antd";
import { PlusOutlined, CopyOutlined, KeyOutlined } from "@ant-design/icons";
import type { ColumnsType, TablePaginationConfig } from "antd/es/table";
import type { FilterValue, SorterResult } from "antd/es/table/interface";

import type { ApiCaller } from "@/lib/api";
import { postApiData, deleteApiData, formatDateTime, shortId } from "@/lib/api";
import { ConfirmButton } from "@/components/shared/ConfirmButton";
import { ApiState } from "@/components/ApiState";
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
}

interface CreatedCaller {
  id: string;
  caller_key: string;
  name: string;
  token: string;
}

const PERMISSION_OPTIONS = [
  { label: "search", value: "search" },
  { label: "qa", value: "qa" },
  { label: "ingest", value: "ingest" },
  { label: "read:asset", value: "read:asset" },
  { label: "read:knowledge", value: "read:knowledge" },
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
        caller_key: string;
        name: string;
        token: string;
        permission_scope: string[];
        status: string;
        created_at: string;
        updated_at: string;
      }>("/api/api-callers", {
        name: values.name,
        permission_scope: values.permission_scope,
      });

      setCreatedCaller({
        id: result.data.id,
        caller_key: result.data.caller_key,
        name: result.data.name,
        token: result.data.token,
      });

      // Add to list
      setCallers((prev) => [
        {
          id: result.data.id,
          caller_key: result.data.caller_key,
          name: result.data.name,
          org_scope: [],
          permission_scope: result.data.permission_scope,
          owner_user_id: null,
          status: result.data.status,
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
      c.id === caller.id ? { ...c, status: "revoked" } : c,
    ));
    message.success(`已吊销 ${caller.name}`);
  }, [message]);

  const handleCopyToken = useCallback(async () => {
    if (!createdCaller?.token) return;
    try {
      await navigator.clipboard.writeText(createdCaller.token);
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
      render: (name: string, record) => (
        <Space>
          <KeyOutlined style={{ color: "var(--text-muted)" }} />
          <span style={{ fontWeight: 500 }}>{name}</span>
          <code style={{ fontSize: 11, color: "var(--text-muted)" }}>{record.caller_key}</code>
        </Space>
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
      dataIndex: "status",
      key: "status",
      width: 100,
      render: (status: string) => {
        const color = status === "active" ? "green" : status === "revoked" ? "red" : "default";
        return <Tag color={color}>{status === "active" ? "有效" : status === "revoked" ? "已吊销" : status}</Tag>;
      },
    },
    {
      title: "创建时间",
      dataIndex: "created_at",
      key: "created_at",
      width: 160,
      render: (v: string) => (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {formatDateTime(v)}
        </Typography.Text>
      ),
    },
    {
      title: "操作",
      key: "actions",
      width: 100,
      render: (_: unknown, record: ApiCaller) =>
        record.status === "active" ? (
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
        ) : null,
    },
  ];

  return (
    <>
      <ApiState ok={ok} error={error} traceId={traceId} />

      <div style={{ marginBottom: 16, display: "flex", justifyContent: "space-between" }}>
        <Typography.Text type="secondary">
          共 {totalCount} 个 API 调用方
        </Typography.Text>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
          创建 API Caller
        </Button>
      </div>

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
        locale={{ emptyText: "暂无 API 调用方" }}
      />

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
        destroyOnClose
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
                {createdCaller.token}
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

            <Button type="primary" htmlType="submit" block loading={createLoading}>
              创建
            </Button>
          </Form>
        )}
      </Modal>
    </>
  );
}
