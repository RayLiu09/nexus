"use client";

/**
 * ChunkDetailDrawer — Layer 2 lineage panel shared by search/QA playground
 * and asset detail. Surfaces full content, locator block list, and the
 * "view original file" entry point that mints a short-lived MinIO
 * presigned URL via the /api/raw-objects/[id]/download-url proxy.
 */
import { useCallback, useEffect, useState } from "react";
import { Alert, Button, Descriptions, Drawer, Empty, Space, Tag, Typography } from "antd";
import { ExportOutlined } from "@ant-design/icons";
import type { KnowledgeChunkHit, LocatorBlock, RawDownloadResponse } from "@/lib/chunkTypes";
import { LocatorChip } from "./LocatorChip";

interface PresignState {
  status: "idle" | "loading" | "ok" | "error";
  error: string | null;
  url: string | null;
  expiresAt: string | null;
}

const INITIAL: PresignState = {
  status: "idle",
  error: null,
  url: null,
  expiresAt: null,
};

export interface ChunkDetailDrawerProps {
  chunk: KnowledgeChunkHit | null;
  open: boolean;
  onClose: () => void;
}

export function ChunkDetailDrawer({ chunk, open, onClose }: ChunkDetailDrawerProps) {
  const [presign, setPresign] = useState<PresignState>(INITIAL);

  useEffect(() => {
    if (!open) setPresign(INITIAL);
  }, [open]);
  useEffect(() => {
    setPresign(INITIAL);
  }, [chunk?.chunk_id]);

  const rawObjectId = chunk?.raw_object_id;

  const requestPresign = useCallback(async () => {
    if (!rawObjectId) return;
    setPresign({ status: "loading", error: null, url: null, expiresAt: null });
    try {
      const res = await fetch(`/api/raw-objects/${encodeURIComponent(rawObjectId)}/download-url`, {
        cache: "no-store",
      });
      const body = (await res.json()) as
        | { ok: true; data: RawDownloadResponse }
        | { ok: false; message?: string; status?: number };
      if (!body.ok) {
        throw new Error(body.message ?? `HTTP ${res.status}`);
      }
      window.open(body.data.download_url, "_blank", "noopener,noreferrer");
      setPresign({
        status: "ok",
        error: null,
        url: body.data.download_url,
        expiresAt: body.data.expires_at,
      });
    } catch (err) {
      setPresign({
        status: "error",
        error: err instanceof Error ? err.message : String(err),
        url: null,
        expiresAt: null,
      });
    }
  }, [rawObjectId]);

  return (
    <Drawer title="chunk 详情" open={open} onClose={onClose} size={560} destroyOnHidden>
      {chunk ? (
        <div
          id={`chunk-detail-${chunk.chunk_id ?? chunk.id ?? ""}`}
          className="flex flex-col gap-4"
        >
          <Descriptions size="small" column={1} bordered>
            {chunk.source?.doc_name && (
              <Descriptions.Item label="原文档">{chunk.source.doc_name}</Descriptions.Item>
            )}
            {chunk.asset_id && (
              <Descriptions.Item label="资产 ID">
                <a
                  href={`/assets/${encodeURIComponent(chunk.asset_id)}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-brand font-mono text-xs"
                >
                  {chunk.asset_id} <ExportOutlined />
                </a>
              </Descriptions.Item>
            )}
            <Descriptions.Item label="页面定位">
              <Space size={6}>
                <LocatorChip locator={chunk.locator} fallbackPage={chunk.source?.page} />
                {chunk.locator && chunk.locator.page_start !== chunk.locator.page_end && (
                  <Typography.Text type="secondary" className="text-xs">
                    （跨页 chunk）
                  </Typography.Text>
                )}
              </Space>
            </Descriptions.Item>
            {chunk.source_block_ids && chunk.source_block_ids.length > 0 && (
              <Descriptions.Item label="Block IDs">
                <Space size={4} wrap>
                  {chunk.source_block_ids.map((bid) => (
                    <BlockAnchorTag key={bid} blockId={bid} onClose={onClose} />
                  ))}
                </Space>
              </Descriptions.Item>
            )}
            {chunk.primary_block_ids !== undefined && (
              <Descriptions.Item label="提取出处">
                <Space size={4} wrap>
                  {chunk.primary_block_ids.length === 0 ? (
                    <Typography.Text type="secondary" className="text-xs">
                      无（未定位）
                    </Typography.Text>
                  ) : (
                    chunk.primary_block_ids.map((bid) => (
                      <BlockAnchorTag key={bid} blockId={bid} color="blue" onClose={onClose} />
                    ))
                  )}
                </Space>
              </Descriptions.Item>
            )}
            {chunk.evidence_block_ids !== undefined && (
              <Descriptions.Item label="支撑证据">
                <Space size={4} wrap>
                  {chunk.evidence_block_ids.length === 0 ? (
                    <Typography.Text type="secondary" className="text-xs">
                      无
                    </Typography.Text>
                  ) : (
                    chunk.evidence_block_ids.map((bid) => (
                      <BlockAnchorTag key={bid} blockId={bid} onClose={onClose} />
                    ))
                  )}
                </Space>
              </Descriptions.Item>
            )}
          </Descriptions>

          <section>
            <Typography.Title level={5} className="!mb-2">
              完整内容
            </Typography.Title>
            <Typography.Paragraph className="!mb-0 whitespace-pre-wrap">
              {chunk.content}
            </Typography.Paragraph>
          </section>

          {chunk.locator && chunk.locator.blocks.length > 0 && (
            <section>
              <Typography.Title level={5} className="!mb-2">
                Block 坐标
              </Typography.Title>
              <BlockListTable blocks={chunk.locator.blocks} />
            </section>
          )}

          <section className="flex flex-col gap-2">
            <Typography.Title level={5} className="!mb-0">
              查看原始文件
            </Typography.Title>
            <Typography.Text type="secondary" className="text-xs">
              链接 15 分钟内有效；过期后请重新获取。
            </Typography.Text>
            <Button
              type="primary"
              icon={<ExportOutlined />}
              loading={presign.status === "loading"}
              disabled={!rawObjectId}
              onClick={requestPresign}
            >
              {presign.status === "ok" ? "重新获取链接" : "查看原始文件"}
            </Button>
            {!rawObjectId && (
              <Alert
                type="info"
                showIcon
                title="该 chunk 未携带 raw_object_uri，无法定位原始文件。"
              />
            )}
            {presign.status === "error" && presign.error && (
              <Alert type="error" showIcon title={presign.error} />
            )}
          </section>
        </div>
      ) : (
        <Empty description="未选中 chunk" />
      )}
    </Drawer>
  );
}

/**
 * BlockAnchorTag — a block_id tag rendered as an anchor link that deep-links
 * to `#block-<id>` and closes the drawer so the operator sees the scrolled
 * markdown viewer underneath. Works on the Asset Detail "原文预览" tab; on
 * other pages the hash is set but nothing scrolls (graceful no-op).
 */
function BlockAnchorTag({
  blockId,
  color,
  onClose,
}: {
  blockId: string;
  color?: string;
  onClose: () => void;
}) {
  return (
    <a
      href={`#block-${blockId}`}
      onClick={onClose}
      aria-label={`跳转到 ${blockId}`}
      className="inline-flex"
    >
      <Tag color={color} className="cursor-pointer font-mono text-xs">
        {blockId}
      </Tag>
    </a>
  );
}

function BlockListTable({ blocks }: { blocks: LocatorBlock[] }) {
  return (
    <ul className="m-0 list-none space-y-1 p-0">
      {blocks.map((b) => (
        <li key={b.block_id} className="font-mono text-xs">
          <Tag>p{b.page}</Tag>
          <span className="text-gray-600">
            {b.block_id} · [{b.bbox.map((n) => Math.round(n)).join(", ")}]
          </span>
        </li>
      ))}
    </ul>
  );
}
