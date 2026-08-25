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

  if (preselectedType === "crawler") {
    return (
      <>
        <PageHeader
          eyebrow="数据源 — Crawler"
          title="Crawler 使用内置 Firecrawl"
          description="系统仅支持 Firecrawl 作为 Crawler 连接器，连接配置由服务器环境变量管理；无需新建 Crawler 数据源。"
          actions={
            <Link href="/data-sources?type=crawler" style={{ fontSize: 13, color: "var(--brand)" }}>
              ← 返回 Crawler 计划
            </Link>
          }
        />
        <div
          style={{
            padding: "16px 20px",
            borderRadius: "var(--radius-lg)",
            background: "var(--surface)",
            border: "1px solid var(--line)",
            fontSize: 13,
          }}
        >
          请在 Crawler 计划列表中创建爬虫计划，计划会自动使用系统内置的 Firecrawl 源。
        </div>
      </>
    );
  }

  return (
    <>
      <PageHeader
        eyebrow="数据源 — 新建"
        title="注册数据源"
        description="按引导完成 4 步即可注册一个新的数据源连接器。"
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
              file_upload
              类型可直接在顶栏「快速上传」入口提交文件；其他类型按调度计划或手动触发同步。
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
