import Link from "next/link";
import type { ReactNode } from "react";
import { MarketIndexCard } from "@/components/MarketIndexCard";
import { PageHeader, SectionHeader } from "@/components/PageHeader";
import { WatchlistTable } from "@/components/WatchlistTable";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ArrowRight, Database, MessageSquareText, ShieldCheck } from "lucide-react";

export default function Home() {
  return (
    <main className="mx-auto max-w-6xl space-y-8 px-4 py-8 sm:px-6">
      <PageHeader
        eyebrow="Local fund dashboard"
        title="基金信息助手"
        description="面向本地单用户的基金信息看板，聚合公开市场数据、自选池和 LangGraph 问答。当前阶段只读展示，不提供投资建议。"
        actions={
          <>
            <Link href="/watchlist">
              <Button variant="outline">查看自选池</Button>
            </Link>
            <Link href="/qa">
              <Button>进入问答</Button>
            </Link>
          </>
        }
      />

      <section className="grid grid-cols-1 gap-4 lg:grid-cols-[1.45fr_0.85fr]">
        <Card className="p-6">
          <CardHeader>
            <div>
              <CardTitle className="text-base">今日工作台</CardTitle>
              <p className="mt-1 text-sm text-gray-500">从市场概览、自选池和问答开始。</p>
            </div>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <QuickLink
                href="/watchlist"
                icon={<Database className="h-4 w-4" />}
                label="自选池"
                text="查看已关注基金"
              />
              <QuickLink
                href="/qa?prefill=110011%20%E6%9C%80%E6%96%B0%E5%87%80%E5%80%BC"
                icon={<MessageSquareText className="h-4 w-4" />}
                label="净值问答"
                text="查询基金最新数据"
              />
              <QuickLink
                href="/announcements"
                icon={<ShieldCheck className="h-4 w-4" />}
                label="公告占位"
                text="Phase 5 接入 RAG"
              />
            </div>
          </CardContent>
        </Card>

        <Card className="p-6">
          <CardHeader>
            <CardTitle className="text-base">边界说明</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm leading-6 text-gray-600">
            <p>所有页面展示 source、as_of 或数据日期，便于判断数据时点。</p>
            <p>问答链路会拦截买卖、推荐、收益预测等请求。</p>
          </CardContent>
        </Card>
      </section>

      <section>
        <SectionHeader title="主要指数" description="来自后端本地缓存的市场快照。" />
        <MarketIndexCard />
      </section>

      <section>
        <SectionHeader
          title="自选池概览"
          description="只读展示，缺失数据不会阻断页面。"
          action={
            <Link className="inline-flex items-center gap-1 text-sm font-medium text-blue-700 hover:text-blue-800" href="/watchlist">
              查看全部
              <ArrowRight className="h-4 w-4" />
            </Link>
          }
        />
        <WatchlistTable limit={10} />
      </section>
    </main>
  );
}

function QuickLink({ href, icon, label, text }: { href: string; icon: ReactNode; label: string; text: string }) {
  return (
    <Link
      className="group rounded-lg border border-gray-200 bg-gray-50 p-4 transition hover:border-blue-200 hover:bg-blue-50"
      href={href}
    >
      <span className="mb-3 flex h-9 w-9 items-center justify-center rounded-lg bg-white text-blue-700 shadow-sm">
        {icon}
      </span>
      <span className="block text-sm font-medium text-gray-950">{label}</span>
      <span className="mt-1 block text-xs text-gray-500 group-hover:text-blue-700">{text}</span>
    </Link>
  );
}
