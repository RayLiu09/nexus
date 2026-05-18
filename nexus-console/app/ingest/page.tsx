import { redirect } from "next/navigation";
import { ApiState } from "@/components/ApiState";
import { PageHeader } from "@/components/PageHeader";
import { StatusLabel } from "@/components/StatusLabel";
import { EmptyState } from "@/components/EmptyState";
import {
  formatDateTime,
  getApiData,
  postApiData,
  shortId,
  type DataSource,
  type IngestBatch
} from "@/lib/api";

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
      process_now: formData.get("process_now") === "on"
    };
    await postApiData("/v1/ingest/files", payload);
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
    getApiData<DataSource[]>("/v1/data-sources", []),
    getApiData<IngestBatch[]>("/v1/ingest/batches", [])
  ]);
  const error = typeof params.error === "string" ? params.error : null;
  const submitted = params.submitted === "1";

  return (
    <>
      <PageHeader
        prototypeId="NX-03"
        title="数据接入"
        description="基于已注册的数据源创建数据导入/同步批次。选择数据源 → 配置批次参数 → 提交后系统自动完成接入校验、资产化和标准化处理。"
      />

      <ApiState
        ok={sources.ok && batches.ok && !error}
        error={error ?? sources.error ?? batches.error}
        traceId={sources.traceId ?? batches.traceId}
      />
      {submitted ? <div className="notice notice-success">批次提交成功，作业已自动创建并开始处理。</div> : null}

      <div className="ingest-batch-layout">
        {/* ── New batch form ───────────────────────────────── */}
        <div className="card">
          <div className="card-header">
            <span className="card-title">新建数据批次</span>
            <span className="text-xs text-muted">选择数据源并配置批次参数</span>
          </div>
          <div className="card-body">
            <form action={submitFileIngest}>
              <div className="flex flex-col gap-3">
                <div className="form-group">
                  <label>数据源</label>
                  <select name="data_source_id" required className="form-select">
                    <option value="">— 选择已注册的数据源 —</option>
                    {sources.data.map((source) => (
                      <option value={source.id} key={source.id}>
                        {source.name} ({source.source_type})
                      </option>
                    ))}
                  </select>
                </div>
                <div className="form-group">
                  <label>幂等键</label>
                  <input name="idempotency_key" defaultValue={`console-${Date.now()}`} required className="form-input" />
                </div>
                <div className="form-group">
                  <label>文件名</label>
                  <input name="filename" defaultValue="console-sample.txt" required className="form-input" />
                </div>
                <div className="form-group">
                  <label>内容类型</label>
                  <input name="content_type" defaultValue="text/plain" required className="form-input" />
                </div>
                <div className="form-group">
                  <label>内容（样本文本）</label>
                  <textarea
                    name="content_text"
                    defaultValue="NEXUS console live API ingest sample for connectivity."
                    required
                    className="form-textarea"
                    rows={4}
                  />
                </div>
                <div className="form-group form-inline">
                  <label>
                    <input name="process_now" type="checkbox" defaultChecked />
                    立即处理并生成资产化结果
                  </label>
                </div>
                <button className="btn btn-primary" type="submit" disabled={!sources.data.length}>
                  提交批次
                </button>
              </div>
            </form>
          </div>
        </div>

        {/* ── Pipeline stage flow ──────────────────────────── */}
        <div className="card">
          <div className="card-header">
            <span className="card-title">批次处理流水线</span>
            <span className="text-xs text-muted">提交后自动执行</span>
          </div>
          <div className="card-body">
            <div className="m1-flow">
              {[
                { name: "接入校验", desc: "ingest_validate" },
                { name: "资产化", desc: "assetize" },
                { name: "解析", desc: "parse" },
                { name: "标准化", desc: "normalize" },
                { name: "AI 治理", desc: "ai_governance" },
                { name: "完成", desc: "complete" }
              ].map((s) => (
                <span key={s.name}>
                  {s.name}
                  <em className="text-xs text-muted" style={{ display: "block", fontStyle: "normal" }}>{s.desc}</em>
                </span>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* ── Batch history ──────────────────────────────────── */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">批次历史</span>
          <span className="text-xs text-muted">{batches.data.length} 个批次</span>
        </div>
        <div className="card-body" style={{ padding: 0 }}>
          {batches.data.length === 0 ? (
            <EmptyState icon="↥" title="暂无批次" description="提交第一个数据批次后将在此显示" />
          ) : (
            batches.data.map((batch) => (
              <div className="table-row" key={batch.id}
                style={{ gridTemplateColumns: "1fr 140px 120px 100px 100px 140px" }}>
                <span style={{ fontWeight: 500 }}>
                  {String(batch.summary.filename ?? batch.summary.package_type ?? "-")}
                </span>
                <span className="mono-cell">{shortId(batch.id)}</span>
                <span className="mono-cell">{shortId(batch.data_source_id)}</span>
                <span>{batch.source_type}</span>
                <StatusLabel value={batch.status} />
                <span className="text-sm text-muted">{formatDateTime(batch.updated_at)}</span>
              </div>
            ))
          )}
        </div>
      </div>
    </>
  );
}
