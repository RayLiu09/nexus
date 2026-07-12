/**
 * Conversation-loop wire types shared across the /search playground
 * subcomponents. Kept out of the M-C canonical types (lib/retrievalTypes)
 * because they only describe the playground's local reducer state, not
 * the backend contract.
 */
import type { KnowledgeRetrievalResponse, QaResponse, SearchResponse } from "./searchTypes";

export type Mode = "retrieval" | "search" | "qa";
export type MessageRole = "user" | "assistant";
export type MessageStatus = "idle" | "running" | "completed" | "needs_clarification" | "failed";

export interface ConversationMessage {
  id: string;
  role: MessageRole;
  mode: Mode;
  query: string;
  createdAt: Date;
  status: MessageStatus;
  searchData?: SearchResponse;
  qaData?: QaResponse;
  retrievalData?: KnowledgeRetrievalResponse;
  error?: string;
}

/**
 * Shape of the ProxySuccess envelope that the console proxy routes
 * return. Same wire format as `lib/api/proxy.ts::ProxySuccess<T>`, but
 * duplicated here so client-only bundles don't drag in server-only
 * `next/headers` imports.
 */
export interface ProxyEnvelope<T> {
  ok: true;
  status: number;
  data: T;
  traceId: string | null;
}

export interface ProxyErrorEnvelope {
  ok: false;
  status: number;
  message: string;
}

export const DEFAULT_TOP_K = 5;
export const DEFAULT_THRESHOLD = 0.7;

export const MODE_LABELS: Record<Mode, string> = {
  retrieval: "智能召回",
  search: "语义检索",
  qa: "问答验证",
};
