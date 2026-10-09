import { redirect } from "next/navigation";

/**
 * `/ingest` 已下线为顶级页面。
 * 文件上传统一从文件数据同步进入。
 */
export default function IngestRedirectPage() {
  redirect("/file-sync");
}
