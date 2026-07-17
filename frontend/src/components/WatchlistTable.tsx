"use client";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { Pencil, RefreshCw, Trash2 } from "lucide-react";
import { StateBlock } from "@/components/StateBlock";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import { useToast } from "@/components/Toast";
import { cn } from "@/lib/cn";
import { formatDate, formatPct } from "@/lib/format";
import type { WatchlistRow } from "@/types/api";

interface WatchlistTableProps {
  error?: unknown;
  emptyMessage?: string;
  isLoading?: boolean;
  limit?: number;
  rows?: WatchlistRow[];
  /** 编辑回调 —— 由上层(抽屉)接管实际保存。 */
  onEdit?: (row: WatchlistRow) => void;
}

export function WatchlistTable({
  emptyMessage = "自选池为空。点击右上角“加入自选”开始记录。",
  error: externalError,
  isLoading: externalLoading,
  limit,
  rows: externalRows,
  onEdit,
}: WatchlistTableProps) {
  const router = useRouter();
  const shouldFetch = externalRows === undefined;
  const { data, isLoading, error } = useQuery({
    queryKey: queryKeys.watchlist.all,
    queryFn: api.watchlist,
    enabled: shouldFetch,
  });
  if (externalLoading ?? isLoading) {
    return <StateBlock title="加载自选池" tone="loading">正在读取本地自选池。</StateBlock>;
  }
  if (externalError ?? error) {
    return <StateBlock title="自选池加载失败" tone="error">请确认 FastAPI 后端正在运行。</StateBlock>;
  }
  const rows = limit ? (externalRows ?? data ?? []).slice(0, limit) : externalRows ?? data ?? [];
  if (rows.length === 0) {
    return <StateBlock title="暂无自选基金">{emptyMessage}</StateBlock>;
  }
  return (
    <div className="overflow-hidden rounded-lg border border-gray-200 bg-white shadow-sm">
      <Table>
        <THead>
          <TR>
            <TH>基金</TH>
            <TH>当日盈亏</TH>
            <TH>类型</TH>
            <TH>持仓摘要</TH>
            <TH>备注</TH>
            <TH>更新时间</TH>
            <TH className="text-right">操作</TH>
          </TR>
        </THead>
        <TBody>
          {rows.map((r) => (
            <RowActions key={r.fund_code} row={r} onEdit={onEdit}>
              {(handleEdit, handleDelete, handleRefresh, isRefreshing) => (
                <TR
                  className="cursor-pointer transition hover:bg-blue-50/50 focus-within:bg-blue-50/50"
                  onClick={() => router.push(`/funds/${r.fund_code}`)}
                  onKeyDown={(event) => {
                    if (event.target !== event.currentTarget) return;
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      router.push(`/funds/${r.fund_code}`);
                    }
                  }}
                  role="link"
                  tabIndex={0}
                >
                  <TD>
                    <FundIdentity row={r} />
                  </TD>
                  <TD>
                    <DailyPnl row={r} />
                  </TD>
                  <TD>
                    <TypeBadges row={r} />
                  </TD>
                  <TD className="text-gray-600">
                    <HoldingSummary row={r} />
                  </TD>
                  <TD className="max-w-[260px] text-gray-600">
                    <span className="line-clamp-2 break-words">{r.note ?? "--"}</span>
                  </TD>
                  <TD className="text-xs text-gray-500">
                    {r.updated_at ? formatDate(r.updated_at) : "--"}
                  </TD>
                  <TD className="text-right">
                    <div className="inline-flex items-center gap-1">
                      {onEdit && (
                        <Button
                          aria-label={`编辑 ${r.fund_code}`}
                          onClick={(event) => {
                            event.stopPropagation();
                            handleEdit();
                          }}
                          size="sm"
                          variant="ghost"
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </Button>
                      )}
                      <Button
                        aria-label={`更新 ${r.fund_code}`}
                        disabled={isRefreshing}
                        onClick={(event) => {
                          event.stopPropagation();
                          handleRefresh();
                        }}
                        size="sm"
                        variant="ghost"
                      >
                        <RefreshCw className={cn("h-3.5 w-3.5 text-blue-600", isRefreshing && "animate-spin")} />
                      </Button>
                      <Button
                        aria-label={`删除 ${r.fund_code}`}
                        onClick={(event) => {
                          event.stopPropagation();
                          handleDelete();
                        }}
                        size="sm"
                        variant="ghost"
                      >
                        <Trash2 className="h-3.5 w-3.5 text-red-600" />
                      </Button>
                    </div>
                  </TD>
                </TR>
              )}
            </RowActions>
          ))}
        </TBody>
      </Table>
    </div>
  );
}

function FundIdentity({ row }: { row: WatchlistRow }) {
  return (
    <div className="min-w-[150px]">
      <div className="font-medium text-gray-950">
        {row.fund_name || "未拉取基金名称"}
      </div>
      <code className="mt-1 inline-flex rounded bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-700">
        {row.fund_code}
      </code>
    </div>
  );
}

function DailyPnl({ row }: { row: WatchlistRow }) {
  const pct = row.daily_pnl_pct ?? row.daily_return ?? null;
  const amount = row.daily_pnl_abs ?? null;
  if (pct == null && amount == null) {
    return <span className="text-xs text-gray-400">暂无净值</span>;
  }
  const tone = trendTextClass(amount ?? pct);
  return (
    <div className="min-w-[110px] text-right sm:text-left">
      {row.is_holding && amount != null ? (
        <div className={`font-semibold tabular-nums ${tone}`}>
          {formatSignedCurrency(amount)}
        </div>
      ) : (
        <div className={`font-semibold tabular-nums ${tone}`}>
          {formatPct(pct)}
        </div>
      )}
      <div className="mt-1 text-xs text-gray-500">
        {row.is_holding && amount != null ? formatPct(pct) : "日涨跌"}
        {row.nav_date ? ` · ${formatDate(row.nav_date)}` : ""}
      </div>
    </div>
  );
}

function TypeBadges({ row }: { row: WatchlistRow }) {
  const badges: { label: string; cls: string }[] = [];
  if (row.is_holding) badges.push({ label: "持仓", cls: "bg-green-50 text-green-700 ring-green-200" });
  if (row.is_focus) badges.push({ label: "关注", cls: "bg-blue-50 text-blue-700 ring-blue-200" });
  if (row.preload_status === "pending" || row.preload_status === "running") {
    badges.push({ label: "同步中", cls: "bg-amber-50 text-amber-700 ring-amber-200" });
  } else if (row.preload_status === "partial" || row.preload_status === "failed") {
    badges.push({ label: "部分缺失", cls: "bg-gray-50 text-gray-500 ring-gray-200" });
  }
  if (badges.length === 0) {
    return (
      <span className="inline-flex items-center rounded-md bg-gray-50 px-2 py-0.5 text-xs text-gray-500 ring-1 ring-gray-200">
        普通
      </span>
    );
  }
  return (
    <div className="flex flex-wrap gap-1">
      {badges.map((b) => (
        <span
          key={b.label}
          className={cn(
            "inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ring-1",
            b.cls,
          )}
        >
          {b.label}
        </span>
      ))}
    </div>
  );
}

function HoldingSummary({ row }: { row: WatchlistRow }) {
  if (!row.is_holding) return <span className="text-gray-400">--</span>;
  const parts: string[] = [];
  if (row.holding_amount != null) parts.push(`¥${row.holding_amount.toFixed(2)}`);
  if (row.holding_share != null) parts.push(`${row.holding_share.toFixed(2)} 份`);
  if (row.cost_nav != null) parts.push(`成本 ${row.cost_nav.toFixed(4)}`);
  if (parts.length === 0) return <span className="text-gray-500">已标记,待补字段</span>;
  return (
    <span className="text-xs">
      {parts.join(" · ")}
      {row.transaction_count != null && row.transaction_count > 0 && (
        <span className="text-gray-400"> · 加仓 {row.transaction_count} 笔</span>
      )}
    </span>
  );
}

function formatSignedCurrency(value: number) {
  const sign = value > 0 ? "+" : value < 0 ? "-" : "";
  return `${sign}¥${Math.abs(value).toFixed(2)}`;
}

function trendTextClass(value: number | null | undefined) {
  if (value == null) return "text-gray-600";
  if (value > 0) return "text-red-600";
  if (value < 0) return "text-green-600";
  return "text-gray-600";
}

/**
 * 渲染子元素模式(类似 render-prop)的删除确认封装,
 * 把 useQueryClient / toast / 删除的乐观更新集中在一处。
 */
function RowActions({
  row, onEdit, children,
}: {
  row: WatchlistRow;
  onEdit?: (row: WatchlistRow) => void;
  children: (
    handleEdit: () => void,
    handleDelete: () => void,
    handleRefresh: () => void,
    isRefreshing: boolean,
  ) => React.ReactNode;
}) {
  const qc = useQueryClient();
  const toast = useToast();
  const [isRefreshing, setRefreshing] = useState(false);

  function handleEdit() {
    if (onEdit) onEdit(row);
  }

  async function handleRefresh() {
    if (isRefreshing) return;
    setRefreshing(true);
    const code = row.fund_code;
    try {
      const result = await api.refreshFund(row.fund_code);
      qc.invalidateQueries({ queryKey: queryKeys.watchlist.all });
      qc.invalidateQueries({ queryKey: queryKeys.fund.detail(code) });
      qc.invalidateQueries({ queryKey: queryKeys.fund.navForFund(code) });
      qc.invalidateQueries({ queryKey: queryKeys.fund.navHistoryForFund(code) });
      qc.invalidateQueries({ queryKey: queryKeys.fund.metrics(code) });
      qc.invalidateQueries({ queryKey: queryKeys.fund.summaryForFund(code) });
      qc.invalidateQueries({ queryKey: queryKeys.fund.diagnosisForFund(code) });
      qc.invalidateQueries({ queryKey: queryKeys.portfolio.pnl([code]) });
      qc.invalidateQueries({ queryKey: queryKeys.portfolio.pnl([]) });
      if (result.already_up_to_date) {
        toast.push(`${row.fund_code} 已是最新`, "success");
      } else {
        toast.push(`${row.fund_code} 已更新，新增 ${result.navs_inserted} 条净值`, "success");
      }
    } catch (err) {
      toast.push(`更新失败：${String(err)}`, "error");
    } finally {
      setRefreshing(false);
    }
  }

  async function handleDelete() {
    if (typeof window !== "undefined") {
      const ok = window.confirm(`确认从自选池移除 ${row.fund_code}?`);
      if (!ok) return;
    }
    try {
      await api.watchlistRemove(row.fund_code);
      // 与详情页 `removeFromWatchlist` 对齐,后端级联删 Fund/FundNav
      // 后,前端也要把可能正显示在详情页的缓存一并失效,否则用户
      // 走到 `/funds/{fund_code}` 会看到"幽灵数据"。
      const code = row.fund_code;
      qc.invalidateQueries({ queryKey: queryKeys.watchlist.all });
      qc.invalidateQueries({ queryKey: queryKeys.fund.detail(code) });
      qc.invalidateQueries({ queryKey: queryKeys.fund.navForFund(code) });
      qc.invalidateQueries({ queryKey: queryKeys.fund.navHistoryForFund(code) });
      qc.invalidateQueries({ queryKey: queryKeys.fund.metrics(code) });
      qc.invalidateQueries({ queryKey: queryKeys.portfolio.pnl([code]) });
      qc.invalidateQueries({ queryKey: queryKeys.portfolio.pnl([]) });
      toast.push(`已从自选池移除 ${row.fund_code}`, "success");
    } catch (err) {
      toast.push(`移除失败：${String(err)}`, "error");
    }
  }

  return <>{children(handleEdit, handleDelete, handleRefresh, isRefreshing)}</>;
}
