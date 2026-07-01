"use client";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, Pencil, Trash2 } from "lucide-react";
import { StateBlock } from "@/components/StateBlock";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import { useToast } from "@/components/Toast";
import { cn } from "@/lib/cn";
import { formatDate } from "@/lib/format";
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
  const shouldFetch = externalRows === undefined;
  const { data, isLoading, error } = useQuery({
    queryKey: ["watchlist"],
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
            <TH>基金代码</TH>
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
              {(handleEdit, handleDelete) => (
                <TR className="hover:bg-gray-50/80">
                  <TD>
                    <code className="rounded bg-gray-100 px-2 py-1 text-xs font-medium text-gray-800">
                      {r.fund_code}
                    </code>
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
                      <Link
                        className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-sm font-medium text-blue-700 hover:bg-blue-50 hover:text-blue-800"
                        href={`/funds/${r.fund_code}`}
                      >
                        查看
                        <ArrowUpRight className="h-3.5 w-3.5" />
                      </Link>
                      {onEdit && (
                        <Button
                          aria-label={`编辑 ${r.fund_code}`}
                          onClick={handleEdit}
                          size="sm"
                          variant="ghost"
                        >
                          <Pencil className="h-3.5 w-3.5" />
                        </Button>
                      )}
                      <Button
                        aria-label={`删除 ${r.fund_code}`}
                        onClick={handleDelete}
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

function TypeBadges({ row }: { row: WatchlistRow }) {
  const badges: { label: string; cls: string }[] = [];
  if (row.is_holding) badges.push({ label: "持仓", cls: "bg-green-50 text-green-700 ring-green-200" });
  if (row.is_focus) badges.push({ label: "关注", cls: "bg-blue-50 text-blue-700 ring-blue-200" });
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
  return <span className="text-xs">{parts.join(" · ")}</span>;
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
  ) => React.ReactNode;
}) {
  const qc = useQueryClient();
  const toast = useToast();

  function handleEdit() {
    if (onEdit) onEdit(row);
  }

  async function handleDelete() {
    if (typeof window !== "undefined") {
      const ok = window.confirm(`确认从自选池移除 ${row.fund_code}?`);
      if (!ok) return;
    }
    try {
      await api.watchlistRemove(row.fund_code);
      qc.invalidateQueries({ queryKey: ["watchlist"] });
      toast.push(`已从自选池移除 ${row.fund_code}`, "success");
    } catch (err) {
      toast.push(`移除失败：${String(err)}`, "error");
    }
  }

  return <>{children(handleEdit, handleDelete)}</>;
}