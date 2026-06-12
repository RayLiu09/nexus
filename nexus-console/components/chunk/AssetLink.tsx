/**
 * AssetLink — icon button to open the asset detail page in a new tab.
 */
import { ExportOutlined } from "@ant-design/icons";
import { Tooltip } from "antd";

export interface AssetLinkProps {
  assetId: string | undefined;
}

export function AssetLink({ assetId }: AssetLinkProps) {
  if (!assetId) {
    return (
      <Tooltip title="该 chunk 未绑定资产，无法跳转">
        <span
          aria-hidden="true"
          className="inline-flex h-5 w-5 items-center justify-center text-gray-300"
        >
          <ExportOutlined />
        </span>
      </Tooltip>
    );
  }
  return (
    <Tooltip title={`查看资产 ${assetId} 详情`}>
      <a
        href={`/assets/${encodeURIComponent(assetId)}`}
        target="_blank"
        rel="noopener noreferrer"
        aria-label={`查看资产 ${assetId} 详情`}
        className="text-brand inline-flex h-5 w-5 items-center justify-center hover:opacity-80"
      >
        <ExportOutlined />
      </a>
    </Tooltip>
  );
}
