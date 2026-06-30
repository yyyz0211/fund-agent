import Link from "next/link";
import { Disclaimer } from "@/components/Disclaimer";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function AnnouncementsPage() {
  return (
    <>
      <Disclaimer />
      <main className="mx-auto max-w-5xl space-y-6 p-6">
        <h1 className="text-2xl font-bold">公告</h1>
        <Card>
          <CardHeader><CardTitle>阶段 2 暂未接入 RAG</CardTitle></CardHeader>
          <CardContent>
            公告检索与摘要在阶段 5 接入；本页当前展示空列表作为占位。
            你仍然可以在 <Link className="text-blue-600 hover:underline" href="/qa">问答页</Link> 提问某只基金的公告相关问题，
            由 Phase 4 QA 流程处理（不做 RAG 摘要）。
          </CardContent>
        </Card>
      </main>
    </>
  );
}
