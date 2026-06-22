"use client";

/**
 * ChunkCard — single chunk row shared by search hits, QA sources, and
 * asset detail's "associated chunks" list.
 *
 * Layer 1 of the lineage UX:
 *   [score] | doc_name | LocatorChip | AssetLink | content (3-row ellipsis)
 *
 * "展开详情" opens a ChunkDetailDrawer (owned by the consuming page).
 */
import { Space, Tag, Typography } from "antd";
import type { KnowledgeChunkHit } from "@/lib/chunkTypes";
import { AssetLink } from "./AssetLink";
import { LocatorChip } from "./LocatorChip";

export interface ChunkCardProps {
  chunk: KnowledgeChunkHit;
  /** Called when the operator clicks "展开详情". */
  onSelect: (chunk: KnowledgeChunkHit) => void;
  /** Hide AssetLink — useful inside the Asset Detail page (avoids self-link). */
  hideAssetLink?: boolean;
  actionLabel?: string;
}

export function ChunkCard({ chunk, onSelect, hideAssetLink, actionLabel = "展开详情" }: ChunkCardProps) {
  const score = typeof chunk.score === "number" ? chunk.score : null;
  const docName = chunk.source?.doc_name;

  return (
    <Space orientation="vertical" size={4} className="w-full">
      <Space size={6} wrap>
        {score !== null && <Tag color="blue">score {score.toFixed(3)}</Tag>}
        {chunk.knowledge_type_code && <Tag color="cyan">{chunk.knowledge_type_code}</Tag>}
        {docName && <Tag>{docName}</Tag>}
        <LocatorChip locator={chunk.locator} fallbackPage={chunk.source?.page} />
        {!hideAssetLink && <AssetLink assetId={chunk.asset_id} />}
        {chunk.primary_block_ids !== undefined && (
          <Tag color="purple" variant="filled">
            图谱 chunk · {chunk.primary_block_ids.length} 主块 ·{" "}
            {chunk.evidence_block_ids?.length ?? 0} 证据
          </Tag>
        )}
      </Space>
      <Typography.Paragraph className="!mb-0" ellipsis={{ rows: 3, expandable: false }}>
        {chunk.content}
      </Typography.Paragraph>
      <button
        type="button"
        onClick={() => onSelect(chunk)}
        aria-controls={`chunk-detail-${chunk.chunk_id ?? chunk.id ?? ""}`}
        className="text-brand self-start text-xs hover:underline"
      >
        {actionLabel}
      </button>
    </Space>
  );
}
