"use client";
import { ArrowDownRight, ArrowUpRight } from "lucide-react";
import { Sparkline } from "./Sparkline";
import { trendTextClass, trendBgClass, formatPctWithSign } from "@/lib/market-format";

export interface MarketIndexCardProps {
  name: string;
  close: number;
  changePct: number;
  history?: number[] | null;
  weight?: "lead" | "normal";
}

export function MarketIndexCard({ name, close, changePct, history, weight = "normal" }: MarketIndexCardProps) {
  const positive = changePct > 0;
  const flat = changePct === 0;
  const Icon = positive ? ArrowUpRight : flat ? null : ArrowDownRight;

  const padding = weight === "lead" ? "p-5" : "p-4";
  const closeSize = weight === "lead" ? "text-3xl" : "text-2xl";

  return (
    <div className={`rounded-xl border border-gray-200 bg-white ${padding} shadow-sm transition hover:shadow-md`}>
      <div className="flex items-center justify-between gap-3">
        <div className="text-sm font-medium text-gray-600">{name}</div>
        <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold tabular-nums ${trendBgClass(changePct)}`}>
          {Icon ? <Icon className="h-3 w-3" /> : null}
          {formatPctWithSign(changePct)}
        </span>
      </div>
      <div className="mt-3 flex items-end justify-between gap-3">
        <div className={`${closeSize} font-semibold tracking-tight tabular-nums ${trendTextClass(changePct)}`}>
          {close.toFixed(2)}
        </div>
        {history && history.length >= 2 ? (
          <div className="opacity-90">
            <Sparkline
              points={history}
              width={weight === "lead" ? 110 : 80}
              height={weight === "lead" ? 36 : 28}
              toneClass={positive ? "text-red-500" : "text-green-500"}
            />
          </div>
        ) : null}
      </div>
    </div>
  );
}
