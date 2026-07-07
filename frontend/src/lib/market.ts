import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

export interface MarketSnapshot {
  trade_date: string;
  snapshot_type: string;
  indices: Array<{ symbol: string; name: string; close: number; change_pct: number }>;
  breadth: { up: number; down: number; limit_up: number; limit_down: number };
  industry_sectors: Array<{ name: string; change_pct: number }>;
  concept_sectors: Array<{ name: string; change_pct: number }>;
  industry_flows: Array<{ name: string; net_flow: number }>;
  concept_flows: Array<{ name: string; net_flow: number }>;
  themes: Array<{ theme: string; count: number; stocks: Array<{ name: string }> }>;
  breadth_indicators: { board_height: Array<{ name: string; boards: number }> };
  overseas: Array<{ market: string; name: string; symbol: string; close: number | null; change_pct: number | null }>;
  announcements: Array<{ title: string; ann_date: string; fund_code: string; fund_name: string }>;
  source: string;
  as_of: string;
}

export function useMarketSnapshot(date: string, type: string) {
  return useQuery<MarketSnapshot>({
    queryKey: ["market", "snapshot", date, type],
    queryFn: () =>
      fetch(`/api/market/snapshot?date=${encodeURIComponent(date)}&type=${encodeURIComponent(type)}`).then(r => {
        if (!r.ok) throw new Error("failed");
        return r.json();
      }),
    staleTime: 5 * 60 * 1000,
    retry: 1,
  });
}

export function useRefreshMarket() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      fetch("/api/market/refresh", {
        method: "POST",
        headers: { "X-Local-Trigger": "1" },
      }).then(r => {
        if (!r.ok) throw new Error("failed");
        return r.json();
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["market"] });
    },
  });
}
