"use client";

import { usePathname } from "next/navigation";
import Link from "next/link";
import { useState } from "react";
import {
  Alert,
  App,
  Avatar,
  Breadcrumb,
  Button,
  Dropdown,
  Form,
  Input,
  Modal,
  Tag,
  Tooltip,
} from "antd";
import {
  CloudUploadOutlined,
  DownOutlined,
  LogoutOutlined,
  SafetyOutlined,
  TeamOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { getBreadcrumb } from "@/lib/navigation";
import { useSession } from "@/lib/auth/useSession";
import { logout } from "@/lib/auth/session";
import { useQuickUpload } from "@/components/QuickUploadProvider";
import { CONSOLE_ROLE_AVATARS, CONSOLE_ROLE_LABELS } from "@/lib/auth/roles";

interface PasswordFormValues {
  currentPassword: string;
  newPassword: string;
  confirmPassword: string;
}

export function Topbar() {
  const pathname = usePathname();
  const crumbs = getBreadcrumb(pathname);
  const { session } = useSession();
  const { open: openQuickUpload } = useQuickUpload();
  const { message } = App.useApp();
  const [passwordOpen, setPasswordOpen] = useState(false);
  const [passwordForm] = Form.useForm<PasswordFormValues>();

  const breadcrumbItems = crumbs.map((crumb, i) => ({
    key: i,
    title: crumb.href ? <Link href={crumb.href}>{crumb.label}</Link> : crumb.label,
  }));

  const displayName = session?.displayName ?? "用户";
  const initial = displayName.charAt(0);
  const roleLabel = session?.role ? CONSOLE_ROLE_LABELS[session.role] : "";
  const orgName = session?.orgUnit?.name ?? "";
  const avatarSrc = session?.role ? CONSOLE_ROLE_AVATARS[session.role] : undefined;

  const openPasswordModal = () => {
    passwordForm.resetFields();
    setPasswordOpen(true);
  };

  const closePasswordModal = () => {
    passwordForm.resetFields();
    setPasswordOpen(false);
  };

  const handlePasswordSubmit = () => {
    message.info("修改密码接口尚未接入，本次未提交任何数据");
  };

  const accountOverlay = (
    <div className="account-center" role="dialog" aria-label="账户信息中心">
      <div className="account-center-header">
        <Avatar
          size={48}
          src={avatarSrc}
          alt={roleLabel || displayName}
          style={{
            backgroundColor: "var(--brand-100)",
            color: "var(--brand-700)",
            fontWeight: 700,
            fontSize: 18,
          }}
        >
          {initial}
        </Avatar>
        <div className="account-center-identity">
          <strong>{displayName}</strong>
          <span>{session?.username ?? "当前会话用户"}</span>
        </div>
      </div>

      <div className="account-center-status">
        <span className="account-center-status-dot" aria-hidden="true" />
        <span>已登录</span>
        {roleLabel && <Tag color="blue">{roleLabel}</Tag>}
      </div>

      <div className="account-center-details">
        <div className="account-center-detail-row">
          <span className="account-center-detail-label">
            <UserOutlined aria-hidden="true" /> 登录身份
          </span>
          <strong>{roleLabel || "Console 用户"}</strong>
        </div>
        <div className="account-center-detail-row">
          <span className="account-center-detail-label">
            <TeamOutlined aria-hidden="true" /> 所属组织
          </span>
          <strong>{orgName || "未设置组织"}</strong>
        </div>
      </div>

      <div className="account-center-actions">
        <Button
          type="text"
          icon={<SafetyOutlined />}
          aria-label="修改密码"
          onClick={openPasswordModal}
          block
        >
          修改密码
        </Button>
        <Button
          type="text"
          danger
          icon={<LogoutOutlined />}
          aria-label="退出登录"
          onClick={() => logout()}
          block
        >
          退出登录
        </Button>
      </div>
    </div>
  );

  return (
    <header className="topbar">
      <div className="topbar-left">
        <Breadcrumb items={breadcrumbItems} />
      </div>

      <div className="topbar-right">
        <Tooltip title="拖拽上传文件，自动入库并触发流水线">
          <Button type="primary" icon={<CloudUploadOutlined />} onClick={() => openQuickUpload()}>
            快速上传
          </Button>
        </Tooltip>
        {session && (
          <Dropdown popupRender={() => accountOverlay} placement="bottomRight" trigger={["click"]}>
            <button type="button" className="topbar-account-trigger" aria-label="打开账户信息中心">
              <Avatar
                size={32}
                src={avatarSrc}
                alt={roleLabel || displayName}
                style={{
                  backgroundColor: "var(--brand-200)",
                  color: "var(--brand-700)",
                  fontWeight: 700,
                }}
              >
                {initial}
              </Avatar>
              <span className="topbar-account-copy">
                <strong>{displayName}</strong>
                <span>{roleLabel || "Console 用户"}</span>
              </span>
              <DownOutlined className="topbar-account-chevron" aria-hidden="true" />
            </button>
          </Dropdown>
        )}
      </div>

      <Modal
        title="修改密码"
        open={passwordOpen}
        onCancel={closePasswordModal}
        footer={null}
        forceRender
        destroyOnHidden
        width={440}
      >
        <div className="password-modal-intro">
          <SafetyOutlined aria-hidden="true" />
          <span>设置新密码后，后续登录将使用新密码。</span>
        </div>
        <Alert
          type="info"
          showIcon
          title="当前为界面演示"
          description="修改密码接口尚未接入，提交后不会改变实际密码。"
          className="password-modal-alert"
        />
        <Form<PasswordFormValues>
          form={passwordForm}
          layout="vertical"
          requiredMark={false}
          onFinish={handlePasswordSubmit}
          className="password-modal-form"
        >
          <Form.Item
            label="当前密码"
            name="currentPassword"
            rules={[{ required: true, message: "请输入当前密码" }]}
          >
            <Input.Password placeholder="请输入当前密码" autoComplete="current-password" />
          </Form.Item>
          <Form.Item
            label="新密码"
            name="newPassword"
            extra="建议使用至少 8 位，包含大小写字母、数字或符号。"
            rules={[
              { required: true, message: "请输入新密码" },
              { min: 8, message: "新密码至少需要 8 位" },
            ]}
          >
            <Input.Password placeholder="请输入新密码" autoComplete="new-password" />
          </Form.Item>
          <Form.Item
            label="确认新密码"
            name="confirmPassword"
            dependencies={["newPassword"]}
            rules={[
              { required: true, message: "请再次输入新密码" },
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value || getFieldValue("newPassword") === value) {
                    return Promise.resolve();
                  }
                  return Promise.reject(new Error("两次输入的新密码不一致"));
                },
              }),
            ]}
          >
            <Input.Password placeholder="请再次输入新密码" autoComplete="new-password" />
          </Form.Item>
          <div className="password-modal-actions">
            <Button onClick={closePasswordModal}>取消</Button>
            <Button type="primary" htmlType="submit">
              确认修改
            </Button>
          </div>
        </Form>
      </Modal>
    </header>
  );
}
