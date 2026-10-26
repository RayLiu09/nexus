import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { apiBaseUrl } from "@/lib/api";

export async function POST(request: Request): Promise<Response> {
  const token = (await cookies()).get("nexus_access_token")?.value;
  if (!token) return NextResponse.json({ error: { message: "请重新登录后操作" } }, { status: 401 });
  const form = await request.formData();
  const file = form.get("file");
  if (!(file instanceof File))
    return NextResponse.json({ error: { message: "请选择 Excel 文件" } }, { status: 422 });
  if (file.size > 10 * 1024 * 1024)
    return NextResponse.json({ error: { message: "文件不能超过 10 MiB" } }, { status: 413 });
  try {
    const headers: Record<string, string> = { authorization: `Bearer ${token}` };
    const key = request.headers.get("idempotency-key");
    if (key) headers["idempotency-key"] = key;
    const upstream = await fetch(`${apiBaseUrl()}/internal/v1/major-offerings/import`, {
      method: "POST", headers, body: form, cache: "no-store",
    });
    return new Response(upstream.body, {
      status: upstream.status,
      headers: { "content-type": "application/json", "cache-control": "no-store" },
    });
  } catch {
    return NextResponse.json({ error: { message: "导入服务暂不可用，请重试" } }, { status: 502 });
  }
}
