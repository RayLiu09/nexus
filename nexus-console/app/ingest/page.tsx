import { redirect } from "next/navigation";

/**
 * `/ingest` 已下线为顶级页面。
 * 文件上传请使用顶栏「快速上传」入口（QuickUploadDrawer）。
 * 旧链接重定向到数据源页，避免书签 404。
 */
export default function IngestRedirectPage() {
  redirect("/data-sources");
}
