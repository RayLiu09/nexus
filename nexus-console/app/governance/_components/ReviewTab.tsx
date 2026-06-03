"use client";

import { useState } from "react";
import { Button, App } from "antd";
import { CheckOutlined } from "@ant-design/icons";
import { type GovernanceRun } from "../_lib/types";
import { ReviewCard } from "./ReviewCard";

interface ReviewTabProps {
  runs: GovernanceRun[];
  onViewDetail: (r: GovernanceRun) => void;
}

export function ReviewTab({ runs, onViewDetail }: ReviewTabProps) {
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const { message, modal } = App.useApp();

  const filtered = runs.filter(
    (r) =>
      r.adoption_status === "review_required" || r.adoption_status === "pending_rule_guardrail",
  );

  const handleSelect = (id: string, checked: boolean) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });
  };

  const handleBulkAdjudicate = () => {
    modal.confirm({
      title: `确认批量裁定 ${selectedIds.size} 项？`,
      content: "每条记录都会生成独立审计事件。此操作不可批量撤销。",
      okText: "确认裁定",
      cancelText: "取消",
      onOk: () => {
        message.success("已提交批量裁定");
        setSelectedIds(new Set());
      },
    });
  };

  const handleBulkReassign = () => {
    modal.confirm({
      title: `确认批量改派 ${selectedIds.size} 项？`,
      content: "改派将影响责任人 SLA，请确认。",
      okText: "确认改派",
      cancelText: "取消",
      onOk: () => {
        message.success("已改派");
        setSelectedIds(new Set());
      },
    });
  };

  if (filtered.length === 0) {
    return (
      <div className="py-12 text-center text-secondary">
        <CheckOutlined className="text-[32px] text-[var(--success-600)] mb-3" />
        <div className="text-h3 font-semibold">待复核队列已清空</div>
        <div className="text-detail mt-1">所有资产均已完成裁定</div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {/* BulkBar */}
      {selectedIds.size > 0 && (
        <div
          className="governance-bulk-bar flex items-center gap-2.5 px-4 py-2.5 rounded-lg border border-[var(--brand-200)] bg-[var(--brand-50)]"
          role="toolbar"
          aria-label="批量操作工具栏"
        >
          <span className="text-detail text-secondary">
            已选 <strong className="text-[var(--text)]">{selectedIds.size}</strong> 项
          </span>
          <Button type="primary" size="small" onClick={handleBulkAdjudicate}>
            批量裁定
          </Button>
          <Button size="small" onClick={handleBulkReassign}>
            批量改派
          </Button>
          <Button
            type="text"
            size="small"
            onClick={() => setSelectedIds(new Set())}
            aria-label="清空选择"
          >
            清空
          </Button>
        </div>
      )}

      {/* review-card stack */}
      {filtered.map((r) => (
        <ReviewCard
          key={r.id}
          run={r}
          selected={selectedIds.has(r.id)}
          onSelect={(checked) => handleSelect(r.id, checked)}
          onAdjudicate={() => onViewDetail(r)}
          onReassign={() => message.info("改派功能即将上线")}
        />
      ))}
    </div>
  );
}
