import { PageHeader } from "@/components/PageHeader";
import TagReviewContent from "./_components/TagReviewContent";
import { toTagReviewData } from "./_lib/tagReviewData";
import { Button } from "antd";
import { getApiData, type AIGovernanceRun } from "@/lib/api";

const MAX_PAGE_SIZE = "100"; // backend pagination cap
import { buildTagDictionary, type TagDictionaryEntry } from "@/lib/tagLabels";

export const dynamic = "force-dynamic";

/** Thin subset of backend AssetCatalogRead needed for ref→title fallback. */
interface AssetCatalogEntry {
  id: string;
  title: string;
  current_normalized_ref_id?: string | null;
  latest_normalized_ref_id?: string | null;
}

interface AssetLookup {
  title: string | null;
  assetId: string | null;
}

/**
 * Fallback resolver: governance runs now carry `asset_title`/`asset_id`
 * directly (see `_serialize_run` in nexus-api), but older or chain-broken
 * runs may still be missing those. The asset catalog supplies a cheap
 * map from current/latest normalized_ref_id → (title, asset_id) without
 * touching object storage.
 */
async function buildAssetLookupMap(refIds: Iterable<string>): Promise<Map<string, AssetLookup>> {
  const lookup = new Map<string, AssetLookup>();
  const needed = new Set(refIds);
  if (needed.size === 0) return lookup;

  const result = await getApiData<AssetCatalogEntry[]>("/internal/v1/assets", [], {
    pageSize: MAX_PAGE_SIZE,
  });
  if (!result.ok || !Array.isArray(result.data)) return lookup;

  for (const asset of result.data) {
    const entry: AssetLookup = { title: asset.title, assetId: asset.id };
    if (asset.current_normalized_ref_id) {
      lookup.set(asset.current_normalized_ref_id, entry);
    }
    if (asset.latest_normalized_ref_id) {
      lookup.set(asset.latest_normalized_ref_id, entry);
    }
  }

  return lookup;
}

function enrich<
  T extends { normalizedRefId: string; assetId?: string | null; assetTitle?: string | null },
>(rows: T[], lookup: Map<string, AssetLookup>): T[] {
  return rows.map((r) => {
    if (r.assetId && r.assetTitle) return r;
    const hit = lookup.get(r.normalizedRefId);
    if (!hit) return r;
    return {
      ...r,
      assetId: r.assetId ?? hit.assetId,
      assetTitle: r.assetTitle ?? hit.title,
    };
  });
}

export default async function TagReviewPage() {
  const [result, rulesResult] = await Promise.all([
    getApiData<AIGovernanceRun[]>("/internal/v1/ai/governance-runs", [], {
      pageSize: MAX_PAGE_SIZE,
    }),
    getApiData<{ tags?: TagDictionaryEntry[] }>("/internal/v1/admin/governance-rules", {}),
  ]);
  const tagDictionary = buildTagDictionary(rulesResult.data.tags);
  const data = toTagReviewData(result.data);

  // Only hit the asset catalog if some rows still need enrichment after the
  // backend join (keeps the page snappy when chains are intact).
  const missing = [
    ...data.drafts.filter((d) => !d.assetId || !d.assetTitle).map((d) => d.normalizedRefId),
    ...data.committed.filter((c) => !c.assetId || !c.assetTitle).map((c) => c.normalizedRefId),
  ];
  const lookup =
    missing.length > 0 ? await buildAssetLookupMap(missing) : new Map<string, AssetLookup>();

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
        initialDrafts={enrich(data.drafts, lookup)}
        initialCommitted={enrich(data.committed, lookup)}
        ok={result.ok}
        error={result.error}
        traceId={result.traceId}
        tagDictionary={tagDictionary}
      />
    </>
  );
}
