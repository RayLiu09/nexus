"use client";

/**
 * ChunkListSection — "关联 Chunks" panel inside Asset Detail → 血缘追溯 tab.
 *
 * Lazily fetches paginated chunks for a normalized_ref via
 * /api/normalized-refs/[refId]/chunks (server-side proxy → backend
 * /open/v1/normalized-refs/{id}/chunks). Re-uses the shared ChunkCard +
 * ChunkDetailDrawer so the citation experience matches the search/QA
 * playground.
 *
 * `hideAssetLink` on ChunkCard avoids a self-link (we're already on the
 * asset's detail page).
 */

import { useCallback, useEffect, useState } from "react";
import { Alert, Card, Empty, Pagination, Skeleton, Space, Tag } from "antd";
import type { KnowledgeChunkHit } from "@/lib/chunkTypes";
import { ChunkCard } from "@/components/chunk/ChunkCard";
import { ChunkDetailDrawer } from "@/components/chunk/ChunkDetailDrawer";
import { ChunkPreviewDrawer } from "@/components/chunk/ChunkPreviewDrawer";

interface ProxyEnvelope {
  ok: true;
  status: number;
  data: KnowledgeChunkHit[];
  traceId: string | null;
  listMeta?: { page?: number; pageSize?: number; total?: number };
}
interface ProxyErrorEnvelope {
  ok: false;
  status: number;
  message: string;
}

const PAGE_SIZE = 10;

export interface ChunkListSectionProps {
  /** Normalized ref id; section renders an info banner when null. */
  refId: string | null;
  title?: string;
  emptyDescription?: string;
  mode?: "detail" | "preview";
  actionLabel?: string;
}

export function ChunkListSection({
  refId,
  title = "关联 Chunks",
  emptyDescription = "该 ref 暂未生成 chunk（可能仍在索引中或属记录类型）",
  mode = "detail",
  actionLabel = mode === "preview" ? "预览定位" : "展开详情",
}: ChunkListSectionProps) {
  const [page, setPage] = useState(1);
  const [data, setData] = useState<KnowledgeChunkHit[] | null>(null);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [selectedChunk, setSelectedChunk] = useState<KnowledgeChunkHit | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const load = useCallback(
    async (targetPage: number) => {
      if (!refId) return;
      setLoading(true);
      setError(null);
      try {
        const url = `/api/normalized-refs/${encodeURIComponent(
          refId,
        )}/chunks?page=${targetPage}&pageSize=${PAGE_SIZE}`;
        const res = await fetch(url, { cache: "no-store" });
        const body = (await res.json()) as ProxyEnvelope | ProxyErrorEnvelope;
        if (!body.ok) {
          throw new Error(body.message || `HTTP ${res.status}`);
        }
        setData(body.data ?? []);
        setTotal(body.listMeta?.total ?? body.data?.length ?? 0);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
        setData([]);
        setTotal(0);
      } finally {
        setLoading(false);
      }
    },
    [refId],
  );

  useEffect(() => {
    if (!refId) return;
    load(page);
  }, [refId, page, load]);

  const openChunkDetail = useCallback((chunk: KnowledgeChunkHit) => {
    setSelectedChunk(chunk);
    setDrawerOpen(true);
  }, []);

  if (!refId) {
    return (
      <Card
        title={
          <Space>
            <span>{title}</span>
          </Space>
        }
        className="!mt-4"
      >
        <Alert type="info" showIcon title="该资产尚无标准化引用，暂无可关联的 chunk。" />
      </Card>
    );
  }

  return (
    <>
      <Card
        title={
          <Space>
            <span>{title}</span>
            {!loading && total > 0 && <Tag color="processing">{total}</Tag>}
          </Space>
        }
        className="!mt-4"
      >
        {error && <Alert type="error" showIcon className="!mb-3" title={error} />}
        {loading && data === null ? (
          <Skeleton active paragraph={{ rows: 3 }} />
        ) : data && data.length > 0 ? (
          <>
            {data.map((item) => (
              <div
                key={item.id ?? item.chunk_id ?? item.nexus_chunk_id}
                className="border-0 border-b border-solid border-line py-3 last:border-b-0"
              >
                <ChunkCard
                  chunk={item}
                  onSelect={openChunkDetail}
                  hideAssetLink
                  actionLabel={actionLabel}
                />
              </div>
            ))}
            {total > PAGE_SIZE && (
              <div className="mt-3 flex justify-end">
                <Pagination
                  current={page}
                  pageSize={PAGE_SIZE}
                  total={total}
                  onChange={setPage}
                  showSizeChanger={false}
                />
              </div>
            )}
          </>
        ) : (
          <Empty description={emptyDescription} />
        )}
      </Card>

      {mode === "preview" ? (
        <ChunkPreviewDrawer
          chunk={selectedChunk}
          open={drawerOpen}
          onClose={() => setDrawerOpen(false)}
        />
      ) : (
        <ChunkDetailDrawer
          chunk={selectedChunk}
          open={drawerOpen}
          onClose={() => setDrawerOpen(false)}
        />
      )}
    </>
  );
}
