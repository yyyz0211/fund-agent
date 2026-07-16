import type { QaToolStep, QaUiMessage, ThreadMeta } from "./types";

export const QA_THREADS_STORAGE_KEY = "qa_threads_v1";
export const QA_ACTIVE_THREAD_STORAGE_KEY = "qa_active_thread_v1";
export const QA_THREAD_MESSAGES_STORAGE_KEY = "qa_thread_messages_v1";

export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

function getStorage(storage?: StorageLike): StorageLike | null {
  if (storage) return storage;
  if (typeof window === "undefined") return null;
  return window.localStorage;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function loadThreads(storage?: StorageLike): ThreadMeta[] {
  const resolved = getStorage(storage);
  if (!resolved) return [];

  try {
    const raw = resolved.getItem(QA_THREADS_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (thread): thread is ThreadMeta =>
        Boolean(
          thread &&
            typeof thread.id === "string" &&
            typeof thread.title === "string",
        ),
    );
  } catch {
    return [];
  }
}

export function saveThreads(threads: ThreadMeta[], storage?: StorageLike): void {
  getStorage(storage)?.setItem(QA_THREADS_STORAGE_KEY, JSON.stringify(threads));
}

export function loadActiveThreadId(storage?: StorageLike): string | null {
  return getStorage(storage)?.getItem(QA_ACTIVE_THREAD_STORAGE_KEY) ?? null;
}

export function saveActiveThreadId(
  threadId: string | null,
  storage?: StorageLike,
): void {
  const resolved = getStorage(storage);
  if (!resolved) return;
  if (threadId) resolved.setItem(QA_ACTIVE_THREAD_STORAGE_KEY, threadId);
  else resolved.removeItem(QA_ACTIVE_THREAD_STORAGE_KEY);
}

function isToolStep(value: unknown): value is QaToolStep {
  if (!isRecord(value)) return false;
  const step = value;
  return (
    typeof step.id === "string" &&
    typeof step.name === "string" &&
    isRecord(step.args) &&
    (step.status === "pending" ||
      step.status === "done" ||
      step.status === "error") &&
    (step.result === undefined || typeof step.result === "string")
  );
}

function isUiMessage(value: unknown): value is QaUiMessage {
  if (!isRecord(value)) return false;
  const message = value;
  return (
    typeof message.id === "string" &&
    (message.role === "user" || message.role === "assistant") &&
    typeof message.content === "string" &&
    typeof message.ts === "string" &&
    Array.isArray(message.toolSteps) &&
    message.toolSteps.every(isToolStep)
  );
}

export type QaThreadHistories = Record<string, QaUiMessage[]>;

export function loadThreadHistories(storage?: StorageLike): QaThreadHistories {
  const resolved = getStorage(storage);
  if (!resolved) return {};

  try {
    const raw = resolved.getItem(QA_THREAD_MESSAGES_STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};

    const result: QaThreadHistories = {};
    for (const [threadId, messages] of Object.entries(parsed)) {
      if (Array.isArray(messages)) {
        result[threadId] = messages.filter(isUiMessage);
      }
    }
    return result;
  } catch {
    return {};
  }
}

export function loadThreadHistory(
  threadId: string,
  storage?: StorageLike,
): QaUiMessage[] {
  return loadThreadHistories(storage)[threadId] ?? [];
}

export function saveThreadHistory(
  threadId: string,
  messages: QaUiMessage[],
  storage?: StorageLike,
): void {
  const resolved = getStorage(storage);
  if (!resolved) return;

  try {
    const allMessages = loadThreadHistories(resolved);
    allMessages[threadId] = messages;
    resolved.setItem(QA_THREAD_MESSAGES_STORAGE_KEY, JSON.stringify(allMessages));
  } catch {
    // A storage quota or privacy-mode failure must not break an active chat.
  }
}

export function removeThreadHistory(
  threadId: string,
  storage?: StorageLike,
): void {
  const resolved = getStorage(storage);
  if (!resolved) return;

  try {
    const allMessages = loadThreadHistories(resolved);
    delete allMessages[threadId];
    if (Object.keys(allMessages).length === 0) {
      resolved.removeItem(QA_THREAD_MESSAGES_STORAGE_KEY);
    } else {
      resolved.setItem(QA_THREAD_MESSAGES_STORAGE_KEY, JSON.stringify(allMessages));
    }
  } catch {
    // Keep deletion best-effort for the same reason as message persistence.
  }
}

export function newThreadId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `t_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}
