"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Alert, App, Button, Form, Input, Spin } from "antd";
import {
  BriefcaseBusiness,
  Database,
  LockKeyhole,
  LogIn,
  ShieldCheck,
  UserRound,
} from "lucide-react";

import styles from "./page.module.css";

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

  return (
    <main className={styles.page}>
      <div className={styles.background} aria-hidden="true" />
      <div className={styles.veil} aria-hidden="true" />
      <div className={styles.layout}>
        <section className={styles.brand} aria-label="NEXUS 平台品牌">
          <div className={styles.brandLockup}>
            <div className={styles.logo} role="img" aria-label="NEXUS Logo">
              N
            </div>
            <div>
              <h1 className={styles.brandName}>NEXUS</h1>
              <p className={styles.platformName}>企业数据与知识资产平台</p>
            </div>
          </div>
          <div className={styles.brandRule} aria-hidden="true" />
        </section>

        <div className={styles.panelWrap}>
          <section className={styles.panel} aria-labelledby="login-heading">
            {checkingSession ? (
              <div className={styles.loading} role="status" aria-live="polite">
                <Spin size="large" />
                <span>正在验证登录状态</span>
              </div>
            ) : (
              <>
                <header className={styles.panelHeader}>
                  <h2 id="login-heading" className={styles.panelTitle}>
                    账户登录
                  </h2>
                  <p className={styles.panelSubtitle}>使用 NEXUS 平台账号访问工作台</p>
                </header>

                <div className={styles.roleSection} aria-label="支持的登录角色">
                  <span className={styles.roleLabel}>支持的登录角色</span>
                  <ul className={styles.roles}>
                    <li className={styles.role}>
                      <Database size={16} aria-hidden="true" />
                      数据管理员
                    </li>
                    <li className={styles.role}>
                      <BriefcaseBusiness size={16} aria-hidden="true" />
                      业务专家
                    </li>
                  </ul>
                </div>

                {error && (
                  <Alert
                    className={styles.error}
                    type="error"
                    showIcon
                    title={error}
                    role="alert"
                  />
                )}

                <Form<LoginFormValues>
                  className={styles.form}
                  onFinish={handleLogin}
                  layout="vertical"
                  size="large"
                  requiredMark={false}
                >
                  <Form.Item
                    label="账号"
                    name="username"
                    rules={[{ required: true, message: "请输入用户名" }]}
                  >
                    <Input
                      prefix={
                        <UserRound className={styles.inputIcon} size={17} aria-hidden="true" />
                      }
                      placeholder="请输入用户名"
                      autoComplete="username"
                      autoFocus
                    />
                  </Form.Item>

                  <Form.Item
                    label="密码"
                    name="password"
                    rules={[{ required: true, message: "请输入密码" }]}
                  >
                    <Input.Password
                      prefix={
                        <LockKeyhole className={styles.inputIcon} size={17} aria-hidden="true" />
                      }
                      placeholder="请输入密码"
                      autoComplete="current-password"
                    />
                  </Form.Item>

                  <Form.Item className="!mb-0">
                    <Button
                      className={styles.submit}
                      type="primary"
                      htmlType="submit"
                      block
                      loading={loading}
                      icon={<LogIn size={17} aria-hidden="true" />}
                    >
                      登录
                    </Button>
                  </Form.Item>
                </Form>

                <p className={styles.securityNote}>
                  <ShieldCheck size={15} aria-hidden="true" />
                  受保护的本地身份认证
                </p>
              </>
            )}
          </section>
          <p className={styles.copyright}>NEXUS Console</p>
        </div>
      </div>
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <main className={styles.page}>
          <div className={styles.background} aria-hidden="true" />
          <div className={styles.veil} aria-hidden="true" />
          <div className={styles.layout}>
            <section className={styles.brand} aria-label="NEXUS 平台品牌">
              <div className={styles.brandLockup}>
                <div className={styles.logo} role="img" aria-label="NEXUS Logo">
                  N
                </div>
                <div>
                  <h1 className={styles.brandName}>NEXUS</h1>
                  <p className={styles.platformName}>企业数据与知识资产平台</p>
                </div>
              </div>
            </section>
            <section className={styles.panel} aria-label="加载登录页">
              <div className={styles.loading} role="status">
                <Spin size="large" />
                <span>正在加载登录页</span>
              </div>
            </section>
          </div>
        </main>
      }
    >
      <LoginForm />
    </Suspense>
  );
}
