/**
 * LocatorChip — page-range chip rendered from a chunk's locator.
 *
 *   single page   → `第3页`        (Antd default Tag)
 *   cross page    → `p3–p5 跨页`   (orange Tag)
 *   missing       → `—`            (灰文本 — record-type chunk or legacy data)
 *
 * Pure display; no client runtime required.
 */
import { Tag, Tooltip } from "antd";
import type { LocatorInfo } from "@/lib/chunkTypes";

export interface LocatorChipProps {
  locator: LocatorInfo | null | undefined;
  /** Optional fallback for the legacy `source.page` field. */
  fallbackPage?: number;
}

export function LocatorChip({ locator, fallbackPage }: LocatorChipProps) {
  if (!locator) {
    if (typeof fallbackPage === "number") {
      return <Tag>第{fallbackPage}页</Tag>;
    }
    return (
      <Tooltip title="该 chunk 无页码定位（记录类型或未携带 locator）">
        <Tag>—</Tag>
      </Tooltip>
    );
  }

  const { page_start, page_end } = locator;
  if (page_start === page_end) {
    return <Tag>第{page_start}页</Tag>;
  }
  return (
    <Tag color="orange">
      p{page_start}–p{page_end} 跨页
    </Tag>
  );
}
