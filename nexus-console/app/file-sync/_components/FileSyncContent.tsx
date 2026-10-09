"use client";

import Link from "next/link";
import { Button, Form, Input, Table, Tabs, Tag } from "antd";
import { FolderSync, Upload } from "lucide-react";

import { BatchUploadPage } from "@/app/ingest/batch/_components/BatchUploadPage";
import { formatTime } from "@/lib/format-time";
import type { IngestBatch } from "@/lib/api";

export function FileSyncContent() {
  return (
    <Tabs
      defaultActiveKey="upload"
      items={[
        {
          key: "upload",
          label: <span className="inline-flex items-center gap-2"><Upload size={16} />本地上传</span>,
          children: <BatchUploadPage />,
        },
        {
          key: "nas",
          label: <span className="inline-flex items-center gap-2"><FolderSync size={16} />NAS 同步</span>,
          children: (
            <section className="max-w-2xl py-3">
              <div className="mb-5 flex items-center gap-2">
                <h2 className="text-base font-semibold">手动同步 NAS 目录</h2>
                <Tag>暂未开放</Tag>
              </div>
              <Form layout="vertical" disabled>
                <Form.Item label="挂载目录" required>
                  <Input placeholder="服务器上的 NAS 挂载路径" />
                </Form.Item>
                <Form.Item label="包含文件">
                  <Input placeholder="例如 **/*.pdf,**/*.docx" />
                </Form.Item>
                <Button type="primary" icon={<FolderSync size={16} />} disabled>开始同步</Button>
              </Form>
            </section>
          ),
        },
      ]}
    />
  );
}

export function FileSyncHistory({ batches }: { batches: IngestBatch[] }) {
  return (
    <section className="mt-8">
      <h2 className="mb-3 text-base font-semibold">最近文件批次</h2>
      <Table
        rowKey="id"
        size="small"
        pagination={{ pageSize: 10 }}
        dataSource={batches}
        columns={[
          { title: "批次", dataIndex: "id", render: (id: string) => <Link href={`/raw-ledger?batch_id=${id}`}>{id.slice(0, 8)}</Link> },
          { title: "方式", dataIndex: "source_type", render: (type: string) => type === "nas" ? "NAS" : "本地上传" },
          { title: "状态", dataIndex: "status", render: (status: string) => <Tag>{status}</Tag> },
          { title: "更新时间", dataIndex: "updated_at", render: (value: string) => formatTime(value).display },
        ]}
      />
    </section>
  );
}
