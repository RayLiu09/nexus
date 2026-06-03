/**
 * Route handler: POST /api/ingest/files/multi
 *
 * Forwards a multi-file ingest payload to the backend POST /v1/ingest/files/multi
 * endpoint. Keeps the backend base URL on the server.
 */
import { NextResponse } from "next/server";

import { ingestProxyPost } from "@/lib/ingestProxy";

export const dynamic = "force-dynamic";

interface MultiFileItem {
  file_idempotency_key: string;
  filename: string;
  content_base64: string;
  content_type?: string;
  source_uri?: string | null;
}

interface MultiFilePayload {
  data_source_id: string;
  batch_idempotency_key: string;
  owner_user_id?: string | null;
  files: MultiFileItem[];
}

interface MultiFileResult {
  batch: { id: string; status: string };
  items: Array<{
    raw_object_id: string;
    job_id: string;
    job_status: string;
    file_idempotency_key: string;
    duplicate: boolean;
  }>;
}

export async function POST(request: Request): Promise<NextResponse> {
  let payload: MultiFilePayload;
  try {
    payload = (await request.json()) as MultiFilePayload;
  } catch (err) {
    return NextResponse.json(
      {
        ok: false,
        status: 400,
        message: `请求体不是有效 JSON：${err instanceof Error ? err.message : String(err)}`,
      },
      { status: 400 },
    );
  }
  const result = await ingestProxyPost<MultiFileResult>("/v1/ingest/files/multi", payload);
  return NextResponse.json(result, { status: result.ok ? 202 : result.status });
}
