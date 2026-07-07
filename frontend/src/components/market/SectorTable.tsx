"use client";
import { ChangeBar } from "./MarketTableUtils";

interface Row {
  name: string;
  change_pct: number;
}

interface Flow {
  name: string;
  net_flow: number;
}

function formatFlow(value: number | null) {
  if (value == null || Number.isNaN(value)) return "--";
  const flowY = value / 10000;
  const sign = flowY > 0 ? "+" : "";
  return `${sign}${flowY.toFixed(2)}亿`;
}

export function SectorTable({
  title,
  rows,
  flows,
}: {
  title: string;
  rows: Row[];
  flows: Flow[];
}) {
  const flowMap = new Map(flows.map((f) => [f.name, f.net_flow]));
  const sorted = [...rows]
    .sort((a, b) => Math.abs(b.change_pct) - Math.abs(a.change_pct))
    .slice(0, 15);
  const strongest = sorted[0];
  return (
    <div className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
      <div className="flex items-center justify-between gap-3 border-b border-gray-100 px-4 py-3">
        <div>
          <h3 className="text-sm font-semibold text-gray-950">{title}</h3>
          <p className="mt-0.5 text-xs text-gray-500">按涨跌幅绝对值排序，显示波动最明显的方向</p>
        </div>
        {strongest && (
          <span className="rounded-full bg-gray-100 px-2.5 py-1 text-xs font-medium text-gray-600">
            {strongest.name}
          </span>
        )}
      </div>
      {sorted.length === 0 ? (
        <div className="px-4 py-10 text-center text-sm text-gray-400">暂无板块数据</div>
      ) : (
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 text-xs text-gray-500">
              <th className="px-4 py-2.5 text-left font-medium">名称</th>
              <th className="px-4 py-2.5 text-left font-medium">强弱</th>
              <th className="px-4 py-2.5 text-right font-medium">净流入</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((s) => {
              const hasFlow = flowMap.has(s.name);
              const nf = hasFlow ? flowMap.get(s.name) ?? null : null;
              const flowY = nf == null ? null : nf / 10000;
              const flowColor =
                flowY == null
                  ? "text-gray-400"
                  : flowY > 0
                  ? "text-red-700"
                  : flowY < 0
                  ? "text-green-700"
                  : "text-gray-500";
              return (
                <tr key={s.name} className="border-t border-gray-100 hover:bg-gray-50/70">
                  <td className="whitespace-nowrap px-4 py-3 font-medium text-gray-950">{s.name}</td>
                  <td className="px-4 py-3">
                    <ChangeBar pct={s.change_pct} />
                  </td>
                  <td
                    className={`whitespace-nowrap px-4 py-3 text-right font-mono text-xs tabular-nums ${flowColor}`}
                  >
                    {formatFlow(nf)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      )}
    </div>
  );
}
