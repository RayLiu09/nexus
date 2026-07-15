"use client";

import { useEffect, useState } from "react";
import { Empty, Segmented, Skeleton, Tree } from "antd";
import type { DataNode } from "antd/es/tree";
import { ChunkListSection } from "./ChunkListSection";
import { CapabilityGraphView } from "./CapabilityGraphView";

type View = "chunks" | "directory" | "graph";
type TocItem = { title?: string; text?: string; children?: TocItem[] };

export function TeachingStandardKnowledgeView({ normalizedRefId }: { normalizedRefId: string }) {
  const [view, setView] = useState<View>("chunks");
  const [toc, setToc] = useState<TocItem[]>([]);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    if (view !== "directory") return;
    setLoading(true);
    fetch(`/api/normalized-refs/${encodeURIComponent(normalizedRefId)}/content`, { cache: "no-store" })
      .then((r) => r.json()).then((body) => setToc(Array.isArray(body?.data?.toc) ? body.data.toc : []))
      .finally(() => setLoading(false));
  }, [normalizedRefId, view]);
  return <div className="flex flex-col gap-4">
    <div className="flex justify-end">
      <Segmented
        value={view}
        onChange={(value) => setView(value as View)}
        options={[
          { label: "知识块", value: "chunks" },
          { label: "目录", value: "directory" },
          { label: "岗位知识图谱", value: "graph" },
        ]}
        aria-label="切换专业教学标准知识视图"
      />
    </div>
    {view === "chunks" ? (
      <ChunkListSection
        refId={normalizedRefId}
        title="知识块"
        emptyDescription="该教学标准暂未生成语义知识块。"
        mode="preview"
        actionLabel="定位原文"
        knowledgeTypeCode="course_standard_authoring_process"
      />
    ) : null}
    {view === "directory" && loading ? <Skeleton active paragraph={{ rows: 8 }} /> : null}
    {view === "directory" && !loading && toc.length === 0 ? <Empty description="该教学标准暂未提取目录" /> : null}
    {view === "directory" && !loading && toc.length > 0 ? <Tree treeData={tocToTree(toc)} defaultExpandAll /> : null}
    {view === "graph" ? (
      <CapabilityGraphView
        normalizedRefId={normalizedRefId}
        buildType="teaching_standard"
        title="岗位知识图谱"
      />
    ) : null}
  </div>;
}

function tocToTree(items: TocItem[], prefix = "section"): DataNode[] {
  return items.map((item, index) => {
    const key = `${prefix}-${index}`;
    const children = Array.isArray(item.children) ? tocToTree(item.children, key) : [];
    return {
      key,
      title: item.title ?? item.text ?? "未命名章节",
      ...(children.length > 0 ? { children } : {}),
    };
  });
}
