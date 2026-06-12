/**
 * Shared wire types for knowledge_chunk citations.
 *
 * Used by both the search/QA playground (`app/search/`) and the asset detail
 * lineage view (`app/assets/[assetId]/`). Backend contract:
 *   ARCHITECT.md → Chunk Locator Contract / Lineage-Facing API Endpoints
 *
 * Search-specific envelopes (SearchResponse, QaResponse, KnowledgeTypeOption)
 * still live in `app/search/_lib/searchTypes.ts`.
 */

/** Chunk-to-source coordinate provenance (Stage 2.2). */
export interface LocatorBlock {
  block_id: string;
  page: number;
  bbox: [number, number, number, number];
}

export interface LocatorInfo {
  page_start: number;
  page_end: number;
  bbox_union: [number, number, number, number] | null;
  blocks: LocatorBlock[];
}

/** Legacy `source` subfield retained for backward compatibility. */
export interface SearchChunkSource {
  doc_id?: string;
  doc_name?: string;
  page?: number;
  normalized_ref_id?: string;
}

/**
 * A single search hit, QA citation, or asset-detail chunk row. Backend
 * enriches the same shape via `_enrich_with_nexus_refs` regardless of
 * which entry point produced it, so one component (ChunkCard) renders
 * all variants.
 */
export interface KnowledgeChunkHit {
  chunk_id: string;
  content: string;
  /** Optional — search/QA carry it; raw chunk-list (no scoring) does not. */
  score?: number;
  source?: SearchChunkSource;
  // NEXUS-side citation fields (added by _enrich_with_nexus_refs)
  nexus_chunk_id?: string;
  normalized_ref_id?: string;
  version_id?: string;
  asset_id?: string;
  // Stage 1-2.4 provenance
  locator?: LocatorInfo | null;
  source_block_ids?: string[] | null;
  raw_object_id?: string;
  raw_object_uri?: string;
  data_source_id?: string;
  // Stage 2.4 graph_extract only (omitted for non-graph chunks)
  primary_block_ids?: string[];
  evidence_block_ids?: string[];
  // Asset-detail chunks expose richer fields than search hits
  knowledge_type_code?: string;
  chunk_type?: string;
  chunk_index?: number;
  id?: string;
}

/** Response of `/api/raw-objects/[id]/download-url`. */
export interface RawDownloadResponse {
  raw_object_id: string;
  download_url: string;
  expires_at: string;
  ttl_seconds: number;
}

/** Response of `/api/normalized-refs/[id]/chunks`. */
export interface ChunkListResponse {
  data: KnowledgeChunkHit[];
  meta: {
    trace_id?: string;
    page: number;
    page_size: number;
    total: number;
  };
}

/**
 * Block descriptor as returned by `/api/normalized-refs/[id]/content`.
 * Includes the out-of-band `md_char_range = [start, end]` used by the
 * MarkdownViewer to split body_markdown into anchor-wrapped segments
 * (without ever mutating the markdown text itself).
 */
export interface NormalizedBlock {
  block_id: string;
  block_type?: string;
  page?: number;
  bbox?: [number, number, number, number];
  text?: string;
  content?: string;
  heading_level?: number;
  md_char_range: [number, number] | null;
}

/** Response of `/api/normalized-refs/[id]/content`. */
export interface NormalizedRefContent {
  ref_id: string;
  asset_id: string | null;
  version_id: string;
  normalized_type: "document" | "record" | string;
  body_markdown: string | null;
  blocks: NormalizedBlock[] | null;
  record_body: Record<string, unknown> | null;
}
