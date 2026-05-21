import { ApiState } from "@/components/ApiState";
import { PageHeader } from "@/components/PageHeader";
import { StatusLabel } from "@/components/StatusLabel";
import { Card } from "@/components/shared/Card";
import { Empty } from "@/components/shared/Empty";
import { formatTime } from "@/lib/format-time";
import { getApiData, shortId, type RawObject } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function RawLedgerPage() {
  const result = await getApiData<RawObject[]>("/v1/raw-objects", []);
  const objects = result.data;

  const totalCount = objects.length;
  const validatedCount = objects.filter((o) => o.status === "validated").length;
  const pendingCount = objects.filter((o) => o.status === "pending").length;
  const failedCount = objects.filter((o) => o.status === "failed").length;

  return (
    <>
      <PageHeader
        eyebrow="数据接入 — 原始留存与追溯"
        title="原始数据台账"
        description="按批次和对象追溯原始留存位置、checksum、来源和接入状态。每个原始对象对应一次接入校验记录。"
      />

      <ApiState ok={result.ok} error={result.error} traceId={result.traceId} />

      {/* ── Metrics ── */}
      <div className="metric-grid-4">
        <Card variant="metric" weight="secondary">
          <div className="card-label">原始对象总数</div>
          <div className="card-value">{totalCount}</div>
        </Card>
        <Card variant="metric" weight="secondary" tone="success">
          <div className="card-label">已校验</div>
          <div className="card-value">{validatedCount}</div>
        </Card>
        <Card variant="metric" weight="secondary" tone={pendingCount > 0 ? "warning" : "default"}>
          <div className="card-label">待处理</div>
          <div className="card-value">{pendingCount}</div>
        </Card>
        <Card variant="metric" weight="secondary" tone={failedCount > 0 ? "danger" : "default"}>
          <div className="card-label">校验失败</div>
          <div className="card-value">{failedCount}</div>
        </Card>
      </div>

      {/* ── Object List ── */}
      {objects.length === 0 ? (
        <Empty title="暂无原始对象" description="完成数据接入后原始对象将在此处显示" />
      ) : (
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
            <div style={{ fontSize: 15, fontWeight: 600 }}>原始对象列表</div>
            <span style={{ fontSize: 12, color: "var(--text-muted)" }}>{totalCount} 条记录</span>
          </div>
          <div style={{ overflowX: "auto" }}>
            <div style={{ minWidth: 900 }}>
              {/* Header */}
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "130px 130px 1.5fr 1fr 130px 90px",
                  gap: 12,
                  padding: "8px 20px",
                  borderBottom: "1px solid var(--line-light)",
                  fontSize: 12,
                  fontWeight: 600,
                  color: "var(--text-secondary)",
                }}
              >
                <span>对象 ID</span>
                <span>批次号</span>
                <span>对象 URI</span>
                <span>Checksum</span>
                <span>创建时间</span>
                <span>状态</span>
              </div>
              {/* Rows */}
              {objects.map((obj) => {
                const { display, iso } = formatTime(obj.created_at);
                return (
                  <div
                    key={obj.id}
                    style={{
                      display: "grid",
                      gridTemplateColumns: "130px 130px 1.5fr 1fr 130px 90px",
                      gap: 12,
                      padding: "10px 20px",
                      borderBottom: "1px solid var(--line-light)",
                      fontSize: 13,
                      alignItems: "center",
                    }}
                  >
                    <code
                      style={{
                        fontSize: 11,
                        fontFamily: "var(--font-mono)",
                        color: "var(--text-secondary)",
                      }}
                    >
                      {shortId(obj.id)}
                    </code>
                    <code
                      style={{
                        fontSize: 11,
                        fontFamily: "var(--font-mono)",
                        color: "var(--text-muted)",
                      }}
                    >
                      {shortId(obj.batch_id)}
                    </code>
                    <span
                      style={{
                        fontSize: 12,
                        fontFamily: "var(--font-mono)",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                      title={obj.object_uri}
                    >
                      {obj.object_uri}
                    </span>
                    <span
                      style={{
                        fontSize: 11,
                        fontFamily: "var(--font-mono)",
                        color: "var(--text-muted)",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                      }}
                      title={obj.checksum}
                    >
                      {obj.checksum}
                    </span>
                    <time
                      dateTime={iso}
                      title={iso}
                      style={{ fontSize: 12, color: "var(--text-muted)" }}
                    >
                      {display}
                    </time>
                    <StatusLabel value={obj.status} />
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
