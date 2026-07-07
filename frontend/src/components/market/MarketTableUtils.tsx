/** Shared market table utilities */
export function ChangeCell({ pct }: { pct: number }) {
  const color = pct > 0 ? "text-green-600" : pct < 0 ? "text-red-600" : "text-gray-500";
  const sign = pct > 0 ? "+" : "";
  return <span className={color}>{sign}{pct.toFixed(2)}%</span>;
}

const BAR_MAX = 5; // |pct| <= BAR_MAX 时填满，之外饱和用于视觉提示

export function ChangeBar({ pct }: { pct: number }) {
  const fillPct = Math.min(Math.abs(pct), BAR_MAX) / BAR_MAX * 100;
  const positive = pct >= 0;
  const bar = positive ? "bg-green-500" : "bg-red-500";
  const lightBar = positive ? "bg-green-100" : "bg-red-100";
  const textColor = positive ? "text-green-700" : pct < 0 ? "text-red-700" : "text-gray-500";
  const sign = positive ? "+" : "";
  return (
    <div className="flex items-center gap-2">
      <div className={`relative h-2 w-24 rounded-full ${lightBar} overflow-hidden`}>
        <div
          className={`absolute inset-y-0 left-0 ${bar} rounded-full`}
          style={{ width: `${fillPct}%` }}
        />
      </div>
      <span className={`font-mono text-xs tabular-nums ${textColor} w-14 text-right`}>
        {sign}{pct.toFixed(2)}%
      </span>
    </div>
  );
}
