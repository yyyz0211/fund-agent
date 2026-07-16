import { formatDate, formatMoney, formatNav } from "@/lib/format";
import type { WatchlistRow } from "@/types/api";

export function HoldingSnapshot({ row }: { row: WatchlistRow }) {
  const isTxBasis = row.cost_nav_basis === "transactions";
  return (
    <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-xs text-gray-600">
      <div className="font-medium text-gray-900">
        {isTxBasis ? "持仓由交易记录维护" : "已有持仓信息"}
      </div>
      <div className="mt-2 grid grid-cols-2 gap-2">
        <SummaryItem
          label="投入金额"
          value={row.holding_amount != null ? `¥ ${formatMoney(row.holding_amount)}` : "—"}
        />
        <SummaryItem
          label="持仓份额"
          value={row.holding_share != null ? row.holding_share.toFixed(2) : "—"}
        />
        <SummaryItem
          label="成本 NAV"
          value={row.cost_nav != null ? formatNav(row.cost_nav) : "—"}
        />
        <SummaryItem
          label="建仓日期"
          value={row.buy_date ? formatDate(row.buy_date) : "—"}
        />
      </div>
      <p className="mt-2 text-[11px] text-gray-500">
        追加投入请使用“加仓记录”,系统会按所选交易日期 NAV 自动重算份额和成本。
      </p>
    </div>
  );
}

export function SummaryItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[11px] text-gray-500">{label}</div>
      <div className="mt-0.5 font-medium text-gray-900">{value}</div>
    </div>
  );
}
