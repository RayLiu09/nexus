import { PageHeader } from "@/components/PageHeader";
import TagReviewContent from "./_components/TagReviewContent";
import { toTagReviewData } from "./_lib/tagReviewData";
import { Button } from "antd";
import { getApiData, type AIGovernanceRun } from "@/lib/api";

const MAX_PAGE_SIZE = "100"; // backend pagination cap
import { buildTagDictionary, type TagDictionaryEntry } from "@/lib/tagLabels";

export const dynamic = "force-dynamic";

/** Thin subset of backend AssetCatalogRead needed for ref→title mapping. */
interface AssetCatalogEntry {
  id: string;
  title: string;
  current_normalized_ref_id?: string | null;
  latest_normalized_ref_id?: string | null;
}

/**
 * Resolve asset titles for committed tags by mapping normalized_ref_id → asset title.
 *
 * Uses the asset listing endpoint (single call, no S3 reads) instead of
 * the content endpoint (N calls, each hitting object storage). Builds a
 * bi-directional map from both current_ref and latest_ref to the asset title.
 */
async function buildAssetNameMap(
  committed: { normalizedRefId: string }[],
): Promise<Map<string, string>> {
  const nameMap = new Map<string, string>();
  if (committed.length === 0) return nameMap;

  const result = await getApiData<AssetCatalogEntry[]>(
    "/internal/v1/assets",
    [],
    { pageSize: MAX_PAGE_SIZE },
  );
  if (!result.ok || !Array.isArray(result.data)) return nameMap;

  for (const asset of result.data) {
    if (asset.current_normalized_ref_id) {
      nameMap.set(asset.current_normalized_ref_id, asset.title);
    }
    if (asset.latest_normalized_ref_id) {
      nameMap.set(asset.latest_normalized_ref_id, asset.title);
    }
  }

  return nameMap;
}

export default async function TagReviewPage() {
  const [result, rulesResult] = await Promise.all([
    getApiData<AIGovernanceRun[]>("/internal/v1/ai/governance-runs", [], { pageSize: MAX_PAGE_SIZE }),
    getApiData<{ tags?: TagDictionaryEntry[] }>("/internal/v1/admin/governance-rules", {}),
  ]);
  const tagDictionary = buildTagDictionary(rulesResult.data.tags);
  const data = toTagReviewData(result.data);

  // Resolve asset names for committed history
  const assetNameMap = await buildAssetNameMap(data.committed);
  const committedWithNames = data.committed.map((c) => ({
    ...c,
    assetTitle: assetNameMap.get(c.normalizedRefId),
  }));

  return (
    <>
      <PageHeader
        eyebrow="资产与治理 — normalized asset 标签运营"
        title="标签审核"
        description="标签生成在 metadata_enrich 阶段针对 normalized asset 执行。页面读取真实 AI 治理运行记录，高置信自动提交，低置信进入人工审核。"
        actions={
          <Button type="primary" href="/governance">
            返回治理中心
          </Button>
        }
      />
      <TagReviewContent
        initialDrafts={data.drafts}
        initialCommitted={committedWithNames}
        ok={result.ok}
        error={result.error}
        traceId={result.traceId}
        tagDictionary={tagDictionary}
      />
    </>
  );
}
