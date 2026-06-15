"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { App, Modal } from "antd";
import { ConfirmButton } from "@/components/shared/ConfirmButton";
import { deleteApiData, NexusApiError } from "@/lib/api";

interface DeleteDataSourceButtonProps {
  dataSourceId: string;
  dataSourceName: string;
}

export function DeleteDataSourceButton({
  dataSourceId,
  dataSourceName,
}: DeleteDataSourceButtonProps) {
  const router = useRouter();
  const { message } = App.useApp();
  const [forceOpen, setForceOpen] = useState(false);
  const [forceLoading, setForceLoading] = useState(false);

  async function handleDelete() {
    try {
      await deleteApiData(`/api/data-sources/${dataSourceId}`);
    } catch (err: unknown) {
      if (err instanceof NexusApiError && err.status === 409) {
        setForceOpen(true);
        return;
      }
      throw err;
    }
    message.success(`数据源「${dataSourceName}」已删除`);
    router.push("/data-sources");
  }

  async function handleForceDelete() {
    setForceLoading(true);
    try {
      await deleteApiData(`/api/data-sources/${dataSourceId}?force=true`);
    } finally {
      setForceLoading(false);
    }
    setForceOpen(false);
    message.success(`数据源「${dataSourceName}」已强制删除`);
    router.push("/data-sources");
  }

  return (
    <>
      <ConfirmButton
        title="删除数据源"
        description={
          <>
            确定要删除数据源 <strong>{dataSourceName}</strong> 吗？
            <br />
            删除后，该数据源的配置将不可恢复。关联的批次和原始对象将保留。
          </>
        }
        confirmWord={dataSourceName}
        confirmLabel="确认删除"
        severity="danger"
        danger
        buttonProps={{ size: "middle" }}
        onConfirm={handleDelete}
      >
        删除数据源
      </ConfirmButton>

      <Modal
        title="无法直接删除"
        open={forceOpen}
        onOk={handleForceDelete}
        onCancel={() => setForceOpen(false)}
        okText="强制删除"
        cancelText="取消"
        okButtonProps={{ danger: true, loading: forceLoading }}
        confirmLoading={forceLoading}
      >
        <p>
          数据源 <strong>{dataSourceName}</strong>{" "}
          仍有未清理的原始对象或资产记录。
        </p>
        <p>
          强制删除仅将数据源标记为禁用，下游数据链路将保留但处于游离状态。
          建议先清理关联数据后再操作。
        </p>
      </Modal>
    </>
  );
}
