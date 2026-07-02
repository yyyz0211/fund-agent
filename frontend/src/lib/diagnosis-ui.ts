import type { DiagnosisLabel, RiskLightLevel } from "@/types/api";

export function riskLightClass(level: RiskLightLevel): string {
  if (level === "red") return "border-red-200 bg-red-50 text-red-700";
  if (level === "yellow") return "border-amber-200 bg-amber-50 text-amber-700";
  if (level === "green") return "border-green-200 bg-green-50 text-green-700";
  return "border-gray-200 bg-gray-50 text-gray-500";
}

export function riskLightDotClass(level: RiskLightLevel): string {
  if (level === "red") return "bg-red-500";
  if (level === "yellow") return "bg-amber-500";
  if (level === "green") return "bg-green-500";
  return "bg-gray-400";
}

export function decisionLabelClass(label: DiagnosisLabel): string {
  if (label === "暂不碰") return "border-red-200 bg-red-50 text-red-700";
  if (label === "观察") return "border-amber-200 bg-amber-50 text-amber-700";
  if (label === "小仓试验") return "border-blue-200 bg-blue-50 text-blue-700";
  return "border-green-200 bg-green-50 text-green-700";
}

export function confidenceLabel(value: "low" | "medium" | "high"): string {
  if (value === "high") return "高";
  if (value === "medium") return "中";
  return "低";
}

export function compareUrlForPeers(code: string, peers: { fund_code: string }[]): string {
  const codes = [code, ...peers.map((peer) => peer.fund_code)]
    .filter(Boolean)
    .slice(0, 6);
  return `/compare?codes=${encodeURIComponent(codes.join(","))}`;
}
