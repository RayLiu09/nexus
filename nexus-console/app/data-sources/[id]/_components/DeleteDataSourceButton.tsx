"use client";

import { useRouter } from "next/navigation";
import { App } from "antd";
import { ConfirmButton } from "@/components/shared/ConfirmButton";
import { deleteApiData } from "@/lib/api";

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

  async function handleDelete() {
    await deleteApiData(`/internal/v1/data-sources/${dataSourceId}`);
    message.success(`数据源「${dataSourceName}」已删除`);
    router.push("/data-sources");
  }

  return (
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
  );
}
