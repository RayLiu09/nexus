/**
 * Wire types specific to the search / QA playground envelopes.
 *
 * Shared chunk-citation types (LocatorInfo, KnowledgeChunkHit, RawDownloadResponse)
 * live in `lib/chunkTypes.ts` and are used by both this playground and the
 * asset detail lineage view.
 */
import type { KnowledgeChunkHit } from "@/lib/chunkTypes";

export interface SearchResponse {
  query: string;
  kb: string | null;
  results: KnowledgeChunkHit[];
  count: number;
  caller_id: string;
}

export interface QaResponse {
  question: string;
  kb: string | null;
  caller_id: string;
  answer: string;
  /** P0 derived: max(sources[].score). Null when no scored sources. */
  answer_confidence: number | null;
  sources: KnowledgeChunkHit[];
}

/** Knowledge type option (Select uses only code + name). */
export interface KnowledgeTypeOption {
  code: string;
  name: string;
}
