"use client";

import { useState } from "react";
import { Segmented } from "antd";

import { ChunkListSection } from "./ChunkListSection";
import { EvidenceGraphView } from "./EvidenceGraphView";
import type { NormalizedAssetRef } from "@/lib/api";
import { shouldShowEvidenceGraph } from "@/lib/evidenceGraphAdmission";

type Props = {
  normalizedRef: NormalizedAssetRef | null;
  classification?: string | null;
};

type ViewKey = "chunks" | "evidence_graph";

const CHUNK_VIEW_OPTION = { label: "RAG知识块", value: "chunks" as const };
const EVIDENCE_GRAPH_VIEW_OPTION = { label: "Evidence Graph", value: "evidence_graph" as const };
export function DocumentKnowledgeView({ normalizedRef, classification = null }: Props) {
  const [view, setView] = useState<ViewKey>("chunks");
  const normalizedRefId = normalizedRef?.id ?? null;
  const showEvidenceGraph = shouldShowEvidenceGraph(null, classification);

  const viewOptions: Array<{ label: string; value: ViewKey }> = [
    CHUNK_VIEW_OPTION,
    ...(showEvidenceGraph ? [EVIDENCE_GRAPH_VIEW_OPTION] : []),
  ];

  const activeView = showEvidenceGraph ? view : "chunks";

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-end gap-3">
        <Segmented
          value={activeView}
          onChange={(value) => setView(value as ViewKey)}
          options={viewOptions}
          aria-label="切换文档知识块视图"
        />
      </div>

      {activeView === "chunks" ? (
        <ChunkListSection
          refId={normalizedRefId}
          title="RAG知识块"
          emptyDescription="该 ref 暂未生成 RAG 语义知识块。"
          mode="preview"
          actionLabel="定位原文"
        />
      ) : null}
      {activeView === "evidence_graph" && showEvidenceGraph ? (
        <EvidenceGraphView normalizedRef={normalizedRef} />
      ) : null}
    </div>
  );
}
