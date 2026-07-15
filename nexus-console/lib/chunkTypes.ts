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
  // Theory-knowledge textbook citation breadcrumb — populated by
  // `_enrich_with_nexus_refs` when the chunk links to a knowledge_outline_node.
  knowledge_outline?: KnowledgeOutlineCitation;
}

export interface KnowledgeOutlineCitationPathEntry {
  id: string;
  title: string;
  numbering: string | null;
  level: number;
}

export interface KnowledgeOutlineCitation {
  node_id: string;
  title: string;
  numbering: string | null;
  level: number;
  /** Root-first breadcrumb; the synthetic root (level 0) is not included. */
  path: KnowledgeOutlineCitationPathEntry[];
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

export interface NormalizedTocItem {
  title?: string;
  text?: string;
  number?: string;
  level?: number;
  page?: number;
  block_id?: string;
  children?: NormalizedTocItem[];
}

export interface MarkdownHighlightRange {
  start: number;
  end: number;
  block_id?: string | null;
}

export interface PageAnchor {
  page: number;
  bbox: [number, number, number, number] | null;
  block_id?: string | null;
}

export interface ChunkPreviewResponse {
  chunk: KnowledgeChunkHit;
  normalized_ref: {
    ref_id: string;
    asset_id: string | null;
    version_id: string;
    normalized_type: "document" | "record" | string;
  };
  source: {
    body_markdown: string | null;
    blocks: NormalizedBlock[] | null;
    record_body: Record<string, unknown> | null;
  };
  highlight: {
    md_char_range?: [number, number] | null;
    md_spans?: Array<{ start: number; end: number; block_id?: string | null }> | null;
    markdown_ranges: MarkdownHighlightRange[];
    page_anchors: PageAnchor[];
    heading_path: Array<{ level: number; title: string }>;
    anchor_role?: string | null;
  };
}

export interface SemanticContextChunk {
  id: string;
  chunk_id: string;
  normalized_ref_id: string;
  knowledge_type_code: string;
  chunk_type: string;
  chunk_index: number;
  content: string;
  locator?: LocatorInfo | null;
  source_block_ids?: string[] | null;
  anchor_role?: string | null;
  caption?: string | null;
  reason: string;
}

export interface SemanticContextSection {
  section_key?: string | null;
  section_key_hash?: string | null;
  section_path: Array<{ level: number; title: string }>;
  siblings: SemanticContextChunk[];
}

export interface SemanticHierarchyPathItem {
  node_id: string;
  title: string;
  display_title: string;
  node_type: "chapter" | "section" | "knowledge_point" | string;
  level: number;
  source_block_id?: string | null;
  seq_range?: [number | null, number | null] | null;
}

export interface SemanticHierarchyNode extends SemanticHierarchyPathItem {
  is_current: boolean;
  contains_current: boolean;
  chunks: Array<SemanticContextChunk & { is_current?: boolean }>;
  chunk_range?: [number, number] | null;
  children: SemanticHierarchyNode[];
}

export interface SemanticHierarchyParentScope extends SemanticHierarchyPathItem {
  overview_chunks: SemanticContextChunk[];
  knowledge_points: SemanticHierarchyNode[];
  children: SemanticHierarchyNode[];
  chunk_range?: [number, number] | null;
  is_current_parent: boolean;
}

export interface SemanticHierarchyContext {
  current_chunk_id: string;
  current_node_id?: string | null;
  parent_node_id?: string | null;
  path: SemanticHierarchyPathItem[];
  tree: SemanticHierarchyNode[];
  parent_scope: SemanticHierarchyParentScope | null;
  source: "normalized_blocks" | "chunk_locator" | string;
}

export interface ChunkSemanticContext {
  current_chunk_id: string;
  section: SemanticContextSection;
  neighbors: {
    previous: SemanticContextChunk[];
    next: SemanticContextChunk[];
  };
  table: {
    overview: SemanticContextChunk | null;
    related_rows: SemanticContextChunk[];
    table_parent_block_id?: string | null;
  };
  media: {
    nearby_body_chunks: SemanticContextChunk[];
  };
  hierarchy?: SemanticHierarchyContext;
  policy: {
    neighbor_window: number;
    section_limit: number;
    table_row_window: number;
    source: "internal_console" | string;
  };
}

export interface ChunkSemanticContextResponse {
  chunk: KnowledgeChunkHit;
  context: ChunkSemanticContext;
}

/** Response of `/api/normalized-refs/[id]/content`. */
export interface NormalizedRefContent {
  ref_id: string;
  asset_id: string | null;
  version_id: string;
  normalized_type: "document" | "record" | string;
  body_markdown: string | null;
  blocks: NormalizedBlock[] | null;
  toc: NormalizedTocItem[] | null;
  record_body: Record<string, unknown> | null;
}
