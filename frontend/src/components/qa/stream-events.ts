import type { QaUiMessage } from "./types";

export interface StreamToolCall {
  id: string;
  name: string;
  args?: Record<string, unknown>;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export interface StreamMessage {
  type?: string;
  role?: string;
  content?: unknown;
  tool_calls?: StreamToolCall[];
  tool_call_id?: string;
}

export function parseStreamMessage(data: unknown): StreamMessage | null {
  const raw = Array.isArray(data) ? data[data.length - 1] : data;
  return isRecord(raw) ? (raw as StreamMessage) : null;
}

export function isAssistantMessage(message: StreamMessage): boolean {
  return message.type === "ai" || message.role === "assistant";
}

export function isToolMessage(
  message: StreamMessage,
): message is StreamMessage & { tool_call_id: string } {
  return message.type === "tool" && typeof message.tool_call_id === "string";
}

export function readToolCalls(message: StreamMessage): StreamToolCall[] | null {
  const calls = message.tool_calls;
  return Array.isArray(calls) && calls.length > 0 ? calls : null;
}

export function readAssistantContent(content: unknown): string {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .map((part) => {
      if (typeof part === "string") return part;
      if (isRecord(part) && typeof part.text === "string") return part.text;
      return "";
    })
    .join("");
}

export function readToolResult(content: unknown): string {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) return readAssistantContent(content);
  return JSON.stringify(content ?? "");
}

export function appendPendingToolCalls(
  history: QaUiMessage[],
  assistantId: string,
  toolCalls: StreamToolCall[],
): QaUiMessage[] {
  const targetIndex = history.findIndex((message) => message.id === assistantId);
  if (targetIndex < 0) return history;

  const target = history[targetIndex];
  const knownIds = new Set(target.toolSteps.map((step) => step.id));
  const pending = toolCalls
    .filter((call) => !knownIds.has(call.id))
    .map((call) => ({
      id: call.id,
      name: call.name,
      args: call.args ?? {},
      status: "pending" as const,
    }));
  if (pending.length === 0) return history;

  return history.map((message, index) =>
    index === targetIndex
      ? { ...message, toolSteps: [...message.toolSteps, ...pending] }
      : message,
  );
}

export function completeToolStep(
  history: QaUiMessage[],
  assistantId: string,
  toolCallId: string,
  result: string,
): QaUiMessage[] {
  const targetIndex = history.findIndex((message) => message.id === assistantId);
  if (targetIndex < 0) return history;
  const target = history[targetIndex];
  const stepIndex = target.toolSteps.findIndex((step) => step.id === toolCallId);
  if (stepIndex < 0 || target.toolSteps[stepIndex].status === "done") return history;

  return history.map((message, index) =>
    index === targetIndex
      ? {
          ...message,
          toolSteps: message.toolSteps.map((step, currentStepIndex) =>
            currentStepIndex === stepIndex
              ? { ...step, status: "done" as const, result }
              : step,
          ),
        }
      : message,
  );
}

export function replaceAssistantContent(
  history: QaUiMessage[],
  assistantId: string,
  content: string,
): QaUiMessage[] {
  const targetIndex = history.findIndex((message) => message.id === assistantId);
  if (targetIndex < 0) return history;
  return history.map((message, index) =>
    index === targetIndex ? { ...message, content } : message,
  );
}
