import { useCallback, useEffect, useRef, useState } from "react";
import {
  loadActiveThreadId,
  loadThreadHistory,
  loadThreads,
  newThreadId,
  removeThreadHistory,
  saveActiveThreadId,
  saveThreadHistory,
  saveThreads,
} from "../storage";
import type { QaUiMessage, ThreadMeta } from "../types";

export function useQaThreads() {
  const [history, setHistory] = useState<QaUiMessage[]>([]);
  const [threadId, setThreadId] = useState<string | null>(null);
  const threadIdRef = useRef<string | null>(null);
  const [threads, setThreads] = useState<ThreadMeta[]>([]);

  const activateThread = useCallback(
    (id: string | null, messages?: QaUiMessage[]) => {
      threadIdRef.current = id;
      setThreadId(id);
      setHistory(id ? messages ?? loadThreadHistory(id) : []);
      saveActiveThreadId(id);
    },
    [],
  );

  const updateThreadHistory = useCallback(
    (id: string, updater: (current: QaUiMessage[]) => QaUiMessage[]) => {
      const next = updater(loadThreadHistory(id));
      saveThreadHistory(id, next);
      if (threadIdRef.current === id) setHistory(next);
      return next;
    },
    [],
  );

  useEffect(() => {
    const storedThreads = loadThreads();
    setThreads(storedThreads);
    const active = loadActiveThreadId();
    if (active && storedThreads.some((thread) => thread.id === active)) {
      activateThread(active);
    } else if (storedThreads.length > 0) {
      const sorted = [...storedThreads].sort((a, b) =>
        b.updatedAt.localeCompare(a.updatedAt),
      );
      activateThread(sorted[0].id);
    }
  }, [activateThread]);

  const upsertThread = useCallback((id: string, title: string) => {
    setThreads((current) => {
      const now = new Date().toISOString();
      const exists = current.some((thread) => thread.id === id);
      const next = exists
        ? current.map((thread) =>
            thread.id === id
              ? { ...thread, title: title || thread.title, updatedAt: now }
              : thread,
          )
        : [...current, { id, title: title || "新对话", updatedAt: now }];
      next.sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
      saveThreads(next);
      return next;
    });
  }, []);

  const switchThread = useCallback(
    (id: string) => {
      activateThread(id);
    },
    [activateThread],
  );

  const newThread = useCallback(() => {
    const id = newThreadId();
    saveThreadHistory(id, []);
    activateThread(id, []);
    upsertThread(id, "新对话");
    return id;
  }, [activateThread, upsertThread]);

  const ensureActiveThread = useCallback(() => {
    if (threadIdRef.current) return threadIdRef.current;
    const id = newThreadId();
    saveThreadHistory(id, []);
    activateThread(id, []);
    return id;
  }, [activateThread]);

  const deleteThread = useCallback(
    (id: string) => {
      const next = threads.filter((thread) => thread.id !== id);
      setThreads(next);
      saveThreads(next);
      removeThreadHistory(id);
      if (threadIdRef.current === id) {
        if (next.length > 0) activateThread(next[0].id);
        else activateThread(null, []);
      }
    },
    [activateThread, threads],
  );

  return {
    threadId,
    threads,
    history,
    switchThread,
    newThread,
    ensureActiveThread,
    deleteThread,
    upsertThread,
    updateThreadHistory,
  };
}
