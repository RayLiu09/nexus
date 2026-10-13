import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { apiBaseUrl } from "@/lib/api";

export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  context: { params: Promise<{ refId: string; blockId: string; imageIndex: string }> },
): Promise<Response> {
  const { refId, blockId, imageIndex } = await context.params;
  if (!refId || !blockId || !/^\d+$/.test(imageIndex)) {
    return NextResponse.json({ message: "图片定位无效" }, { status: 400 });
  }

  const token = (await cookies()).get("nexus_access_token")?.value;
  if (!token) {
    return NextResponse.json({ message: "请重新登录" }, { status: 401 });
  }

  let upstream: Response;
  try {
    upstream = await fetch(
      `${apiBaseUrl()}/internal/v1/normalized-refs/${encodeURIComponent(refId)}/blocks/${encodeURIComponent(blockId)}/images/${imageIndex}`,
      { headers: { authorization: `Bearer ${token}` }, cache: "no-store" },
    );
  } catch {
    return NextResponse.json({ message: "图片服务暂不可用" }, { status: 502 });
  }

  if (!upstream.ok) {
    return NextResponse.json({ message: "图片加载失败" }, { status: upstream.status });
  }
  return new Response(upstream.body, {
    status: 200,
    headers: {
      "content-type": upstream.headers.get("content-type") ?? "application/octet-stream",
      "cache-control": "private, max-age=300",
      "x-content-type-options": "nosniff",
    },
  });
}
