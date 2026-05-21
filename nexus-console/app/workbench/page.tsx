import { PageHeader } from "@/components/PageHeader";
import { ApiState } from "@/components/ApiState";
import { StatusLabel } from "@/components/StatusLabel";
import { Card } from "@/components/shared/Card";
import { formatTime } from "@/lib/format-time";
import { loadWorkbenchData } from "@/lib/console-data";
import Link from "next/link";

export const dynamic = "force-dynamic";

export default async function WorkbenchPage() {
  const data = await loadWorkbenchData();

  // ── Counts ──────────────────────────────────────────────────
  const assetCount = data.assets.data.length;
  const refCount = data.normalizedRefs.data.length;
  const jobCount = data.jobs.data.length;
  const grCount = data.governanceRuns.data.length;

  // ── Pipeline health ─────────────────────────────────────────
  const succeededJobs = data.jobs.data.filter((j) => j.status === "succeeded").length;
  const failedJobs = data.jobs.data.filter(
    (j) => j.status === "failed" || j.status === "dead_lettered",
  ).length;
  const runningJobs = data.jobs.data.filter(
    (j) => j.status === "running" || j.status === "queued",
  ).length;
  const pipelineHealth = jobCount > 0 ? Math.round((succeededJobs / jobCount) * 100) : 100;

  // ── Governance ──────────────────────────────────────────────
  const governedRefIds = new Set(data.governanceRuns.data.map((gr) => gr.normalized_ref_id));
  const governanceCoverage = refCount > 0 ? Math.round((governedRefIds.size / refCount) * 100) : 0;
  const autoAdopted = data.governanceRuns.data.filter(
    (gr) => gr.adoption_status === "auto_adopted",
  ).length;
  const reviewRequired = data.governanceRuns.data.filter(
    (gr) =>
      gr.adoption_status === "review_required" || gr.adoption_status === "pending_rule_guardrail",
  ).length;

  // ── Quality ─────────────────────────────────────────────────
  let qualityPass = 0;
  let qualityWarning = 0;
  let qualityFail = 0;
  let qualitySumTotal = 0;
  let qualityCountTotal = 0;

  data.governanceRuns.data.forEach((gr) => {
    const qs = gr.quality_summary as Record<string, unknown> | null;
    const score =
      (qs?.overall_score as number) ??
      (qs?.quality_score as number) ??
      ((gr.ai_output as Record<string, unknown> | null)?.overall_score as number);
    if (typeof score === "number") {
      qualitySumTotal += score;
      qualityCountTotal += 1;
      if (score >= 80) qualityPass += 1;
      else if (score >= 60) qualityWarning += 1;
      else qualityFail += 1;
    }
  });
  const avgQuality = qualityCountTotal > 0 ? Math.round(qualitySumTotal / qualityCountTotal) : 0;

  // ── Attention zone items ────────────────────────────────────
  const attentionItems: { tone: "danger" | "warning"; text: string; href: string }[] = [];
  if (failedJobs > 0)
    attentionItems.push({
      tone: "danger",
      text: `${failedJobs} 个作业失败，需排查`,
      href: "/jobs",
    });
  if (reviewRequired > 0)
    attentionItems.push({
      tone: "warning",
      text: `${reviewRequired} 项治理待复核`,
      href: "/governance",
    });
  if (qualityFail > 0)
    attentionItems.push({
      tone: "warning",
      text: `${qualityFail} 个资产质量未达标`,
      href: "/governance",
    });

  // ── Pipeline funnel ─────────────────────────────────────────
  const rawCount = data.rawObjects.data.length;
  const batchCount = data.batches.data.length;
  const funnelSteps = [
    { label: "原始对象", value: rawCount },
    { label: "数据资产", value: assetCount },
    { label: "标准化引用", value: refCount },
    { label: "已治理", value: governedRefIds.size },
  ];

  // ── Latest activity ─────────────────────────────────────────
  const recentAudits = data.audits.data.slice(0, 5);

  return (
    <>
      <PageHeader
        eyebrow="工作台 — 全局概览"
        title="工作台"
        description="问题驱动的运营首页。关注异常项、流水线健康度和待办决策。"
      />

      <ApiState ok={data.ok} error={data.error} traceId={data.traceId} />

      {/* ── Hero Strip (4 cards) ── */}
      <div className="hero-strip">
        <Card variant="hero" weight="primary">
          <div className="card-label">数据资产总量</div>
          <div className="card-value">{assetCount}</div>
          <div className="card-sub">已标准化 {refCount} 个引用</div>
        </Card>
        <Card variant="hero" weight="primary" tone={pipelineHealth < 80 ? "warning" : "success"}>
          <div className="card-label">流水线健康度</div>
          <div className="card-value">{pipelineHealth}%</div>
          <div className="card-sub">
            {succeededJobs} 成功 · {runningJobs} 运行 · {failedJobs} 失败
          </div>
        </Card>
        <Card variant="hero" weight="primary">
          <div className="card-label">AI 治理覆盖率</div>
          <div className="card-value">{governanceCoverage}%</div>
          <div className="card-sub">
            {autoAdopted} 自动采纳 · {reviewRequired} 待复核
          </div>
        </Card>
        <Card
          variant="hero"
          weight="primary"
          tone={avgQuality < 60 ? "danger" : avgQuality < 80 ? "warning" : "success"}
        >
          <div className="card-label">数据质量均分</div>
          <div className="card-value">{avgQuality || "-"}</div>
          <div className="card-sub">
            通过 {qualityPass} · 预警 {qualityWarning} · 未过 {qualityFail}
          </div>
        </Card>
      </div>

      {/* ── Attention Zone ── */}
      <section
        aria-label="需要关注的异常"
        style={{
          display: "grid",
          gap: 8,
          padding: "16px 20px",
          borderRadius: "var(--radius-xl)",
          border:
            attentionItems.length > 0 ? "1px solid var(--warning-100)" : "1px solid var(--line)",
          background: attentionItems.length > 0 ? "var(--warning-bg)" : "var(--success-bg)",
          marginBottom: 20,
        }}
      >
        {attentionItems.length === 0 ? (
          <div
            style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--success-700)" }}
          >
            <span aria-hidden="true">✓</span>
            <span style={{ fontSize: 14, fontWeight: 500 }}>系统运行正常，无需关注</span>
          </div>
        ) : (
          attentionItems.map((item, i) => (
            <Link
              key={i}
              href={item.href}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                fontSize: 13,
                color: item.tone === "danger" ? "var(--danger-700)" : "var(--warning-700)",
                textDecoration: "none",
              }}
            >
              <span aria-hidden="true">{item.tone === "danger" ? "⚠" : "⚑"}</span>
              <span>{item.text}</span>
              <span style={{ marginLeft: "auto", fontSize: 12, opacity: 0.7 }}>→</span>
            </Link>
          ))
        )}
      </section>

      {/* ── Main Grid (2 columns) ── */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(0, 3fr) minmax(280px, 2fr)",
          gap: 20,
        }}
      >
        {/* Left: Funnel + Timeline */}
        <div style={{ display: "grid", gap: 16 }}>
          {/* Pipeline Funnel */}
          <Card variant="default" weight="secondary" className="card">
            <div className="card-header">
              <span className="card-title">主链路漏斗</span>
            </div>
            <div className="card-body">
              <div style={{ display: "grid", gap: 10 }}>
                {funnelSteps.map((step, i) => {
                  const pct = rawCount > 0 ? Math.round((step.value / rawCount) * 100) : 0;
                  const convRate =
                    i > 0 && funnelSteps[i - 1].value > 0
                      ? Math.round((step.value / funnelSteps[i - 1].value) * 100)
                      : null;
                  return (
                    <div key={step.label}>
                      <div
                        style={{
                          display: "flex",
                          justifyContent: "space-between",
                          fontSize: 13,
                          marginBottom: 4,
                        }}
                      >
                        <span>{step.label}</span>
                        <span style={{ fontWeight: 600 }}>
                          {step.value}
                          {convRate !== null && (
                            <span
                              style={{ fontSize: 11, color: "var(--text-muted)", marginLeft: 6 }}
                            >
                              ({convRate}%)
                            </span>
                          )}
                        </span>
                      </div>
                      <div
                        style={{
                          height: 6,
                          borderRadius: 3,
                          background: "var(--line-light)",
                          overflow: "hidden",
                        }}
                      >
                        <div
                          style={{
                            height: "100%",
                            width: `${pct}%`,
                            borderRadius: 3,
                            background: "var(--brand-gradient)",
                            transition: "width 0.3s ease",
                          }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </Card>

          {/* Recent Activity Timeline */}
          <Card variant="default" weight="secondary" className="card">
            <div className="card-header">
              <span className="card-title">最近活动</span>
            </div>
            <div className="card-body">
              {recentAudits.length === 0 ? (
                <div
                  style={{
                    color: "var(--text-muted)",
                    fontSize: 13,
                    textAlign: "center",
                    padding: 20,
                  }}
                >
                  暂无审计事件
                </div>
              ) : (
                <div style={{ display: "grid", gap: 12 }}>
                  {recentAudits.map((audit) => {
                    const { display, iso } = formatTime(audit.created_at);
                    return (
                      <div
                        key={audit.id}
                        style={{
                          display: "grid",
                          gridTemplateColumns: "auto 1fr",
                          gap: 10,
                          fontSize: 13,
                        }}
                      >
                        <time
                          dateTime={iso}
                          title={iso}
                          style={{
                            fontSize: 11,
                            color: "var(--text-muted)",
                            whiteSpace: "nowrap",
                            paddingTop: 2,
                          }}
                        >
                          {display}
                        </time>
                        <div>
                          <span style={{ fontWeight: 500 }}>{audit.event_type}</span>
                          {audit.actor_id && (
                            <span style={{ color: "var(--text-secondary)", marginLeft: 6 }}>
                              by {audit.actor_id.slice(0, 8)}
                            </span>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </Card>
        </div>

        {/* Right: Decision Queue + Running Status */}
        <div style={{ display: "grid", gap: 16, alignContent: "start" }}>
          {/* Decision Queue */}
          <Card variant="default" weight="secondary" className="card">
            <div className="card-header">
              <span className="card-title">决策待办</span>
              <Link href="/governance" style={{ fontSize: 12, color: "var(--brand)" }}>
                查看全部 →
              </Link>
            </div>
            <div className="card-body">
              {reviewRequired === 0 ? (
                <div
                  style={{
                    color: "var(--text-muted)",
                    fontSize: 13,
                    textAlign: "center",
                    padding: 16,
                  }}
                >
                  待复核队列已清空
                </div>
              ) : (
                <div style={{ display: "grid", gap: 8 }}>
                  {data.governanceRuns.data
                    .filter(
                      (gr) =>
                        gr.adoption_status === "review_required" ||
                        gr.adoption_status === "pending_rule_guardrail",
                    )
                    .slice(0, 5)
                    .map((gr) => (
                      <Link
                        key={gr.id}
                        href="/governance"
                        style={{
                          display: "flex",
                          justifyContent: "space-between",
                          alignItems: "center",
                          padding: "8px 12px",
                          borderRadius: "var(--radius-md)",
                          border: "1px solid var(--line-light)",
                          fontSize: 12,
                          color: "var(--text)",
                          textDecoration: "none",
                        }}
                      >
                        <code style={{ fontFamily: "var(--font-mono)" }}>
                          {gr.normalized_ref_id.slice(0, 20)}…
                        </code>
                        <StatusLabel value={gr.adoption_status} />
                      </Link>
                    ))}
                </div>
              )}
            </div>
          </Card>

          {/* Running Status (3 mini cards) */}
          <div className="metric-grid-4" style={{ gridTemplateColumns: "repeat(3, 1fr)" }}>
            <Card variant="metric" weight="tertiary">
              <div className="card-label">运行中作业</div>
              <div className="card-value" style={{ fontSize: 20 }}>
                {runningJobs}
              </div>
            </Card>
            <Card variant="metric" weight="tertiary">
              <div className="card-label">处理中批次</div>
              <div className="card-value" style={{ fontSize: 20 }}>
                {data.batches.data.filter((b) => b.status === "processing").length}
              </div>
            </Card>
            <Card variant="metric" weight="tertiary">
              <div className="card-label">治理队列</div>
              <div className="card-value" style={{ fontSize: 20 }}>
                {grCount}
              </div>
            </Card>
          </div>

          {/* Batch Progress */}
          <Card variant="default" weight="tertiary" className="card">
            <div className="card-header">
              <span className="card-title">最近批次</span>
              <Link href="/ingest" style={{ fontSize: 12, color: "var(--brand)" }}>
                接入仪表盘 →
              </Link>
            </div>
            <div className="card-body">
              {batchCount === 0 ? (
                <div
                  style={{
                    color: "var(--text-muted)",
                    fontSize: 13,
                    textAlign: "center",
                    padding: 16,
                  }}
                >
                  暂无批次
                </div>
              ) : (
                <div style={{ display: "grid", gap: 8 }}>
                  {data.batches.data.slice(0, 4).map((b) => {
                    const { display, iso } = formatTime(b.created_at);
                    return (
                      <div
                        key={b.id}
                        style={{
                          display: "flex",
                          justifyContent: "space-between",
                          alignItems: "center",
                          fontSize: 12,
                        }}
                      >
                        <span style={{ fontFamily: "var(--font-mono)" }}>{b.id.slice(0, 12)}…</span>
                        <StatusLabel value={b.status} />
                        <time dateTime={iso} title={iso} style={{ color: "var(--text-muted)" }}>
                          {display}
                        </time>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </Card>
        </div>
      </div>
    </>
  );
}
