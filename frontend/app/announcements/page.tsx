import Link from "next/link";
import { FileText, MessageSquareText } from "lucide-react";
import { PageHeader } from "@/components/PageHeader";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

export default function AnnouncementsPage() {
  return (
    <main className="mx-auto max-w-6xl space-y-6 px-4 py-8 sm:px-6">
      <PageHeader
        eyebrow="Announcements"
        title="公告"
        description="Phase 2 仅保留公告入口和空状态。公告检索、摘要和 RAG 会在 Phase 5 接入。"
        actions={
          <Link href="/qa">
            <Button variant="outline">
              <MessageSquareText className="mr-2 h-4 w-4" />
              去问答页
            </Button>
          </Link>
        }
      />

      <Card className="p-6">
        <CardHeader>
          <div className="flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-50 text-blue-700">
              <FileText className="h-5 w-5" />
            </span>
            <div>
              <CardTitle className="text-base">公告 RAG 尚未启用</CardTitle>
              <p className="mt-1 text-sm text-gray-500">当前 API 会返回空列表和阶段说明。</p>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-3 leading-6 text-gray-600">
          <p>本页不会展示未经处理的公告摘要，也不会编造公告内容。</p>
          <p>
            基金基础数据问题仍可在{" "}
            <Link className="font-medium text-blue-700 hover:text-blue-800" href="/qa">
              问答页
            </Link>{" "}
            通过 Phase 4 LangGraph 流程处理。
          </p>
        </CardContent>
      </Card>
    </main>
  );
}
