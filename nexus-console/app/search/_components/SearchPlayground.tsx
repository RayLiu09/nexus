"use client";

import { Card, Empty, Space } from "antd";
import { useCallback, useEffect, useRef, useState } from "react";

import { ChunkDetailDrawer } from "@/components/chunk/ChunkDetailDrawer";
import type { KnowledgeChunkHit } from "@/lib/chunkTypes";

import { fetchKnowledgeRetrieval, fetchQa, fetchSearch } from "../_lib/fetchers";
import { createId } from "../_lib/playgroundHelpers";
import type { ConversationMessage, Mode } from "../_lib/playgroundTypes";
import { DEFAULT_THRESHOLD, DEFAULT_TOP_K } from "../_lib/playgroundTypes";
import type { KnowledgeTypeOption } from "../_lib/searchTypes";

import { Composer } from "./Composer";
import { ConversationBubble } from "./ConversationBubble";
import { ConversationHeader } from "./ConversationHeader";
import { RunInspector } from "./RunInspector";

interface SearchPlaygroundProps {
  knowledgeTypes: KnowledgeTypeOption[];
}

export function SearchPlayground({ knowledgeTypes }: SearchPlaygroundProps) {
  const [mode, setMode] = useState<Mode>("retrieval");
  const [query, setQuery] = useState("");
  const [kb, setKb] = useState<string | undefined>(undefined);
  const [topK, setTopK] = useState<number>(DEFAULT_TOP_K);
  const [threshold, setThreshold] = useState<number>(DEFAULT_THRESHOLD);
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [progressTick, setProgressTick] = useState(0);
  const [selectedChunk, setSelectedChunk] = useState<KnowledgeChunkHit | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const feedRef = useRef<HTMLDivElement | null>(null);

  const loading = activeRunId !== null;

  useEffect(() => {
    if (!loading) return;
    const timer = window.setInterval(() => {
      setProgressTick((value) => value + 1);
    }, 900);
    return () => window.clearInterval(timer);
  }, [loading]);

  useEffect(() => {
    feedRef.current?.scrollTo({
      top: feedRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages, progressTick]);

  const appendUserAndAssistant = useCallback((trimmed: string, runMode: Mode): string => {
    const now = new Date();
    const runId = createId("run");
    const userMessage: ConversationMessage = {
      id: createId("user"),
      role: "user",
      mode: runMode,
      query: trimmed,
      createdAt: now,
      status: "completed",
    };
    const assistantMessage: ConversationMessage = {
      id: runId,
      role: "assistant",
      mode: runMode,
      query: trimmed,
      createdAt: now,
      status: "running",
    };
    setMessages((prev) => [...prev, userMessage, assistantMessage]);
    setActiveRunId(runId);
    setProgressTick(0);
    setQuery("");
    return runId;
  }, []);

  const completeRun = useCallback((runId: string, patch: Partial<ConversationMessage>) => {
    setMessages((prev) =>
      prev.map((message) =>
        message.id === runId
          ? {
              ...message,
              ...patch,
            }
          : message,
      ),
    );
    setActiveRunId(null);
  }, []);

  const executeQuery = useCallback(
    async (trimmed: string, runMode: Mode) => {
      if (!trimmed || activeRunId) return;
      const runId = appendUserAndAssistant(trimmed, runMode);
      try {
        if (runMode === "search") {
          const data = await fetchSearch(trimmed, kb, topK, threshold);
          completeRun(runId, { status: "completed", searchData: data });
          return;
        }
        if (runMode === "qa") {
          const data = await fetchQa(trimmed, kb, topK);
          completeRun(runId, { status: "completed", qaData: data });
          return;
        }

        const data = await fetchKnowledgeRetrieval(trimmed);
        completeRun(runId, {
          status: data.status === "needs_clarification" ? "needs_clarification" : "completed",
          retrievalData: data,
        });
      } catch (err) {
        completeRun(runId, {
          status: "failed",
          error: err instanceof Error ? err.message : String(err),
        });
      }
    },
    [activeRunId, appendUserAndAssistant, completeRun, kb, threshold, topK],
  );

  const handleSubmit = useCallback(async () => {
    const trimmed = query.trim();
    await executeQuery(trimmed, mode);
  }, [executeQuery, mode, query]);

  const rerunMessage = useCallback(
    (message: ConversationMessage) => {
      if (loading) return;
      void executeQuery(message.query, message.mode);
    },
    [executeQuery, loading],
  );

  const applyRefinement = useCallback(
    (text: string) => {
      if (loading) return;
      setMode("retrieval");
      setQuery(text);
    },
    [loading],
  );

  const openChunkDetail = useCallback((chunk: KnowledgeChunkHit) => {
    setSelectedChunk(chunk);
    setDrawerOpen(true);
  }, []);

  return (
    <>
      <section className="grid min-h-[calc(100vh-210px)] grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        <Card className="overflow-hidden" styles={{ body: { padding: 0 } }}>
          <div className="flex min-h-[calc(100vh-230px)] flex-col bg-[var(--surface)]">
            <ConversationHeader mode={mode} loading={loading} onClear={() => setMessages([])} />

            <div ref={feedRef} className="flex-1 overflow-y-auto bg-[var(--surface-alt)] px-4 py-5">
              {messages.length === 0 ? (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="暂无检索会话"
                  className="mt-20"
                />
              ) : (
                <Space orientation="vertical" size="large" className="w-full">
                  {messages.map((message) => (
                    <ConversationBubble
                      key={message.id}
                      message={message}
                      progressTick={progressTick}
                      onSelectChunk={openChunkDetail}
                      onRerun={rerunMessage}
                      onApplyRefinement={applyRefinement}
                    />
                  ))}
                </Space>
              )}
            </div>

            <Composer
              mode={mode}
              query={query}
              loading={loading}
              onModeChange={setMode}
              onQueryChange={setQuery}
              onSubmit={handleSubmit}
              kb={kb}
              topK={topK}
              threshold={threshold}
              knowledgeTypes={knowledgeTypes}
              onKbChange={setKb}
              onTopKChange={setTopK}
              onThresholdChange={setThreshold}
            />
          </div>
        </Card>

        <RunInspector
          latestAssistant={[...messages].reverse().find((message) => message.role === "assistant")}
          progressTick={progressTick}
        />
      </section>

      <ChunkDetailDrawer
        chunk={selectedChunk}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
      />
    </>
  );
}
