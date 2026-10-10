export default function CrawlerLoading() {
  return (
    <section aria-label="正在加载 Crawler">
      <div className="border-line bg-surface overflow-hidden rounded-lg border">
        <div className="border-line-light flex items-center justify-between border-b px-5 py-4">
          <div className="grid gap-2">
            <div className="bg-bg-alt h-5 w-28 animate-pulse rounded" />
            <div className="bg-bg-alt h-3 w-44 animate-pulse rounded" />
          </div>
          <div className="bg-bg-alt h-8 w-24 animate-pulse rounded" />
        </div>
        <div className="grid gap-3 p-5">
          {Array.from({ length: 6 }, (_, index) => (
            <div
              key={index}
              className="bg-bg-alt h-12 animate-pulse rounded"
              aria-hidden="true"
            />
          ))}
        </div>
      </div>
    </section>
  );
}
