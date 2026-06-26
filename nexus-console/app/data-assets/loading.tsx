import { Skeleton } from "antd";

/**
 * Loading shell for `/data-assets` — mirrors the real board's layout
 * proportions so the page doesn't jump when data resolves.
 */
export default function DataAssetsLoading() {
  return (
    <div className="-mx-[var(--space-4)] -mt-[var(--space-4)] flex flex-col">
      <div className="border-y border-line bg-surface px-6 py-10 lg:px-10">
        <Skeleton active title={{ width: 320 }} paragraph={{ rows: 3, width: ["60%", "75%", "40%"] }} />
      </div>
      <div className="grid grid-cols-1 gap-5 px-6 py-8 md:grid-cols-2 lg:px-10 xl:grid-cols-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <div
            key={i}
            className={`${i === 0 ? "xl:col-span-2" : ""} rounded-lg border border-line bg-surface p-6`}
          >
            <Skeleton active title={{ width: 200 }} paragraph={{ rows: 4 }} />
          </div>
        ))}
      </div>
    </div>
  );
}
