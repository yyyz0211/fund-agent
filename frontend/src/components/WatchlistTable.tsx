"use client";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api } from "@/lib/api";

export function WatchlistTable({ limit }: { limit?: number }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["watchlist"], queryFn: api.watchlist,
  });
  if (isLoading) return <p className="text-sm text-gray-500">加载自选池…</p>;
  if (error) return <p className="text-sm text-red-600">自选池加载失败</p>;
  const rows = limit ? (data ?? []).slice(0, limit) : data ?? [];
  if (rows.length === 0) {
    return (
      <p className="text-sm text-gray-500">
        自选池为空。请运行 <code>python -m backend.scripts.add_to_watchlist 110011</code> 添加。
      </p>
    );
  }
  return (
    <Table>
      <THead><TR><TH>基金代码</TH><TH>备注</TH><TH>操作</TH></TR></THead>
      <TBody>
        {rows.map((r) => (
          <TR key={r.fund_code}>
            <TD><code>{r.fund_code}</code></TD>
            <TD>{r.note ?? "—"}</TD>
            <TD><Link className="text-blue-600 hover:underline" href={`/funds/${r.fund_code}`}>查看详情</Link></TD>
          </TR>
        ))}
      </TBody>
    </Table>
  );
}
