/**
 * Catch-all proxy for /api/admin/governance-prompts/*
 *
 * Routes to /internal/v1/admin/governance-prompts/...
 *
 * Supported patterns:
 *   GET  /api/admin/governance-prompts                  → list all templates
 *   GET  /api/admin/governance-prompts/{template_id}    → get single template
 *   PUT  /api/admin/governance-prompts/{task_type}/active → update active template
 *   POST /api/admin/governance-prompts/{template_id}/disable → disable template
 */
import { NextResponse } from "next/server";

import { proxy } from "@/lib/api/proxy";

export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ path?: string[] }> },
): Promise<NextResponse> {
  const { path } = await params;
  const suffix = path?.length ? `/${path.join("/")}` : "";
  const result = await proxy<unknown>(
    `/internal/v1/admin/governance-prompts${suffix}`,
  );
  return NextResponse.json(result, { status: result.ok ? 200 : result.status });
}

export async function PUT(
  request: Request,
  { params }: { params: Promise<{ path?: string[] }> },
): Promise<NextResponse> {
  const { path } = await params;
  const suffix = path?.length ? `/${path.join("/")}` : "";
  const body = await request.json().catch(() => null);
  if (body === null) {
    return NextResponse.json(
      { ok: false, status: 400, message: "请求体不是合法 JSON" },
      { status: 400 },
    );
  }
  const result = await proxy<unknown>(
    `/internal/v1/admin/governance-prompts${suffix}`,
    { method: "PUT", body },
  );
  return NextResponse.json(result, { status: result.ok ? 200 : result.status });
}

export async function POST(
  request: Request,
  { params }: { params: Promise<{ path?: string[] }> },
): Promise<NextResponse> {
  const { path } = await params;
  const suffix = path?.length ? `/${path.join("/")}` : "";
  const body = await request.json().catch(() => undefined);
  const result = await proxy<unknown>(
    `/internal/v1/admin/governance-prompts${suffix}`,
    { method: "POST", body },
  );
  return NextResponse.json(result, { status: result.ok ? 200 : result.status });
}
