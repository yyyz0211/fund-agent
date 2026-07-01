"use client";
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { cn } from "@/lib/cn";

export type ToastTone = "info" | "success" | "error";

interface ToastItem {
  id: number;
  message: string;
  tone: ToastTone;
}

interface ToastContextValue {
  push: (message: string, tone?: ToastTone) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within <ToastProvider>");
  return ctx;
}

const TOAST_TTL_MS = 3200;

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const push = useCallback((message: string, tone: ToastTone = "info") => {
    const id = Date.now() + Math.random();
    setItems((prev) => [...prev, { id, message, tone }]);
  }, []);

  useEffect(() => {
    if (items.length === 0) return;
    const timers = items.map((it) =>
      setTimeout(() => {
        setItems((prev) => prev.filter((p) => p.id !== it.id));
      }, TOAST_TTL_MS),
    );
    return () => timers.forEach(clearTimeout);
  }, [items]);

  return (
    <ToastContext.Provider value={{ push }}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-[320px] flex-col gap-2">
        {items.map((it) => (
          <div
            key={it.id}
            className={cn(
              "pointer-events-auto rounded-lg px-3 py-2 text-sm shadow-lg ring-1 transition",
              it.tone === "error" && "bg-red-50 text-red-800 ring-red-200",
              it.tone === "success" && "bg-green-50 text-green-800 ring-green-200",
              it.tone === "info" && "bg-white text-gray-800 ring-gray-200",
            )}
          >
            {it.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}