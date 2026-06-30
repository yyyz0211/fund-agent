import Link from "next/link";
import { Disclaimer } from "@/components/Disclaimer";
import { MarketIndexCard } from "@/components/MarketIndexCard";
import { WatchlistTable } from "@/components/WatchlistTable";
import { Button } from "@/components/ui/button";

export default function Home() {
  return (
    <>
      <Disclaimer />
      <main className="mx-auto max-w-5xl space-y-6 p-6">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold">基金信息助手</h1>
          <div className="space-x-2">
            <Link href="/watchlist"><Button variant="outline">自选池</Button></Link>
            <Link href="/qa"><Button>进入问答</Button></Link>
          </div>
        </div>

        <section>
          <h2 className="mb-3 text-lg font-semibold">主要指数</h2>
          <MarketIndexCard />
        </section>

        <section>
          <h2 className="mb-3 text-lg font-semibold">自选池概览</h2>
          <WatchlistTable limit={10} />
          <p className="mt-2 text-right text-sm">
            <Link className="text-blue-600 hover:underline" href="/watchlist">查看全部 →</Link>
          </p>
        </section>
      </main>
    </>
  );
}
