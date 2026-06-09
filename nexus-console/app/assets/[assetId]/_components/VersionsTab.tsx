"use client";

import { Empty, Table } from "antd";
import type { ColumnsType } from "antd/es/table";
import { StatusLabel } from "@/components/StatusLabel";
import { formatDateTime, shortId, type AssetVersion } from "@/lib/api";

type Props = {
  versions: AssetVersion[];
};

const COLUMNS: ColumnsType<AssetVersion> = [
  {
    title: "版本ID",
    dataIndex: "id",
    width: 150,
    render: (id: string) => <span className="font-mono text-xs">{shortId(id)}</span>,
  },
  {
    title: "版本号",
    dataIndex: "version_no",
    width: 80,
    render: (v: number) => `v${v}`,
  },
  {
    title: "原始对象",
    dataIndex: "raw_object_id",
    width: 150,
    render: (id: string) => <span className="font-mono text-xs">{shortId(id)}</span>,
  },
  {
    title: "更新时间",
    dataIndex: "updated_at",
    width: 160,
    render: (t: string) => <span className="text-sm text-muted">{formatDateTime(t)}</span>,
  },
  {
    title: "状态",
    dataIndex: "version_status",
    width: 100,
    render: (s: string) => <StatusLabel value={s} />,
  },
];

export function VersionsTab({ versions }: Props) {
  if (versions.length === 0) {
    return <Empty description="暂无版本记录" />;
  }

  return (
    <Table
      rowKey="id"
      dataSource={versions}
      columns={COLUMNS}
      size="middle"
      pagination={false}
    />
  );
}
