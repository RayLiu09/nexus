"use client";

import { useCallback, useMemo, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import {
  App,
  Avatar,
  Button,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import { EditOutlined, KeyOutlined, PlusOutlined } from "@ant-design/icons";
import type { ColumnsType, TablePaginationConfig } from "antd/es/table";

import type {
  UserAccount,
  UserCreatePayload,
  UserUpdatePayload,
  UserPasswordResetPayload,
} from "@/lib/api";
import { patchApiData, postApiData, shortId } from "@/lib/api";
import type { SessionRole } from "@/lib/auth/session";
import {
  CONSOLE_ROLE_AVATARS,
  CONSOLE_ROLE_SHORT_LABELS,
  CONSOLE_SESSION_ROLES,
} from "@/lib/auth/roles";
import { ApiState } from "@/components/ApiState";
import { EmptyState } from "@/components/shared/EmptyState";
import { StatusLabel } from "@/components/StatusLabel";
import { formatTime } from "@/lib/format-time";
import { DEFAULT_PAGE_SIZE } from "@/lib/pagination";

type UserStatus = "active" | "disabled";

interface UsersContentProps {
  users: UserAccount[];
  totalCount: number;
  currentPage: number;
  pageSize: number;
  ok: boolean;
  error: string | null;
  traceId: string | null;
}

interface CreateFormValues {
  username: string;
  display_name: string;
  role: SessionRole;
  password: string;
  description?: string;
}

interface EditFormValues {
  display_name: string;
  role: SessionRole;
  description?: string;
}

interface PasswordFormValues {
  password: string;
  confirm: string;
}

const ROLE_OPTIONS = CONSOLE_SESSION_ROLES.map((role) => ({
  label: CONSOLE_ROLE_SHORT_LABELS[role],
  value: role,
}));

const EMAIL_PATTERN = /^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/;

function normalizeRole(value: string): SessionRole | null {
  return (CONSOLE_SESSION_ROLES as readonly string[]).includes(value)
    ? (value as SessionRole)
    : null;
}

function roleTag(role: string) {
  const known = normalizeRole(role);
  if (known === "platform_data_admin") {
    return <Tag color="geekblue">{CONSOLE_ROLE_SHORT_LABELS[known]}</Tag>;
  }
  if (known === "business_expert") {
    return <Tag color="gold">{CONSOLE_ROLE_SHORT_LABELS[known]}</Tag>;
  }
  return <Tag>{role}</Tag>;
}

function roleAvatar(role: string, size: number = 32) {
  const known = normalizeRole(role);
  const src = known ? CONSOLE_ROLE_AVATARS[known] : undefined;
  return (
    <Avatar
      size={size}
      src={src}
      alt={known ? CONSOLE_ROLE_SHORT_LABELS[known] : role}
      style={{ backgroundColor: "var(--brand-100)" }}
    />
  );
}

export function UsersContent({
  users: initialUsers,
  totalCount,
  currentPage,
  pageSize,
  ok,
  error,
  traceId,
}: UsersContentProps) {
  const { message } = App.useApp();
  const router = useRouter();
  const pathname = usePathname();

  const [users, setUsers] = useState<UserAccount[]>(initialUsers);

  const [createOpen, setCreateOpen] = useState(false);
  const [createLoading, setCreateLoading] = useState(false);
  const [createForm] = Form.useForm<CreateFormValues>();

  const [editTarget, setEditTarget] = useState<UserAccount | null>(null);
  const [editLoading, setEditLoading] = useState(false);
  const [editForm] = Form.useForm<EditFormValues>();

  const [passwordTarget, setPasswordTarget] = useState<UserAccount | null>(null);
  const [passwordLoading, setPasswordLoading] = useState(false);
  const [passwordForm] = Form.useForm<PasswordFormValues>();

  const [statusMutatingId, setStatusMutatingId] = useState<string | null>(null);

  const handleTableChange = useCallback(
    (pagination: TablePaginationConfig) => {
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

  const openCreate = useCallback(() => {
    createForm.resetFields();
    setCreateOpen(true);
  }, [createForm]);

  const handleCreate = useCallback(
    async (values: CreateFormValues) => {
      setCreateLoading(true);
      try {
        const payload: UserCreatePayload = {
          username: values.username.trim().toLowerCase(),
          display_name: values.display_name.trim(),
          role: values.role,
          password: values.password,
          description: values.description?.trim() || null,
          status: "active",
        };
        const result = await postApiData<UserAccount>("/api/users", payload);
        setUsers((prev) => [result.data, ...prev]);
        message.success(`已创建用户 ${payload.display_name}`);
        setCreateOpen(false);
        createForm.resetFields();
      } catch (err) {
        const text = err instanceof Error ? err.message : "创建失败";
        message.error(text);
      } finally {
        setCreateLoading(false);
      }
    },
    [createForm, message],
  );

  const openEdit = useCallback(
    (user: UserAccount) => {
      const role = normalizeRole(user.role);
      setEditTarget(user);
      editForm.setFieldsValue({
        display_name: user.display_name,
        role: role ?? "business_expert",
        description: user.description ?? "",
      });
    },
    [editForm],
  );

  const handleEdit = useCallback(
    async (values: EditFormValues) => {
      if (!editTarget) return;
      setEditLoading(true);
      try {
        const payload: UserUpdatePayload = {
          display_name: values.display_name.trim(),
          role: values.role,
          description: values.description?.trim() || null,
        };
        const result = await patchApiData<UserAccount>(`/api/users/${editTarget.id}`, payload);
        setUsers((prev) => prev.map((u) => (u.id === editTarget.id ? result.data : u)));
        message.success(`已更新用户 ${result.data.display_name}`);
        setEditTarget(null);
        editForm.resetFields();
      } catch (err) {
        const text = err instanceof Error ? err.message : "更新失败";
        message.error(text);
      } finally {
        setEditLoading(false);
      }
    },
    [editForm, editTarget, message],
  );

  const openPasswordReset = useCallback(
    (user: UserAccount) => {
      setPasswordTarget(user);
      passwordForm.resetFields();
    },
    [passwordForm],
  );

  const handlePasswordReset = useCallback(
    async (values: PasswordFormValues) => {
      if (!passwordTarget) return;
      setPasswordLoading(true);
      try {
        const payload: UserPasswordResetPayload = { password: values.password };
        await postApiData<UserAccount>(`/api/users/${passwordTarget.id}/password`, payload);
        message.success(`已重置 ${passwordTarget.display_name} 的登录密码`);
        setPasswordTarget(null);
        passwordForm.resetFields();
      } catch (err) {
        const text = err instanceof Error ? err.message : "重置密码失败";
        message.error(text);
      } finally {
        setPasswordLoading(false);
      }
    },
    [message, passwordForm, passwordTarget],
  );

  const handleToggleStatus = useCallback(
    async (user: UserAccount) => {
      const nextStatus: UserStatus = user.status === "active" ? "disabled" : "active";
      setStatusMutatingId(user.id);
      try {
        const result = await patchApiData<UserAccount>(`/api/users/${user.id}`, {
          status: nextStatus,
        });
        setUsers((prev) => prev.map((u) => (u.id === user.id ? result.data : u)));
        message.success(
          nextStatus === "disabled"
            ? `已禁用用户 ${user.display_name}`
            : `已激活用户 ${user.display_name}`,
        );
      } catch (err) {
        const text = err instanceof Error ? err.message : "状态切换失败";
        message.error(text);
      } finally {
        setStatusMutatingId(null);
      }
    },
    [message],
  );

  const columns = useMemo<ColumnsType<UserAccount>>(
    () => [
      {
        title: "头像",
        dataIndex: "role",
        key: "avatar",
        width: 68,
        render: (role: string) => roleAvatar(role, 36),
      },
      {
        title: "显示名称",
        dataIndex: "display_name",
        key: "display_name",
        render: (name: string, user) => (
          <div className="flex flex-col">
            <strong>{name}</strong>
            {user.description ? (
              <Typography.Text type="secondary" className="text-xs">
                {user.description}
              </Typography.Text>
            ) : null}
          </div>
        ),
      },
      {
        title: "登录邮箱",
        dataIndex: "username",
        key: "username",
        render: (username: string) => <span className="font-mono text-sm">{username}</span>,
      },
      {
        title: "角色",
        dataIndex: "role",
        key: "role",
        width: 140,
        render: (role: string) => roleTag(role),
      },
      {
        title: "状态",
        dataIndex: "status",
        key: "status",
        width: 110,
        render: (status: string) => <StatusLabel value={status} />,
      },
      {
        title: "创建时间",
        dataIndex: "created_at",
        key: "created_at",
        width: 200,
        render: (value: string) => {
          const { display, iso } = formatTime(value);
          return <Tooltip title={iso}>{display}</Tooltip>;
        },
      },
      {
        title: "ID",
        dataIndex: "id",
        key: "id",
        width: 120,
        render: (id: string) => <span className="font-mono text-xs">{shortId(id)}</span>,
      },
      {
        title: "操作",
        key: "actions",
        width: 260,
        fixed: "right",
        render: (_, user) => {
          const isActive = user.status === "active";
          return (
            <Space size="small">
              <Button
                size="small"
                type="link"
                icon={<EditOutlined />}
                onClick={() => openEdit(user)}
              >
                编辑
              </Button>
              <Button
                size="small"
                type="link"
                icon={<KeyOutlined />}
                onClick={() => openPasswordReset(user)}
              >
                重置密码
              </Button>
              <Popconfirm
                title={isActive ? "禁用该用户？" : "重新激活该用户？"}
                description={
                  isActive
                    ? "禁用后该用户将无法登录 Console，可稍后恢复。"
                    : "激活后该用户可使用现有密码正常登录。"
                }
                okText="确定"
                cancelText="取消"
                onConfirm={() => handleToggleStatus(user)}
              >
                <Button
                  size="small"
                  type="link"
                  danger={isActive}
                  loading={statusMutatingId === user.id}
                >
                  {isActive ? "禁用" : "激活"}
                </Button>
              </Popconfirm>
            </Space>
          );
        },
      },
    ],
    [handleToggleStatus, openEdit, openPasswordReset, statusMutatingId],
  );

  return (
    <>
      <ApiState ok={ok} error={error} traceId={traceId} />

      <div className="mb-3 flex items-center justify-end">
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
          创建用户
        </Button>
      </div>

      {users.length === 0 && ok ? (
        <EmptyState title="暂无用户" hint="点击右上角「创建用户」新增第一位平台账号" />
      ) : (
        <Table<UserAccount>
          rowKey="id"
          columns={columns}
          dataSource={users}
          onChange={handleTableChange}
          scroll={{ x: "max-content" }}
          pagination={{
            current: currentPage,
            pageSize,
            total: totalCount,
            showSizeChanger: true,
            showTotal: (total) => `共 ${total} 条`,
          }}
        />
      )}

      {/* ── Create user ── */}
      <Modal
        title="创建用户"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        footer={null}
        destroyOnHidden
        width={520}
      >
        <Form<CreateFormValues>
          form={createForm}
          layout="vertical"
          onFinish={handleCreate}
          requiredMark={false}
          initialValues={{ role: "business_expert" }}
        >
          <Form.Item
            label="显示名称"
            name="display_name"
            rules={[
              { required: true, message: "请输入显示名称" },
              { max: 128, message: "显示名称最长 128 字符" },
            ]}
          >
            <Input placeholder="例如：张敏" autoComplete="off" maxLength={128} />
          </Form.Item>

          <Form.Item
            label="登录邮箱"
            name="username"
            rules={[
              { required: true, message: "请输入登录邮箱" },
              {
                pattern: EMAIL_PATTERN,
                message: "请输入合法的邮箱地址",
              },
            ]}
          >
            <Input placeholder="例如：admin@nexus.local" autoComplete="off" />
          </Form.Item>

          <Form.Item label="角色" name="role" rules={[{ required: true, message: "请选择角色" }]}>
            <Select options={ROLE_OPTIONS} />
          </Form.Item>

          <Form.Item
            label="登录密码"
            name="password"
            extra="至少 8 位，建议包含大小写字母、数字或符号"
            rules={[
              { required: true, message: "请输入登录密码" },
              { min: 8, max: 128, message: "密码长度需在 8-128 位之间" },
            ]}
          >
            <Input.Password placeholder="请输入初始密码" autoComplete="new-password" />
          </Form.Item>

          <Form.Item
            label="描述"
            name="description"
            rules={[{ max: 500, message: "描述最长 500 字符" }]}
          >
            <Input.TextArea
              placeholder="可留空。用于备注该账号的职责或备注信息。"
              rows={3}
              maxLength={500}
              showCount
            />
          </Form.Item>

          <div className="flex justify-end gap-2">
            <Button onClick={() => setCreateOpen(false)}>取消</Button>
            <Button type="primary" htmlType="submit" loading={createLoading}>
              创建
            </Button>
          </div>
        </Form>
      </Modal>

      {/* ── Edit user ── */}
      <Modal
        title={editTarget ? `编辑用户 · ${editTarget.display_name}` : "编辑用户"}
        open={editTarget !== null}
        onCancel={() => setEditTarget(null)}
        footer={null}
        destroyOnHidden
        width={520}
      >
        {editTarget ? (
          <Form<EditFormValues>
            form={editForm}
            layout="vertical"
            onFinish={handleEdit}
            requiredMark={false}
          >
            <div className="mb-4 flex items-center gap-3">
              {roleAvatar(editTarget.role, 40)}
              <div className="flex flex-col">
                <strong>{editTarget.username}</strong>
                <Typography.Text type="secondary" className="text-xs">
                  登录邮箱不可修改；如需变更请新建账号后再禁用旧账号。
                </Typography.Text>
              </div>
            </div>

            <Form.Item
              label="显示名称"
              name="display_name"
              rules={[
                { required: true, message: "请输入显示名称" },
                { max: 128, message: "显示名称最长 128 字符" },
              ]}
            >
              <Input maxLength={128} />
            </Form.Item>

            <Form.Item label="角色" name="role" rules={[{ required: true, message: "请选择角色" }]}>
              <Select options={ROLE_OPTIONS} />
            </Form.Item>

            <Form.Item
              label="描述"
              name="description"
              rules={[{ max: 500, message: "描述最长 500 字符" }]}
            >
              <Input.TextArea rows={3} maxLength={500} showCount />
            </Form.Item>

            <div className="flex justify-end gap-2">
              <Button onClick={() => setEditTarget(null)}>取消</Button>
              <Button type="primary" htmlType="submit" loading={editLoading}>
                保存
              </Button>
            </div>
          </Form>
        ) : null}
      </Modal>

      {/* ── Reset password ── */}
      <Modal
        title={passwordTarget ? `重置密码 · ${passwordTarget.display_name}` : "重置密码"}
        open={passwordTarget !== null}
        onCancel={() => setPasswordTarget(null)}
        footer={null}
        destroyOnHidden
        width={440}
      >
        {passwordTarget ? (
          <Form<PasswordFormValues>
            form={passwordForm}
            layout="vertical"
            onFinish={handlePasswordReset}
            requiredMark={false}
          >
            <Typography.Paragraph type="secondary" className="!mb-4 text-sm">
              管理员重置密码后，该用户此前的登录失败计数与锁定状态会被清空，可立即使用新密码登录。
            </Typography.Paragraph>

            <Form.Item
              label="新密码"
              name="password"
              rules={[
                { required: true, message: "请输入新密码" },
                { min: 8, max: 128, message: "密码长度需在 8-128 位之间" },
              ]}
            >
              <Input.Password autoComplete="new-password" />
            </Form.Item>

            <Form.Item
              label="确认新密码"
              name="confirm"
              dependencies={["password"]}
              rules={[
                { required: true, message: "请再次输入新密码" },
                ({ getFieldValue }) => ({
                  validator(_, value) {
                    if (!value || getFieldValue("password") === value) {
                      return Promise.resolve();
                    }
                    return Promise.reject(new Error("两次输入的新密码不一致"));
                  },
                }),
              ]}
            >
              <Input.Password autoComplete="new-password" />
            </Form.Item>

            <div className="flex justify-end gap-2">
              <Button onClick={() => setPasswordTarget(null)}>取消</Button>
              <Button type="primary" danger htmlType="submit" loading={passwordLoading}>
                重置密码
              </Button>
            </div>
          </Form>
        ) : null}
      </Modal>
    </>
  );
}
