"use client";

import { useState } from "react";
import Link from "next/link";
import { StatusLabel } from "@/components/StatusLabel";
import { DomainTag } from "@/components/DomainTag";
import { EmptyState } from "@/components/EmptyState";
import { formatDateTime, type DocumentAsset } from "@/lib/api";

type AssetWithMeta = DocumentAsset & {
  domain?: string;
  level?: string;
  thumbnailHint?: string;
};

type AssetsContentProps = {
  assets: AssetWithMeta[];
};

export function AssetsContent({ assets }: AssetsContentProps) {
  const [viewMode, setViewMode] = useState<"card" | "list">("list");

  if (assets.length === 0) {
    return (
      <EmptyState
        icon="📁"
        title="暂无资产"
        description="完成数据接入和标准化流程后，资产将在此处显示"
      />
    );
  }

  return (
    <>
      {/* Toolbar */}
      <div className="toolbar">
        <div className="toolbar-left">
          <input
            className="form-input"
            placeholder="搜索资产标题..."
            style={{ minWidth: 240 }}
          />
          <select className="form-select">
            <option>全部类型</option>
            <option>教材</option>
            <option>方案</option>
            <option>报告</option>
            <option>案例</option>
          </select>
        </div>
        <div className="toolbar-right">
          <button
            className={`btn btn-sm ${viewMode === "list" ? "btn-primary" : "btn-ghost"}`}
            onClick={() => setViewMode("list")}
          >
            ☰ 列表
          </button>
          <button
            className={`btn btn-sm ${viewMode === "card" ? "btn-primary" : "btn-ghost"}`}
            onClick={() => setViewMode("card")}
          >
            ⊞ 卡片
          </button>
        </div>
      </div>

      {/* List View */}
      {viewMode === "list" && (
        <div className="table-frame">
          <div className="table-head">
            <div className="table-row" style={{ gridTemplateColumns: "2fr 120px 100px 100px 140px 100px 80px" }}>
              <span>标题</span>
              <span>数据域</span>
              <span>分级</span>
              <span>类型</span>
              <span>更新时间</span>
              <span>状态</span>
              <span>操作</span>
            </div>
          </div>
          {assets.map((asset) => (
            <div
              className="table-row clickable"
              key={asset.id}
              style={{ gridTemplateColumns: "2fr 120px 100px 100px 140px 100px 80px" }}
            >
              <span style={{ fontWeight: 500 }}>{asset.title}</span>
              <span>{asset.domain ? <DomainTag domain={asset.domain} /> : "-"}</span>
              <span className="tag">{asset.level ?? "-"}</span>
              <span>{asset.asset_kind}</span>
              <span className="text-sm text-muted">{formatDateTime(asset.updated_at)}</span>
              <StatusLabel value={asset.status} />
              <Link className="text-link" href={`/assets/${asset.id}`}>
                详情 →
              </Link>
            </div>
          ))}
        </div>
      )}

      {/* Card View */}
      {viewMode === "card" && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: "var(--space-4)" }}>
          {assets.map((asset) => (
            <Link href={`/assets/${asset.id}`} key={asset.id} className="card" style={{ display: "block" }}>
              <div
                style={{
                  height: 120,
                  background: "var(--brand-gradient-soft)",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontSize: 32,
                  color: "var(--brand-600)"
                }}
              >
                {asset.thumbnailHint ?? "📄"}
              </div>
              <div className="card-body">
                <div style={{ fontWeight: 600, marginBottom: "var(--space-2)", lineHeight: 1.4 }}>
                  {asset.title}
                </div>
                <div className="flex gap-2 flex-wrap" style={{ marginBottom: "var(--space-2)" }}>
                  {asset.domain && <DomainTag domain={asset.domain} />}
                  {asset.level && <span className="tag">{asset.level}</span>}
                  <span className="tag">{asset.asset_kind}</span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-xs text-muted">{formatDateTime(asset.updated_at)}</span>
                  <StatusLabel value={asset.status} />
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </>
  );
}
