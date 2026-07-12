"use client";

import { Alert, Button, Tag, Typography } from "antd";
import { Bot, Loader2, RefreshCw, UserRound } from "lucide-react";

import type { KnowledgeChunkHit } from "@/lib/chunkTypes";

import type { ConversationMessage, MessageStatus } from "../_lib/playgroundTypes";
import { formatTime, statusColor, statusLabel } from "../_lib/playgroundHelpers";

import { LegacyQaResult, LegacySearchResult } from "./LegacyResults";
import { RetrievalConversationResult } from "./RetrievalConversationResult";

interface ConversationBubbleProps {
  message: ConversationMessage;
  progressTick: number;
  onSelectChunk: (chunk: KnowledgeChunkHit) => void;
  onRerun: (message: ConversationMessage) => void;
  onApplyRefinement: (text: string) => void;
}

export function ConversationBubble({
  message,
  progressTick,
  onSelectChunk,
  onRerun,
  onApplyRefinement,
}: ConversationBubbleProps) {
  const isUser = message.role === "user";
  return (
    <div className={`flex gap-3 ${isUser ? "justify-end" : "justify-start"}`}>
      {!isUser && <AssistantAvatar status={message.status} />}
      <div className={isUser ? "max-w-[76%]" : "max-w-[92%] flex-1"}>
        <div className={`mb-1 flex items-center gap-2 ${isUser ? "justify-end" : ""}`}>
          <Typography.Text strong>{isUser ? "用户" : "检索执行器"}</Typography.Text>
          <Typography.Text type="secondary" className="text-xs">
            {formatTime(message.createdAt)}
          </Typography.Text>
          {!isUser && <Tag color={statusColor(message.status)}>{statusLabel(message.status)}</Tag>}
        </div>

        {isUser ? (
          <div className="rounded-lg bg-[var(--brand)] px-4 py-3 text-[var(--text-inverse)]">
            <Typography.Paragraph className="!mb-0 whitespace-pre-wrap !text-inherit">
              {message.query}
            </Typography.Paragraph>
          </div>
        ) : (
          <div className="rounded-lg border border-[var(--line)] bg-[var(--surface)] p-4 shadow-sm">
            <AssistantMessageBody
              message={message}
              progressTick={progressTick}
              onSelectChunk={onSelectChunk}
              onApplyRefinement={onApplyRefinement}
            />
            <div className="mt-4 flex justify-end">
              <Button
                size="small"
                icon={<RefreshCw size={14} />}
                disabled={message.status === "running"}
                onClick={() => onRerun(message)}
              >
                重新执行
              </Button>
            </div>
          </div>
        )}
      </div>
      {isUser && (
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[var(--brand-soft)] text-[var(--brand)]">
          <UserRound size={17} aria-hidden="true" />
        </div>
      )}
    </div>
  );
}

function AssistantAvatar({ status }: { status: MessageStatus }) {
  return (
    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[var(--accent-bg)] text-[var(--accent-strong)]">
      {status === "running" ? (
        <Loader2 size={17} className="animate-spin" aria-hidden="true" />
      ) : (
        <Bot size={17} aria-hidden="true" />
      )}
    </div>
  );
}

interface AssistantMessageBodyProps {
  message: ConversationMessage;
  progressTick: number;
  onSelectChunk: (chunk: KnowledgeChunkHit) => void;
  onApplyRefinement: (text: string) => void;
}

function AssistantMessageBody({
  message,
  progressTick,
  onSelectChunk,
  onApplyRefinement,
}: AssistantMessageBodyProps) {
  if (message.error) {
    return <Alert type="error" showIcon title={message.error} />;
  }

  if (message.mode === "search") {
    return (
      <LegacySearchResult
        query={message.query}
        loading={message.status === "running"}
        data={message.searchData}
        onSelectChunk={onSelectChunk}
      />
    );
  }

  if (message.mode === "qa") {
    return (
      <LegacyQaResult
        query={message.query}
        loading={message.status === "running"}
        data={message.qaData}
        onSelectChunk={onSelectChunk}
      />
    );
  }

  return (
    <RetrievalConversationResult
      message={message}
      progressTick={progressTick}
      onApplyRefinement={onApplyRefinement}
    />
  );
}
