"use client";

import { useEffect, useState } from "react";
import { Empty, Segmented, Skeleton, Tree } from "antd";
import { ChunkListSection } from "./ChunkListSection";
import { CapabilityGraphView } from "./CapabilityGraphView";
import {
  resolveTeachingStandardDirectory,
  type TeachingStandardDirectoryNode,
  type TeachingStandardTocItem,
} from "./teachingStandardDirectory";
import type { NormalizedBlock } from "@/lib/chunkTypes";

type View = "chunks" | "directory" | "graph";

export function TeachingStandardKnowledgeView({ normalizedRefId }: { normalizedRefId: string }) {
  const [view, setView] = useState<View>("chunks");
  const [directory, setDirectory] = useState<TeachingStandardDirectoryNode[]>([]);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    if (view !== "directory") return;
    setLoading(true);
    fetch(`/api/normalized-refs/${encodeURIComponent(normalizedRefId)}/content`, {
      cache: "no-store",
    })
      .then((response) => response.json())
      .then((body) => {
        const toc = Array.isArray(body?.data?.toc)
          ? (body.data.toc as TeachingStandardTocItem[])
          : [];
        const blocks = Array.isArray(body?.data?.blocks)
          ? (body.data.blocks as NormalizedBlock[])
          : [];
        setDirectory(resolveTeachingStandardDirectory(toc, blocks));
      })
      .catch(() => setDirectory([]))
      .finally(() => setLoading(false));
  }, [normalizedRefId, view]);
  return (
    <div className="flex flex-col gap-4">
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
      {view === "directory" && !loading && directory.length === 0 ? (
        <Empty description="该教学标准暂未提取目录" />
      ) : null}
      {view === "directory" && !loading && directory.length > 0 ? (
        <Tree treeData={directory} defaultExpandAll />
      ) : null}
      {view === "graph" ? (
        <CapabilityGraphView
          normalizedRefId={normalizedRefId}
          buildType="teaching_standard"
          title="岗位知识图谱"
        />
      ) : null}
    </div>
  );
}
