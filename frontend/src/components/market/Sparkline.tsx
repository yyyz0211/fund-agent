"use client";
import { useMemo } from "react";

interface SparklineProps {
  points: number[];
  width?: number;
  height?: number;
  toneClass?: string;
  color?: string;
  className?: string;
  area?: boolean;
  ariaLabel?: string;
}

export function Sparkline({
  points,
  width = 96,
  height = 28,
  toneClass = "text-blue-500",
  color,
  className,
  area = true,
  ariaLabel,
}: SparklineProps) {
  const path = useMemo(() => {
    if (!points || points.length < 2) return null;
    const min = Math.min(...points);
    const max = Math.max(...points);
    const range = max - min || 1;
    const dx = width / (points.length - 1);
    const ys = points.map((p) => {
      const norm = (p - min) / range;
      return height - norm * (height - 4) - 2;
    });
    const line = ys.map((y, i) => `${i === 0 ? "M" : "L"}${(i * dx).toFixed(2)} ${y.toFixed(2)}`).join(" ");
    const fill = `${line} L${width.toFixed(2)} ${height} L0 ${height} Z`;
    return { line, fill };
  }, [points, width, height]);

  if (!path) {
    return (
      <svg width={width} height={height} className={className} aria-hidden="true">
        <line x1={0} y1={height / 2} x2={width} y2={height / 2} className="stroke-gray-200" strokeWidth={1} />
      </svg>
    );
  }

  const stroke = color ?? "currentColor";
  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className={["block", color ? undefined : toneClass, className].filter(Boolean).join(" ")}
      role={ariaLabel ? "img" : undefined}
      aria-label={ariaLabel}
    >
      {area ? <path d={path.fill} fill={stroke} fillOpacity={0.12} stroke="none" /> : null}
      <path d={path.line} fill="none" stroke={stroke} strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
