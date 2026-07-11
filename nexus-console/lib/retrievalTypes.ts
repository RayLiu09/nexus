/**
 * Shared re-export of M-C v1.3 retrieval wire types.
 *
 * Source of truth is currently `app/search/_lib/searchTypes.ts` (the
 * existing `/search` playground defined them first). This module lets
 * `/retrieval-test` (and any future consumer) depend on a stable
 * `@/lib` path without deep-importing route-scoped files. A future PR
 * (see `docs/retrieval/m_c_report.md` §7 Follow-ups) will invert the
 * relationship: canonical here, re-exported from the route.
 */
export type {
  KnowledgeRetrievalResponse,
  KnowledgeTypeOption,
  RetrievalClarification,
  RetrievalConversationStep,
  RetrievalIntent,
  RetrievalPlan,
  RetrievalResult,
  RetrievalSourceRef,
  RetrievalStatus,
  RetrievalStepStatus,
  RetrievalSubQuery,
  RetrievalSummary,
} from "@/app/search/_lib/searchTypes";
