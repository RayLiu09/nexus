"use client";

import Link from "next/link";
import { CopyableShortId } from "@/components/shared/CopyableShortId";

/**
 * Two-line cell for any list view whose row is a *data asset* surfaced via a
 * `normalized_ref`-keyed record (governance runs, tag review queues, etc.):
 *   line 1 — asset title (when available) as a deep-link to the asset detail
 *            page; falls back to "未命名资产" when the
 *            `normalized_ref → version → asset` chain is broken server-side.
 *   line 2 — `asset_id` short id with copy-to-clipboard, so operators identify
 *            the underlying *data asset*, not the technical normalized_ref.
 *            When `asset_id` is missing we degrade to `normalized_ref_id` so
 *            the row is still cross-referenceable.
 */
export function AssetRefCell({
  title,
  assetId,
  normalizedRefId,
}: {
  title?: string | null;
  assetId?: string | null;
  normalizedRefId: string;
}) {
  const hasTitle = !!title?.trim();
  const titleNode = hasTitle ? (
    assetId ? (
      <Link
        href={`/assets/${assetId}`}
        className="max-w-[260px] truncate text-sm leading-tight font-medium hover:underline"
        style={{ color: "var(--brand)" }}
        title={title!}
      >
        {title}
      </Link>
    ) : (
      <span
        className="text-primary max-w-[260px] truncate text-sm leading-tight font-medium"
        title={title!}
      >
        {title}
      </span>
    )
  ) : (
    <span className="text-muted text-sm leading-tight">未命名资产</span>
  );

  // Prefer asset_id (logical data-asset identity); fall back to
  // normalized_ref_id when the join failed so the row still has a copyable id.
  const idValue = assetId ?? normalizedRefId;
  const idLabel = assetId ? "asset" : "ref";

  return (
    <div className="flex flex-col gap-0.5">
      {titleNode}
      <span className="inline-flex items-center gap-1">
        <span className="text-muted text-[10px]">{idLabel}</span>
        <CopyableShortId value={idValue} className="text-secondary font-mono text-[11px]" />
      </span>
    </div>
  );
}
