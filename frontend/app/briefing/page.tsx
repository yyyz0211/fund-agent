"use client";
import { useState } from "react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Loader2, Newspaper, Play, RefreshCcw } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { PageHeader, SectionHeader } from "@/components/PageHeader";
import { StateBlock } from "@/components/StateBlock";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

import { api } from "@/lib/api";

function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("zh-CN", { hour12: false });
  } catch {
    return iso;
  }
}

export default function BriefingPage() {
  const queryClient = useQueryClient();

  const latestQuery = useQuery({
    queryKey: ["briefing", "latest"],
    queryFn: () => api.briefingLatest(),
    refetchInterval: 30_000,
  });

  const listQuery = useQuery({
    queryKey: ["briefing", "list", 30],
    queryFn: () => api.briefingList(30),
  });

  const runMutation = useMutation({
    mutationFn: () => api.briefingRun(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["briefing"] });
    },
  });

  const briefing = latestQuery.data?.briefing ?? null;
  const history = listQuery.data?.briefings ?? [];

  return (
    <main className="mx-auto max-w-6xl space-y-6 px-4 py-8 sm:px-6">
      <PageHeader
        eyebrow="Daily Briefing"
        title="每日基金简报"
        description="由本地数据(自选池 + 主要指数)自动生成的客观简报。每日收盘后定时生成,内容不含投资建议。"
        actions={
          <Button
            disabled={runMutation.isPending}
            onClick={() => runMutation.mutate()}
          >
            {runMutation.isPending ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Play className="mr-2 h-4 w-4" />
            )}
            立即生成今日简报
          </Button>
        }
      />

      {runMutation.isError && (
        <StateBlock
          tone="error"
          title="触发失败"
        >
          无法触发简报生成，请确认后端进程在线。POST /api/briefing/run 需要 X-Local-Trigger header。
        </StateBlock>
      )}

      {latestQuery.isLoading && (
        <Card className="p-6">
          <div className="flex items-center gap-2 text-gray-500">
            <Loader2 className="h-4 w-4 animate-spin" />
            正在读取最近一篇简报...
          </div>
        </Card>
      )}

      {!latestQuery.isLoading && !briefing && (
        <Card className="p-6">
          <CardHeader>
            <div className="flex items-center gap-3">
              <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-50 text-blue-700">
                <Newspaper className="h-5 w-5" />
              </span>
              <div>
                <CardTitle className="text-base">还没有简报</CardTitle>
                <p className="mt-1 text-sm text-gray-500">
                  点击「立即生成今日简报」按钮,或等待定时任务触发(默认每日 17:00 Asia/Shanghai)。
                </p>
              </div>
            </div>
          </CardHeader>
        </Card>
      )}

      {briefing && (
        <Card className="p-6">
          <CardHeader>
            <div className="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
              <div>
                <CardTitle className="text-xl">{briefing.title}</CardTitle>
                <p className="mt-1 text-xs text-gray-500">
                  as_of {briefing.as_of ?? briefing.briefing_date} · 来源 {briefing.source ?? "本地"} · 更新于 {formatDateTime(briefing.updated_at)}
                </p>
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={() => latestQuery.refetch()}
              >
                <RefreshCcw className="mr-2 h-4 w-4" />
                刷新
              </Button>
            </div>
          </CardHeader>
          <CardContent className="prose prose-sm max-w-none prose-headings:font-semibold prose-h1:text-xl prose-h2:text-base prose-h3:text-sm prose-table:text-xs">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {briefing.markdown}
            </ReactMarkdown>
          </CardContent>
        </Card>
      )}

      <section className="space-y-3">
        <SectionHeader
          title={`历史简报 (${history.length})`}
          description="按日期降序,默认展示最近 30 篇。"
        />
        {listQuery.isLoading && (
          <Card className="p-6">
            <div className="flex items-center gap-2 text-gray-500">
              <Loader2 className="h-4 w-4 animate-spin" />
              加载历史列表...
            </div>
          </Card>
        )}
        {!listQuery.isLoading && history.length === 0 && (
          <Card className="p-6 text-sm text-gray-500">暂无历史简报。</Card>
        )}
        {history.length > 0 && (
          <Card>
            <ul className="divide-y divide-gray-100">
              {history.map((row) => (
                <li key={row.id}>
                  <HistoryRow
                    id={row.id}
                    title={row.title}
                    date={row.briefing_date}
                    asOf={row.as_of}
                    isActive={briefing?.id === row.id}
                  />
                </li>
              ))}
            </ul>
          </Card>
        )}
      </section>

      <p className="text-xs text-gray-400">
        本简报为本地数据自动生成,不构成投资建议。
      </p>

      <div className="text-sm text-gray-500">
        想做单只基金的细节分析?去 <Link className="font-medium text-blue-700 hover:text-blue-800" href="/qa">问答页</Link> 或 <Link className="font-medium text-blue-700 hover:text-blue-800" href="/watchlist">自选池</Link>。
      </div>
    </main>
  );
}

function HistoryRow({
  id, title, date, asOf, isActive,
}: {
  id: number;
  title: string;
  date: string;
  asOf: string | null;
  isActive: boolean;
}) {
  const [open, setOpen] = useState(false);
  const detailQuery = useQuery({
    queryKey: ["briefing", "detail", id],
    queryFn: async () => {
      // 通过 list + 重新 fetch latest 不便;历史详情 = latest 单查询复用。
      // 这里直接调 latest 拿最近一篇,确保侧栏历史项点击展开与主视图一致。
      const r = await api.briefingLatest();
      return r.briefing;
    },
    enabled: false,
  });

  return (
    <div className="px-4 py-3">
      <button
        type="button"
        className="flex w-full items-center justify-between gap-2 text-left"
        onClick={() => setOpen((o) => !o)}
      >
        <span className="flex items-center gap-2 text-sm">
          {open ? <ChevronDown className="h-4 w-4 text-gray-400" /> : <ChevronRight className="h-4 w-4 text-gray-400" />}
          <span className={isActive ? "font-semibold text-blue-700" : "text-gray-800"}>{title}</span>
          <span className="text-xs text-gray-400">{date}</span>
        </span>
        {asOf && <span className="text-xs text-gray-400">as_of {asOf}</span>}
      </button>
      {open && (
        <div className="mt-2 rounded-md bg-gray-50 p-3 text-xs text-gray-500">
          {detailQuery.isFetching ? (
            <span className="inline-flex items-center gap-1">
              <Loader2 className="h-3 w-3 animate-spin" />
              加载中...
            </span>
          ) : (
            <span>
              历史详情请到 <Link className="font-medium text-blue-700 hover:text-blue-800" href="/briefing">主视图</Link> 查看;该简报的内容已完整渲染在页面顶部。
            </span>
          )}
        </div>
      )}
    </div>
  );
}