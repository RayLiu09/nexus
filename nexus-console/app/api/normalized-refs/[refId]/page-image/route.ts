/**
 * Route handler: GET /api/normalized-refs/:refId/page-image?page=&bbox=
 *
 * Binary proxy for backend-rendered source PDF page images with optional bbox
 * overlay. Used by the chunk preview drawer's page-side panel.
 */
import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { apiBaseUrl } from "@/lib/api";

export const dynamic = "force-dynamic";

export async function GET(
  request: Request,
  context: { params: Promise<{ refId: string }> },
): Promise<Response> {
  const { refId } = await context.params;
  if (!refId) {
    return NextResponse.json(
      { ok: false, status: 400, message: "ref_id 不能为空" },
      { status: 400 },
    );
  }

  const store = await cookies();
  const token = store.get("nexus_access_token")?.value;
  if (!token) {
    return NextResponse.json(
      { ok: false, status: 401, message: "未找到有效的访问令牌，请重新登录。" },
      { status: 401 },
    );
  }

  const url = new URL(request.url);
  const backendParams = new URLSearchParams();
  const page = url.searchParams.get("page");
  if (page) backendParams.set("page", page);
  const bbox = url.searchParams.get("bbox");
  if (bbox) backendParams.set("bbox", bbox);
  const query = backendParams.toString();

  let upstream: Response;
  try {
    upstream = await fetch(
      `${apiBaseUrl()}/internal/v1/normalized-refs/${encodeURIComponent(refId)}/page-image${query ? `?${query}` : ""}`,
      {
        method: "GET",
        headers: { authorization: `Bearer ${token}` },
        cache: "no-store",
      },
    );
  } catch (err) {
    return NextResponse.json(
      {
        ok: false,
        status: 502,
        message: `调用 NEXUS 后端失败：${err instanceof Error ? err.message : String(err)}`,
      },
      { status: 502 },
    );
  }

  if (!upstream.ok) {
    const text = await upstream.text();
    let message = `后端返回 HTTP ${upstream.status}`;
    try {
      const body = JSON.parse(text) as { error?: { message?: string }; detail?: string };
      message = body.error?.message ?? body.detail ?? message;
    } catch {
      if (text) message = text.slice(0, 200);
    }
    return NextResponse.json(
      { ok: false, status: upstream.status, message },
      { status: upstream.status },
    );
  }

  const body = await upstream.arrayBuffer();
  return new Response(body, {
    status: upstream.status,
    headers: {
      "content-type": upstream.headers.get("content-type") ?? "image/png",
      "cache-control": "no-store",
    },
  });
}
