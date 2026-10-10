import { NextResponse } from "next/server";

import { forwardedHeadersFrom, proxy } from "@/lib/api/proxy";

export const dynamic = "force-dynamic";

interface Context {
  params: Promise<{ path: string[] }>;
}

const allowed = /^(providers|plans|runs|job-catalog)$/;
const actions = /^(pause|resume|cancel)$/;

function pathFor(parts: string[], method: string): string | null {
  if (parts.some((part) => !part || part === "." || part === "..")) return null;
  const [resource, id, action] = parts;
  if (!allowed.test(resource ?? "")) return null;
  if (resource === "providers") return method === "GET" && parts.length === 1 ? "providers" : null;
  if (resource === "job-catalog")
    return method === "GET" && parts.length === 1 ? "job-catalog" : null;
  if (parts.length === 1)
    return method === "GET" || (method === "POST" && resource === "plans") ? resource : null;
  if (parts.length === 2 && id) {
    if (method === "GET" || (method === "PUT" && resource === "plans") || (method === "DELETE" && resource === "plans"))
      return `${resource}/${encodeURIComponent(id)}`;
  }
  if (parts.length === 3 && id) {
    if (method === "GET" && resource === "runs" && action === "logs")
      return `runs/${encodeURIComponent(id)}/logs`;
    if (method === "POST" && resource === "plans" && action === "runs")
      return `plans/${encodeURIComponent(id)}/runs`;
    if (
      method === "POST" &&
      actions.test(action ?? "") &&
      (resource === "runs" || action !== "cancel")
    )
      return `${resource}/${encodeURIComponent(id)}/${action}`;
  }
  return null;
}

async function handle(request: Request, context: Context, method: "GET" | "POST" | "PUT" | "DELETE") {
  const { path } = await context.params;
  const target = pathFor(path, method);
  if (!target)
    return NextResponse.json({ error: { message: "不支持的数据同步操作" } }, { status: 404 });
  const body = method === "POST" || method === "PUT" ? await request.json().catch(() => ({})) : undefined;
  const result = await proxy<unknown>(`/internal/v1/data-sync/${target}`, {
    method,
    body,
    search: method === "GET" ? new URL(request.url).searchParams.toString() : undefined,
    forwardHeaders: forwardedHeadersFrom(request),
  });
  if (!result.ok)
    return NextResponse.json(
      { error: { message: result.message }, detail: result.detail },
      { status: result.status },
    );
  return NextResponse.json(
    { data: result.data, meta: { trace_id: result.traceId, total: result.total } },
    { status: result.status },
  );
}

export const GET = (request: Request, context: Context) => handle(request, context, "GET");
export const POST = (request: Request, context: Context) => handle(request, context, "POST");
export const PUT = (request: Request, context: Context) => handle(request, context, "PUT");
export const DELETE = (request: Request, context: Context) => handle(request, context, "DELETE");
