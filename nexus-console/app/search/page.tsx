import { PageHeader } from "@/components/PageHeader";
import { Alert } from "antd";
import { fetchGovernanceRules } from "@/lib/governance-rules-api";
import { SearchPlayground } from "./_components/SearchPlayground";
import type { KnowledgeTypeOption } from "./_lib/searchTypes";

export const dynamic = "force-dynamic";

interface KnowledgeTypeEntry {
  code: string;
  name: string;
}

async function loadKnowledgeTypes(): Promise<{
  knowledgeTypes: KnowledgeTypeOption[];
  warning: string | null;
}> {
  const res = await fetchGovernanceRules();
  if (!res.ok) {
    return { knowledgeTypes: [], warning: `无法加载知识类型：${res.error}` };
  }
  const rules = res.data as Record<string, unknown>;
  const rawList = Array.isArray(rules.knowledge_types)
    ? (rules.knowledge_types as unknown[])
    : [];
  const knowledgeTypes: KnowledgeTypeOption[] = [];
  for (const raw of rawList) {
    if (!raw || typeof raw !== "object") continue;
    const obj = raw as Record<string, unknown>;
    const code = typeof obj.code === "string" ? obj.code : null;
    if (!code) continue;
    knowledgeTypes.push({
      code,
      name: typeof obj.name === "string" ? obj.name : code,
    } satisfies KnowledgeTypeEntry);
  }
  return { knowledgeTypes, warning: null };
}

export default async function SearchPage() {
  const { knowledgeTypes, warning } = await loadKnowledgeTypes();

  return (
    <>
      <PageHeader
        eyebrow="访问与审计 — 检索与问答验证"
        title="检索验证"
        description="消费侧验证页面：通过运维 caller key 调用 /v1/search 与 /v1/qa，验证 KB 路由、相似度过滤与引用追溯。"
      />

      {warning && (
        <Alert type="warning" showIcon className="mb-4" title={warning} />
      )}

      <SearchPlayground knowledgeTypes={knowledgeTypes} />
    </>
  );
}
