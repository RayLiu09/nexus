"use client";

import { Tabs, Tag } from "antd";
import type { TabsProps } from "antd";
import { LineageTab } from "./LineageTab";
import { AIGovernanceTab } from "./AIGovernanceTab";
import { QualityTab } from "./QualityTab";
import { VersionsTab } from "./VersionsTab";
import type {
  DocumentAsset,
  DocumentVersion,
  NormalizedAssetRef,
  ParseArtifact,
  AIGovernanceRun,
} from "@/lib/api";

type Props = {
  asset: DocumentAsset | null;
  latestVersion: DocumentVersion | null;
  latestRef: NormalizedAssetRef | null;
  relatedArtifact: ParseArtifact | null;
  versions: DocumentVersion[];
  governanceRuns: AIGovernanceRun[];
};

export function AssetDetailTabs({
  asset,
  latestVersion,
  latestRef,
  relatedArtifact,
  versions,
  governanceRuns,
}: Props) {
  const aiBadge = governanceRuns.length > 0 ? governanceRuns.length : undefined;

  const tabItems: TabsProps["items"] = [
    {
      key: "lineage",
      label: "血缘追溯",
      children: (
        <LineageTab
          asset={asset}
          latestVersion={latestVersion}
          latestRef={latestRef}
          relatedArtifact={relatedArtifact}
        />
      ),
    },
    {
      key: "ai-governance",
      label: (
        <span>
          AI 治理
          {aiBadge != null && (
            <Tag color="blue" className="ml-1 text-[10px] leading-4 px-1">
              {aiBadge}
            </Tag>
          )}
        </span>
      ),
      children: <AIGovernanceTab runs={governanceRuns} />,
    },
    {
      key: "quality",
      label: "质量评分",
      children: <QualityTab runs={governanceRuns} />,
    },
    {
      key: "versions",
      label: "版本历史",
      children: <VersionsTab versions={versions} />,
    },
  ];

  return <Tabs items={tabItems} className="mt-4" />;
}
