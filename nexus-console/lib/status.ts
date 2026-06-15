export type StatusTone = "neutral" | "info" | "success" | "warning" | "danger" | "muted";

export type StatusDefinition = {
  label: string;
  tone: StatusTone;
};

export const statusDefinitions = {
  processing: { label: "处理中", tone: "info" },
  available: { label: "当前可用", tone: "success" },
  review_required: { label: "需复核", tone: "warning" },
  archived: { label: "历史归档", tone: "muted" },
  disabled: { label: "已停用", tone: "muted" },
  failed: { label: "失败", tone: "danger" },

  submitted: { label: "已提交", tone: "neutral" },
  raw_persisted: { label: "已落原始库", tone: "info" },
  completed: { label: "已完成", tone: "success" },
  partial_failed: { label: "部分失败", tone: "warning" },
  duplicate_skipped: { label: "重复跳过", tone: "muted" },
  checksum_failed: { label: "校验失败", tone: "danger" },

  queued: { label: "排队中", tone: "info" },
  running: { label: "处理中", tone: "info" },
  succeeded: { label: "成功", tone: "success" },
  dead_lettered: { label: "死信", tone: "danger" },
  cancelled: { label: "已取消", tone: "muted" },

  not_indexed: { label: "未索引", tone: "neutral" },
  pending: { label: "待处理", tone: "info" },
  building: { label: "索引中", tone: "info" },
  indexed: { label: "已索引", tone: "success" },
  stale: { label: "待重建", tone: "warning" },

  auto_adopted: { label: "已自动采纳", tone: "success" },
  partially_adopted: { label: "部分采纳", tone: "warning" },
  rejected: { label: "已驳回", tone: "danger" },
  overridden: { label: "人工覆盖", tone: "warning" },

  active: { label: "启用", tone: "success" },

  enabled: { label: "启用", tone: "success" },
  error: { label: "异常", tone: "danger" },

  auto_passed: { label: "自动通过", tone: "success" },
  inactive: { label: "未激活", tone: "muted" },
  open: { label: "已创建", tone: "neutral" },
  revoked: { label: "已吊销", tone: "muted" },
  expired: { label: "已过期", tone: "muted" }
} satisfies Record<string, StatusDefinition>;

export type StatusValue = keyof typeof statusDefinitions;
