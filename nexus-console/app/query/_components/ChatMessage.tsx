"use client";

import { Bubble, ThoughtChain } from "@ant-design/x";
import { Alert, Button, Drawer, Tag } from "antd";
import { Bot, Check, Copy, ExternalLink, LoaderCircle, UserRound } from "lucide-react";
import { useState } from "react";

import type { AgenticTurnState } from "./AgenticMessage";
import { QueryRouterAnswer } from "./QueryRouterAnswer";
import { CitationContentPreview } from "./CitationContentPreview";
import type { QueryCitation } from "../_lib/queryTypes";
import styles from "./Chat.module.css";
import { citationExcerpt, citationTitle, readableScope } from "../_lib/citationPresentation";

const SOURCE_LABELS = {
  document: "平台文档",
  record: "业务记录",
  aggregate: "数据统计",
  external_web: "网页来源",
};
const WARNING_LABELS: Record<string, string> = {
  answer_missing_citations: "回答缺少行内引用，请结合来源核对。",
  invalid_citation_removed: "回答中无效的引用已移除。",
  external_search_blocked_sensitive_query: "问题包含敏感信息，已跳过联网搜索。",
  external_search_blocked_local_scope: "问题限定平台资产范围，已跳过联网搜索。",
  public_api_http_401: "业务查询凭证无效，请联系管理员。",
  public_api_http_403: "业务查询未获授权，请联系管理员。",
  public_api_key_not_configured: "业务查询尚未配置，请联系管理员。",
};

function sourceUrl(url: string | null | undefined) {
  try {
    const parsed = new URL(url ?? "");
    return ["https:", "http:"].includes(parsed.protocol) && !parsed.username && !parsed.password
      ? parsed.href
      : null;
  } catch {
    return null;
  }
}

function actionDescription(step: AgenticTurnState["steps"][number]) {
  if (step.status === "cancelled") return "已停止";
  if (step.status === "failed") return "此步骤未完成";
  if (step.status === "running") return "执行中…";
  if (step.output?.outcome === "empty") return "未找到匹配内容";
  // Only new payloads identify the per-call count unambiguously. Older SSE
  // source_count values were cumulative, so do not attribute them to this call.
  const count = step.output?.source_count;
  const added = step.output?.new_source_count;
  if (typeof count === "number" && count > 0 && typeof added === "number") {
    return `本次取得 ${count} 条候选资料${added < count ? `，其中新增 ${added} 条` : ""}`;
  }
  return "已完成";
}

export function ChatMessage({ turn }: { turn: AgenticTurnState }) {
  const [source, setSource] = useState<QueryCitation | null>(null);
  const [copied, setCopied] = useState(false);
  const [allSources, setAllSources] = useState(false);
  const sources = turn.citations ?? [];
  const citedIds = new Set([...turn.markdown.matchAll(/\[(\d+)\](?!\()/g)].map((match) => match[1]));
  const citedSources = sources.filter((s) => citedIds.has(s.citation_id));
  const current = [...turn.steps].reverse().find((step) => step.status === "running");
  const failed = turn.steps.some((step) => step.status === "failed");
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(turn.markdown);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };
  return (
    <article className="w-full min-w-0 space-y-6" data-testid="query-turn">
      <Bubble
        placement="end"
        content={turn.query}
        avatar={<UserRound size={20} />}
        shape="corner"
        styles={{ content: { background: "#eef2ff", whiteSpace: "pre-wrap" } }}
      />
      <Bubble
        variant="borderless"
        avatar={<Bot size={22} className="text-indigo-600" />}
        styles={{
          content: { width: "100%", minWidth: 0, padding: 0 },
          body: { minWidth: 0, width: "100%" },
        }}
        content={
          <div className="min-w-0 space-y-4">
            <div className="flex items-center gap-2 text-sm font-medium">
              NEXUS <span className="font-normal text-gray-400">智能检索</span>
            </div>
            <details
              open={turn.isStreaming || undefined}
              className="rounded-xl border border-gray-200 bg-gray-50/70 px-4 py-3"
            >
              <summary className="cursor-pointer text-sm text-gray-600">
                {turn.isStreaming ? (
                  <LoaderCircle aria-hidden className="mr-2 inline animate-spin" size={14} />
                ) : null}
                {current?.label ??
                  (turn.cancelled
                    ? "已停止执行"
                    : failed
                      ? "执行结束，部分步骤未完成"
                      : "查看执行过程")}
                <span className="ml-2 text-xs text-gray-400">{turn.steps.length} 个动作</span>
              </summary>
              <div className="mt-4" aria-label="实时执行过程">
                <ThoughtChain
                  items={turn.steps.map((step) => ({
                    key: step.id,
                    title:
                      typeof step.input?.query_summary === "string" && step.input.query_summary
                        ? `${step.label} · ${step.input.query_summary}`
                        : step.label,
                    status:
                      step.status === "running"
                        ? "loading"
                        : step.status === "failed"
                          ? "error"
                          : step.status === "cancelled"
                            ? "error"
                            : "success",
                    description: actionDescription(step),
                  }))}
                />
              </div>
            </details>
            {turn.error ? (
              <Alert type="error" showIcon title="查询未完成" description={turn.error} />
            ) : null}
            {turn.markdown ? (
              <div className={styles.answer}>
                <QueryRouterAnswer
                  markdown={turn.markdown}
                  onSelectCitation={(id) =>
                    setSource(sources.find((s) => s.citation_id === id) ?? null)
                  }
                />
              </div>
            ) : (
              <p role="status" className="py-2 text-sm text-gray-400">
                {turn.cancelled ? "本次查询已停止。" : "正在查询资料并核对来源…"}
              </p>
            )}
            {turn.cancelled && turn.markdown ? (
              <p className="text-xs text-gray-500">已停止，以上为已接收的部分内容。</p>
            ) : null}
            {citedSources.length > 0 ? (
              <details aria-label="引用来源" className="border-t border-gray-100 pt-4">
                <summary className="cursor-pointer text-xs font-medium text-gray-500">
                  引用来源 · {citedSources.length}
                </summary>
                <div className={styles.sources}>
                  {(allSources ? citedSources : citedSources.slice(0, 6)).map((s) => (
                    <button
                      type="button"
                      key={s.citation_id}
                      onClick={() => setSource(s)}
                      className={styles.sourceCard}
                    >
                      <span className="text-xs text-indigo-600">
                        [{s.citation_id}] {SOURCE_LABELS[s.source_type]}
                      </span>
                      <span className="mt-1 block truncate text-sm font-medium">
                        {citationTitle(s)}
                      </span>
                      <span className={`${styles.sourceExcerpt} text-xs text-gray-500`}>
                        {citationExcerpt(s)}
                      </span>
                    </button>
                  ))}
                </div>
                {citedSources.length > 6 ? (
                  <Button type="link" size="small" onClick={() => setAllSources((value) => !value)}>
                    {allSources ? "收起来源" : `查看全部 ${citedSources.length} 条来源`}
                  </Button>
                ) : null}
              </details>
            ) : null}
            {turn.warnings.length > 0 ? (
              <details className="text-xs text-amber-700">
                <summary className="cursor-pointer">查看查询提示（{turn.warnings.length}）</summary>
                <ul className="mt-2 list-disc space-y-1 pl-4">
                  {turn.warnings.map((w) => (
                    <li key={w}>
                      {WARNING_LABELS[w] ??
                        "部分处理未完成，回答可能不完整，请查看执行过程或重试。"}
                    </li>
                  ))}
                </ul>
              </details>
            ) : null}
            {!turn.isStreaming && turn.markdown ? (
              <Button
                size="small"
                type="text"
                icon={copied ? <Check size={14} /> : <Copy size={14} />}
                onClick={() => void copy()}
              >
                {copied ? "已复制" : "复制回答"}
              </Button>
            ) : null}
          </div>
        }
      />
      <Drawer
        title={source ? `引用 [${source.citation_id}] · ${citationTitle(source)}` : "引用来源"}
        open={source !== null}
        onClose={() => setSource(null)}
        size="large"
      >
        {source ? (
          <div className="space-y-4">
            <Tag color={source.source_type === "external_web" ? "gold" : "blue"}>
              {SOURCE_LABELS[source.source_type]}
            </Tag>
            {source.source_type === "external_web" ? (
              <p className="text-sm text-amber-700">
                该引用来自公开网页，不代表已通过平台资产治理。
              </p>
            ) : null}
            {source.evidence_level === "metadata" ? (
              <p className="text-xs text-amber-700">回答检索时取得的是文档元数据，以下正文供进一步核对。</p>
            ) : null}
            <CitationContentPreview key={source.citation_id} source={source} />
            {source.truncated ? (
              <p className="text-xs text-gray-500">此处为节选，来源内容尚有后续。</p>
            ) : null}
            {source.published_at ? (
              <p className="text-xs text-gray-500">发布时间：{source.published_at}</p>
            ) : null}
            {source.collected_at ? (
              <p className="text-xs text-gray-500">采集时间：{source.collected_at}</p>
            ) : null}
            {!["query_market_jobs", "get_market_job"].includes(source.tool) && sourceUrl(source.url) ? (
              <a
                href={sourceUrl(source.url)!}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-blue-600"
              >
                打开网络资源 <ExternalLink size={14} />
              </a>
            ) : null}
            {readableScope(source).length > 0 ? (
              <div className="rounded-lg bg-gray-50 p-3 text-sm text-gray-500">
                <p className="mb-2 font-medium">查询条件</p>
                {readableScope(source).map((line) => (
                  <p key={line}>{line}</p>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}
      </Drawer>
    </article>
  );
}
