import { readFile } from "node:fs/promises";
import path from "node:path";

import { PageHeader } from "@/components/PageHeader";

import { RetrievalTestPanel } from "./_components/RetrievalTestPanel";
import type { FixturePreset, FixtureManifest } from "./_components/fixtures.types";

export const dynamic = "force-dynamic";

async function loadFixtures(): Promise<FixturePreset[]> {
  // Fixtures live under `public/` so browsers could also fetch them, but
  // we read from disk here so the RSC can hydrate the panel with the
  // list on first paint (no client waterfall).
  try {
    const filePath = path.join(process.cwd(), "public", "retrieval-fixtures.json");
    const raw = await readFile(filePath, "utf-8");
    const parsed = JSON.parse(raw) as FixtureManifest;
    if (!Array.isArray(parsed.presets)) return [];
    return parsed.presets;
  } catch {
    // Missing file is a soft failure — panel still works with free-form query.
    return [];
  }
}

export default async function RetrievalTestPage() {
  const presets = await loadFixtures();

  return (
    <>
      <PageHeader
        eyebrow="访问与审计 — M-C v1.3 联调"
        title="检索联调面板"
        description="内部研发/治理侧使用。跑真实 RetrievalOrchestrator（intent → planner → executors → DAG → rerank → summary），把每一层分区展示，方便对拍 golden case 与排查回归。"
      />
      <RetrievalTestPanel presets={presets} />
    </>
  );
}
