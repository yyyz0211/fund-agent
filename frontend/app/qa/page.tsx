"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { LANGGRAPH_URL, getLangGraphClient, LANGGRAPH_ASSISTANT } from "@/lib/langgraph";
import { formatDate } from "@/lib/format";

interface UiMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  ts: string;
}

export default function QaPage({ searchParams }: { searchParams: { prefill?: string } }) {
  const [input, setInput] = useState(searchParams.prefill ?? "");
  const [history, setHistory] = useState<UiMessage[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const health = useQuery({
    queryKey: ["langgraph", "health"],
    queryFn: async () => {
      try {
        const r = await fetch(`${LANGGRAPH_URL}/ok`);
        return r.ok;
      } catch {
        return false;
      }
    },
    retry: false,
  });

  async function send() {
    const question = input.trim();
    if (!question || streaming) return;
    setError(null);
    const userMsg: UiMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: question,
      ts: new Date().toISOString(),
    };
    setHistory((h) => [...h, userMsg]);
    setInput("");
    setStreaming(true);
    const assistantId = crypto.randomUUID();
    setHistory((h) => [
      ...h,
      { id: assistantId, role: "assistant", content: "", ts: new Date().toISOString() },
    ]);
    try {
      const client = getLangGraphClient();
      const stream = client.runs.stream(null, LANGGRAPH_ASSISTANT, {
        input: { messages: [{ role: "human", content: question }] },
        streamMode: "messages",
      });
      for await (const ev of stream) {
        // event "messages/partial" 或 "values" 不同；messages 模式以 {type, content, ...} 形态返回
        const data: any = ev.data;
        const msg = Array.isArray(data) ? data[data.length - 1] : data;
        if (msg && (msg.type === "ai" || msg.role === "assistant")) {
          const chunk =
            typeof msg.content === "string"
              ? msg.content
              : Array.isArray(msg.content)
              ? msg.content
                  .map((c: any) => (typeof c === "string" ? c : c.text ?? ""))
                  .join("")
              : "";
          setHistory((h) =>
            h.map((m) => (m.id === assistantId ? { ...m, content: chunk } : m)),
          );
        }
      }
    } catch (e) {
      setError(`连接 LangGraph Server 失败：${String(e)}`);
    } finally {
      setStreaming(false);
    }
  }

  return (
    <main className="mx-auto grid max-w-5xl grid-cols-1 gap-4 p-6 md:grid-cols-3">
      <section className="space-y-3 md:col-span-2">
        <h1 className="text-2xl font-bold">问答</h1>
        <Card>
          <CardHeader>
            <CardTitle>
              状态：
              {health.isLoading
                ? "检查中…"
                : health.data
                ? "LangGraph Server 在线"
                : "LangGraph Server 未连通（请运行 langgraph dev）"}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {error && <p className="mb-2 text-sm text-red-600">{error}</p>}
            <div className="space-y-3">
              {history.length === 0 && (
                <p className="text-sm text-gray-500">试试提问：基金 110011 净值？</p>
              )}
              {history.map((m) => (
                <div
                  key={m.id}
                  className={`rounded-md p-3 text-sm ${m.role === "user" ? "bg-blue-50" : "bg-gray-50"}`}
                >
                  <div className="mb-1 text-xs text-gray-500">{m.role === "user" ? "你" : "助手"}</div>
                  <div className="whitespace-pre-wrap">
                    {m.content || (m.role === "assistant" && streaming ? "▍" : "")}
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            send();
          }}
          className="flex gap-2"
        >
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="输入问题…"
          />
          <Button type="submit" disabled={!input.trim() || streaming}>
            发送
          </Button>
        </form>
      </section>

      <aside className="space-y-2">
        <Card>
          <CardHeader>
            <CardTitle>来源 / 数据日期</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-xs text-gray-500">
              LangGraph Server 通过 tool call 注入 source 与 as_of；流式消息
              解析后显示在此区。点击问题发送后等待服务器响应。
            </p>
            <ul className="mt-3 space-y-1 text-xs">
              {history
                .filter((m) => m.role === "assistant" && m.content)
                .map((m) => (
                  <li key={m.id}>
                    · {formatDate(m.ts)} · {m.content.slice(0, 40)}…
                  </li>
                ))}
            </ul>
          </CardContent>
        </Card>
      </aside>
    </main>
  );
}
