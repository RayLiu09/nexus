"use client";

import { Alert, Skeleton } from "antd";
import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import type { NormalizedRefContent } from "@/lib/chunkTypes";
import type { QueryCitation } from "../_lib/queryTypes";
import { citationExcerpt, readableText } from "../_lib/citationPresentation";
import styles from "./Chat.module.css";

/** Open lazily; never present metadata or a failed read as document content. */
export function CitationContentPreview({ source }: { source: QueryCitation }) {
  const refId = source.source_type === "document" ? source.normalized_ref_id : null;
  const [state, setState] = useState<{
    refId: string | null;
    body?: string;
    error?: string;
  }>({ refId: null });

  useEffect(() => {
    if (!refId) return;
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await fetch(`/api/normalized-refs/${encodeURIComponent(refId)}/content`, {
          cache: "no-store",
          signal: controller.signal,
        });
        const payload = (await response.json()) as { ok: boolean; data?: NormalizedRefContent };
        if (!response.ok || !payload.ok || !payload.data) {
          throw new Error(
            [401, 403].includes(response.status)
              ? "暂无权限预览此资产，请重新登录或联系管理员。"
              : "资产正文暂时无法加载，请稍后重新打开引用重试。",
          );
        }
        const content = payload.data;
        const body = content.body_markdown || content.blocks?.map((block) => block.text ?? block.content ?? "").join("\n\n") || "";
        if (!controller.signal.aborted) setState({ refId, body: readableText(body) });
      } catch (error) {
        if (!controller.signal.aborted)
          setState({ refId, error: error instanceof Error ? error.message : "资产正文暂时无法加载。" });
      }
    })();
    return () => controller.abort();
  }, [refId]);

  if (refId && (state.refId !== refId || (!state.body && !state.error && state.body !== "")))
    return <div role="status" aria-label="正在加载资产正文"><Skeleton active paragraph={{ rows: 6 }} /></div>;
  if (refId && state.error) return <Alert type="warning" showIcon title={state.error} />;
  const body = refId ? state.body : citationExcerpt(source);
  return (
    <section aria-label="来源内容预览" className={styles.answer}>
      <p className="mb-3 text-sm font-medium text-gray-600">{refId ? "资产正文" : "来源内容"}</p>
      {body ? (
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          skipHtml
          components={{
            // Content never causes automatic requests to external image hosts.
            img: ({ alt }) => <span className="text-gray-400">{alt ? `（图片：${alt}）` : "（图片）"}</span>,
            a: ({ href, children }) => <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>,
          }}
        >{body}</ReactMarkdown>
      ) : <p className="text-sm text-gray-500">此资产暂无可预览的正文。</p>}
    </section>
  );
}
