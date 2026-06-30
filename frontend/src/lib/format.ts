export function formatPct(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${(v * 100).toFixed(digits)}%`;
}

export function formatNav(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return v.toFixed(4);
}

export function formatDate(s: string | null | undefined): string {
  if (!s) return "—";
  return s.slice(0, 10);
}

export function formatMoney(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return v.toFixed(2);
}
