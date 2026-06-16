"use client";

import { useState } from "react";
import { Tabs, Tag, Progress, Empty } from "antd";
import { StatusLabel } from "@/components/StatusLabel";
import { ConfidenceBadge } from "@/components/ConfidenceBadge";
import { ChunkListSection } from "@/app/assets/[assetId]/_components/ChunkListSection";
import { SourcePreviewSection } from "@/app/assets/[assetId]/_components/SourcePreviewSection";
import {
  formatDateTime,
  shortId,
  type Asset,
  type AssetVersion,
  type NormalizedAssetRef,
  type ParseArtifact,
  type AIGovernanceRun,
  type GovernanceResult,
} from "@/lib/api";

type Props = {
  asset: Asset | null;
  latestVersion: AssetVersion | null;
  latestRef: NormalizedAssetRef | null;
  relatedArtifact: ParseArtifact | null;
  versions: AssetVersion[];
  governanceRuns: AIGovernanceRun[];
  latestGovernanceResult?: GovernanceResult | null;
  governanceRunsOk?: boolean;
  governanceRunsError?: string | null;
  governanceRunsTraceId?: string | null;
  rawObjectNames?: Map<string, string>;
  dataSourceName?: string | null;
};

const TABS = [
  { key: "lineage", label: "血缘追溯" },
  { key: "preview", label: "原文预览" },
  { key: "ai-governance", label: "AI 治理" },
  { key: "quality", label: "质量评分" },
  { key: "versions", label: "版本历史" },
];

// ---------------------------------------------------------------------------
// Lineage tab
// ---------------------------------------------------------------------------
function LineageTab({
  asset,
  latestVersion,
  latestRef,
  relatedArtifact,
  rawObjectNames,
  dataSourceName,
}: Omit<Props, "versions" | "governanceRuns" | "latestGovernanceResult" | "governanceRunsOk" | "governanceRunsError" | "governanceRunsTraceId">) {
  return (
    <>
      {/* Flow diagram */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">处理链路</span>
          <span className="text-muted text-xs">raw → parse → normalize → asset</span>
        </div>
        <div className="card-body">
          <div className="m1-flow">
            {/* Raw Object */}
            <div className={`m1-stage ${latestVersion ? "status-done" : "status-pending"}`}>
              <div className="m1-stage-dot" />
              <div className="m1-stage-body">
                <div className="m1-stage-label">Raw Object</div>
                {latestVersion && (
                  <div className="m1-stage-sub">
                    {rawObjectNames?.get(latestVersion.raw_object_id) ?? shortId(latestVersion.raw_object_id)}
                  </div>
                )}
              </div>
            </div>

            {/* Arrow: Raw → Parse */}
            <div className={`m1-arrow ${relatedArtifact ? "done" : ""}`} />

            {/* Parse Artifact */}
            <div className={`m1-stage ${relatedArtifact ? "status-done" : "status-pending"}`}>
              <div className="m1-stage-dot" />
              <div className="m1-stage-body">
                <div className="m1-stage-label">Parse Artifact</div>
                {relatedArtifact && (
                  <div className="m1-stage-sub">{relatedArtifact.parse_mode}</div>
                )}
              </div>
            </div>

            {/* Arrow: Parse → Normalized */}
            <div className={`m1-arrow ${latestRef ? "done" : ""}`} />

            {/* Normalized */}
            <div className={`m1-stage ${latestRef ? "status-done" : "status-pending"}`}>
              <div className="m1-stage-dot" />
              <div className="m1-stage-body">
                <div className="m1-stage-label">Normalized</div>
                {latestRef && (
                  <div className="m1-stage-sub">{latestRef.normalized_type}</div>
                )}
              </div>
            </div>

            {/* Arrow: Normalized → Asset */}
            <div className={`m1-arrow ${asset?.status === "available" ? "done" : ""}`} />

            {/* Asset */}
            <div className={`m1-stage ${asset?.status === "available" ? "status-done" : "status-active"}`}>
              <div className="m1-stage-dot" />
              <div className="m1-stage-body">
                <div className="m1-stage-label">Asset</div>
                {asset && (
                  <div className="m1-stage-sub">{asset.status}</div>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Detail table */}
      <div className="table-frame">
        <div className="table-head">
          <div className="table-row" style={{ gridTemplateColumns: "80px 140px 1fr 100px" }}>
            <span>层级</span>
            <span>对象ID</span>
            <span>URI / 校验</span>
            <span>状态</span>
          </div>
        </div>
        {latestVersion && (
          <div className="table-row" style={{ gridTemplateColumns: "80px 140px 1fr 100px" }}>
            <span className="font-bold">版本</span>
            <span className="mono-cell">{shortId(latestVersion.id)}</span>
            <span className="mono-cell">{latestVersion.source_checksum}</span>
            <StatusLabel value={latestVersion.version_status} />
          </div>
        )}
        {relatedArtifact && (
          <div className="table-row" style={{ gridTemplateColumns: "80px 140px 1fr 100px" }}>
            <span className="font-bold">解析产物</span>
            <span className="mono-cell">{shortId(relatedArtifact.id)}</span>
            <span className="mono-cell">{relatedArtifact.artifact_uri}</span>
            <StatusLabel value={relatedArtifact.status} />
          </div>
        )}
        {latestRef && (
          <div className="table-row" style={{ gridTemplateColumns: "80px 140px 1fr 100px" }}>
            <span className="font-bold">标准化引用</span>
            <span className="mono-cell">{shortId(latestRef.id)}</span>
            <span className="mono-cell">{latestRef.object_uri}</span>
            <StatusLabel value={latestRef.status} />
          </div>
        )}
        {!latestVersion && !relatedArtifact && !latestRef && <Empty description="暂无血缘数据" />}
      </div>

      {/* Stage 2.x lineage: per-chunk drill-down with locator + presigned source */}
      <ChunkListSection refId={latestRef?.id ?? null} />
    </>
  );
}

// ---------------------------------------------------------------------------
// AI Governance tab
// ---------------------------------------------------------------------------
function AIGovernanceTab({
  runs,
  result,
  runsOk = true,
  runsError = null,
  runsTraceId = null,
}: {
  runs: AIGovernanceRun[];
  result?: GovernanceResult | null;
  runsOk?: boolean;
  runsError?: string | null;
  runsTraceId?: string | null;
}) {
  const [selected, setSelected] = useState<AIGovernanceRun | null>(null);

  if (runs.length === 0 && !result) {
    return (
      <>
        {!runsOk && (
          <div className="api-state error" style={{ marginBottom: "var(--space-3)" }}>
            AI 治理执行记录加载失败：{runsError ?? "未知错误"}
            {runsTraceId ? `（trace ${runsTraceId}）` : ""}
          </div>
        )}
        <Empty description="暂无 AI 治理记录" />
      </>
    );
  }

  const run = selected ?? runs[0] ?? null;
  const aiOutput = run?.ai_output ?? {
    classification: result?.classification ?? undefined,
    level: result?.level ?? undefined,
    tags: result?.tags ?? [],
  };
  const evidenceRefs = Array.isArray(aiOutput.evidence_refs)
    ? (aiOutput.evidence_refs as Record<string, unknown>[])
    : [];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
      {!runsOk && (
        <div className="api-state error">
          AI 治理执行记录加载失败：{runsError ?? "未知错误"}
          {runsTraceId ? `（trace ${runsTraceId}）` : ""}
        </div>
      )}

      {/* Run selector */}
      {runs.length > 1 && (
        <div className="card">
          <div className="card-header">
            <span className="card-title">执行记录</span>
          </div>
          <div className="card-body" style={{ padding: 0 }}>
            {runs.map((r) => (
              <div
                key={r.id}
                className="table-row"
                style={{
                  gridTemplateColumns: "140px 120px 120px 1fr",
                  cursor: "pointer",
                  background: r.id === run.id ? "var(--brand-50)" : undefined,
                }}
                onClick={() => setSelected(r)}
              >
                <span className="mono-cell">{shortId(r.id)}</span>
                <span className="text-sm">{r.model_alias.split("/").pop()}</span>
                <StatusLabel value={r.validation_status} />
                <span className="text-muted text-xs">{formatDateTime(r.created_at)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Run detail */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">AI 建议</span>
          <div className="flex gap-2">
            {run ? <Tag>{run.model_alias}</Tag> : <Tag>official result</Tag>}
            {run ? <Tag>{run.prompt_version}</Tag> : null}
            {run ? <StatusLabel value={run.adoption_status} /> : result ? <StatusLabel value={result.status} /> : null}
          </div>
        </div>
        <div className="card-body">
          <div className="detail-grid">
            <div>
              <span>分类建议</span>
              {(aiOutput.classification as string) ? (
                <Tag color="blue">{aiOutput.classification as string}</Tag>
              ) : (
                <span className="text-muted">-</span>
              )}
            </div>
            <div>
              <span>分级建议</span>
              {(aiOutput.level as string) ? (
                <Tag color={["L3", "L4"].includes(aiOutput.level as string) ? "red" : undefined}>
                  {aiOutput.level as string}
                </Tag>
              ) : (
                <span className="text-muted">-</span>
              )}
            </div>
            <div>
              <span>置信度</span>
              <ConfidenceBadge confidence={(aiOutput.confidence as number) ?? 0} />
            </div>
            <div>
              <span>标签建议</span>
              <div className="flex flex-wrap gap-1">
                {Array.isArray(aiOutput.tags) && (aiOutput.tags as string[]).length > 0 ? (
                  (aiOutput.tags as string[]).map((t) => <Tag key={t}>{t}</Tag>)
                ) : (
                  <span className="text-muted text-sm">-</span>
                )}
              </div>
            </div>
          </div>

          {(aiOutput.reasoning as string) && (
            <div
              style={{
                marginTop: "var(--space-3)",
                padding: "var(--space-3)",
                background: "var(--gray-50)",
                borderRadius: "var(--radius-md)",
                fontSize: 13,
                color: "var(--text-muted)",
                lineHeight: 1.6,
              }}
            >
              {aiOutput.reasoning as string}
            </div>
          )}
        </div>
      </div>

      {/* Evidence refs */}
      {evidenceRefs.length > 0 && (
        <div className="card">
          <div className="card-header">
            <span className="card-title">证据引用</span>
            <Tag>{evidenceRefs.length} 条</Tag>
          </div>
          <div className="card-body" style={{ padding: 0 }}>
            {evidenceRefs.map((ref, i) => (
              <div key={i} className="table-row" style={{ gridTemplateColumns: "120px 1fr 80px" }}>
                <span className="text-muted text-sm">{String(ref.field)}</span>
                <span className="text-sm">{String(ref.value)}</span>
                <ConfidenceBadge confidence={(ref.confidence as number) ?? 0} />
              </div>
            ))}
          </div>
        </div>
      )}

      {result && !run && (
        <div className="card">
          <div className="card-header">
            <span className="card-title">官方治理结果</span>
            <StatusLabel value={result.status} />
          </div>
          <div className="card-body">
            <div className="detail-grid">
              <div><span>治理结果</span><strong>{result.status}</strong></div>
              <div><span>组织范围</span><strong>{result.org_scope ?? "-"}</strong></div>
              <div><span>索引准入</span><strong>{result.index_admission ? "允许" : "不允许"}</strong></div>
              <div><span>结果ID</span><strong className="mono-cell">{shortId(result.id)}</strong></div>
            </div>
          </div>
        </div>
      )}

      {run?.validation_error && (
        <div
          style={{
            padding: "var(--space-3)",
            background: "var(--error-50)",
            borderRadius: "var(--radius-md)",
            fontSize: 13,
            color: "var(--error)",
          }}
        >
          验证错误：{run.validation_error}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Quality Score tab
// ---------------------------------------------------------------------------
function QualityTab({
  runs,
  result,
}: {
  runs: AIGovernanceRun[];
  result?: GovernanceResult | null;
}) {
  const runWithQuality = runs.find((r) => r.quality_summary !== null);
  const qs = runWithQuality?.quality_summary ?? result?.quality_summary ?? null;

  if (!qs) {
    return <Empty description="暂无质量评分" />;
  }
  const dimScores = (qs.dimension_scores as Record<string, number>) ?? {};
  const checkItems = Array.isArray(qs.check_items)
    ? (qs.check_items as Record<string, unknown>[])
    : [];
  const blockingReasons = Array.isArray(qs.blocking_reasons)
    ? (qs.blocking_reasons as string[])
    : [];
  const qualityScore = qs.quality_score as number;
  const qualityLevel = qs.quality_level as string;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
      {/* Score overview */}
      <div className="card">
        <div className="card-header">
          <span className="card-title">综合质量评分</span>
          <StatusLabel value={qualityLevel} />
        </div>
        <div className="card-body">
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "var(--space-4)",
              marginBottom: "var(--space-4)",
            }}
          >
            <span
              style={{
                fontSize: 48,
                fontWeight: 700,
                color:
                  qualityScore >= 80
                    ? "var(--success)"
                    : qualityScore >= 60
                      ? "var(--warning)"
                      : "var(--error)",
              }}
            >
              {qualityScore.toFixed(0)}
            </span>
            <div>
              <div className="text-muted text-sm">满分 100</div>
              <div className="text-muted text-sm">
                置信度 {(((qs.confidence as number) ?? 0) * 100).toFixed(0)}%
              </div>
            </div>
          </div>

          {/* Dimension scores */}
          {Object.keys(dimScores).length > 0 && (
            <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
              {Object.entries(dimScores).map(([dim, score]) => (
                <div key={dim} className="flex items-center gap-3">
                  <span style={{ width: 80, fontSize: 13, color: "var(--text-muted)" }}>{dim}</span>
                  <Progress
                    percent={Math.round(score)}
                    size="small"
                    style={{ flex: 1 }}
                    strokeColor={
                      score >= 80 ? "var(--success)" : score >= 60 ? "var(--warning)" : undefined
                    }
                  />
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Blocking reasons */}
      {blockingReasons.length > 0 && (
        <div className="card">
          <div className="card-header">
            <span className="card-title">阻断原因</span>
            <Tag color="red">{blockingReasons.length} 条</Tag>
          </div>
          <div className="card-body">
            {blockingReasons.map((r, i) => (
              <div key={i} style={{ fontSize: 13, color: "var(--error)", marginBottom: 4 }}>
                ❌ {r}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Check items */}
      {checkItems.length > 0 && (
        <div className="card">
          <div className="card-header">
            <span className="card-title">检查项明细</span>
          </div>
          <div className="card-body" style={{ padding: 0 }}>
            {checkItems.map((item, i) => {
              const status = String(item.status);
              const icon = status === "pass" ? "✓" : status === "fail" ? "✗" : "⚠";
              const color =
                status === "pass"
                  ? "var(--success)"
                  : status === "fail"
                    ? "var(--error)"
                    : "var(--warning)";
              return (
                <div
                  key={i}
                  className="table-row"
                  style={{ gridTemplateColumns: "24px 160px 1fr 80px" }}
                >
                  <span style={{ color, fontWeight: 700 }}>{icon}</span>
                  <span className="text-sm">{String(item.check_name)}</span>
                  <span className="text-muted text-sm">{String(item.message)}</span>
                  <span className="text-muted text-xs">{String(item.severity)}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Version history tab
// ---------------------------------------------------------------------------
function VersionsTab({ versions, rawObjectNames }: { versions: AssetVersion[]; rawObjectNames?: Map<string, string> }) {
  if (versions.length === 0) {
    return <Empty description="暂无版本记录" />;
  }
  return (
    <div className="table-frame">
      <div className="table-head">
        <div className="table-row" style={{ gridTemplateColumns: "140px 60px 140px 140px 100px" }}>
          <span>版本ID</span>
          <span>版本号</span>
          <span>原始对象</span>
          <span>更新时间</span>
          <span>状态</span>
        </div>
      </div>
      {versions.map((v) => (
        <div
          key={v.id}
          className="table-row"
          style={{ gridTemplateColumns: "140px 60px 140px 140px 100px" }}
        >
          <span className="mono-cell">{shortId(v.id)}</span>
          <span>v{v.version_no}</span>
          <span title={v.raw_object_id}>
            {rawObjectNames?.get(v.raw_object_id) ?? shortId(v.raw_object_id)}
          </span>
          <span className="text-muted text-sm">{formatDateTime(v.updated_at)}</span>
          <StatusLabel value={v.version_status} />
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------
export function AssetDetailTabs({
  asset,
  latestVersion,
  latestRef,
  relatedArtifact,
  versions,
  governanceRuns,
  latestGovernanceResult,
  governanceRunsOk,
  governanceRunsError,
  governanceRunsTraceId,
  rawObjectNames,
  dataSourceName,
}: Props) {
  const [activeTab, setActiveTab] = useState("lineage");

  const tabItems = TABS.map((t) => {
    const badgeCount =
      t.key === "ai-governance" && (governanceRuns.length > 0 || latestGovernanceResult)
        ? Math.max(governanceRuns.length, 1)
        : undefined;
    return {
      key: t.key,
      label: (
        <span>
          {t.label}
          {badgeCount != null && (
            <span
              style={{
                marginLeft: 6,
                background: "var(--brand-100)",
                color: "var(--brand-700)",
                borderRadius: 10,
                padding: "0 6px",
                fontSize: 12,
              }}
            >
              {badgeCount}
            </span>
          )}
        </span>
      ),
    };
  });

  return (
    <>
      <div className="card" style={{ marginBottom: 0 }}>
        <div className="card-header" style={{ borderBottom: "1px solid var(--line)" }}>
          <Tabs activeKey={activeTab} onChange={setActiveTab} items={tabItems} />
        </div>
      </div>

      <div style={{ marginTop: "var(--space-4)" }}>
        {activeTab === "lineage" && (
          <LineageTab
            asset={asset}
            latestVersion={latestVersion}
            latestRef={latestRef}
            relatedArtifact={relatedArtifact}
            rawObjectNames={rawObjectNames}
            dataSourceName={dataSourceName}
          />
        )}
        {activeTab === "preview" && <SourcePreviewSection refId={latestRef?.id ?? null} />}
        {activeTab === "ai-governance" && (
          <AIGovernanceTab
            runs={governanceRuns}
            result={latestGovernanceResult}
            runsOk={governanceRunsOk}
            runsError={governanceRunsError}
            runsTraceId={governanceRunsTraceId}
          />
        )}
        {activeTab === "quality" && (
          <QualityTab runs={governanceRuns} result={latestGovernanceResult} />
        )}
        {activeTab === "versions" && <VersionsTab versions={versions} rawObjectNames={rawObjectNames} />}
      </div>
    </>
  );
}
