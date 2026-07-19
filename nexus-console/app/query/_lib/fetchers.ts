/**
 * B8 (§10 Batch B3b) — client-side fetcher for POST /api/query.
 *
 * Thin unwrapper over the console proxy envelope; failures throw so
 * the playground can drop the error string into an Antd Alert.
 */
import type { ProxyErrorEnvelope, ProxySuccessEnvelope, QueryRouterResponse } from "./queryTypes";

export async function fetchQueryRouterAnswer(query: string): Promise<QueryRouterResponse> {
  const res = await fetch("/api/query", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ query }),
    cache: "no-store",
  });
  const body = (await res.json()) as ProxySuccessEnvelope<QueryRouterResponse> | ProxyErrorEnvelope;
  if (!body.ok) {
    throw new Error(body.message || `HTTP ${res.status}`);
  }
  return body.data;
}
