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
        description="支持交互式上传（小批量文件即时校验）和异步批量同步（NAS/Web 大批量事后补齐元数据）两种模式。"
      />

      <ApiState
        ok={sources.ok && batches.ok && !error}
        error={error ?? sources.error ?? batches.error}
        traceId={sources.traceId ?? batches.traceId}
      />
      {submitted ? <div className="notice notice-success">提交已发送，列表将展示最新 API 数据。</div> : null}

      {/* Dual mode hint */}
      <div className="notice notice-info">
        数据接入支持两种模式：<strong>交互式上传</strong>（适合少量文件，即时校验）和 <strong>异步批量同步</strong>（适合 NAS/Web 大批量，先接入后补齐元数据）。当前演示交互式上传模式。
      </div>

      {/* Ingest form */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">交互式上传</span>
          <span className="text-xs text-muted">提交文件内容到真实 API 生成接入批次</span>
        </div>
        <div className="card-body">
          <form action={submitFileIngest}>
            <div className="ingest-form">
              <label>
                数据源
                <select name="data_source_id" required className="form-select">
                  <option value="">选择数据源</option>
                  {sources.data.map((source) => (
                    <option value={source.id} key={source.id}>
                      {source.name} / {source.source_type}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                幂等键
                <input
                  name="idempotency_key"
                  defaultValue={`console-${Date.now()}`}
                  required
                  className="form-input"
                />
              </label>
              <label>
                文件名
                <input name="filename" defaultValue="console-sample.txt" required className="form-input" />
              </label>
              <label>
                内容类型
                <input name="content_type" defaultValue="text/plain" required className="form-input" />
              </label>
              <label className="form-wide">
                样本文本
                <textarea
                  name="content_text"
                  defaultValue="NEXUS console live API ingest sample for Week 1 and Week 2 connectivity."
                  required
                  className="form-textarea"
                />
              </label>
              <label className="checkbox-line">
                <input name="process_now" type="checkbox" defaultChecked />
                立即处理并生成资产化结果
              </label>
              <button className="btn btn-primary" type="submit" disabled={!sources.data.length}>
                提交到真实 API
              </button>
            </div>
          </form>
        </div>
      </div>

      {/* Pipeline flow */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">流水线阶段</span>
        </div>
        <div className="card-body">
          <div className="m1-flow">
            {["ingest_batch", "raw_object", "job", "parse_artifact", "normalized_ref", "asset"].map(
              (step) => (
                <span key={step}>{step}</span>
              )
            )}
          </div>
        </div>
      </div>

      {/* Batch history */}
      {batches.data.length === 0 ? (
        <EmptyState icon="↥" title="暂无接入批次" description="提交第一条数据接入后在此查看批次历史" />
      ) : (
        <div className="table-frame">
          <div className="table-head">
            <div className="table-row" style={{ gridTemplateColumns: "1fr 140px 120px 100px 100px 140px" }}>
              <span>文件名</span>
              <span>批次号</span>
              <span>数据源</span>
              <span>类型</span>
              <span>状态</span>
              <span>更新时间</span>
            </div>
          </div>
          {batches.data.map((batch) => (
            <div className="table-row" key={batch.id} style={{ gridTemplateColumns: "1fr 140px 120px 100px 100px 140px" }}>
              <span>{String(batch.summary.filename ?? batch.summary.package_type ?? "-")}</span>
              <span className="mono-cell">{shortId(batch.id)}</span>
              <span className="mono-cell">{shortId(batch.data_source_id)}</span>
              <span>{batch.source_type}</span>
              <StatusLabel value={batch.status} />
              <span className="text-sm text-muted">{formatDateTime(batch.updated_at)}</span>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
