import { redirect } from "next/navigation";
import { ApiState } from "@/components/ApiState";
import { StatusLabel } from "@/components/StatusLabel";
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
    <section className="page-section">
      <div className="page-heading">
        <div>
          <p className="prototype-id">NX-03</p>
          <h1>数据接入</h1>
          <p>提交文件或爬虫 JSON 包，生成接入批次、原始对象、处理作业和资产化结果。</p>
        </div>
      </div>

      <ApiState
        ok={sources.ok && batches.ok && !error}
        error={error ?? sources.error ?? batches.error}
        traceId={sources.traceId ?? batches.traceId}
      />
      {submitted ? <div className="notice">提交已发送，列表将展示最新 API 数据。</div> : null}

      <form className="ingest-form" action={submitFileIngest}>
        <label>
          数据源
          <select name="data_source_id" required>
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
          />
        </label>
        <label>
          文件名
          <input name="filename" defaultValue="console-sample.txt" required />
        </label>
        <label>
          内容类型
          <input name="content_type" defaultValue="text/plain" required />
        </label>
        <label className="form-wide">
          样本文本
          <textarea
            name="content_text"
            defaultValue="NEXUS console live API ingest sample for Week 1 and Week 2 connectivity."
            required
          />
        </label>
        <label className="checkbox-line">
          <input name="process_now" type="checkbox" defaultChecked />
          立即处理并生成资产化结果
        </label>
        <button className="primary-button" type="submit" disabled={!sources.data.length}>
          提交到真实 API
        </button>
      </form>

      <div className="m1-flow">
        {["ingest_batch", "raw_object", "job", "parse_artifact", "normalized_ref", "asset"].map(
          (step) => (
            <span key={step}>{step}</span>
          )
        )}
      </div>

      <div className="table-frame">
        <div className="table-row table-head">
          <span>文件名</span>
          <span>批次号</span>
          <span>数据源</span>
          <span>内容类型</span>
          <span>状态</span>
          <span>后续对象</span>
        </div>
        {batches.data.length ? (
          batches.data.map((batch) => (
            <div className="table-row" key={batch.id}>
              <span>{String(batch.summary.filename ?? batch.summary.package_type ?? "-")}</span>
              <span>{shortId(batch.id)}</span>
              <span>{shortId(batch.data_source_id)}</span>
              <span>{batch.source_type}</span>
              <StatusLabel value={batch.status} />
              <span>{formatDateTime(batch.updated_at)}</span>
            </div>
          ))
        ) : (
          <div className="empty-state">
            <strong>暂无真实接入批次</strong>
          </div>
        )}
      </div>
    </section>
  );
}
