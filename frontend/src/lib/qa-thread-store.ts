export const QA_THREAD_MESSAGES_STORAGE_KEY = "qa_thread_messages_v1";

export interface QaToolStep {
  id: string;
  name: string;
  args: Record<string, unknown>;
  result?: string;
  status: "pending" | "done" | "error";
}

export interface QaUiMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  ts: string;
  toolSteps: QaToolStep[];
}

export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

export type QaThreadHistories = Record<string, QaUiMessage[]>;

function getStorage(storage?: StorageLike): StorageLike | null {
  if (storage) return storage;
  if (typeof window === "undefined") return null;
  return window.localStorage;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isToolStep(value: unknown): value is QaToolStep {
  if (!isRecord(value)) return false;
  return (
    typeof value.id === "string" &&
    typeof value.name === "string" &&
    isRecord(value.args) &&
    (value.result === undefined || typeof value.result === "string") &&
    (value.status === "pending" || value.status === "done" || value.status === "error")
  );
}

function isUiMessage(value: unknown): value is QaUiMessage {
  if (!isRecord(value)) return false;
  return (
    typeof value.id === "string" &&
    (value.role === "user" || value.role === "assistant") &&
    typeof value.content === "string" &&
    typeof value.ts === "string" &&
    Array.isArray(value.toolSteps) &&
    value.toolSteps.every(isToolStep)
  );
}

export function loadThreadHistories(storage?: StorageLike): QaThreadHistories {
  const resolved = getStorage(storage);
  if (!resolved) return {};
  try {
    const raw = resolved.getItem(QA_THREAD_MESSAGES_STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    if (!isRecord(parsed)) return {};
    const histories: QaThreadHistories = {};
    for (const [threadId, messages] of Object.entries(parsed)) {
      if (Array.isArray(messages)) {
        histories[threadId] = messages.filter(isUiMessage);
      }
    }
    return histories;
  } catch {
    return {};
  }
}

export function loadThreadHistory(threadId: string, storage?: StorageLike): QaUiMessage[] {
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
    const histories = loadThreadHistories(resolved);
    histories[threadId] = messages;
    resolved.setItem(QA_THREAD_MESSAGES_STORAGE_KEY, JSON.stringify(histories));
  } catch {
    // localStorage quota or privacy-mode failures should not break chat UI.
  }
}

export function removeThreadHistory(threadId: string, storage?: StorageLike): void {
  const resolved = getStorage(storage);
  if (!resolved) return;
  try {
    const histories = loadThreadHistories(resolved);
    delete histories[threadId];
    if (Object.keys(histories).length === 0) {
      resolved.removeItem(QA_THREAD_MESSAGES_STORAGE_KEY);
    } else {
      resolved.setItem(QA_THREAD_MESSAGES_STORAGE_KEY, JSON.stringify(histories));
    }
  } catch {
    // Ignore storage failures; the in-memory React state remains authoritative.
  }
}
