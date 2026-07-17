"use client";

import { useQuery } from "@tanstack/react-query";
import { MessageSquareText, Plus } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { LANGGRAPH_ASSISTANT, LANGGRAPH_URL } from "@/lib/langgraph";
import { queryKeys } from "@/lib/query-keys";
import { queryPolicy } from "@/lib/query-policy";
import { Composer } from "./Composer";
import { useQaStream } from "./hooks/useQaStream";
import { useQaThreads } from "./hooks/useQaThreads";
import { MessageList } from "./MessageList";
import { ServiceStatusCard } from "./ServiceStatusCard";
import { ThreadSidebar } from "./ThreadSidebar";
import type { QaWorkbenchProps } from "./types";

export function QaWorkbench({ prefill }: QaWorkbenchProps) {
  const threadState = useQaThreads();
  const streamState = useQaStream({
    prefill,
    threadId: threadState.threadId,
    ensureActiveThread: threadState.ensureActiveThread,
    upsertThread: threadState.upsertThread,
    updateThreadHistory: threadState.updateThreadHistory,
  });

  const health = useQuery({
    queryKey: queryKeys.langgraph.health,
    queryFn: async () => {
      try {
        const response = await fetch(`${LANGGRAPH_URL}/ok`);
        return response.ok;
      } catch {
        return false;
      }
    },
    ...queryPolicy.langgraphHealth,
  });

  function switchThread(id: string) {
    threadState.switchThread(id);
    streamState.clearError();
  }

  function createThread() {
    threadState.newThread();
    streamState.clearError();
  }

  function deleteThread(id: string) {
    const switchesToRemaining =
      threadState.threadId === id && threadState.threads.length > 1;
    threadState.deleteThread(id);
    if (switchesToRemaining) streamState.clearError();
  }

  const statusText = health.isLoading
    ? "检查中"
    : health.data
      ? "LangGraph Server 在线"
      : "LangGraph Server 未连通";

  return (
    <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
      <PageHeader
        eyebrow="LangGraph QA"
        title="基金问答"
        description="直接连接 Phase 4 LangGraph Server。适合查询公开信息、历史净值和市场数据；买卖、推荐和收益预测类问题会被合规策略拦截。"
      />

      <div
        data-testid="qa-workbench"
        className="mt-6 grid min-h-[calc(100vh-220px)] grid-cols-1 gap-4 lg:grid-cols-[280px_minmax(0,1fr)]"
      >
        <aside className="space-y-4 lg:sticky lg:top-6 lg:self-start">
          <ThreadSidebar
            threads={threadState.threads}
            threadId={threadState.threadId}
            onNew={createThread}
            onSwitch={switchThread}
            onDelete={deleteThread}
          />
          <ServiceStatusCard
            loading={health.isLoading}
            online={health.data === true}
            assistant={LANGGRAPH_ASSISTANT}
            url={LANGGRAPH_URL}
          />
        </aside>

        <section className="min-w-0">
          <Card className="flex h-[calc(100vh-190px)] min-h-[680px] flex-col overflow-hidden p-0">
            <CardHeader className="mb-0 flex-row items-center justify-between gap-3 border-b border-gray-200 bg-white p-4">
              <div className="flex items-center gap-3">
                <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-gray-950 text-white">
                  <MessageSquareText className="h-5 w-5" />
                </span>
                <div>
                  <CardTitle className="text-base">
                    {threadState.threads.find(
                      (thread) => thread.id === threadState.threadId,
                    )?.title ?? "新对话"}
                  </CardTitle>
                  <p className="mt-1 text-xs text-gray-500">
                    {statusText} · {LANGGRAPH_ASSISTANT}
                  </p>
                </div>
              </div>
              <Button variant="outline" size="sm" type="button" onClick={createThread}>
                <Plus className="mr-1.5 h-3.5 w-3.5" />
                新对话
              </Button>
            </CardHeader>

            <CardContent className="flex min-h-0 flex-1 flex-col p-0">
              <MessageList
                error={streamState.error}
                history={threadState.history}
                streaming={streamState.streaming}
                onSuggestion={streamState.setInput}
              />
              <Composer
                input={streamState.input}
                streaming={streamState.streaming}
                onInputChange={streamState.setInput}
                onSend={streamState.send}
              />
            </CardContent>
          </Card>
        </section>
      </div>
    </main>
  );
}
