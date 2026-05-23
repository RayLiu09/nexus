/** 与 /api/search 路由的响应对齐（见 nexus-console/app/api/search/route.ts） */
export interface SearchChunkSource {
  doc_id?: string;
  doc_name?: string;
  page?: number;
  normalized_ref_id?: string;
  [k: string]: unknown;
}

export interface SearchChunk {
  chunk_id: string;
  content: string;
  score: number;
  source: SearchChunkSource;
  [k: string]: unknown;
}

export interface SearchResponse {
  query: string;
  kb: string | null;
  results: SearchChunk[];
  count: number;
  caller_id: string;
}

/** 与 /api/qa 对齐 */
export interface QaSource {
  doc_id?: string;
  doc_name?: string;
  chunk_id?: string;
  content?: string;
  page?: number;
  normalized_ref_id?: string;
  [k: string]: unknown;
}

export interface QaResponse {
  question: string;
  kb: string | null;
  caller_id: string;
  answer: string;
  sources: QaSource[];
}

/** 知识类型选项（仅展示 code + name，足以渲染 Select） */
export interface KnowledgeTypeOption {
  code: string;
  name: string;
}
