"use client";

import Link from "next/link";
import { Button, Checkbox, Input, Space } from "antd";
import type { DataSource } from "@/lib/api";

const SOURCE_TYPE_LABELS: Record<string, string> = {
  file_upload: "本地文件上传",
  nas: "NAS 同步",
  crawler: "Crawler 爬虫",
  database: "数据库对接",
  webhook: "API 推送",
};

export function IngestForm({
  sources,
  action,
  defaultIdempotencyKey,
}: {
  sources: DataSource[];
  action: (formData: FormData) => void;
  defaultIdempotencyKey: string;
}) {
  return (
    <form action={action}>
      <Space orientation="vertical" className="w-full" size="middle">
        <div>
          <label className="mb-1 block text-sm font-medium text-text">
            数据源 <span className="text-danger">*</span>
          </label>
          <select
            name="data_source_id"
            required
            className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-text outline-none transition-colors focus:border-brand focus:ring-2 focus:ring-brand/20"
          >
            <option value="">— 选择已注册的数据源 —</option>
            {sources.length === 0 ? (
              <option value="" disabled>
                暂无数据源，请先前往「数据源管理」注册
              </option>
            ) : (
              Object.entries(
                sources.reduce<Record<string, DataSource[]>>((acc, s) => {
                  const type = s.source_type;
                  if (!acc[type]) acc[type] = [];
                  acc[type].push(s);
                  return acc;
                }, {}),
              ).map(([type, items]) => (
                <optgroup key={type} label={SOURCE_TYPE_LABELS[type] ?? type}>
                  {items.map((source) => (
                    <option value={source.id} key={source.id}>
                      {source.name} [{source.code}]
                    </option>
                  ))}
                </optgroup>
              ))
            )}
          </select>
          {sources.length === 0 && (
            <Link
              href="/data-sources/new"
              className="mt-1.5 inline-block text-xs text-brand hover:text-brand-strong"
            >
              前往注册数据源
            </Link>
          )}
        </div>

        <div>
          <label className="mb-1 block text-sm font-medium text-text">
            幂等键 <span className="text-danger">*</span>
          </label>
          <Input name="idempotency_key" defaultValue={defaultIdempotencyKey} required />
        </div>

        <div>
          <label className="mb-1 block text-sm font-medium text-text">
            文件名 <span className="text-danger">*</span>
          </label>
          <Input name="filename" defaultValue="console-sample.txt" required />
        </div>

        <div>
          <label className="mb-1 block text-sm font-medium text-text">
            内容类型 <span className="text-danger">*</span>
          </label>
          <Input name="content_type" defaultValue="text/plain" required />
        </div>

        <div>
          <label className="mb-1 block text-sm font-medium text-text">
            内容（样本文本） <span className="text-danger">*</span>
          </label>
          <Input.TextArea
            name="content_text"
            defaultValue="NEXUS console live API ingest sample for connectivity."
            required
            rows={3}
          />
        </div>

        <Checkbox name="process_now" defaultChecked checked>
          立即处理并生成资产化结果
        </Checkbox>

        <Button
          type="primary"
          htmlType="submit"
          disabled={sources.length === 0}
        >
          提交批次
        </Button>
      </Space>
    </form>
  );
}
