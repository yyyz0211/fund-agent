import { useState } from "react";
import Link from "next/link";
import {
  Check,
  ChevronDown,
  ChevronRight,
  Database,
  ExternalLink,
  Loader2,
} from "lucide-react";
import type { QaToolStep } from "./types";

const TOOLS_WITH_FUND_CODE = new Set([
  "refresh_fund",
  "get_fund_nav_history",
  "get_latest_fund_nav",
  "get_fund_basic_info",
  "calculate_holding_pnl",
]);

function extractFundCode(args: Record<string, unknown>): string | null {
  const raw = args.fund_code ?? args.code;
  return typeof raw === "string" && raw.length > 0 ? raw : null;
}

export function ToolStepList({ steps }: { steps: QaToolStep[] }) {
  if (steps.length === 0) return null;
  return (
    <div className="mt-3 space-y-2 rounded-lg border border-gray-200 bg-gray-50 p-3">
      <div className="flex items-center gap-1.5 text-xs font-medium text-gray-500">
        <Database className="h-3.5 w-3.5" />
        已查询的数据 ({steps.length})
      </div>
      <ul className="space-y-1.5">
        {steps.map((step) => (
          <ToolStepItem key={step.id} step={step} />
        ))}
      </ul>
    </div>
  );
}

function ToolStepItem({ step }: { step: QaToolStep }) {
  const [open, setOpen] = useState(false);
  const argsJson = JSON.stringify(step.args, null, 2);
  const fundCode = TOOLS_WITH_FUND_CODE.has(step.name)
    ? extractFundCode(step.args)
    : null;
  return (
    <li className="rounded-md border border-gray-200 bg-gray-50">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-xs text-gray-700 hover:bg-gray-100"
      >
        {open ? (
          <ChevronDown className="h-3.5 w-3.5 shrink-0 text-gray-400" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 shrink-0 text-gray-400" />
        )}
        {step.status === "pending" ? (
          <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-gray-400" />
        ) : (
          <Check className="h-3.5 w-3.5 shrink-0 text-green-600" />
        )}
        <span className="font-mono font-medium text-gray-800">{step.name}</span>
        {fundCode && (
          <span className="inline-flex items-center gap-1 rounded-full border border-blue-200 bg-blue-50 px-2 py-0.5 font-mono text-[10px] text-blue-700">
            {fundCode}
          </span>
        )}
        <span className="ml-auto truncate font-mono text-[11px] text-gray-500">
          {truncate(argsJson, 80)}
        </span>
      </button>
      {open && (
        <div className="space-y-2 border-t border-gray-200 bg-white p-2.5">
          {fundCode && (
            <Link
              href={`/funds/${encodeURIComponent(fundCode)}`}
              className="inline-flex items-center gap-1.5 rounded-md border border-blue-200 bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700 transition hover:border-blue-300 hover:bg-blue-100"
            >
              <ExternalLink className="h-3.5 w-3.5" />
              查看基金详情（{fundCode}）
            </Link>
          )}
          <div>
            <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-gray-500">
              参数
            </div>
            <pre className="overflow-x-auto rounded bg-gray-50 p-2 font-mono text-[11px] leading-5 text-gray-700">
              {argsJson}
            </pre>
          </div>
          {step.result !== undefined && (
            <div>
              <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-gray-500">
                返回
              </div>
              <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded bg-gray-50 p-2 font-mono text-[11px] leading-5 text-gray-700">
                {truncate(step.result, 4000)}
              </pre>
            </div>
          )}
        </div>
      )}
    </li>
  );
}

function truncate(value: string, length: number): string {
  return value.length > length ? value.slice(0, length) + "…" : value;
}
