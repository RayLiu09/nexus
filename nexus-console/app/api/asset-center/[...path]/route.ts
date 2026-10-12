import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { apiBaseUrl } from "@/lib/api";

export const dynamic = "force-dynamic";

export async function GET(
  request: Request,
  context: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  const token = (await cookies()).get("nexus_access_token")?.value;
  if (!token) return NextResponse.json({ error: { message: "请重新登录后操作" } }, { status: 401 });
  const { path } = await context.params;
  const suffix = path.join("/");
  const incoming = new URL(request.url);
  const upstream = await fetch(`${apiBaseUrl()}/internal/v1/${suffix}${incoming.search}`, {
    headers: { authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!upstream.ok)
    return NextResponse.json(
      await upstream.json().catch(() => ({ error: { message: "请求失败" } })),
      { status: upstream.status },
    );
  if (suffix.endsWith("/export"))
    return new Response(upstream.body, {
      headers: {
        "content-type": upstream.headers.get("content-type") ?? "application/octet-stream",
        "content-disposition": upstream.headers.get("content-disposition") ?? "attachment",
        "cache-control": "no-store",
      },
    });
  return new Response(upstream.body, {
    headers: {
      "content-type": upstream.headers.get("content-type") ?? "application/json",
      "cache-control": "no-store",
    },
  });
}
