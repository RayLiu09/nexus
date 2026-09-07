import { Skeleton } from "antd";

export default function AssetCenterLoading() {
  return (
    <div className="flex flex-col gap-6">
      <Skeleton active title={{ width: 180 }} paragraph={{ rows: 1, width: 420 }} />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {Array.from({ length: 5 }, (_, index) => (
          <div className="border-line bg-surface min-h-[320px] rounded-lg border p-6" key={index}>
            <Skeleton active title={{ width: 180 }} paragraph={{ rows: 5 }} />
          </div>
        ))}
      </div>
    </div>
  );
}
