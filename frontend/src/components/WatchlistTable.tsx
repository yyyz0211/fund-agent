"use client";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight } from "lucide-react";
import { StateBlock } from "@/components/StateBlock";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api } from "@/lib/api";
import type { WatchlistRow } from "@/types/api";

interface WatchlistTableProps {
  error?: unknown;
  emptyMessage?: string;
  isLoading?: boolean;
  limit?: number;
  rows?: WatchlistRow[];
}

export function WatchlistTable({
  emptyMessage = "自选池为空。本阶段前端只读，请先在后端准备自选池数据。",
  error: externalError,
  isLoading: externalLoading,
  limit,
  rows: externalRows,
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
            <TH>备注</TH>
            <TH className="text-right">操作</TH>
          </TR>
        </THead>
        <TBody>
          {rows.map((r) => (
            <TR key={r.fund_code} className="hover:bg-gray-50/80">
              <TD>
                <code className="rounded bg-gray-100 px-2 py-1 text-xs font-medium text-gray-800">
                  {r.fund_code}
                </code>
              </TD>
              <TD className="text-gray-600">{r.note ?? "--"}</TD>
              <TD className="text-right">
                <Link
                  className="inline-flex items-center gap-1 text-sm font-medium text-blue-700 hover:text-blue-800"
                  href={`/funds/${r.fund_code}`}
                >
                  查看详情
                  <ArrowUpRight className="h-3.5 w-3.5" />
                </Link>
              </TD>
            </TR>
          ))}
        </TBody>
      </Table>
    </div>
  );
}
