"use client";
import { MarketSnapshot } from "@/lib/market";
import { ChangeCell } from "./MarketTableUtils";

export function ConceptSectorTable({ snap }: { snap: MarketSnapshot }) {
  const concepts = (snap.concept_sectors || []).slice(0, 20);
  const flows = snap.concept_flows || [];
  return (
    <div className="grid grid-cols-2 gap-4">
      <div>
        <h3 className="font-semibold mb-2 text-sm text-gray-700">概念涨跌幅</h3>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-gray-400 text-xs"><th className="text-left pb-1">概念</th><th className="text-right pb-1">涨跌幅</th></tr>
          </thead>
          <tbody>
            {concepts.map(s => (
              <tr key={s.name} className="border-t border-gray-100">
                <td className="py-1">{s.name}</td>
                <td className="text-right"><ChangeCell pct={s.change_pct} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div>
        <h3 className="font-semibold mb-2 text-sm text-gray-700">概念资金流向</h3>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-gray-400 text-xs"><th className="text-left pb-1">概念</th><th className="text-right pb-1">净流入(亿)</th></tr>
          </thead>
          <tbody>
            {flows.map(f => (
              <tr key={f.name} className="border-t border-gray-100">
                <td className="py-1">{f.name}</td>
                <td className={`text-right ${(f.net_flow ?? 0) >= 0 ? "text-green-600" : "text-red-600"}`}>
                  {((f.net_flow ?? 0) / 10000).toFixed(2)}亿
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
