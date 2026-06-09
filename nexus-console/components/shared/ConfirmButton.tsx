"use client";

import { useState } from "react";
import { Button, Input, Modal, Space, Typography } from "antd";
import type { ButtonProps } from "antd";
import { ExclamationCircleOutlined } from "@ant-design/icons";

export interface ConfirmButtonProps {
  /** Button label in normal state. */
  children: React.ReactNode;
  /** Modal title. */
  title: string;
  /** Modal description. Supports JSX for rich content. */
  description?: React.ReactNode;
  /**
   * If set, user must type this exact word to confirm.
   * Use for high blast-radius operations (e.g., "delete", "revoke").
   */
  confirmWord?: string;
  /** Tooltip on the confirm button when confirmWord is typed. */
  confirmLabel?: string;
  /** Called when user confirms. Should return a Promise for loading state. */
  onConfirm: () => Promise<void> | void;
  /** Button variant. */
  danger?: boolean;
  /** Antd button props passed through. */
  buttonProps?: Omit<ButtonProps, "danger" | "onClick" | "children">;
  /** Severity of the confirm. Affects icon and tone. */
  severity?: "warning" | "danger";
}

/**
 * A button that opens a confirmation dialog before executing a dangerous action.
 *
 * Supports two modes:
 * - Simple: "确定要执行此操作吗？" → confirm/cancel
 * - Confirm-word: user must type a specific word (e.g., "DELETE") to unlock the confirm button
 */
export function ConfirmButton({
  children,
  title,
  description,
  confirmWord,
  confirmLabel = "确认",
  onConfirm,
  danger = false,
  buttonProps,
  severity = "warning",
}: ConfirmButtonProps) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [typed, setTyped] = useState("");

  const needsWord = Boolean(confirmWord);
  const wordMatch = !needsWord || typed === confirmWord;
  const icon =
    severity === "danger" ? (
      <ExclamationCircleOutlined style={{ color: "var(--danger)" }} />
    ) : undefined;

  const handleOk = async () => {
    setLoading(true);
    try {
      await onConfirm();
      setOpen(false);
    } catch (e: unknown) {
      // Keep modal open and let the caller show its own error feedback.
      // If onConfirm throws without user-visible feedback, log a warning.
      console.warn("ConfirmButton: onConfirm threw an unhandled error", e);
    } finally {
      setLoading(false);
      setTyped("");
    }
  };

  const handleCancel = () => {
    setOpen(false);
    setTyped("");
  };

  return (
    <>
      <Button danger={danger} onClick={() => setOpen(true)} {...buttonProps}>
        {children}
      </Button>

      <Modal
        title={
          <Space>
            {icon}
            <span>{title}</span>
          </Space>
        }
        open={open}
        onOk={handleOk}
        onCancel={handleCancel}
        okText={confirmLabel}
        cancelText="取消"
        okButtonProps={{
          danger: severity === "danger",
          disabled: !wordMatch,
          loading,
        }}
        confirmLoading={loading}
        destroyOnClose
      >
        <Space orientation="vertical" size="middle" className="w-full">
          {description && (
            <Typography.Text type="secondary">{description}</Typography.Text>
          )}

          {needsWord && (
            <div>
              <Typography.Text type="secondary" className="text-xs">
                请输入 <code className="font-bold">{confirmWord}</code> 以确认操作：
              </Typography.Text>
              <Input
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
                placeholder={confirmWord}
                className="mt-2"
                autoFocus
              />
            </div>
          )}
        </Space>
      </Modal>
    </>
  );
}
