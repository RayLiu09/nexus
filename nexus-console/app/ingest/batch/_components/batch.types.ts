export interface BatchDetail {
  id: string;
  status: string;
  batch_status_detail: Record<string, string>;
  summary: Record<string, unknown>;
  updated_at: string;
}

export interface BatchSubmitItem {
  raw_object_id: string;
  job_id: string;
  job_status: string;
  file_idempotency_key: string;
  duplicate: boolean;
}

export interface BatchSubmitResult {
  batch: { id: string; status: string };
  items: BatchSubmitItem[];
}

export type BatchProxySuccess = {
  ok: true;
  status: number;
  data: BatchDetail;
  traceId: string | null;
};

export type BatchProxyError = {
  ok: false;
  status: number;
  message: string;
};

export type BatchProxyResult = BatchProxySuccess | BatchProxyError;

export type BatchSubmitProxySuccess = {
  ok: true;
  status: number;
  data: BatchSubmitResult;
  traceId: string | null;
};

export type BatchSubmitProxyResult = BatchSubmitProxySuccess | BatchProxyError;

export interface SelectedFile {
  key: string;
  name: string;
  size: number;
  type: string;
  base64: string;
}
