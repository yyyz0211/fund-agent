"use client";

import Link from "next/link";
import { AlertTriangle, GitCompareArrows, RefreshCw, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { StateBlock } from "@/components/StateBlock";
import {
  compareUrlForPeers,
  confidenceLabel,
  decisionLabelClass,
  riskLightClass,
  riskLightDotClass,
} from "@/lib/diagnosis-ui";
import { formatDate, formatPct } from "@/lib/format";
import type { FundDiagnosis, RiskLight } from "@/types/api";

interface FundDiagnosisCardProps {
  code: string;
  data: FundDiagnosis | undefined;
  error: unknown;
  isLoading: boolean;
  onRefresh: () => void;
  refreshing: boolean;
}

export function FundDiagnosisCard({
  code,
  data,
  error,
  isLoading,
  onRefresh,
  refreshing,
}: FundDiagnosisCardProps) {
  if (isLoading) {
    return <StateBlock title="加载基金体检" tone="loading">正在读取本地体检结果。</StateBlock>;
  }
  if (error) {
    return (
      <StateBlock
        action={<Button onClick={onRefresh} type="button">刷新体检数据</Button>}
        title="基金体检加载失败"
        tone="error"
      >
        本地暂时无法生成体检结果。
      </StateBlock>
    );
  }
  if (!data) {
    return (
      <StateBlock
        action={<Button onClick={onRefresh} type="button">刷新体检数据</Button>}
        title="暂无基金体检"
      >
        可先刷新画像数据，系统会在后台补充规模、同类候选和持仓集中度。
      </StateBlock>
    );
  }

  const compareHref = compareUrlForPeers(code, data.peers);

  return (
    <Card className="overflow-hidden p-0">
      <CardHeader className="border-b border-gray-100 bg-white p-5">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <CardTitle className="text-base">基金体检</CardTitle>
              <span className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${decisionLabelClass(data.decision_label)}`}>
                {data.decision_label}
              </span>
              <span className="rounded-full border border-gray-200 bg-gray-50 px-2.5 py-1 text-xs text-gray-600">
                置信度 {confidenceLabel(data.confidence)}
              </span>
            </div>
            <p className="max-w-3xl text-sm leading-6 text-gray-600">{data.summary}</p>
            <p className="text-xs text-gray-500">
              来源 {data.source} · as_of {formatDate(data.as_of)}
            </p>
          </div>
          <Button disabled={refreshing} onClick={onRefresh} type="button" variant="outline">
            <RefreshCw className={`mr-2 h-4 w-4 ${refreshing ? "animate-spin" : ""}`} />
            {refreshing ? "刷新中" : "刷新体检"}
          </Button>
        </div>
      </CardHeader>

      <CardContent className="space-y-5 p-5">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          {data.risk_lights.map((light) => (
            <RiskLightItem key={light.key} light={light} />
          ))}
        </div>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_1fr]">
          <div className="rounded-lg border border-gray-200 bg-white p-4">
            <div className="mb-3 flex items-center gap-2 text-sm font-medium text-gray-900">
              <ShieldCheck className="h-4 w-4 text-blue-600" />
              核心理由
            </div>
            <ul className="space-y-2 text-sm leading-6 text-gray-600">
              {data.reasons.length > 0
                ? data.reasons.map((reason) => <li key={reason}>· {reason}</li>)
                : <li>· 暂无明显异常理由。</li>}
            </ul>
          </div>

          <div className="rounded-lg border border-gray-200 bg-white p-4">
            <div className="mb-3 flex items-center gap-2 text-sm font-medium text-gray-900">
              <AlertTriangle className="h-4 w-4 text-amber-600" />
              避坑提示
            </div>
            <ul className="space-y-2 text-sm leading-6 text-gray-600">
              {data.pitfalls.length > 0
                ? data.pitfalls.map((item) => <li key={item.key}>· {item.detail}</li>)
                : <li>· 暂未触发明显避坑项。</li>}
            </ul>
          </div>
        </div>

        <div className="rounded-lg border border-gray-200 bg-gray-50 p-4">
          <div className="grid grid-cols-1 gap-4 text-sm md:grid-cols-2">
            <div>
              <p className="mb-2 font-medium text-gray-900">适合</p>
              <ul className="space-y-1 text-gray-600">
                {data.suitable_for.fit.map((item) => <li key={item}>· {item}</li>)}
              </ul>
            </div>
            <div>
              <p className="mb-2 font-medium text-gray-900">不适合</p>
              <ul className="space-y-1 text-gray-600">
                {data.suitable_for.avoid.map((item) => <li key={item}>· {item}</li>)}
              </ul>
            </div>
          </div>
        </div>

        {data.missing_data.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {data.missing_data.map((item) => (
              <span key={item} className="rounded-full bg-gray-100 px-2.5 py-1 text-xs text-gray-500">
                缺失 {item}
              </span>
            ))}
          </div>
        )}

        <div className="rounded-lg border border-gray-200 bg-white p-4">
          <div className="mb-3 flex items-center justify-between gap-3">
            <div>
              <p className="text-sm font-medium text-gray-900">同类候选</p>
              <p className="mt-1 text-xs text-gray-500">优先展示同类候选；缺少本地 NAV 时指标显示 --。</p>
            </div>
            {data.peers.length > 0 && (
              <Link href={compareHref}>
                <Button size="sm" type="button" variant="outline">
                  <GitCompareArrows className="mr-2 h-4 w-4" />
                  对比
                </Button>
              </Link>
            )}
          </div>
          {data.peers.length === 0 ? (
            <p className="rounded-lg bg-gray-50 p-3 text-sm text-gray-500">
              暂无同类候选数据，可先刷新体检数据。
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full text-left text-sm">
                <thead className="text-xs text-gray-500">
                  <tr>
                    <th className="py-2 pr-4 font-medium">基金</th>
                    <th className="py-2 pr-4 font-medium">类型</th>
                    <th className="py-2 pr-4 text-right font-medium">区间收益</th>
                    <th className="py-2 pr-4 text-right font-medium">最大回撤</th>
                    <th className="py-2 text-right font-medium">规模</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {data.peers.map((peer) => (
                    <tr key={peer.fund_code}>
                      <td className="py-2 pr-4">
                        <Link className="font-medium text-blue-700 hover:underline" href={`/funds/${peer.fund_code}`}>
                          {peer.fund_name ?? peer.fund_code}
                        </Link>
                        <div className="text-xs text-gray-500">{peer.fund_code}</div>
                      </td>
                      <td className="py-2 pr-4 text-gray-600">{peer.fund_type ?? "--"}</td>
                      <td className="py-2 pr-4 text-right tabular-nums">{formatPct(peer.period_return)}</td>
                      <td className="py-2 pr-4 text-right tabular-nums">{formatPct(peer.max_drawdown)}</td>
                      <td className="py-2 text-right tabular-nums">
                        {peer.scale === null || peer.scale === undefined ? "--" : `${peer.scale.toFixed(2)}亿`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function RiskLightItem({ light }: { light: RiskLight }) {
  return (
    <div className={`rounded-lg border p-3 ${riskLightClass(light.level)}`}>
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className={`h-2.5 w-2.5 rounded-full ${riskLightDotClass(light.level)}`} />
          <span className="text-sm font-medium">{light.label}</span>
        </div>
        <span className="text-sm font-semibold tabular-nums">{formatRiskValue(light)}</span>
      </div>
      <p className="mt-2 text-xs leading-5 opacity-80">{light.reason}</p>
    </div>
  );
}

function formatRiskValue(light: RiskLight) {
  const value = light.value;
  if (value === null || value === undefined) return "--";
  if (typeof value === "number") {
    if (
      light.key.includes("return") ||
      light.key.includes("drawdown") ||
      light.key.includes("volatility") ||
      light.key.includes("pct")
    ) {
      return formatPct(value);
    }
    if (light.key === "scale") return `${value.toFixed(2)}亿`;
    return value.toFixed(2);
  }
  return value;
}
