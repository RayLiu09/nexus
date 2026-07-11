/**
 * Playground-scoped wire types for /search: the plain `/api/search` and
 * `/api/qa` GET envelopes plus the shared knowledge-type dropdown option.
 *
 * All M-C v1.3 retrieval types (KnowledgeRetrievalResponse, RetrievalIntent, …)
 * now live in `@/lib/retrievalTypes` as the canonical location. This file
 * re-exports them so historic import paths keep compiling.
 */
import type { KnowledgeChunkHit } from "@/lib/chunkTypes";

export type {
  KnowledgeRetrievalResponse,
  RetrievalClarification,
  RetrievalConversationStep,
  RetrievalIntent,
  RetrievalPlan,
  RetrievalResult,
  RetrievalSourceRef,
  RetrievalStatus,
  RetrievalStepStatus,
  RetrievalSubQuery,
  RetrievalSummary,
} from "@/lib/retrievalTypes";

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
