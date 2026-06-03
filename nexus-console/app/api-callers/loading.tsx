import { Skeleton } from "antd";

export default function ApiCallersLoading() {
  return (
    <>
      <Skeleton active title paragraph={{ rows: 1 }} />
      <Skeleton active title={false} paragraph={{ rows: 6 }} />
    </>
  );
}
