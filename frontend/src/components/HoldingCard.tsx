"use client";
import { Briefcase } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { StateBlock } from "@/components/StateBlock";
import { api } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import { formatMoney, formatNav, formatPct, formatDate } from "@/lib/format";
import type { PnlItem } from "@/types/api";

const missing = "--";

/**
 * 持仓信息卡 — 无持仓时也展示占位数据,避免详情页左列出现空白。
 * 始终独立读取 `/api/portfolio/pnl?codes={code}`。不要复用详情页 summary
 * 里的 `pnl_item`,否则 NAV/交易更新后容易显示旧快照。
 */
export function HoldingCard({
  fundCode,
}: {
  fundCode: string;
}) {
  const pnl = useQuery({
    queryKey: queryKeys.portfolio.pnl([fundCode]),
    queryFn: () => api.portfolioPnl([fundCode]),
    refetchOnMount: "always",
  });
  const pendingBuys = useQuery({
    queryKey: queryKeys.watchlist.pendingBuys(fundCode),
    queryFn: () => api.pendingBuys(fundCode),
    refetchOnMount: "always",
  });

  const isLoading = pnl.isLoading;
  const error = pnl.error;
  const item = (pnl.data?.items ?? []).find((i) => i.fund_code === fundCode);
  const pendingAmount = (pendingBuys.data ?? [])
    .filter((row) => row.status === "pending")
    .reduce((sum, row) => sum + (row.pending_amount ?? row.amount), 0);

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
  const empty = item == null;
  const isProfit = item ? item.pnl_abs >= 0 : true;
  const isDailyProfit = item ? (item.daily_pnl_abs ?? 0) >= 0 : true;
  const accent = empty ? "text-gray-900" : isProfit ? "text-emerald-700" : "text-rose-700";
  const dailyAccent = empty ? "text-gray-900" : isDailyProfit ? "text-emerald-700" : "text-rose-700";
  const accentBg = empty ? "bg-gray-50" : isProfit ? "bg-emerald-50" : "bg-rose-50";
  // 交易表驱动:用 item.buy_date(已 recalc 成最早一笔) + 笔数提示;
  // 老数据(legacy):保持单行"买入日期"。
  const isTxBasis = (item?.cost_nav_basis ?? "legacy") === "transactions";
  const txCount = item?.transaction_count ?? 0;
  const dataDate = item?.nav_date ?? pnl.data?.as_of;

  return (
    <Card className="p-6">
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-base">
            <Briefcase className="h-4 w-4 text-gray-500" />
            持仓信息
          </CardTitle>
          <span className="text-xs text-gray-500">数据日期 {formatOptionalDate(dataDate)}</span>
        </div>
      </CardHeader>
      <CardContent>
        {empty && (
          <p className="mb-4 rounded-lg bg-gray-50 p-3 text-sm text-gray-500">
            暂无持仓记录，持仓相关字段以 {missing} 占位。
          </p>
        )}
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Stat label="成本 NAV" value={formatOptionalNav(item?.cost_nav)} />
          <Stat label="最新 NAV" value={formatOptionalNav(item?.current_nav)} />
          <Stat label="持仓份额" value={formatShare(item?.holding_share)} />
          <Stat
            label={isTxBasis ? "建仓" : "买入日期"}
            value={formatBuyDate(item, isTxBasis, txCount)}
          />
        </div>

        <div className={`mt-5 rounded-lg ${accentBg} p-4`}>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
            <div>
              <div className="text-xs text-gray-500">投入本金</div>
              <div className="mt-1 text-lg font-semibold text-gray-900">
                {formatCurrency(item?.invested)}
              </div>
            </div>
            <div>
              <div className="text-xs text-gray-500">当前市值</div>
              <div className="mt-1 text-lg font-semibold text-gray-900">
                {formatCurrency(item?.market_value)}
              </div>
            </div>
            <div>
              <div className="text-xs text-gray-500">申购中金额</div>
              <div className="mt-1 text-lg font-semibold text-amber-700">
                {formatPendingAmount(pendingAmount, pendingBuys.isLoading, pendingBuys.error)}
              </div>
            </div>
            <div>
              <div className="text-xs text-gray-500">当日盈亏</div>
              <div className={`mt-1 text-lg font-semibold ${dailyAccent}`}>
                {formatSignedMoney(item?.daily_pnl_abs)}
                <span className="ml-2 text-sm font-medium">
                  ({formatOptionalPct(item?.daily_pnl_pct ?? item?.daily_return)})
                </span>
              </div>
            </div>
            <div>
              <div className="text-xs text-gray-500">累计浮盈浮亏</div>
              <div className={`mt-1 text-lg font-semibold ${accent}`}>
                {formatSignedMoney(item?.pnl_abs)}
                <span className="ml-2 text-sm font-medium">
                  ({formatOptionalPct(item?.pnl_pct)})
                </span>
              </div>
            </div>
          </div>
        </div>

        <p className="mt-3 text-xs text-gray-500">
          来源 {pnl.data?.source ?? "akshare"} · as_of {formatOptionalDate(pnl.data?.as_of ?? item?.nav_date)}。
          当前市值和盈亏只包含已确认份额；申购中金额单独展示，不含交易费用与分红再投调整。
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
  if (value === null || value === undefined) return missing;
  const sign = value >= 0 ? "+" : "−";
  return `${sign}¥ ${formatMoney(Math.abs(value))}`;
}

function formatCurrency(value: number | null | undefined) {
  if (value === null || value === undefined) return missing;
  return `¥ ${formatMoney(value)}`;
}

function formatPendingAmount(
  value: number,
  loading: boolean,
  error: unknown,
) {
  if (loading) return "读取中";
  if (error) return missing;
  return `¥ ${formatMoney(value)}`;
}

function formatOptionalDate(value: string | null | undefined) {
  if (!value) return missing;
  return formatDate(value);
}

function formatOptionalNav(value: number | null | undefined) {
  if (value === null || value === undefined) return missing;
  return formatNav(value);
}

function formatOptionalPct(value: number | null | undefined) {
  if (value === null || value === undefined) return missing;
  return formatPct(value);
}

function formatShare(value: number | null | undefined) {
  if (value === null || value === undefined) return missing;
  return value.toLocaleString();
}

function formatBuyDate(item: PnlItem | undefined, isTxBasis: boolean, txCount: number) {
  if (!item) return missing;
  if (isTxBasis) {
    return item.buy_date
      ? `首次建仓 ${formatDate(item.buy_date)} · 加仓 ${txCount} 笔`
      : `加仓 ${txCount} 笔`;
  }
  return item.buy_date ? formatDate(item.buy_date) : missing;
}
