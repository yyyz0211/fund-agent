import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";

export default function Home() {
  return (
    <main className="mx-auto max-w-4xl p-6">
      <h1 className="mb-4 text-2xl font-bold">基金信息助手</h1>
      <Card>
        <CardHeader><CardTitle>scaffold ok</CardTitle></CardHeader>
        <CardContent>前端依赖安装成功。后续 Task 会替换此页。</CardContent>
      </Card>
    </main>
  );
}
