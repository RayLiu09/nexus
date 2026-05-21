"use client";

/**
 * /tag-review — 标签审核（P2.2）
 *
 * v3.2 布局：2-1
 *   左：bulk-bar + 低置信标签草稿表 + 自动提交历史表
 *   右：标签流程说明（notice × 4）
 *
 * 危险动作（A3）：
 *   - 批量确认  → undo-toast 10s
 *   - 批量驳回  → confirm-dialog
 *   - 撤销标签  → undo-toast
 */

import { useState } from "react";
import { Table, Tag, Button, Progress, Tooltip, App } from "antd";
import type { ColumnsType } from "antd/es/table";
import { CheckOutlined, CloseOutlined, EditOutlined } from "@ant-design/icons";

// ── mock 数据（实际接 /v1/tags/pending 与 /v1/tags/committed） ──

interface TagDraft {
  id: string;
  normalizedRefId: string;
  tags: string[];
  evidence: string;
  confidence: number;
}

interface CommittedTag {
  id: string;
  normalizedRefId: string;
  tags: string[];
  confidence: number;
  committedAt: string;
}

const MOCK_DRAFTS: TagDraft[] = [
  {
    id: "d1",
    normalizedRefId: "ref_doc_20260514_102",
    tags: ["课程思政", "案例教学"],
    evidence: "课程融入产业真实案例，以企业场景重构知识结构...",
    confidence: 0.63,
  },
  {
    id: "d2",
    normalizedRefId: "ref_record_20260514_077",
    tags: ["就业趋势", "区域画像"],
    evidence: "重点城市需求增长 12%，新兴岗位集中在数字化领域...",
    confidence: 0.69,
  },
  {
    id: "d3",
    normalizedRefId: "ref_doc_20260513_041",
    tags: ["课程大纲", "双元制"],
    evidence: "引入德国双元制职业教育模式，分阶段递进...",
    confidence: 0.72,
  },
];

const MOCK_COMMITTED: CommittedTag[] = [
  {
    id: "c1",
    normalizedRefId: "ref_doc_20260515_003",
    tags: ["电子商务", "教材", "职业教育"],
    confidence: 0.91,
    committedAt: "2026-05-15T09:21:00Z",
  },
  {
    id: "c2",
    normalizedRefId: "ref_record_20260514_077",
    tags: ["就业分析", "区域用工"],
    confidence: 0.88,
    committedAt: "2026-05-14T16:05:00Z",
  },
];

// ── 置信度进度条 ──────────────────────────────────────────────

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const status = pct >= 85 ? "success" : pct >= 60 ? "normal" : "exception";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
      <Progress
        percent={pct}
        size="small"
        status={status}
        showInfo={false}
        style={{ width: 80 }}
        aria-label={`置信度 ${pct}%`}
      />
      <span
        style={{
          fontSize: 11,
          fontWeight: 600,
          color:
            pct >= 85
              ? "var(--success-600)"
              : pct >= 60
                ? "var(--warning-600)"
                : "var(--danger-600)",
        }}
      >
        {pct}%
      </span>
    </div>
  );
}

// ── TagReviewPage ─────────────────────────────────────────────

export default function TagReviewContent() {
  const [drafts, setDrafts] = useState<TagDraft[]>(MOCK_DRAFTS);
  const [committed, setCommitted] = useState<CommittedTag[]>(MOCK_COMMITTED);
  const [selectedIds, setSelectedIds] = useState<React.Key[]>([]);
  const { message, modal, notification } = App.useApp();

  // ── 批量确认（undo-toast 10s） ──
  const handleBulkConfirm = () => {
    const toConfirm = drafts.filter((d) => selectedIds.includes(d.id));
    const key = `confirm-${Date.now()}`;
    setDrafts((prev) => prev.filter((d) => !selectedIds.includes(d.id)));
    const reverted = [...selectedIds];
    setSelectedIds([]);
    notification.success({
      key,
      message: `已确认 ${toConfirm.length} 条标签草稿`,
      description: "10 秒内可撤销。确认动作将写入审计日志。",
      duration: 10,
      btn: (
        <Button
          type="link"
          size="small"
          onClick={() => {
            setDrafts((prev) => [...toConfirm, ...prev]);
            notification.destroy(key);
            message.info("已撤销标签确认");
          }}
        >
          撤销
        </Button>
      ),
    });
    // 同时加入自动提交历史（模拟写库）
    const now = new Date().toISOString();
    const newCommitted: CommittedTag[] = toConfirm.map((d) => ({
      id: `c${Date.now()}-${d.id}`,
      normalizedRefId: d.normalizedRefId,
      tags: d.tags,
      confidence: d.confidence,
      committedAt: now,
    }));
    setCommitted((prev) => [...newCommitted, ...prev]);
    void reverted; // reverted 用于 undo 时恢复选择
  };

  // ── 批量驳回（confirm-dialog） ──
  const handleBulkReject = () => {
    modal.confirm({
      title: `确认驳回 ${selectedIds.length} 条标签草稿？`,
      content: "驳回后这些标签草稿将从队列中移除，此操作写入审计日志且无法自动恢复。",
      okText: "确认驳回",
      okButtonProps: { danger: true },
      cancelText: "取消",
      onOk: () => {
        setDrafts((prev) => prev.filter((d) => !selectedIds.includes(d.id)));
        setSelectedIds([]);
        message.success("已驳回所选标签草稿");
      },
    });
  };

  // ── 撤销已提交标签（undo-toast） ──
  const handleRevoke = (item: CommittedTag) => {
    const key = `revoke-${item.id}`;
    setCommitted((prev) => prev.filter((c) => c.id !== item.id));
    notification.info({
      key,
      message: `已撤销 ${item.normalizedRefId} 的标签`,
      description: "10 秒内可恢复。撤销操作写入审计日志。",
      duration: 10,
      btn: (
        <Button
          type="link"
          size="small"
          onClick={() => {
            setCommitted((prev) => [item, ...prev]);
            notification.destroy(key);
            message.info("已恢复标签");
          }}
        >
          恢复
        </Button>
      ),
    });
  };

  // ── 低置信草稿表列 ──
  const draftColumns: ColumnsType<TagDraft> = [
    {
      title: "normalized_ref",
      dataIndex: "normalizedRefId",
      render: (id: string) => (
        <code style={{ fontSize: 12, fontFamily: "var(--font-mono)" }}>{id}</code>
      ),
    },
    {
      title: "候选标签",
      dataIndex: "tags",
      render: (tags: string[]) => (
        <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
          {tags.map((t) => (
            <Tag key={t} color="default">
              #{t}
            </Tag>
          ))}
        </div>
      ),
    },
    {
      title: "证据片段",
      dataIndex: "evidence",
      render: (text: string) => (
        <Tooltip title={text}>
          <span style={{ fontSize: 12, color: "var(--text-secondary)", cursor: "help" }}>
            {text.slice(0, 30)}…
          </span>
        </Tooltip>
      ),
    },
    {
      title: "置信度",
      dataIndex: "confidence",
      width: 120,
      render: (v: number) => <ConfidenceBar value={v} />,
    },
    {
      title: "操作",
      width: 60,
      render: (_: unknown, record: TagDraft) => (
        <Button
          size="small"
          icon={<EditOutlined />}
          onClick={() => message.info(`审核 ${record.normalizedRefId} — 功能即将上线`)}
          aria-label={`审核 ${record.normalizedRefId}`}
        >
          审核
        </Button>
      ),
    },
  ];

  // ── 自动提交历史列 ──
  const committedColumns: ColumnsType<CommittedTag> = [
    {
      title: "normalized_ref",
      dataIndex: "normalizedRefId",
      render: (id: string) => (
        <code style={{ fontSize: 12, fontFamily: "var(--font-mono)" }}>{id}</code>
      ),
    },
    {
      title: "已提交标签",
      dataIndex: "tags",
      render: (tags: string[]) => (
        <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
          {tags.map((t) => (
            <Tag key={t} color="blue">
              #{t}
            </Tag>
          ))}
        </div>
      ),
    },
    {
      title: "置信度",
      dataIndex: "confidence",
      width: 110,
      render: (v: number) => <ConfidenceBar value={v} />,
    },
    {
      title: "方式",
      width: 110,
      render: () => <Tag>auto_commit</Tag>,
    },
    {
      title: "操作",
      width: 80,
      render: (_: unknown, record: CommittedTag) => (
        <Button
          type="link"
          size="small"
          onClick={() => handleRevoke(record)}
          aria-label={`撤销 ${record.normalizedRefId} 的标签`}
        >
          撤销
        </Button>
      ),
    },
  ];

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "minmax(0, 2fr) minmax(280px, 1fr)",
        gap: 20,
        alignItems: "start",
      }}
    >
      {/* ── 左侧主区 ── */}
      <div style={{ display: "grid", gap: 16 }}>
        {/* BulkBar */}
        {selectedIds.length > 0 && (
          <div
            role="toolbar"
            aria-label="标签批量操作工具栏"
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              padding: "10px 16px",
              borderRadius: "var(--radius-lg)",
              border: "1px solid var(--brand-200)",
              background: "var(--brand-50)",
            }}
          >
            <span style={{ fontSize: 13, color: "var(--text-secondary)" }}>
              已选 <strong style={{ color: "var(--text)" }}>{selectedIds.length}</strong> 项
            </span>
            <Button
              type="primary"
              size="small"
              icon={<CheckOutlined />}
              onClick={handleBulkConfirm}
            >
              确认
            </Button>
            <Button
              size="small"
              icon={<EditOutlined />}
              onClick={() => message.info("改写功能即将上线")}
            >
              改写
            </Button>
            <Button size="small" danger icon={<CloseOutlined />} onClick={handleBulkReject}>
              驳回
            </Button>
            <Button
              type="text"
              size="small"
              onClick={() => setSelectedIds([])}
              aria-label="清空选择"
            >
              清空
            </Button>
          </div>
        )}

        {/* 低置信标签草稿 */}
        <div
          style={{
            background: "var(--surface)",
            border: "1px solid var(--line)",
            borderRadius: "var(--radius-xl)",
            overflow: "hidden",
          }}
        >
          <div
            style={{
              padding: "16px 20px",
              borderBottom: "1px solid var(--line-light)",
              display: "flex",
              justifyContent: "space-between",
              alignItems: "flex-start",
            }}
          >
            <div>
              <div style={{ fontSize: 15, fontWeight: 600 }}>低置信标签草稿</div>
              <div style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 2 }}>
                业务专家需决定 confirm / revise / reject
              </div>
            </div>
          </div>
          <div style={{ padding: "0 0 4px" }}>
            <Table
              rowKey="id"
              dataSource={drafts}
              columns={draftColumns}
              size="middle"
              pagination={false}
              rowSelection={{
                selectedRowKeys: selectedIds,
                onChange: setSelectedIds,
              }}
              locale={{ emptyText: "暂无低置信标签草稿 — 所有标签均已高置信自动提交" }}
            />
          </div>
        </div>

        {/* 自动提交历史 */}
        <div
          style={{
            background: "var(--surface)",
            border: "1px solid var(--line)",
            borderRadius: "var(--radius-xl)",
            overflow: "hidden",
          }}
        >
          <div
            style={{
              padding: "16px 20px",
              borderBottom: "1px solid var(--line-light)",
            }}
          >
            <div style={{ fontSize: 15, fontWeight: 600 }}>自动提交历史</div>
            <div style={{ fontSize: 12, color: "var(--text-secondary)", marginTop: 2 }}>
              高置信标签自动落库，允许事后追溯和撤销
            </div>
          </div>
          <Table
            rowKey="id"
            dataSource={committed}
            columns={committedColumns}
            size="middle"
            pagination={false}
            locale={{ emptyText: "暂无自动提交记录" }}
          />
        </div>
      </div>

      {/* ── 右侧说明 ── */}
      <div
        style={{
          background: "var(--surface)",
          border: "1px solid var(--line)",
          borderRadius: "var(--radius-xl)",
          padding: 20,
        }}
      >
        <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 16 }}>标签流程说明</div>
        <div style={{ display: "grid", gap: 12 }}>
          <div
            style={{
              padding: "12px 14px",
              borderRadius: "var(--radius-lg)",
              background: "var(--brand-50)",
              border: "1px solid var(--brand-200)",
              fontSize: 13,
            }}
          >
            <strong style={{ display: "block", marginBottom: 4 }}>输入对象</strong>
            normalized_document / normalized_record。
          </div>
          <div
            style={{
              padding: "12px 14px",
              borderRadius: "var(--radius-lg)",
              background: "var(--surface-alt)",
              border: "1px solid var(--line)",
              fontSize: 13,
            }}
          >
            <strong style={{ display: "block", marginBottom: 4 }}>生成阶段</strong>
            metadata_enrich，在 chunk 生成之前执行。
          </div>
          <div
            style={{
              padding: "12px 14px",
              borderRadius: "var(--radius-lg)",
              background: "var(--warning-bg)",
              border: "1px solid var(--warning-100)",
              fontSize: 13,
            }}
          >
            <strong style={{ display: "block", marginBottom: 4 }}>低置信策略</strong>
            置信度 &lt; 85% 时进入人工审核队列，不自动提交。
          </div>
          <div
            style={{
              padding: "12px 14px",
              borderRadius: "var(--radius-lg)",
              background: "var(--surface-alt)",
              border: "1px solid var(--line)",
              fontSize: 13,
            }}
          >
            <strong style={{ display: "block", marginBottom: 4 }}>审计要求</strong>
            自动提交、撤销、人工改写均写入审计日志，trace_id 关联。
          </div>
        </div>
      </div>
    </div>
  );
}
