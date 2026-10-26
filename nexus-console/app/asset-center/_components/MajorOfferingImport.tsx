"use client";

import { useRef, useState } from "react";
import { Alert, Button, Input, Modal, Space, Typography } from "antd";
import { Upload } from "lucide-react";
import { postFormApiData } from "@/lib/api";

type ImportResult = {
  import_id: string;
  total_count: number;
  imported_count: number;
  skipped_count: number;
};

export function MajorOfferingImport({ onImported }: { onImported: () => void }) {
  const [open, setOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const submitting = useRef(false);
  const operationKey = useRef("");

  async function submit() {
    if (!file || submitting.current || result) return;
    if (!file.name.toLowerCase().endsWith(".xlsx") || file.size > 10 * 1024 * 1024) {
      setError("请选择不超过 10 MiB 的 .xlsx 文件");
      return;
    }
    submitting.current = true;
    setBusy(true);
    setError(null);
    try {
      const data = new FormData();
      data.set("file", file);
      const response = await postFormApiData<ImportResult>("/api/asset-center/major-offerings/import", data, {
        idempotencyKey: operationKey.current,
      });
      setResult(response.data);
      onImported();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "导入失败，请重试");
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  }

  return (
    <>
      <Button icon={<Upload size={15} />} onClick={() => {
        setFile(null);
        setError(null);
        setResult(null);
        setOpen(true);
      }}>导入布点数据</Button>
      <Modal title="导入布点数据" open={open} destroyOnHidden
        closable={!busy} mask={{ closable: !busy }} keyboard={!busy}
        onCancel={() => { if (!submitting.current) setOpen(false); }}
        footer={result ? <Button aria-label="完成" type="primary" onClick={() => setOpen(false)}>完成</Button> : (
          <Space>
            <Button aria-label="取消" disabled={busy} onClick={() => setOpen(false)}>取消</Button>
            <Button aria-label="导入" type="primary" loading={busy} disabled={!file} onClick={submit}>导入</Button>
          </Space>
        )}>
        <Space orientation="vertical" className="w-full" size={16}>
          <Typography.Paragraph className="!mb-0">
            请使用模板填写年份、省份、专业代码、专业名称、学校名称和年限。学校标识码、备注可留空。
            支持 .xlsx 文件，最多 10,000 行、10 MiB；专业代码和学校标识码请按文本填写。
            同一年份、同一学校、同一专业的数据会自动跳过。
          </Typography.Paragraph>
          <Button href="/api/asset-center/major-offerings/import-template" target="_blank">下载导入模板</Button>
          {!result && <Input type="file" aria-label="布点 Excel 文件" accept=".xlsx" disabled={busy}
            onChange={(event) => {
              setFile(event.target.files?.[0] ?? null);
              operationKey.current = crypto.randomUUID();
              setError(null);
            }} />}
          {error && <Alert type="error" showIcon title={error} />}
          {result && <Alert type="success" showIcon title="导入完成"
            description={`共 ${result.total_count} 条，新增 ${result.imported_count} 条，重复跳过 ${result.skipped_count} 条。`} />}
        </Space>
      </Modal>
    </>
  );
}
