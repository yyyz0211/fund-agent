import type { ReactNode } from "react";
import { AlertCircle, Database, Loader2 } from "lucide-react";
import { cn } from "@/lib/cn";

type StateTone = "empty" | "error" | "loading";

const TONE_STYLES: Record<StateTone, string> = {
  empty: "border-gray-200 bg-white text-gray-600",
  error: "border-red-200 bg-red-50 text-red-700",
  loading: "border-gray-200 bg-white text-gray-600",
};

interface StateBlockProps {
  action?: ReactNode;
  children?: ReactNode;
  className?: string;
  title: string;
  tone?: StateTone;
}

export function StateBlock({ action, children, className, title, tone = "empty" }: StateBlockProps) {
  const Icon = tone === "error" ? AlertCircle : tone === "loading" ? Loader2 : Database;

  return (
    <div className={cn("rounded-lg border p-4 shadow-sm", TONE_STYLES[tone], className)}>
      <div className="flex items-start gap-3">
        <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-current/10 bg-white/70">
          <Icon className={cn("h-4 w-4", tone === "loading" && "animate-spin")} />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium">{title}</p>
          {children && <div className="mt-1 text-sm leading-6 text-current/80">{children}</div>}
          {action && <div className="mt-3">{action}</div>}
        </div>
      </div>
    </div>
  );
}
