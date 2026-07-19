import { Skeleton } from "antd";

export default function Loading() {
  return (
    <div className="flex flex-col gap-6">
      <Skeleton active title paragraph={{ rows: 1 }} />
      <Skeleton active paragraph={{ rows: 6 }} />
    </div>
  );
}
