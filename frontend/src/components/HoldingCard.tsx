"use client";
import { Briefcase } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { StateBlock } from "@/components/StateBlock";
import { api } from "@/lib/api";
import { formatMoney, formatNav, formatPct, formatDate } from "@/lib/format";

/**
 * 持仓信息卡 — 只在 `is_holding=true && holding_share>0` 时显示。
 * 始终独立读取 `/api/portfolio/pnl?codes={code}`。不要复用详情页 summary
 * 里的 `pnl_item`,否则 NAV/交易更新后容易显示旧快照。
 */
export function HoldingCard({
  fundCode,
}: {
  fundCode: string;
}) {
  const pnl = useQuery({
    queryKey: ["portfolioPnl", [fundCode]],
    queryFn: () => api.portfolioPnl([fundCode]),
    refetchOnMount: "always",
  });

  const isLoading = pnl.isLoading;
  const error = pnl.error;
  const item = (pnl.data?.items ?? []).find((i) => i.fund_code === fundCode);

  if (isLoading) {
    return (
      <Card className="p-6">
        <CardHeader>
          <CardTitle className="text-base">持仓信息</CardTitle>
        </CardHeader>
        <CardContent>
          <StateBlock title="读取持仓" tone="loading">正在从自选池与本地 NAV 拉取持仓数据。</StateBlock>
        </CardContent>
      </Card>
    );
  }
  if (error) {
    return (
      <Card className="p-6">
        <CardHeader>
          <CardTitle className="text-base">持仓信息</CardTitle>
        </CardHeader>
        <CardContent>
          <StateBlock title="持仓加载失败" tone="error">{String(error)}</StateBlock>
        </CardContent>
      </Card>
    );
  }
  // 不是持仓 / 数据不足 → 整张卡不显示
  if (!item) return null;

  const isProfit = (item.pnl_abs ?? 0) >= 0;
  const isDailyProfit = (item.daily_pnl_abs ?? 0) >= 0;
  const accent = isProfit ? "text-emerald-700" : "text-rose-700";
  const dailyAccent = isDailyProfit ? "text-emerald-700" : "text-rose-700";
  const accentBg = isProfit ? "bg-emerald-50" : "bg-rose-50";
  // 交易表驱动:用 item.buy_date(已 recalc 成最早一笔) + 笔数提示;
  // 老数据(legacy):保持单行"买入日期"。
  const isTxBasis = (item.cost_nav_basis ?? "legacy") === "transactions";
  const txCount = item.transaction_count ?? 0;

  return (
    <Card className="p-6">
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-base">
            <Briefcase className="h-4 w-4 text-gray-500" />
            持仓信息
          </CardTitle>
          <span className="text-xs text-gray-500">数据日期 {formatDate(item.nav_date)}</span>
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Stat label="成本 NAV" value={formatNav(item.cost_nav)} />
          <Stat label="最新 NAV" value={formatNav(item.current_nav)} />
          <Stat label="持仓份额" value={item.holding_share.toLocaleString()} />
          <Stat
            label={isTxBasis ? "建仓" : "买入日期"}
            value={
              isTxBasis
                ? item.buy_date
                  ? `首次建仓 ${formatDate(item.buy_date)} · 加仓 ${txCount} 笔`
                  : `加仓 ${txCount} 笔`
                : item.buy_date
                  ? formatDate(item.buy_date)
                  : "—"
            }
          />
        </div>

        <div className={`mt-5 rounded-lg ${accentBg} p-4`}>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <div className="text-xs text-gray-500">投入本金</div>
              <div className="mt-1 text-lg font-semibold text-gray-900">
                ¥ {formatMoney(item.invested)}
              </div>
            </div>
            <div>
              <div className="text-xs text-gray-500">当前市值</div>
              <div className="mt-1 text-lg font-semibold text-gray-900">
                ¥ {formatMoney(item.market_value)}
              </div>
            </div>
            <div>
              <div className="text-xs text-gray-500">当日盈亏</div>
              <div className={`mt-1 text-lg font-semibold ${dailyAccent}`}>
                {formatSignedMoney(item.daily_pnl_abs)}
                <span className="ml-2 text-sm font-medium">
                  ({formatPct(item.daily_pnl_pct ?? item.daily_return)})
                </span>
              </div>
            </div>
            <div>
              <div className="text-xs text-gray-500">累计浮盈浮亏</div>
              <div className={`mt-1 text-lg font-semibold ${accent}`}>
                {formatSignedMoney(item.pnl_abs)}
                <span className="ml-2 text-sm font-medium">
                  ({formatPct(item.pnl_pct)})
                </span>
              </div>
            </div>
          </div>
        </div>

        <p className="mt-3 text-xs text-gray-500">
          来源 {pnl.data?.source ?? "akshare"} · as_of {formatDate(pnl.data?.as_of ?? item.nav_date)}。
          数字基于本地最新 NAV 与自选池记录，不含交易费用与分红再投调整。
        </p>
      </CardContent>
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-gray-50 p-3">
      <div className="text-xs text-gray-500">{label}</div>
      <div className="mt-1 text-sm font-semibold text-gray-900">{value}</div>
    </div>
  );
}

function formatSignedMoney(value: number | null | undefined) {
  if (value === null || value === undefined) return "—";
  const sign = value >= 0 ? "+" : "−";
  return `${sign}¥ ${formatMoney(Math.abs(value))}`;
}
