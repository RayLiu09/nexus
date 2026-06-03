"use client";

import { useMemo, useState } from "react";
import { Input, Table } from "antd";
import type { ColumnsType } from "antd/es/table";
import { SearchOutlined } from "@ant-design/icons";
import { Empty } from "@/components/shared/Empty";
import { StatusLabel } from "@/components/StatusLabel";
import { formatTime } from "@/lib/format-time";
import { shortId, type RawObject } from "@/lib/api";

const PAGE_SIZE = 20;

export function RawLedgerContent({ objects }: { objects: RawObject[] }) {
  const [search, setSearch] = useState("");

  const filtered = useMemo(() => {
    if (!search.trim()) return objects;
    const q = search.toLowerCase();
    return objects.filter(
      (o) =>
        o.id.toLowerCase().includes(q) ||
        o.batch_id.toLowerCase().includes(q) ||
        o.object_uri.toLowerCase().includes(q) ||
        o.checksum.toLowerCase().includes(q),
    );
  }, [objects, search]);

  const columns: ColumnsType<RawObject> = [
    {
      title: "对象 ID",
      dataIndex: "id",
      key: "id",
      width: 130,
      render: (id: string) => <code className="text-xs">{shortId(id)}</code>,
    },
    {
      title: "批次号",
      dataIndex: "batch_id",
      key: "batch_id",
      width: 130,
      render: (id: string) => <code className="text-xs text-muted">{shortId(id)}</code>,
    },
    {
      title: "对象 URI",
      dataIndex: "object_uri",
      key: "object_uri",
      ellipsis: true,
      render: (uri: string) => (
        <code className="text-xs" title={uri}>
          {uri}
        </code>
      ),
    },
    {
      title: "Checksum",
      dataIndex: "checksum",
      key: "checksum",
      width: 140,
      ellipsis: true,
      render: (s: string) => (
        <code className="text-xs text-muted" title={s}>
          {s}
        </code>
      ),
    },
    {
      title: "创建时间",
      dataIndex: "created_at",
      key: "created_at",
      width: 150,
      render: (t: string) => {
        const { display, iso } = formatTime(t);
        return (
          <time dateTime={iso} title={iso} className="text-xs text-muted">
            {display}
          </time>
        );
      },
    },
    {
      title: "状态",
      dataIndex: "status",
      key: "status",
      width: 100,
      render: (status: string) => <StatusLabel value={status} />,
    },
  ];

  return (
    <>
      {/* Search */}
      <div className="flex justify-center mb-4">
        <Input.Search
          placeholder="搜索对象 ID、批次号、URI 或 checksum..."
          allowClear
          size="large"
          prefix={<SearchOutlined />}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="max-w-xl"
        />
      </div>

      {objects.length === 0 ? (
        <Empty title="暂无原始对象" description="完成数据接入后原始对象将在此处显示" />
      ) : (
        <Table<RawObject>
          columns={columns}
          dataSource={filtered}
          rowKey="id"
          size="middle"
          pagination={{
            pageSize: PAGE_SIZE,
            showSizeChanger: true,
            pageSizeOptions: ["10", "20", "50"],
            showTotal: (total, range) => `${range[0]}-${range[1]} / ${total} 条`,
          }}
          locale={{ emptyText: "未找到匹配的原始对象" }}
        />
      )}
    </>
  );
}
