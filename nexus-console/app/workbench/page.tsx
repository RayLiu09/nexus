import { ApiState } from "@/components/ApiState";
import { StatusLabel } from "@/components/StatusLabel";
import { formatDateTime, shortId } from "@/lib/api";
import { loadWorkbenchData } from "@/lib/console-data";

export const dynamic = "force-dynamic";

// ── Helpers ──────────────────────────────────────────────────────

const SOURCE_TYPE_META: Record<string, { label: string; color: string }> = {
  file_upload: { label: "文件上传", color: "var(--brand-500)" },
  nas: { label: "NAS 同步", color: "var(--info-500)" },
  crawler: { label: "爬虫采集", color: "var(--success-500)" },
  database: { label: "数据库", color: "var(--warning-500)" },
  webhook: { label: "API 推送", color: "var(--domain-d6)" }
};

const DOMAIN_COLORS: Record<string, string> = {
  D1: "var(--domain-d1)", D2: "var(--domain-d2)", D3: "var(--domain-d3)",
  D4: "var(--domain-d4)", D5: "var(--domain-d5)", D6: "var(--domain-d6)"
};

function getDomainColor(domain: string): string {
  return DOMAIN_COLORS[domain] ?? "var(--brand-500)";
}

// ── Page ─────────────────────────────────────────────────────────

export default async function WorkbenchPage() {
  const data = await loadWorkbenchData();

  // ── Counts ──────────────────────────────────────────────────
  const dsCount = data.dataSources.data.length;
  const batchCount = data.batches.data.length;
  const rawCount = data.rawObjects.data.length;
  const assetCount = data.assets.data.length;
  const jobCount = data.jobs.data.length;
  const refCount = data.normalizedRefs.data.length;
  const grCount = data.governanceRuns.data.length;

  // ── Pipeline health ─────────────────────────────────────────
  const succeededJobs = data.jobs.data.filter((j) => j.status === "succeeded").length;
  const failedJobs = data.jobs.data.filter((j) => j.status === "failed" || j.status === "dead_lettered").length;
  const runningJobs = data.jobs.data.filter((j) => j.status === "running" || j.status === "queued").length;
  const pipelineHealth = jobCount > 0 ? Math.round((succeededJobs / jobCount) * 100) : 100;

  // ── Data source connector landscape ─────────────────────────
  // For each source type: count of sources + connected assets + data volume (raw objects)
  const sourceLandscape: Record<string, { sources: number; assets: number; rawObjects: number; totalSizeBytes: number }> = {};
  data.dataSources.data.forEach((s) => {
    const entry = sourceLandscape[s.source_type] ?? { sources: 0, assets: 0, rawObjects: 0, totalSizeBytes: 0 };
    entry.sources += 1;
    sourceLandscape[s.source_type] = entry;
  });
  data.assets.data.forEach((a) => {
    // Find which data source this asset belongs to
    const ds = data.dataSources.data.find((s) => s.id === a.data_source_id);
    if (ds && sourceLandscape[ds.source_type]) {
      sourceLandscape[ds.source_type].assets += 1;
    }
  });
  data.rawObjects.data.forEach((r) => {
    if (sourceLandscape[r.source_type]) {
      sourceLandscape[r.source_type].rawObjects += 1;
      sourceLandscape[r.source_type].totalSizeBytes += r.size_bytes ?? 0;
    }
  });
  const maxSourceAssets = Math.max(1, ...Object.values(sourceLandscape).map((v) => v.assets));

  // ── Domain distribution (from governance ai_output) ─────────
  const domainMap: Record<string, { count: number; qualitySum: number; qualityCount: number }> = {};
  data.governanceRuns.data.forEach((gr) => {
    const ao = gr.ai_output ?? {};
    const domain = (ao.classification as string) ?? (ao.domain as string) ?? "未分类";
    if (!domainMap[domain]) domainMap[domain] = { count: 0, qualitySum: 0, qualityCount: 0 };
    domainMap[domain].count += 1;
    const qs = gr.quality_summary as Record<string, unknown> | null;
    const score = (qs?.overall_score as number) ?? (qs?.quality_score as number) ?? (ao.overall_score as number);
    if (typeof score === "number") {
      domainMap[domain].qualitySum += score;
      domainMap[domain].qualityCount += 1;
    }
  });
  const domainEntries = Object.entries(domainMap).sort((a, b) => b[1].count - a[1].count);
  const maxDomainCount = Math.max(1, ...domainEntries.map(([, v]) => v.count));

  // ── Governance coverage ─────────────────────────────────────
  const governedRefIds = new Set(data.governanceRuns.data.map((gr) => gr.normalized_ref_id));
  const governedAssetCount = governedRefIds.size;
  const governanceCoverage = refCount > 0 ? Math.round((governedAssetCount / refCount) * 100) : 0;

  // ── Quality distribution ────────────────────────────────────
  let qualityPass = 0, qualityWarning = 0, qualityFail = 0, qualitySumTotal = 0, qualityCountTotal = 0;
  const qualityScores: number[] = [];
  data.governanceRuns.data.forEach((gr) => {
    const qs = gr.quality_summary as Record<string, unknown> | null;
    const score = (qs?.overall_score as number) ?? (qs?.quality_score as number) ?? (gr.ai_output as Record<string, unknown> | null)?.overall_score as number;
    if (typeof score === "number") {
      qualityScores.push(score);
      qualitySumTotal += score;
      qualityCountTotal += 1;
      if (score >= 80) qualityPass += 1;
      else if (score >= 60) qualityWarning += 1;
      else qualityFail += 1;
    }
  });
  const avgQuality = qualityCountTotal > 0 ? Math.round(qualitySumTotal / qualityCountTotal) : 0;
  const qualityTotal = qualityPass + qualityWarning + qualityFail || 1;

  // ── Governance adoption breakdown ───────────────────────────
  let autoAdopted = 0, reviewRequired = 0, rejected = 0;
  data.governanceRuns.data.forEach((gr) => {
    if (gr.adoption_status === "auto_adopted") autoAdopted += 1;
    else if (gr.adoption_status === "rejected") rejected += 1;
    else reviewRequired += 1;
  });

  // ── Governance activity by day (last 7 days) ────────────────
  const dailyActivity: Record<string, { total: number; auto: number; review: number; rejected: number }> = {};
  const now = new Date();
  for (let i = 6; i >= 0; i--) {
    const d = new Date(now);
    d.setDate(d.getDate() - i);
    const key = `${d.getMonth() + 1}/${d.getDate()}`;
    dailyActivity[key] = { total: 0, auto: 0, review: 0, rejected: 0 };
  }
  data.governanceRuns.data.forEach((gr) => {
    const d = new Date(gr.created_at);
    const key = `${d.getMonth() + 1}/${d.getDate()}`;
    if (dailyActivity[key]) {
      dailyActivity[key].total += 1;
      if (gr.adoption_status === "auto_adopted") dailyActivity[key].auto += 1;
      else if (gr.adoption_status === "rejected") dailyActivity[key].rejected += 1;
      else dailyActivity[key].review += 1;
    }
  });
  const maxDailyTotal = Math.max(1, ...Object.values(dailyActivity).map((v) => v.total));

  // ── Asset status distribution ──────────────────────────────
  const assetStatuses: Record<string, number> = {};
  data.assets.data.forEach((a) => {
    assetStatuses[a.status] = (assetStatuses[a.status] ?? 0) + 1;
  });

  // ── Latest activity ─────────────────────────────────────────
  const latestBatch = data.batches.data[0];
  const latestJob = data.jobs.data[0];
  const latestAsset = data.assets.data[0];

  return (
    <>
      {/* ══════════════════════════════════════════════════════════
          Row 0 — KPI Tiles (5 cards)
          ══════════════════════════════════════════════════════════ */}
      <div className="stat-grid stat-grid-5">
        {/* 1. Total Assets */}
        <div className="stat-card stat-hero-brand">
          <div className="stat-card-icon">◈</div>
          <span className="stat-card-label">数据资产总量</span>
          <span className="stat-card-value">{assetCount}</span>
          <span className="stat-card-sub">
            {refCount > 0 ? `已标准化 ${refCount} 个引用` : "暂无标准化引用"}
          </span>
        </div>

        {/* 2. Data Source Connectors */}
        <div className="stat-card stat-hero-info">
          <div className="stat-card-icon">◎</div>
          <span className="stat-card-label">数据源连接器</span>
          <span className="stat-card-value">{dsCount}</span>
          <span className="stat-card-sub">
            {Object.keys(sourceLandscape).length} 种类型 · {rawCount} 个原始对象
          </span>
        </div>

        {/* 3. Governance Coverage */}
        <div className="stat-card stat-hero-success">
          <div className="stat-card-icon">✓</div>
          <span className="stat-card-label">AI 治理覆盖率</span>
          <span className="stat-card-value">{governanceCoverage}%</span>
          <span className="stat-card-sub">
            {autoAdopted} 自动采纳 · {reviewRequired} 待复核
          </span>
        </div>

        {/* 4. Pipeline Health */}
        <div className={`stat-card ${pipelineHealth >= 80 ? "stat-hero-success" : "stat-hero-warning"}`}>
          <div className="stat-card-icon">⚙</div>
          <span className="stat-card-label">流水线健康度</span>
          <span className="stat-card-value">{pipelineHealth}%</span>
          <span className="stat-card-sub">
            {succeededJobs} 成功 · {runningJobs} 运行 · {failedJobs} 失败
          </span>
        </div>

        {/* 5. Average Quality Score */}
        <div className={`stat-card ${avgQuality >= 80 ? "stat-hero-success" : avgQuality >= 60 ? "stat-hero-warning" : "stat-hero-brand"}`}>
          <div className="stat-card-icon">⊡</div>
          <span className="stat-card-label">数据质量均分</span>
          <span className="stat-card-value">{avgQuality || "-"}</span>
          <span className="stat-card-sub">
            {grCount > 0 ? `通过 ${qualityPass} · 预警 ${qualityWarning} · 未过 ${qualityFail}` : "暂无治理数据"}
          </span>
        </div>
      </div>

      <ApiState ok={data.ok} error={data.error} traceId={data.traceId} />

      {/* ══════════════════════════════════════════════════════════
          Row 1 — Connector Landscape + Domain Distribution
          ══════════════════════════════════════════════════════════ */}
      <div className="dashboard-section-label">数据全景</div>
      <div className="dashboard-grid">
        {/* -- Left: Data Connector Landscape -- */}
        <div className="card">
          <div className="card-header">
            <span className="card-title">数据源连接器全景</span>
            <span className="text-xs text-muted">按连接器类型聚合的数据规模</span>
          </div>
          <div className="card-body">
            {Object.keys(sourceLandscape).length === 0 ? (
              <div className="empty-state">
                <span className="empty-state-icon">◎</span>
                <strong>暂无数据源连接器</strong>
                <p>注册数据源后将在此展示各连接器的数据规模</p>
              </div>
            ) : (
              <div className="connector-chart">
                {Object.entries(sourceLandscape).map(([type, stats]) => {
                  const meta = SOURCE_TYPE_META[type] ?? { label: type, color: "var(--gray-400)" };
                  const barPct = Math.round((stats.assets / maxSourceAssets) * 100);
                  const sizeMB = stats.totalSizeBytes > 0 ? (stats.totalSizeBytes / (1024 * 1024)).toFixed(1) : "0";
                  return (
                    <div className="connector-row" key={type}>
                      <div className="connector-header">
                        <span className="connector-label">{meta.label}</span>
                        <span className="text-xs text-muted">
                          {stats.sources} 个连接器 · {stats.assets} 个资产 · {stats.rawObjects} 个对象 · {sizeMB} MB
                        </span>
                      </div>
                      <div className="bar-track">
                        <div className="bar-fill" style={{ width: `${barPct}%`, background: meta.color }} />
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        {/* -- Right: Asset Domain Distribution -- */}
        <div className="card">
          <div className="card-header">
            <span className="card-title">资产数据域分布</span>
            <span className="text-xs text-muted">基于 AI 治理分类结果</span>
          </div>
          <div className="card-body">
            {domainEntries.length === 0 ? (
              <div className="empty-state">
                <span className="empty-state-icon">⊞</span>
                <strong>暂无域分布数据</strong>
                <p>完成 AI 治理后将在此展示数据域分布</p>
              </div>
            ) : (
              <div className="domain-chart">
                {domainEntries.map(([domain, stats]) => {
                  const barPct = Math.round((stats.count / maxDomainCount) * 100);
                  const avgQ = stats.qualityCount > 0 ? Math.round(stats.qualitySum / stats.qualityCount) : 0;
                  return (
                    <div className="domain-row" key={domain}>
                      <div className="domain-header">
                        <span className="domain-tag" style={{ background: getDomainColor(domain) }}>{domain}</span>
                        <span className="text-xs text-muted">{stats.count} 个资产</span>
                        {stats.qualityCount > 0 && (
                          <span className={`text-xs ${avgQ >= 80 ? "text-success" : avgQ >= 60 ? "text-warning" : "text-danger"}`}>
                            均分 {avgQ}
                          </span>
                        )}
                      </div>
                      <div className="bar-track">
                        <div className="bar-fill" style={{ width: `${barPct}%`, background: getDomainColor(domain) }} />
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ══════════════════════════════════════════════════════════
          Row 2 — Governance Activity + Quality Distribution
          ══════════════════════════════════════════════════════════ */}
      <div className="dashboard-section-label">治理与质量</div>
      <div className="dashboard-grid">
        {/* -- Left: Governance Activity ── */}
        <div className="card">
          <div className="card-header">
            <span className="card-title">治理活动总览</span>
            <span className="text-xs text-muted">{grCount} 次治理运行</span>
          </div>
          <div className="card-body">
            {grCount === 0 ? (
              <div className="empty-state">
                <span className="empty-state-icon">⚡</span>
                <strong>暂无治理活动</strong>
                <p>完成数据标准化后将自动触发 AI 治理</p>
              </div>
            ) : (
              <>
                {/* Adoption status summary cards */}
                <div className="governance-summary-row">
                  <div className="governance-summary-item">
                    <span className="governance-summary-num" style={{ color: "var(--success-600)" }}>{autoAdopted}</span>
                    <span className="governance-summary-label">自动采纳</span>
                  </div>
                  <div className="governance-summary-item">
                    <span className="governance-summary-num" style={{ color: "var(--warning-600)" }}>{reviewRequired}</span>
                    <span className="governance-summary-label">待复核</span>
                  </div>
                  <div className="governance-summary-item">
                    <span className="governance-summary-num" style={{ color: "var(--danger-600)" }}>{rejected}</span>
                    <span className="governance-summary-label">已驳回</span>
                  </div>
                </div>
                {/* Daily activity mini bars */}
                <div className="daily-activity">
                  <span className="text-xs text-muted" style={{ marginBottom: "var(--space-2)", display: "block" }}>近7日治理活动</span>
                  <div className="daily-bars">
                    {Object.entries(dailyActivity).map(([day, counts]) => {
                      const h = Math.max(4, Math.round((counts.total / maxDailyTotal) * 60));
                      return (
                        <div className="daily-bar-group" key={day} title={`${day}: ${counts.total} 次 (自动 ${counts.auto}, 复核 ${counts.review}, 驳回 ${counts.rejected})`}>
                          <div className="daily-bar-stack">
                            {counts.rejected > 0 && (
                              <div className="daily-bar-segment" style={{ height: `${Math.round((counts.rejected / maxDailyTotal) * 60)}px`, background: "var(--danger-400)" }} />
                            )}
                            {counts.review > 0 && (
                              <div className="daily-bar-segment" style={{ height: `${Math.round((counts.review / maxDailyTotal) * 60)}px`, background: "var(--warning-400)" }} />
                            )}
                            {counts.auto > 0 && (
                              <div className="daily-bar-segment" style={{ height: `${Math.round((counts.auto / maxDailyTotal) * 60)}px`, background: "var(--success-400)" }} />
                            )}
                          </div>
                          <span className="text-xs text-muted">{day}</span>
                        </div>
                      );
                    })}
                  </div>
                  <div className="daily-legend">
                    <span className="text-xs"><span className="legend-dot" style={{ background: "var(--success-400)" }} />自动采纳</span>
                    <span className="text-xs"><span className="legend-dot" style={{ background: "var(--warning-400)" }} />待复核</span>
                    <span className="text-xs"><span className="legend-dot" style={{ background: "var(--danger-400)" }} />驳回</span>
                  </div>
                </div>
              </>
            )}
          </div>
        </div>

        {/* -- Right: Quality Distribution ── */}
        <div className="card">
          <div className="card-header">
            <span className="card-title">数据质量分布</span>
            <span className="text-xs text-muted">{qualityCountTotal} 个已评分资产</span>
          </div>
          <div className="card-body">
            {qualityCountTotal === 0 ? (
              <div className="empty-state">
                <span className="empty-state-icon">⊡</span>
                <strong>暂无质量评分</strong>
                <p>AI 治理运行后将自动生成质量评分</p>
              </div>
            ) : (
              <div className="quality-distribution">
                {/* Quality gauge */}
                <div className="quality-gauge-container">
                  <div className="quality-gauge-ring">
                    <svg viewBox="0 0 120 120" width="120" height="120">
                      <circle cx="60" cy="60" r="52" fill="none" stroke="var(--gray-200)" strokeWidth="10" />
                      <circle cx="60" cy="60" r="52" fill="none"
                        stroke={avgQuality >= 80 ? "var(--success-500)" : avgQuality >= 60 ? "var(--warning-500)" : "var(--danger-500)"}
                        strokeWidth="10"
                        strokeDasharray={`${(avgQuality / 100) * 327} 327`}
                        strokeLinecap="round"
                        transform="rotate(-90 60 60)" />
                    </svg>
                    <div className="quality-gauge-center">
                      <span className="quality-gauge-value">{avgQuality}</span>
                      <span className="quality-gauge-label">均分</span>
                    </div>
                  </div>
                </div>
                {/* Quality level bars */}
                <div className="quality-bars">
                  <div className="quality-bar-item">
                    <div className="quality-bar-header">
                      <span className="text-sm">通过</span>
                      <span className="text-sm" style={{ color: "var(--success-600)" }}>{qualityPass}</span>
                    </div>
                    <div className="bar-track">
                      <div className="bar-fill" style={{ width: `${Math.round((qualityPass / qualityTotal) * 100)}%`, background: "var(--success-500)" }} />
                    </div>
                  </div>
                  <div className="quality-bar-item">
                    <div className="quality-bar-header">
                      <span className="text-sm">预警</span>
                      <span className="text-sm" style={{ color: "var(--warning-600)" }}>{qualityWarning}</span>
                    </div>
                    <div className="bar-track">
                      <div className="bar-fill" style={{ width: `${Math.round((qualityWarning / qualityTotal) * 100)}%`, background: "var(--warning-500)" }} />
                    </div>
                  </div>
                  <div className="quality-bar-item">
                    <div className="quality-bar-header">
                      <span className="text-sm">未通过</span>
                      <span className="text-sm" style={{ color: "var(--danger-600)" }}>{qualityFail}</span>
                    </div>
                    <div className="bar-track">
                      <div className="bar-fill" style={{ width: `${Math.round((qualityFail / qualityTotal) * 100)}%`, background: "var(--danger-500)" }} />
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ══════════════════════════════════════════════════════════
          Row 3 — Asset Status Overview + Activity Timeline
          ══════════════════════════════════════════════════════════ */}
      <div className="dashboard-section-label">资产状态与活动</div>
      <div className="dashboard-grid">
        {/* -- Left: Asset Status Distribution -- */}
        <div className="card">
          <div className="card-header">
            <span className="card-title">资产状态分布</span>
            <span className="text-xs text-muted">{assetCount} 个资产</span>
          </div>
          <div className="card-body">
            {assetCount === 0 ? (
              <div className="empty-state">
                <span className="empty-state-icon">◈</span>
                <strong>暂无资产</strong>
                <p>提交数据接入后将自动创建资产</p>
              </div>
            ) : (
              <div className="asset-status-grid">
                {Object.entries(assetStatuses).sort((a, b) => b[1] - a[1]).map(([status, count]) => {
                  const pct = Math.round((count / assetCount) * 100);
                  const statusColors: Record<string, string> = {
                    available: "var(--success-500)",
                    processing: "var(--info-500)",
                    review_required: "var(--warning-500)",
                    failed: "var(--danger-500)",
                    archived: "var(--gray-400)",
                    disabled: "var(--gray-400)"
                  };
                  const statusLabels: Record<string, string> = {
                    available: "可用",
                    processing: "处理中",
                    review_required: "待复核",
                    failed: "失败",
                    archived: "已归档",
                    disabled: "已禁用"
                  };
                  return (
                    <div className="asset-status-row" key={status}>
                      <div className="asset-status-header">
                        <span className="text-sm">{statusLabels[status] ?? status}</span>
                        <span className="text-sm font-medium">{count}</span>
                      </div>
                      <div className="bar-track">
                        <div className="bar-fill" style={{ width: `${pct}%`, background: statusColors[status] ?? "var(--gray-400)" }} />
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        {/* -- Right: Activity Timeline -- */}
        <div className="card">
          <div className="card-header">
            <span className="card-title">最近活动</span>
            <span className="text-xs text-muted">实时更新</span>
          </div>
          <div className="card-body" style={{ padding: 0 }}>
            {!latestBatch && !latestJob && !latestAsset ? (
              <div className="empty-state">
                <span className="empty-state-icon">📋</span>
                <strong>暂无活动</strong>
                <p>完成首次数据接入后将在此显示活动记录</p>
              </div>
            ) : (
              <div className="timeline">
                {latestBatch && (
                  <div className="timeline-item">
                    <div className="timeline-dot timeline-dot-brand" />
                    <div className="timeline-content">
                      <div className="timeline-header">
                        <strong>接入批次</strong>
                        <span className="text-xs text-muted">{formatDateTime(latestBatch.created_at)}</span>
                      </div>
                      <span className="mono-cell">{shortId(latestBatch.id)}</span>
                      <span className="text-sm text-muted"> · {latestBatch.source_type}</span>
                      <StatusLabel value={latestBatch.status} />
                    </div>
                  </div>
                )}
                {latestJob && (
                  <div className="timeline-item">
                    <div className={`timeline-dot ${latestJob.status === "succeeded" ? "timeline-dot-success" : latestJob.status === "running" ? "timeline-dot-info" : "timeline-dot-warning"}`} />
                    <div className="timeline-content">
                      <div className="timeline-header">
                        <strong>最新作业</strong>
                        <span className="text-xs text-muted">{formatDateTime(latestJob.created_at)}</span>
                      </div>
                      <span className="mono-cell">{shortId(latestJob.id)}</span>
                      <span className="text-sm text-muted"> · {latestJob.current_stage ?? latestJob.job_type}</span>
                      <StatusLabel value={latestJob.status} />
                    </div>
                  </div>
                )}
                {latestAsset && (
                  <div className="timeline-item">
                    <div className={`timeline-dot ${latestAsset.status === "available" ? "timeline-dot-success" : "timeline-dot-brand"}`} />
                    <div className="timeline-content">
                      <div className="timeline-header">
                        <strong>最新资产</strong>
                        <span className="text-xs text-muted">{formatDateTime(latestAsset.updated_at)}</span>
                      </div>
                      <span>{latestAsset.title}</span>
                      <span className="text-sm text-muted"> · {latestAsset.asset_kind}</span>
                      <StatusLabel value={latestAsset.status} />
                    </div>
                  </div>
                )}
                {/* Recent audit events */}
                {data.audits.data.slice(0, 2).map((event) => (
                  <div className="timeline-item" key={event.id}>
                    <div className="timeline-dot timeline-dot-muted" />
                    <div className="timeline-content">
                      <div className="timeline-header">
                        <strong>{event.event_type}</strong>
                        <span className="text-xs text-muted">{formatDateTime(event.created_at)}</span>
                      </div>
                      <span className="text-sm text-muted">
                        {event.target_type} / <span className="mono-cell">{shortId(event.target_id)}</span>
                      </span>
                    </div>
                  </div>
                ))}
                {/* Recent governance runs */}
                {data.governanceRuns.data.slice(0, 2).map((gr) => {
                  const ao = gr.ai_output as Record<string, unknown> | null;
                  const domain = ao?.classification ?? ao?.domain ?? "-";
                  return (
                    <div className="timeline-item" key={gr.id}>
                      <div className={`timeline-dot ${gr.adoption_status === "auto_adopted" ? "timeline-dot-success" : gr.adoption_status === "rejected" ? "timeline-dot-warning" : "timeline-dot-info"}`} />
                      <div className="timeline-content">
                        <div className="timeline-header">
                          <strong>AI 治理运行</strong>
                          <span className="text-xs text-muted">{formatDateTime(gr.created_at)}</span>
                        </div>
                        <span className="text-sm text-muted">
                          域 {String(domain)} · {gr.model_alias}
                        </span>
                        <StatusLabel value={gr.adoption_status} />
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
