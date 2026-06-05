import { redirect } from "next/navigation";
import Link from "next/link";
import { PageHeader } from "@/components/PageHeader";
import { postApiData } from "@/lib/api";
import { CreateDataSourceForm } from "./_components/CreateDataSourceForm";

export const dynamic = "force-dynamic";

function buildConnectionConfig(formData: FormData): Record<string, unknown> | null {
  const sourceType = String(formData.get("source_type") ?? "file_upload");
  const config: Record<string, unknown> = {};

  if (sourceType === "nas") {
    const mountPath = String(formData.get("cfg_mount_path") ?? "").trim();
    const scanPattern = String(formData.get("cfg_scan_pattern") ?? "").trim();
    if (mountPath) config.mount_path = mountPath;
    if (scanPattern) config.scan_pattern = scanPattern;
  } else if (sourceType === "crawler") {
    const targetUrl = String(formData.get("cfg_target_url") ?? "").trim();
    const cron = String(formData.get("cfg_schedule_cron") ?? "").trim();
    const token = String(formData.get("cfg_auth_token") ?? "").trim();
    if (targetUrl) config.target_url = targetUrl;
    if (cron) config.schedule_cron = cron;
    if (token) config.auth_token = token;
  } else if (sourceType === "database") {
    const connStr = String(formData.get("cfg_connection_string") ?? "").trim();
    const query = String(formData.get("cfg_query") ?? "").trim();
    const cron = String(formData.get("cfg_schedule_cron") ?? "").trim();
    if (connStr) config.connection_string = connStr;
    if (query) config.query = query;
    if (cron) config.schedule_cron = cron;
  } else if (sourceType === "webhook") {
    const secret = String(formData.get("cfg_webhook_secret") ?? "").trim();
    const ips = String(formData.get("cfg_allowed_ips") ?? "").trim();
    if (secret) config.webhook_secret = secret;
    if (ips)
      config.allowed_ips = ips
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
  }

  return Object.keys(config).length > 0 ? config : null;
}

async function createDataSource(formData: FormData) {
  "use server";

  let target = "/data-sources";
  try {
    const payload = {
      name: String(formData.get("name") ?? ""),
      code: String(formData.get("code") ?? ""),
      source_type: String(formData.get("source_type") ?? "file_upload"),
      description: String(formData.get("description") ?? "") || null,
      org_scope_hint: String(formData.get("org_scope_hint") ?? "")
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
      default_governance_hints: {},
      connection_config: buildConnectionConfig(formData),
    };
    const result = await postApiData<{ id: string }>("/internal/v1/data-sources", payload);
    if (result?.data?.id) {
      target = `/data-sources/${result.data.id}`;
    }
  } catch (error) {
    const msg = error instanceof Error ? error.message : String(error);
    target = `/data-sources/new?error=${encodeURIComponent(msg.slice(0, 160))}`;
  }
  redirect(target);
}

type Props = {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export default async function NewDataSourcePage({ searchParams }: Props) {
  const params = await searchParams;
  const error = typeof params.error === "string" ? params.error : null;
  const preselectedType = typeof params.type === "string" ? params.type : "";

  return (
    <>
      <PageHeader
        eyebrow="数据源管理 — 新建"
        title="注册数据源"
        description="注册一个新的数据源连接器。注册后可在「数据接入」页面基于此数据源创建批次。"
        actions={
          <Link href="/data-sources" style={{ fontSize: 13, color: "var(--brand)" }}>
            ← 返回列表
          </Link>
        }
      />

      {error && (
        <div
          style={{
            padding: "12px 16px",
            borderRadius: "var(--radius-lg)",
            background: "var(--danger-bg)",
            border: "1px solid var(--danger-100)",
            color: "var(--danger-700)",
            fontSize: 13,
            marginBottom: 16,
          }}
        >
          创建失败：{error}
        </div>
      )}

      {/* ── Layout: Form + Side notes ── */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(0, 2fr) minmax(280px, 1fr)",
          gap: 20,
          alignItems: "start",
        }}
      >
        <div
          style={{
            background: "var(--surface)",
            border: "1px solid var(--line)",
            borderRadius: "var(--radius-xl)",
            padding: 24,
          }}
        >
          <CreateDataSourceForm action={createDataSource} preselectedType={preselectedType} />
        </div>

        {/* Side notes */}
        <div
          style={{
            background: "var(--surface)",
            border: "1px solid var(--line)",
            borderRadius: "var(--radius-xl)",
            padding: 20,
          }}
        >
          <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 16 }}>注册说明</div>
          <div style={{ display: "grid", gap: 12 }}>
            <div
              style={{
                padding: "12px 14px",
                borderRadius: "var(--radius-lg)",
                background: "var(--brand-50)",
                border: "1px solid var(--brand-200)",
                fontSize: 13,
              }}
            >
              <strong style={{ display: "block", marginBottom: 4 }}>注册后</strong>
              数据源注册后即可在「数据接入」页面基于此数据源创建批次。
            </div>
            <div
              style={{
                padding: "12px 14px",
                borderRadius: "var(--radius-lg)",
                background: "var(--surface-alt)",
                border: "1px solid var(--line)",
                fontSize: 13,
              }}
            >
              <strong style={{ display: "block", marginBottom: 4 }}>治理策略</strong>
              默认启用「高置信自动采纳」。可在详情页修改。
            </div>
            <div
              style={{
                padding: "12px 14px",
                borderRadius: "var(--radius-lg)",
                background: "var(--warning-bg)",
                border: "1px solid var(--warning-100)",
                fontSize: 13,
              }}
            >
              <strong style={{ display: "block", marginBottom: 4 }}>编码不可修改</strong>
              编码（code）一旦注册不可更改，请谨慎填写。
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
