"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { App, Button, Input, Modal, Typography } from "antd";
import { deleteApiData, postApiData } from "@/lib/api";
import { ConfirmButton } from "@/components/shared/ConfirmButton";

type AssetLifecycleActionsProps = {
  assetId: string;
  assetTitle: string;
  assetStatus: string;
};

export function AssetLifecycleActions({
  assetId,
  assetTitle,
  assetStatus,
}: AssetLifecycleActionsProps) {
  const router = useRouter();
  const { message } = App.useApp();
  const [warningOpen, setWarningOpen] = useState(false);
  const [finalConfirmOpen, setFinalConfirmOpen] = useState(false);
  const [typedTitle, setTypedTitle] = useState("");
  const [deleting, setDeleting] = useState(false);
  const isArchived = assetStatus === "archived";

  async function archive() {
    await postApiData(`/api/assets/${encodeURIComponent(assetId)}/archive`, {});
    message.success(`资产「${assetTitle}」已归档`);
    router.refresh();
  }

  async function remove() {
    setDeleting(true);
    try {
      await deleteApiData(`/api/assets/${encodeURIComponent(assetId)}`);
      message.success(`资产「${assetTitle}」及其衍生数据已删除`);
      router.replace("/assets");
      router.refresh();
    } finally {
      setDeleting(false);
    }
  }

  return (
    <>
      {!isArchived && (
        <ConfirmButton
          title="归档资产"
          description={<>归档后，资产将退出目录和检索，但保留数据与血缘记录。</>}
          confirmLabel="确认归档"
          severity="warning"
          buttonProps={{ size: "middle" }}
          onConfirm={archive}
        >
          归档
        </ConfirmButton>
      )}
      <Button danger onClick={() => setWarningOpen(true)}>
        删除
      </Button>

      <Modal
        title="删除资产"
        open={warningOpen}
        onCancel={() => setWarningOpen(false)}
        onOk={() => {
          setWarningOpen(false);
          setFinalConfirmOpen(true);
        }}
        okText="继续"
        cancelText="取消"
        okButtonProps={{ danger: true }}
        destroyOnHidden
      >
        <Typography.Paragraph>
          删除不可恢复，将同时清理该资产的版本、标准化内容、治理结果、索引和其他衍生对象数据。
        </Typography.Paragraph>
        <Typography.Text type="secondary">共享的原始对象不会被删除。</Typography.Text>
      </Modal>

      <Modal
        title="最终确认删除"
        open={finalConfirmOpen}
        onCancel={() => {
          setFinalConfirmOpen(false);
          setTypedTitle("");
        }}
        onOk={remove}
        okText="永久删除"
        cancelText="取消"
        okButtonProps={{ danger: true, disabled: typedTitle !== assetTitle, loading: deleting }}
        confirmLoading={deleting}
        destroyOnHidden
      >
        <Typography.Paragraph>
          请输入完整资产标题 <Typography.Text code>{assetTitle}</Typography.Text> 以确认永久删除。
        </Typography.Paragraph>
        <Input
          value={typedTitle}
          onChange={(event) => setTypedTitle(event.target.value)}
          placeholder={assetTitle}
          autoFocus
        />
      </Modal>
    </>
  );
}
