import { PageHeader } from "@/components/PageHeader";
import { fetchGovernanceRules } from "@/lib/governance-rules-api";
import { SearchPlayground } from "./_components/SearchPlayground";
import type { KnowledgeTypeOption } from "./_lib/searchTypes";

export const dynamic = "force-dynamic";

const FALLBACK_KNOWLEDGE_TYPES: KnowledgeTypeOption[] = [
  { code: "textbook_kb", name: "教材知识库" },
];

interface KnowledgeTypeEntry {
  code: string;
  name: string;
}

async function loadKnowledgeTypes(): Promise<{
  knowledgeTypes: KnowledgeTypeOption[];
}> {
  const res = await fetchGovernanceRules();
  if (!res.ok) {
    return { knowledgeTypes: FALLBACK_KNOWLEDGE_TYPES };
  }
  const rules = res.data as Record<string, unknown>;
  const rawList = Array.isArray(rules.knowledge_types) ? (rules.knowledge_types as unknown[]) : [];
  const knowledgeTypes = new Map<string, KnowledgeTypeOption>(
    FALLBACK_KNOWLEDGE_TYPES.map((item) => [item.code, item]),
  );
  for (const raw of rawList) {
    if (!raw || typeof raw !== "object") continue;
    const obj = raw as Record<string, unknown>;
    const code = typeof obj.code === "string" ? obj.code : null;
    if (!code) continue;
    knowledgeTypes.set(code, {
      code,
      name: typeof obj.name === "string" ? obj.name : code,
    } satisfies KnowledgeTypeEntry);
  }
  return { knowledgeTypes: [...knowledgeTypes.values()] };
}

export default async function SearchPage() {
  const { knowledgeTypes } = await loadKnowledgeTypes();

  return (
    <>
      <PageHeader
        eyebrow="访问与审计 — 检索/召回验证"
        title="检索召回对话验证"
        description="以对话窗口呈现 v1.0 检索/召回流程，展示意图识别、问题转化、并行检索、上下文组装和 Markdown 结果生成的执行过程与辅助分析。"
      />
      <SearchPlayground knowledgeTypes={knowledgeTypes} />
    </>
  );
}
