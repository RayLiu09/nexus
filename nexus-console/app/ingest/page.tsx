import { redirect } from "next/navigation";
import { PageHeader } from "@/components/PageHeader";
import { ApiState } from "@/components/ApiState";
import { StatusLabel } from "@/components/StatusLabel";
import { Card } from "@/components/shared/Card";
import { Empty } from "antd";
import { formatTime } from "@/lib/format-time";
import { getApiData, postApiData, shortId, type DataSource, type IngestBatch } from "@/lib/api";
import Link from "next/link";

export const dynamic = "force-dynamic";

async function submitFileIngest(formData: FormData) {
  "use server";

  let target = "/ingest?submitted=1";
  try {
    const content = String(formData.get("content_text") ?? "");
    const payload = {
      data_source_id: String(formData.get("data_source_id") ?? ""),
      idempotency_key: String(formData.get("idempotency_key") ?? ""),
      filename: String(formData.get("filename") ?? "console-sample.txt"),
      content_type: String(formData.get("content_type") ?? "text/plain"),
      content_base64: Buffer.from(content, "utf-8").toString("base64"),
      process_now: formData.get("process_now") === "on",
    };
    await postApiData("/internal/v1/ingest/files", payload);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    target = `/ingest?error=${encodeURIComponent(message.slice(0, 160))}`;
  }
  redirect(target);
}

type IngestPageProps = {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export default async function IngestPage({ searchParams }: IngestPageProps) {
  const params = await searchParams;
  const [sources, batches] = await Promise.all([
    getApiData<DataSource[]>("/internal/v1/data-sources", []),
    getApiData<IngestBatch[]>("/internal/v1/ingest/batches", []),
  ]);
  const error = typeof params.error === "string" ? params.error : null;
  const submitted = params.submitted === "1";

  const totalBatches = batches.data.length;
  const processing = batches.data.filter((b) => b.status === "processing").length;
  const completed = batches.data.filter((b) => b.status === "completed").length;
  const failed = batches.data.filter((b) => b.status === "failed").length;

  return (
    <>
      <PageHeader
        eyebrow="数据接入 — 批次管理与流水线"
        title="数据接入"
        description="基于已注册的数据源创建数据导入/同步批次。提交后系统自动完成接入校验、资产化和标准化处理。"
      />

      <ApiState
        ok={sources.ok && batches.ok && !error}
        error={error ?? sources.error ?? batches.error}
        traceId={sources.traceId ?? batches.traceId}
      />

      {submitted && (
        <div
          style={{
            padding: "12px 16px",
            borderRadius: "var(--radius-lg)",
            background: "var(--success-bg)",
            border: "1px solid var(--success-100)",
            color: "var(--success-700)",
            fontSize: 13,
            marginBottom: 16,
          }}
        >
          批次提交成功，作业已自动创建并开始处理。
        </div>
      )}

      {/* ── Hero Strip ── */}
      <div className="hero-strip">
        <Card variant="hero" weight="primary">
          <div className="card-label">批次总数</div>
          <div className="card-value">{totalBatches}</div>
          <div className="card-sub">{sources.data.length} 个数据源</div>
        </Card>
        <Card variant="hero" weight="primary" tone={processing > 0 ? "warning" : "default"}>
          <div className="card-label">处理中</div>
          <div className="card-value">{processing}</div>
          <div className="card-sub">正在执行流水线</div>
        </Card>
        <Card variant="hero" weight="primary" tone="success">
          <div className="card-label">已完成</div>
          <div className="card-value">{completed}</div>
          <div className="card-sub">成功入库</div>
        </Card>
        <Card variant="hero" weight="primary" tone={failed > 0 ? "danger" : "default"}>
          <div className="card-label">失败</div>
          <div className="card-value">{failed}</div>
          <div className="card-sub">{failed > 0 ? "需排查" : "无异常"}</div>
        </Card>
      </div>

      {/* ── Main Layout: Form + Pipeline ── */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(0, 1fr) minmax(280px, 1fr)",
          gap: 20,
          marginBottom: 20,
        }}
      >
        {/* New batch form */}
        <div
          style={{
            background: "var(--surface)",
            border: "1px solid var(--line)",
            borderRadius: "var(--radius-xl)",
            overflow: "hidden",
          }}
        >
          <div style={{ padding: "16px 20px", borderBottom: "1px solid var(--line-light)" }}>
            <div style={{ fontSize: 15, fontWeight: 600 }}>新建数据批次</div>
            <div style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 2 }}>
              选择数据源并配置批次参数
            </div>
          </div>
          <div style={{ padding: 20 }}>
            <form action={submitFileIngest}>
              <div style={{ display: "grid", gap: 14 }}>
                <div className="form-group">
                  <label>数据源</label>
                  <select name="data_source_id" required className="form-select">
                    <option value="">— 选择已注册的数据源 —</option>
                    {sources.data.length === 0 ? (
                      <option value="" disabled>
                        暂无数据源，请先前往「数据源管理」注册
                      </option>
                    ) : (
                      Object.entries(
                        sources.data.reduce<Record<string, typeof sources.data>>((acc, s) => {
                          const type = s.source_type;
                          if (!acc[type]) acc[type] = [];
                          acc[type].push(s);
                          return acc;
                        }, {}),
                      ).map(([type, items]) => {
                        const typeLabels: Record<string, string> = {
                          file_upload: "本地文件上传",
                          nas: "NAS 同步",
                          crawler: "Crawler 爬虫",
                          database: "数据库对接",
                          webhook: "API 推送",
                        };
                        return (
                          <optgroup key={type} label={typeLabels[type] ?? type}>
                            {items.map((source) => (
                              <option value={source.id} key={source.id}>
                                {source.name} [{source.code}]
                              </option>
                            ))}
                          </optgroup>
                        );
                      })
                    )}
                  </select>
                  {sources.data.length === 0 && (
                    <Link
                      href="/data-sources/new"
                      style={{
                        fontSize: 12,
                        color: "var(--brand)",
                        marginTop: 6,
                        display: "inline-block",
                      }}
                    >
                      → 前往注册数据源
                    </Link>
                  )}
                </div>
                <div className="form-group">
                  <label>幂等键</label>
                  <input
                    name="idempotency_key"
                    defaultValue={`console-batch-${Date.now()}`}
                    required
                    className="form-input"
                  />
                </div>
                <div className="form-group">
                  <label>文件名</label>
                  <input
                    name="filename"
                    defaultValue="console-sample.txt"
                    required
                    className="form-input"
                  />
                </div>
                <div className="form-group">
                  <label>内容类型</label>
                  <input
                    name="content_type"
                    defaultValue="text/plain"
                    required
                    className="form-input"
                  />
                </div>
                <div className="form-group">
                  <label>内容（样本文本）</label>
                  <textarea
                    name="content_text"
                    defaultValue="NEXUS console live API ingest sample for connectivity."
                    required
                    className="form-textarea"
                    rows={3}
                  />
                </div>
                <div className="form-group form-inline">
                  <label>
                    <input name="process_now" type="checkbox" defaultChecked />
                    立即处理并生成资产化结果
                  </label>
                </div>
                <button
                  className="btn btn-primary"
                  type="submit"
                  disabled={!sources.data.length}
                  style={{
                    padding: "8px 20px",
                    borderRadius: "var(--radius-lg)",
                    background: "var(--brand)",
                    color: "#fff",
                    fontWeight: 600,
                    fontSize: 14,
                  }}
                >
                  提交批次
                </button>
              </div>
            </form>
          </div>
        </div>

        {/* Pipeline flow */}
        <div
          style={{
            background: "var(--surface)",
            border: "1px solid var(--line)",
            borderRadius: "var(--radius-xl)",
            overflow: "hidden",
          }}
        >
          <div style={{ padding: "16px 20px", borderBottom: "1px solid var(--line-light)" }}>
            <div style={{ fontSize: 15, fontWeight: 600 }}>批次处理流水线</div>
            <div style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 2 }}>
              提交后自动执行
            </div>
          </div>
          <div style={{ padding: 20 }}>
            <div style={{ display: "grid", gap: 12 }}>
              {[
                { name: "接入校验", desc: "ingest_validate", icon: "1" },
                { name: "资产化", desc: "assetize", icon: "2" },
                { name: "解析", desc: "parse (MinerU)", icon: "3" },
                { name: "标准化", desc: "normalize (LLM)", icon: "4" },
                { name: "AI 治理", desc: "ai_governance", icon: "5" },
                { name: "完成", desc: "complete", icon: "✓" },
              ].map((s, i) => (
                <div
                  key={s.name}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 12,
                    padding: "10px 14px",
                    borderRadius: "var(--radius-lg)",
                    background: i === 5 ? "var(--success-bg)" : "var(--surface-alt)",
                    border: `1px solid ${i === 5 ? "var(--success-100)" : "var(--line-light)"}`,
                  }}
                >
                  <span
                    style={{
                      width: 28,
                      height: 28,
                      borderRadius: "50%",
                      background: i === 5 ? "var(--success-600)" : "var(--brand)",
                      color: "#fff",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontSize: 12,
                      fontWeight: 700,
                      flexShrink: 0,
                    }}
                  >
                    {s.icon}
                  </span>
                  <div>
                    <div style={{ fontSize: 14, fontWeight: 600 }}>{s.name}</div>
                    <div style={{ fontSize: 11, color: "var(--text-muted)" }}>{s.desc}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* ── Batch History ── */}
      <div
        style={{
          background: "var(--surface)",
          border: "1px solid var(--line)",
          borderRadius: "var(--radius-xl)",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            padding: "16px 20px",
            borderBottom: "1px solid var(--line-light)",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
          }}
        >
          <div>
            <div style={{ fontSize: 15, fontWeight: 600 }}>批次历史</div>
            <div style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 2 }}>
              {totalBatches} 个批次
            </div>
          </div>
          <Link href="/raw-ledger" style={{ fontSize: 12, color: "var(--brand)" }}>
            原始数据台账 →
          </Link>
        </div>
        {batches.data.length === 0 ? (
          <Empty description="暂无批次" />
        ) : (
          <div style={{ display: "grid", gap: 0 }}>
            {batches.data.map((batch) => {
              const { display, iso } = formatTime(batch.updated_at);
              return (
                <div
                  key={batch.id}
                  style={{
                    display: "grid",
                    gridTemplateColumns: "1.5fr 120px 100px 100px 130px",
                    alignItems: "center",
                    gap: 12,
                    padding: "10px 20px",
                    borderBottom: "1px solid var(--line-light)",
                    fontSize: 13,
                  }}
                >
                  <span style={{ fontWeight: 500 }}>
                    {String(batch.summary.filename ?? batch.summary.package_type ?? "-")}
                  </span>
                  <code
                    style={{
                      fontSize: 11,
                      fontFamily: "var(--font-mono)",
                      color: "var(--text-muted)",
                    }}
                  >
                    {shortId(batch.id)}
                  </code>
                  <span style={{ color: "var(--text-secondary)" }}>{batch.source_type}</span>
                  <StatusLabel value={batch.status} />
                  <time
                    dateTime={iso}
                    title={iso}
                    style={{ fontSize: 12, color: "var(--text-muted)" }}
                  >
                    {display}
                  </time>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </>
  );
}
