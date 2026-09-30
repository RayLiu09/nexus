import { PageHeader } from "@/components/PageHeader";
import { CrawlerPlansPanel } from "./_components/CrawlerPlansPanel";

export const dynamic = "force-dynamic";

export default function CrawlerPage() {
  return (
    <>
      <PageHeader eyebrow="数据管理" title="Crawler 爬虫" description="管理抓取计划和运行记录。" />
      <CrawlerPlansPanel />
    </>
  );
}
