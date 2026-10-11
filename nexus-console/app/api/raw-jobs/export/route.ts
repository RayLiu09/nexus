import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { apiBaseUrl } from "@/lib/api";

export const dynamic = "force-dynamic";

export async function GET(request: Request): Promise<Response> {
  const token = (await cookies()).get("nexus_access_token")?.value;
  if (!token) {
    return NextResponse.json({ error: { message: "请重新登录后导出" } }, { status: 401 });
  }

  const params = new URLSearchParams();
  const incoming = new URL(request.url).searchParams;
  for (const key of ["q", "industry"]) {
    const value = incoming.get(key)?.trim();
    if (value) params.set(key, value);
  }
  let upstream: Response;
  try {
    upstream = await fetch(
      `${apiBaseUrl()}/internal/v1/raw-jobs/export${params.size ? `?${params}` : ""}`,
      { headers: { authorization: `Bearer ${token}` }, cache: "no-store" },
    );
  } catch {
    return NextResponse.json({ error: { message: "导出服务暂不可用" } }, { status: 502 });
  }
  if (!upstream.ok) {
    const body = await upstream.json().catch(() => ({})) as { detail?: string; error?: { message?: string } };
    return NextResponse.json(
      { error: { message: body.error?.message ?? body.detail ?? "导出失败" } },
      { status: upstream.status },
    );
  }
  return new Response(upstream.body, {
    headers: {
      "content-type": upstream.headers.get("content-type") ?? "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      "content-disposition": upstream.headers.get("content-disposition") ?? "attachment; filename=raw-jobs.xlsx",
      "cache-control": "no-store",
    },
  });
}
