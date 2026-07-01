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
  // ISO datetime: 取本地时区的 YYYY-MM-DD HH:MM(无秒);纯日期串则取前 10。
  if (s.length > 10 && s.includes("T")) {
    const d = new Date(s);
    if (!Number.isNaN(d.getTime())) {
      const pad = (n: number) => String(n).padStart(2, "0");
      return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
    }
  }
  return s.slice(0, 10);
}

export function formatMoney(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return v.toFixed(2);
}
