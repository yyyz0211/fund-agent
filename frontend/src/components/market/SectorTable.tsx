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
  return (
    <div className="rounded-lg border border-gray-200 bg-white shadow-sm overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-100">
        <h3 className="text-sm font-semibold text-gray-950">{title}</h3>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 text-xs text-gray-500">
              <th className="text-left font-medium px-4 py-2">名称</th>
              <th className="text-left font-medium px-4 py-2">涨跌幅</th>
              <th className="text-right font-medium px-4 py-2">净流入(亿)</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((s) => {
              const nf = flowMap.get(s.name) ?? 0;
              const flowY = nf / 10000;
              const flowColor =
                flowY > 0
                  ? "text-green-700"
                  : flowY < 0
                  ? "text-red-700"
                  : "text-gray-500";
              return (
                <tr key={s.name} className="border-t border-gray-100 hover:bg-gray-50/60">
                  <td className="px-4 py-2 text-gray-950">{s.name}</td>
                  <td className="px-4 py-2">
                    <ChangeBar pct={s.change_pct} />
                  </td>
                  <td
                    className={`px-4 py-2 text-right font-mono tabular-nums text-xs ${flowColor}`}
                  >
                    {flowY > 0 ? "+" : ""}
                    {flowY.toFixed(2)}亿
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
