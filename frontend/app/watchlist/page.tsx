"use client";
import { useMemo, useState } from "react";
import { Plus, RefreshCw, Search } from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { PageHeader } from "@/components/PageHeader";
import { WatchlistDrawer } from "@/components/WatchlistDrawer";
import { WatchlistTable } from "@/components/WatchlistTable";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/Toast";
import { api } from "@/lib/api";
import { filterWatchlistRows } from "@/lib/watchlist-filter";
import { formatMoney, formatPct } from "@/lib/format";
import type { WatchlistRow } from "@/types/api";

export default function WatchlistPage() {
  const [q, setQ] = useState("");
  const [editing, setEditing] = useState<WatchlistRow | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [refreshingAll, setRefreshingAll] = useState(false);
  const [refreshAllProgress, setRefreshAllProgress] = useState<{ done: number; total: number } | null>(null);
  const qc = useQueryClient();
  const toast = useToast();

  const { data, error, isLoading } = useQuery({
    queryKey: ["watchlist"],
    queryFn: api.watchlist,
  });
  const portfolioPnl = useQuery({
    queryKey: ["portfolioPnl", []],
    queryFn: () => api.portfolioPnl(),
  });

  const filtered = useMemo(() => {
    if (!data) return [];
    return filterWatchlistRows(data, q);
  }, [data, q]);

  function openAdd() {
    setEditing(null);
    setDrawerOpen(true);
  }

  function openEdit(row: WatchlistRow) {
    setEditing(row);
    setDrawerOpen(true);
  }

  function closeDrawer() {
    setDrawerOpen(false);
    setEditing(null);
  }

  async function handleRefreshAll() {
    if (refreshingAll) return;
    const rowsToRefresh = data ?? [];
    if (rowsToRefresh.length === 0) {
      toast.push("没有可更新的自选基金", "info");
      return;
    }

    setRefreshingAll(true);
    setRefreshAllProgress({ done: 0, total: rowsToRefresh.length });
    let success = 0;
    let failed = 0;
    try {
      for (const row of rowsToRefresh) {
        try {
          await api.refreshFund(row.fund_code);
          success += 1;
          invalidateFundQueries(row.fund_code);
        } catch {
          failed += 1;
        } finally {
          setRefreshAllProgress({ done: success + failed, total: rowsToRefresh.length });
        }
      }
      qc.invalidateQueries({ queryKey: ["watchlist"] });
      qc.invalidateQueries({ queryKey: ["portfolioPnl", []] });
      toast.push(
        failed > 0
          ? `全量更新完成：成功 ${success} 只，失败 ${failed} 只`
          : `全量更新完成：成功 ${success} 只`,
        failed > 0 ? "info" : "success",
      );
    } finally {
      setRefreshingAll(false);
      setRefreshAllProgress(null);
    }
  }

  function invalidateFundQueries(code: string) {
    qc.invalidateQueries({ queryKey: ["fund", code] });
    qc.invalidateQueries({ queryKey: ["nav", code] });
    qc.invalidateQueries({ queryKey: ["navHistory", code] });
    qc.invalidateQueries({ queryKey: ["metrics", code] });
    qc.invalidateQueries({ queryKey: ["fundSummary", code] });
    qc.invalidateQueries({ queryKey: ["fundDiagnosis", code] });
    qc.invalidateQueries({ queryKey: ["portfolioPnl", [code]] });
    qc.invalidateQueries({ queryKey: ["portfolioPnl", []] });
  }

  const totals = portfolioPnl.data?.totals;
  const totalPnl = totals?.count ? totals.pnl_abs : null;
  const pnlTone = totalPnl == null
    ? "text-gray-500"
    : totalPnl > 0
      ? "text-red-600"
      : totalPnl < 0
        ? "text-green-600"
        : "text-gray-900";

  return (
    <main className="mx-auto max-w-6xl space-y-6 px-4 py-8 sm:px-6">
      <PageHeader
        eyebrow="Watchlist"
        title="自选池"
        description="本地维护的基金清单。可新建、编辑备注/持仓信息,或删除条目;搜索在前端完成,不会修改后端数据。"
        actions={
          <>
            <Button
              disabled={refreshingAll || isLoading || !data?.length}
              onClick={handleRefreshAll}
              type="button"
              variant="outline"
            >
              <RefreshCw className={`mr-2 h-4 w-4 ${refreshingAll ? "animate-spin" : ""}`} />
              {refreshAllProgress
                ? `全量更新 ${refreshAllProgress.done}/${refreshAllProgress.total}`
                : "全量更新"}
            </Button>
            <Button onClick={openAdd} type="button">
              <Plus className="mr-2 h-4 w-4" />
              加入自选
            </Button>
          </>
        }
      />

      <section className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="relative w-full sm:max-w-sm">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
            <Input
              className="pl-9"
              onChange={(e) => setQ(e.target.value)}
              placeholder="搜索基金代码或备注..."
              value={q}
            />
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <SummaryStat label="总盈亏" value={formatSignedMoney(portfolioPnl.data?.totals.pnl_abs, totals?.count)} valueClassName={pnlTone} />
            <SummaryStat label="收益率" value={totals?.count ? formatPct(totals.pnl_pct) : "--"} valueClassName={pnlTone} />
            <SummaryStat label="投入本金" value={totals?.count ? `¥ ${formatMoney(totals.invested)}` : "--"} />
            <SummaryStat label="当前市值" value={totals?.count ? `¥ ${formatMoney(totals.market_value)}` : "--"} />
          </div>
        </div>
        <div className="mt-3 flex flex-col gap-1 text-xs text-gray-500 sm:flex-row sm:items-center sm:justify-between">
          <p>{data ? `显示 ${filtered.length} / ${data.length} 行` : "等待数据加载"}</p>
          <p>
            {portfolioPnl.isLoading
              ? "正在计算持仓总盈亏"
              : portfolioPnl.error
                ? "总盈亏暂不可用"
                : `持仓 ${totals?.count ?? 0} 只 · as_of ${portfolioPnl.data?.as_of ?? "--"}`}
          </p>
        </div>
      </section>

      <WatchlistTable
        emptyMessage={q ? "没有匹配当前搜索条件的自选基金。" : "尚未加入任何自选基金。点击右上角“加入自选”开始记录。"}
        error={error}
        isLoading={isLoading}
        onEdit={openEdit}
        rows={filtered}
      />

      <WatchlistDrawer
        onClose={closeDrawer}
        open={drawerOpen}
        row={editing}
      />
    </main>
  );
}

function SummaryStat({
  label,
  value,
  valueClassName = "text-gray-900",
}: {
  label: string;
  value: string;
  valueClassName?: string;
}) {
  return (
    <div className="min-w-[120px] rounded-lg bg-gray-50 px-3 py-2">
      <div className="text-xs text-gray-500">{label}</div>
      <div className={`mt-1 text-sm font-semibold tabular-nums ${valueClassName}`}>{value}</div>
    </div>
  );
}

function formatSignedMoney(value: number | null | undefined, count: number | null | undefined) {
  if (!count || value === null || value === undefined) return "--";
  const sign = value > 0 ? "+" : value < 0 ? "-" : "";
  return `${sign}¥ ${formatMoney(Math.abs(value))}`;
}
