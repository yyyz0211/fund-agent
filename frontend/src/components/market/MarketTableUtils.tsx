/** Shared market table utilities */
export function ChangeCell({ pct }: { pct: number }) {
  const color = pct > 0 ? "text-red-600" : pct < 0 ? "text-green-600" : "text-gray-500";
  const sign = pct > 0 ? "+" : "";
  return <span className={color}>{sign}{pct.toFixed(2)}%</span>;
}

const BAR_MAX = 5;
const BAR_MAX_WIDTH = 56;

export function ChangeBar({ pct }: { pct: number }) {
  const width = Math.max(3, Math.round((Math.min(Math.abs(pct), BAR_MAX) / BAR_MAX) * BAR_MAX_WIDTH));
  const positive = pct > 0;
  const negative = pct < 0;
  const bar = positive ? "bg-red-500" : negative ? "bg-green-500" : "bg-gray-300";
  const textColor = pct > 0 ? "text-red-700" : pct < 0 ? "text-green-700" : "text-gray-500";
  const sign = positive ? "+" : "";
  return (
    <div className="flex items-center gap-3">
      <div className="relative h-3 w-32 rounded-full bg-gray-100">
        <span className="absolute left-1/2 top-0 h-3 w-px translate-x-[1px] bg-gray-300" />
        <span
          className={`absolute left-1/2 top-1/2 h-2 -translate-y-1/2 rounded-full ${bar} ${
            negative ? "-translate-x-full" : ""
          }`}
          style={{ width }}
        />
      </div>
      <span className={`font-mono text-xs tabular-nums ${textColor} w-14 text-right`}>
        {sign}{pct.toFixed(2)}%
      </span>
    </div>
  );
}
