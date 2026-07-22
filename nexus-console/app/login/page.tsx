"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Alert, App, Button, Card, Form, Input, Space, Typography } from "antd";
import { LockOutlined, UserOutlined } from "@ant-design/icons";

interface LoginFormValues {
  username: string;
  password: string;
}

function safeRedirect(value: string | null): string {
  if (!value || !value.startsWith("/") || value.startsWith("//")) {
    return "/workbench";
  }
  if (value === "/login" || value.startsWith("/login?")) {
    return "/workbench";
  }
  return value;
}

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { message } = App.useApp();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [checkingSession, setCheckingSession] = useState(true);

  // The access cookie is httpOnly — JS can't read it. Ask the server.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const resp = await fetch("/api/auth/session", { cache: "no-store" });
        // 200 = session exists; 204 = no cookie / expired → show login form
        if (resp.status === 200 && !cancelled) {
          router.replace(safeRedirect(searchParams.get("redirect")));
          router.refresh();
          return;
        }
      } catch {
        /* fall through — show login form */
      }
      if (!cancelled) {
        setCheckingSession(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [router, searchParams]);

  const handleLogin = useCallback(
    async (values: LoginFormValues) => {
      setLoading(true);
      setError(null);

      try {
        const resp = await fetch("/api/auth/login", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify(values),
        });

        const body = await resp.json();

        if (!resp.ok) {
          setError(body?.error?.message ?? "登录失败，请稍后重试");
          return;
        }

        message.success(`欢迎回来，${body.data?.displayName ?? "用户"}`);
        router.replace(safeRedirect(searchParams.get("redirect")));
        router.refresh();
      } catch {
        setError("网络异常，无法连接认证服务");
      } finally {
        setLoading(false);
      }
    },
    [router, searchParams, message],
  );

  if (checkingSession) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-[var(--bg)]">
        <Card className="w-full max-w-sm">
          <div className="flex items-center justify-center py-12">
            <Typography.Text type="secondary">检查登录状态...</Typography.Text>
          </div>
        </Card>
      </main>
    );
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-[var(--bg)]">
      <Card
        className="w-full max-w-sm shadow-sm"
        styles={{ body: { padding: 32 } }}
      >
        <Space orientation="vertical" size="large" className="w-full">
          {/* Brand */}
          <div className="text-center">
            <div className="mx-auto mb-3 flex size-12 items-center justify-center rounded-xl bg-gradient-to-br from-[#2563eb] to-[#0d9488]">
              <span className="text-xl font-bold text-white">N</span>
            </div>
            <Typography.Title level={4} className="!mb-1">
              NEXUS
            </Typography.Title>
            <Typography.Text type="secondary" className="text-sm">
              企业数据与知识资产平台
            </Typography.Text>
          </div>

          {/* Error */}
          {error && <Alert type="error" showIcon title={error} />}

          {/* Form */}
          <Form<LoginFormValues>
            onFinish={handleLogin}
            layout="vertical"
            size="large"
            requiredMark={false}
          >
            <Form.Item
              name="username"
              rules={[{ required: true, message: "请输入用户名" }]}
            >
              <Input
                prefix={<UserOutlined />}
                placeholder="用户名"
                autoComplete="username"
                autoFocus
              />
            </Form.Item>

            <Form.Item
              name="password"
              rules={[{ required: true, message: "请输入密码" }]}
            >
              <Input.Password
                prefix={<LockOutlined />}
                placeholder="密码"
                autoComplete="current-password"
              />
            </Form.Item>

            <Form.Item className="!mb-0">
              <Button type="primary" htmlType="submit" block loading={loading}>
                进入工作台
              </Button>
            </Form.Item>
          </Form>
        </Space>
      </Card>
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <main className="flex min-h-screen items-center justify-center bg-[var(--bg)]">
          <Card className="w-full max-w-sm">
            <div className="flex items-center justify-center py-12">
              <Typography.Text type="secondary">加载中...</Typography.Text>
            </div>
          </Card>
        </main>
      }
    >
      <LoginForm />
    </Suspense>
  );
}
