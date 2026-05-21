"use client";

import Link from "next/link";
import { Table, Tag, Select, Button, Alert, Card } from "antd";
import { SaveOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { formatDateTime } from "@/lib/api";
import type { AssetWithMeta } from "../_lib/types";
import { deriveStats, deriveDomainDist } from "../_lib/types";
import { AssetsSummary } from "./AssetsSummary";
import { DomainDistribution } from "./DomainDistribution";

const DOMAIN_COLOR_KEY: Record<string, string> = {
  D1: "geekblue",
  D2: "cyan",
  D3: "green",
  D4: "gold",
  D5: "orange",
  D6: "magenta",
};

const LEVEL_COLOR_KEY: Record<string, string> = {
  L1: "success",
  L2: "processing",
  L3: "warning",
  L4: "error",
};

function statusTag(status: string) {
  const map: Record<string, { color: string; label: string }> = {
    available: { color: "success", label: "available" },
    review_required: { color: "warning", label: "review_required" },
    archived: { color: "default", label: "archived" },
    disabled: { color: "default", label: "disabled" },
    failed: { color: "error", label: "failed" },
    processing: { color: "processing", label: "processing" },
  };
  const m = map[status] ?? { color: "default", label: status };
  return <Tag color={m.color}>{m.label}</Tag>;
}

function indexTag(s?: string) {
  if (!s) return <span style={{ color: "var(--text-muted)" }}>-</span>;
  const map: Record<string, { color: string; label: string }> = {
    indexed: { color: "success", label: "indexed" },
    stale: { color: "warning", label: "stale" },
    blocked: { color: "default", label: "blocked" },
    pending: { color: "processing", label: "pending" },
  };
  const m = map[s] ?? { color: "default", label: s };
  return <Tag color={m.color}>{m.label}</Tag>;
}

function governanceTag(s?: string) {
  if (!s) return <span style={{ color: "var(--text-muted)" }}>-</span>;
  const map: Record<string, { color: string; label: string }> = {
    auto_passed: { color: "success", label: "auto_passed" },
    auto_adopted: { color: "success", label: "auto_passed" },
    review_required: { color: "warning", label: "review_required" },
    manual_overridden: { color: "processing", label: "manual_overridden" },
    rejected: { color: "error", label: "rejected" },
  };
  const m = map[s] ?? { color: "default", label: s };
  return <Tag color={m.color}>{m.label}</Tag>;
}

export function AssetsContent({ assets }: { assets: AssetWithMeta[] }) {
  const stats = deriveStats(assets);
  const domainDist = deriveDomainDist(assets);

  const columns: ColumnsType<AssetWithMeta> = [
    {
      title: "资产",
      dataIndex: "title",
      width: 280,
      fixed: "left",
      render: (title: string, r) => (
        <div>
          <Link
            href={`/assets/${r.id}`}
            className="font-semibold"
            style={{ color: "var(--brand)" }}
          >
            {title}
          </Link>
          <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 2 }}>
            <code>{r.id.slice(0, 18)}…</code>
          </div>
        </div>
      ),
    },
    {
      title: "当前版本",
      width: 160,
      render: (_, r) => (
        <span style={{ fontSize: 13 }}>
          {r.current_version_no ? (
            <code>{r.current_version_no}</code>
          ) : (
            <span style={{ color: "var(--text-muted)" }}>-</span>
          )}
        </span>
      ),
    },
    {
      title: "标准化引用",
      width: 200,
      render: (_, r) =>
        r.current_normalized_ref_id ? (
          <code style={{ fontSize: 12 }}>{r.current_normalized_ref_id.slice(0, 22)}…</code>
        ) : (
          <span style={{ color: "var(--text-muted)" }}>-</span>
        ),
    },
    {
      title: "域 / 分级",
      width: 140,
      render: (_, r) => (
        <span>
          {r.domain && <Tag color={DOMAIN_COLOR_KEY[r.domain] ?? "default"}>{r.domain}</Tag>}
          {r.level && <Tag color={LEVEL_COLOR_KEY[r.level] ?? "default"}>{r.level}</Tag>}
        </span>
      ),
    },
    {
      title: "质量",
      dataIndex: "quality_score",
      width: 80,
      align: "center" as const,
      sorter: (a, b) => (a.quality_score ?? 0) - (b.quality_score ?? 0),
      render: (s?: number) =>
        s != null ? <strong>{s}</strong> : <span style={{ color: "var(--text-muted)" }}>-</span>,
    },
    { title: "治理", width: 160, render: (_, r) => governanceTag(r.governance_status) },
    { title: "索引", width: 110, render: (_, r) => indexTag(r.index_status) },
    {
      title: "组织范围",
      width: 180,
      render: (_, r) =>
        r.org_scope?.length ? (
          r.org_scope.join(" / ")
        ) : (
          <span style={{ color: "var(--text-muted)" }}>-</span>
        ),
    },
    {
      title: "状态",
      width: 130,
      render: (_, r) => statusTag(r.status),
      filters: [
        { text: "available", value: "available" },
        { text: "review_required", value: "review_required" },
        { text: "archived", value: "archived" },
      ],
      onFilter: (val, r) => r.status === val,
    },
    {
      title: "更新时间",
      dataIndex: "updated_at",
      width: 150,
      sorter: (a, b) => new Date(a.updated_at).getTime() - new Date(b.updated_at).getTime(),
      render: (t: string) => (
        <span style={{ fontSize: 12, color: "var(--text-muted)" }}>{formatDateTime(t)}</span>
      ),
    },
  ];

  return (
    <>
      <AssetsSummary stats={stats} />

      <div className="assets-toolbar">
        <Select
          defaultValue="all-domain"
          options={[
            { value: "all-domain", label: "全部数据域" },
            { value: "D1", label: "D1 教学资源" },
            { value: "D2", label: "D2 人才培养" },
            { value: "D3", label: "D3 科研数据" },
            { value: "D4", label: "D4 产教融合" },
            { value: "D5", label: "D5 政策法规" },
            { value: "D6", label: "D6 综合管理" },
          ]}
          style={{ width: 160 }}
        />
        <Select
          defaultValue="all-level"
          options={[
            { value: "all-level", label: "全部分级" },
            { value: "L1", label: "L1 公开" },
            { value: "L2", label: "L2 内部" },
            { value: "L3", label: "L3 机密" },
            { value: "L4", label: "L4 受控" },
          ]}
          style={{ width: 130 }}
        />
        <Select
          defaultValue="visible"
          options={[
            { value: "visible", label: "available + review_required" },
            { value: "all", label: "全部状态" },
            { value: "archived", label: "归档" },
          ]}
          style={{ width: 240 }}
        />
        <Button icon={<SaveOutlined />}>保存视图</Button>
      </div>

      <div className="assets-layout">
        <Card variant="borderless" style={{ minWidth: 0 }}>
          <Table
            rowKey="id"
            dataSource={assets}
            columns={columns}
            size="middle"
            pagination={{ pageSize: 20, showSizeChanger: false }}
            scroll={{ x: 1280 }}
            locale={{ emptyText: "暂无资产" }}
          />
        </Card>

        <div className="assets-side">
          <DomainDistribution items={domainDist} />

          <Card title="目录页解释" size="small">
            <Alert
              type="info"
              showIcon={false}
              banner
              message={
                <span style={{ fontSize: 12 }}>
                  <strong>current version</strong> 来自 read model，不在 asset 表上存储反向指针。
                </span>
              }
              style={{ marginBottom: 8 }}
            />
            <Alert
              type="info"
              showIcon={false}
              banner
              message={
                <span style={{ fontSize: 12 }}>
                  <strong>current normalized ref</strong> 只表示当前可读标准化引用，不与 version
                  双向绑定。
                </span>
              }
              style={{ marginBottom: 8 }}
            />
            <Alert
              type="warning"
              showIcon={false}
              banner
              message={
                <span style={{ fontSize: 12 }}>
                  <strong>stale index</strong> 表示需要重建索引，不等于资产不可读。
                </span>
              }
            />
          </Card>
        </div>
      </div>
    </>
  );
}
