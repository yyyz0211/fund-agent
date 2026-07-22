import { useCallback, useState } from "react";
import {
  ensureLangGraphThread,
  getLangGraphClient,
  LANGGRAPH_ASSISTANT,
} from "@/lib/langgraph";
import {
  appendPendingToolCalls,
  completeToolStep,
  isAssistantMessage,
  isToolMessage,
  parseStreamMessage,
  readAssistantContent,
  readToolCalls,
  readToolResult,
  replaceAssistantContent,
} from "../stream-events";
import type { QaUiMessage } from "../types";

interface UseQaStreamOptions {
  prefill?: string;
  threadId: string | null;
  ensureActiveThread: () => string;
  upsertThread: (id: string, title: string) => void;
  updateThreadHistory: (
    id: string,
    updater: (current: QaUiMessage[]) => QaUiMessage[],
  ) => QaUiMessage[];
}

export function useQaStream({
  prefill,
  threadId,
  ensureActiveThread,
  upsertThread,
  updateThreadHistory,
}: UseQaStreamOptions) {
  const [input, setInput] = useState(prefill ?? "");
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const clearError = useCallback(() => setError(null), []);

  const send = useCallback(async () => {
    const question = input.trim();
    if (!question || streaming) return;
    setError(null);

    const activeId = threadId ?? ensureActiveThread();
    upsertThread(activeId, question.slice(0, 24));
    const userMessage: QaUiMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: question,
      ts: new Date().toISOString(),
      toolSteps: [],
    };
    setInput("");
    setStreaming(true);
    const assistantId = crypto.randomUUID();
    const assistantMessage: QaUiMessage = {
      id: assistantId,
      role: "assistant",
      content: "",
      ts: new Date().toISOString(),
      toolSteps: [],
    };
    updateThreadHistory(activeId, (history) => [
      ...history,
      userMessage,
      assistantMessage,
    ]);

    try {
      const client = getLangGraphClient();
      await ensureLangGraphThread(activeId);
      const stream = client.runs.stream(activeId, LANGGRAPH_ASSISTANT, {
        input: { messages: [{ role: "human", content: question }] },
        streamMode: "messages",
      });

      for await (const event of stream) {
        const message = parseStreamMessage(event.data);
        if (!message) continue;

        if (isAssistantMessage(message)) {
          const toolCalls = readToolCalls(message);
          if (toolCalls) {
            updateThreadHistory(activeId, (history) =>
              appendPendingToolCalls(history, assistantId, toolCalls),
            );
          }
        }

        if (isToolMessage(message)) {
          const result = readToolResult(message.content);
          updateThreadHistory(activeId, (history) =>
            completeToolStep(
              history,
              assistantId,
              message.tool_call_id,
              result,
            ),
          );
        }

        if (isAssistantMessage(message)) {
          const chunk = readAssistantContent(message.content);
          if (chunk) {
            updateThreadHistory(activeId, (history) =>
              replaceAssistantContent(history, assistantId, chunk),
            );
          }
        }
      }
    } catch (caught) {
      const message = `连接 LangGraph Server 失败：${String(caught)}`;
      setError(message);
      updateThreadHistory(activeId, (history) =>
        replaceAssistantContent(history, assistantId, message),
      );
    } finally {
      setStreaming(false);
    }
  }, [
    ensureActiveThread,
    input,
    streaming,
    threadId,
    updateThreadHistory,
    upsertThread,
  ]);

  return { input, setInput, streaming, error, clearError, send };
}
