"use client";
import { AlertCircle } from "lucide-react";
import { MarketSnapshot, normalizeMarketBreadth } from "@/lib/market";
import { MarketIndexCard } from "./MarketIndexCard";
import { trendBgClass, formatPctWithSign, trendTextClass } from "@/lib/market-format";

const LEAD_INDEX_NAMES = new Set(["上证指数", "深证成指", "创业板指", "科创50"]);

type Sentiment = { label: string; note: string; tone: string };

function sentimentFor(up: number, down: number): Sentiment {
  if (up === 0 && down === 0) return { label: "—", note: "暂无市场宽度数据", tone: "bg-gray-100 text-gray-600" };
  if (up > down * 1.3) return { label: "偏暖", note: "上涨家数占优", tone: trendBgClass(up - down) };
  if (down > up * 1.3) return { label: "偏弱", note: "下跌家数占优", tone: trendBgClass(up - down) };
  return { label: "震荡", note: "涨跌接近平衡", tone: trendBgClass(up - down) };
}

export function MarketHero({ snap }: { snap: MarketSnapshot }) {
  const breadth = normalizeMarketBreadth(snap.breadth);
  const { up, down, limit_up, limit_down } = breadth;
  const total = up + down;
  const upRatio = total > 0 ? (up / total) * 100 : 0;
  const downRatio = total > 0 ? (down / total) * 100 : 0;
  const hasError = Boolean(breadth.error);
  const isStale = Boolean(breadth.stale);
  const showEmpty = hasError || isStale || total === 0;
  const sentiment = showEmpty
    ? { label: hasError ? "异常" : "暂无数据", note: "市场宽度不可用", tone: "bg-gray-100 text-gray-600" }
    : sentimentFor(up, down);

  const lead = snap.indices.filter((i) => LEAD_INDEX_NAMES.has(i.name));
  const rest = snap.indices.filter((i) => !LEAD_INDEX_NAMES.has(i.name));
  const shown = lead.length > 0 ? lead : snap.indices.slice(0, 4);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {shown.map((idx) => (
          <MarketIndexCard
            key={idx.symbol}
            name={idx.name}
            close={idx.close}
            changePct={idx.change_pct}
            history={idx.history}
            weight="lead"
          />
        ))}
      </div>

      <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2 text-sm text-gray-500">
              <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                Market breadth · {snap.trade_date}
              </span>
              <span className={`rounded-full border border-gray-200 px-2 py-0.5 text-xs font-semibold ${sentiment.tone}`}>
                {sentiment.label}
              </span>
              <span>{sentiment.note}</span>
            </div>
            {showEmpty ? (
              <p className="mt-1.5 inline-flex items-start gap-1.5 rounded-md bg-amber-50 px-2.5 py-1.5 text-[11px] leading-4 text-amber-700">
                <AlertCircle className="mt-0.5 h-3 w-3 shrink-0" />
                <span>
                  {hasError
                    ? `数据源异常:${breadth.error}`
                    : isStale
                    ? `数据可能非交易日或接口静默失败${breadth.stale_reason ? `(${breadth.stale_reason})` : ""}`
                    : "今日总成交家数为 0,可能非交易日。"}
                </span>
              </p>
            ) : null}
          </div>

          <div className="grid grid-cols-4 gap-2 lg:min-w-[420px]">
            <Stat label="上涨" value={up} toneClass={showEmpty ? "text-gray-400" : "text-red-700"} sub={showEmpty ? "—" : `${upRatio.toFixed(1)}%`} />
            <Stat label="下跌" value={down} toneClass={showEmpty ? "text-gray-400" : "text-green-700"} sub={showEmpty ? "—" : `${downRatio.toFixed(1)}%`} />
            <Stat label="涨停" value={limit_up} toneClass={showEmpty ? "text-gray-400" : "text-red-700"} sub={showEmpty ? "—" : "情绪温度"} />
            <Stat label="跌停" value={limit_down} toneClass={showEmpty ? "text-gray-400" : "text-green-700"} sub={showEmpty ? "—" : "风险信号"} />
          </div>
        </div>

        <div className="mt-4 flex h-2.5 w-full overflow-hidden rounded-full bg-gray-100">
          {showEmpty ? (
            <div className="flex h-full w-full items-center justify-center text-[10px] text-gray-400">— 无市场宽度数据 —</div>
          ) : (
            <>
              <div className="bg-red-500" style={{ width: `${upRatio}%` }} />
              <div className="bg-green-500" style={{ width: `${downRatio}%` }} />
            </>
          )}
        </div>
      </div>

      {rest.length > 0 ? (
        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-gray-200 bg-white px-4 py-3 shadow-sm">
          <span className="text-xs font-semibold uppercase tracking-wide text-gray-500">其他指数</span>
          {rest.map((idx) => (
            <span
              key={idx.symbol}
              className="inline-flex items-center gap-1.5 rounded-full border border-gray-200 bg-gray-50 px-2.5 py-1 text-xs"
            >
              <span className="font-medium text-gray-700">{idx.name}</span>
              <span className={`tabular-nums ${trendTextClass(idx.change_pct)}`}>
                {formatPctWithSign(idx.change_pct)}
              </span>
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function Stat({ label, value, toneClass, sub }: { label: string; value: number; toneClass: string; sub?: string }) {
  return (
    <div className="rounded-lg bg-gray-50 px-3 py-2">
      <div className="text-[11px] text-gray-500">{label}</div>
      <div className={`mt-0.5 font-semibold tabular-nums ${toneClass}`}>{value}</div>
      {sub ? <div className="text-[10px] text-gray-500">{sub}</div> : null}
    </div>
  );
}
