"use client";
import { useQuery } from "@tanstack/react-query";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import { api } from "@/lib/api";

export function NavChart({ code }: { code: string }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["navHistory", code], queryFn: () => api.navHistory(code),
  });
  if (isLoading) return <p className="text-sm text-gray-500">加载净值…</p>;
  if (error) return <p className="text-sm text-red-600">净值加载失败，请先 refresh_fund</p>;
  const points = (data!.navs ?? []).map((p) => ({
    date: p.nav_date, nav: p.accumulated_nav,
  }));
  return (
    <div style={{ width: "100%", height: 320 }}>
      <ResponsiveContainer>
        <LineChart data={points}>
          <XAxis dataKey="date" tick={{ fontSize: 11 }} />
          <YAxis domain={["auto", "auto"]} tick={{ fontSize: 11 }} />
          <Tooltip />
          <Line type="monotone" dataKey="nav" stroke="#2563eb" dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
