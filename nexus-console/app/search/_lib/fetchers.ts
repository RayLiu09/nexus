/**
 * Thin client-side fetchers over the console's proxy routes. Each returns
 * the unwrapped `data` payload of the ProxySuccess envelope; failures
 * bubble as thrown Errors so callers can drop them into
 * ConversationMessage.error unchanged.
 */
import type { KnowledgeRetrievalResponse, QaResponse, SearchResponse } from "./searchTypes";
import type { ProxyEnvelope, ProxyErrorEnvelope } from "./playgroundTypes";

export async function fetchSearch(
  q: string,
  kb: string | undefined,
  topK: number,
  threshold: number,
): Promise<SearchResponse> {
  const params = buildParams({ q, kb, top_k: topK, similarity_threshold: threshold });
  return readEnvelope<SearchResponse>(await fetch(`/api/search?${params}`, { cache: "no-store" }));
}

export async function fetchQa(
  q: string,
  kb: string | undefined,
  topK: number,
): Promise<QaResponse> {
  const params = buildParams({ q, kb, top_k: topK });
  return readEnvelope<QaResponse>(await fetch(`/api/qa?${params}`, { cache: "no-store" }));
}

export async function fetchKnowledgeRetrieval(q: string): Promise<KnowledgeRetrievalResponse> {
  return readEnvelope<KnowledgeRetrievalResponse>(
    await fetch("/api/knowledge-retrieval", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ query: q }),
      cache: "no-store",
    }),
  );
}

function buildParams(p: Record<string, string | number | undefined>): string {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(p)) {
    if (v === undefined || v === null || v === "") continue;
    params.set(k, String(v));
  }
  return params.toString();
}

async function readEnvelope<T>(res: Response): Promise<T> {
  const body = (await res.json()) as ProxyEnvelope<T> | ProxyErrorEnvelope;
  if (!body.ok) {
    throw new Error(body.message || `HTTP ${res.status}`);
  }
  return body.data;
}
