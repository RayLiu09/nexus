"use client";

import { Card, Empty, Steps } from "antd";
import {
  FileTextOutlined,
  CodeOutlined,
  FileSearchOutlined,
  DatabaseOutlined,
} from "@ant-design/icons";
import { StatusLabel } from "@/components/StatusLabel";
import {
  shortId,
  type Asset,
  type AssetVersion,
  type NormalizedAssetRef,
  type ParseArtifact,
} from "@/lib/api";

type Props = {
  asset: Asset | null;
  latestVersion: AssetVersion | null;
  latestRef: NormalizedAssetRef | null;
  relatedArtifact: ParseArtifact | null;
};

export function LineageTab({ asset, latestVersion, latestRef, relatedArtifact }: Props) {
  const hasData = latestVersion || relatedArtifact || latestRef;

  return (
    <div className="grid gap-4">
      {/* Flow diagram */}
      <Card
        title="处理链路"
        extra={<span className="text-xs text-muted">raw → parse → normalize → asset</span>}
      >
        <Steps
          size="small"
          current={asset?.status === "available" ? 4 : relatedArtifact ? 3 : latestVersion ? 2 : 1}
          items={[
            {
              title: "Raw Object",
              content: latestVersion ? shortId(latestVersion.raw_object_id) : undefined,
              icon: <FileTextOutlined />,
            },
            {
              title: "Parse Artifact",
              content: relatedArtifact?.parse_mode,
              icon: <CodeOutlined />,
            },
            {
              title: "Normalized",
              content: latestRef?.normalized_type,
              icon: <FileSearchOutlined />,
            },
            {
              title: "Asset",
              content: asset?.status,
              icon: <DatabaseOutlined />,
            },
          ]}
        />
      </Card>

      {/* Detail table */}
      {hasData ? (
        <Card title="链路明细" styles={{ body: { padding: 0 } }}>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--line)] text-xs text-muted uppercase tracking-wide">
                  <th className="text-left p-3 w-24">层级</th>
                  <th className="text-left p-3 w-36">对象ID</th>
                  <th className="text-left p-3">URI / 校验</th>
                  <th className="text-left p-3 w-28">状态</th>
                </tr>
              </thead>
              <tbody>
                {latestVersion && (
                  <tr className="border-b border-[var(--line)]">
                    <td className="p-3 font-semibold">版本</td>
                    <td className="p-3 font-mono text-xs">{shortId(latestVersion.id)}</td>
                    <td className="p-3 font-mono text-xs">{latestVersion.source_checksum}</td>
                    <td className="p-3"><StatusLabel value={latestVersion.version_status} /></td>
                  </tr>
                )}
                {relatedArtifact && (
                  <tr className="border-b border-[var(--line)]">
                    <td className="p-3 font-semibold">解析产物</td>
                    <td className="p-3 font-mono text-xs">{shortId(relatedArtifact.id)}</td>
                    <td className="p-3 font-mono text-xs">{relatedArtifact.artifact_uri}</td>
                    <td className="p-3"><StatusLabel value={relatedArtifact.status} /></td>
                  </tr>
                )}
                {latestRef && (
                  <tr className="border-b border-[var(--line)]">
                    <td className="p-3 font-semibold">标准化引用</td>
                    <td className="p-3 font-mono text-xs">{shortId(latestRef.id)}</td>
                    <td className="p-3 font-mono text-xs">{latestRef.object_uri}</td>
                    <td className="p-3"><StatusLabel value={latestRef.status} /></td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </Card>
      ) : (
        <Empty description="暂无血缘数据 — 继续完成接入和标准化流水线以生成完整血缘链路" />
      )}
    </div>
  );
}
