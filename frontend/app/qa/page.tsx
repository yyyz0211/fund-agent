"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Bot,
  Check,
  ChevronDown,
  ChevronRight,
  Clock3,
  Database,
  Loader2,
  MessageSquareText,
  Send,
  Server,
  User,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { PageHeader } from "@/components/PageHeader";
import { StateBlock } from "@/components/StateBlock";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { LANGGRAPH_URL, getLangGraphClient, LANGGRAPH_ASSISTANT } from "@/lib/langgraph";
import { formatDate } from "@/lib/format";

interface ToolStep {
  id: string;
  name: string;
  args: Record<string, unknown>;
  result?: string;
  status: "pending" | "done" | "error";
}

interface UiMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  ts: string;
  toolSteps: ToolStep[];
}

const SUGGESTIONS = [
  "110011 最新净值",
  "110011 近一个月最大回撤",
  "沪深300 今天怎么样",
];

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
      toolSteps: [],
    };
    setHistory((h) => [...h, userMsg]);
    setInput("");
    setStreaming(true);
    const assistantId = crypto.randomUUID();
    setHistory((h) => [
      ...h,
      {
        id: assistantId,
        role: "assistant",
        content: "",
        ts: new Date().toISOString(),
        toolSteps: [],
      },
    ]);
    try {
      const client = getLangGraphClient();
      const stream = client.runs.stream(null, LANGGRAPH_ASSISTANT, {
        input: { messages: [{ role: "human", content: question }] },
        streamMode: "messages",
      });
      for await (const ev of stream) {
        const data: any = ev.data;
        const msg = Array.isArray(data) ? data[data.length - 1] : data;
        if (!msg) continue;

        if ((msg.type === "ai" || msg.role === "assistant") && Array.isArray(msg.tool_calls) && msg.tool_calls.length > 0) {
          setHistory((h) =>
            h.map((m) =>
              m.id === assistantId
                ? {
                    ...m,
                    toolSteps: [
                      ...m.toolSteps,
                      ...msg.tool_calls.map((tc: any) => ({
                        id: tc.id,
                        name: tc.name,
                        args: tc.args ?? {},
                        status: "pending" as const,
                      })),
                    ],
                  }
                : m,
            ),
          );
        }

        if (msg.type === "tool" && msg.tool_call_id) {
          const resultText =
            typeof msg.content === "string"
              ? msg.content
              : Array.isArray(msg.content)
                ? msg.content
                    .map((c: any) => (typeof c === "string" ? c : c.text ?? ""))
                    .join("")
                : JSON.stringify(msg.content ?? "");
          setHistory((h) =>
            h.map((m) =>
              m.id === assistantId
                ? {
                    ...m,
                    toolSteps: m.toolSteps.map((s) =>
                      s.id === msg.tool_call_id
                        ? { ...s, status: "done", result: resultText }
                        : s,
                    ),
                  }
                : m,
            ),
          );
        }

        if (msg.type === "ai" || msg.role === "assistant") {
          const chunk =
            typeof msg.content === "string"
              ? msg.content
              : Array.isArray(msg.content)
                ? msg.content
                    .map((c: any) => (typeof c === "string" ? c : c.text ?? ""))
                    .join("")
                : "";
          if (chunk) {
            setHistory((h) =>
              h.map((m) => (m.id === assistantId ? { ...m, content: chunk } : m)),
            );
          }
        }
      }
    } catch (e) {
      setError(`连接 LangGraph Server 失败：${String(e)}`);
    } finally {
      setStreaming(false);
    }
  }

  const statusText = health.isLoading
    ? "检查中"
    : health.data
      ? "LangGraph Server 在线"
      : "LangGraph Server 未连通";

  return (
    <main className="mx-auto max-w-6xl space-y-6 px-4 py-8 sm:px-6">
      <PageHeader
        eyebrow="LangGraph QA"
        title="基金问答"
        description="直接连接 Phase 4 LangGraph Server。适合查询公开信息、历史净值和市场数据；买卖、推荐和收益预测类问题会被合规策略拦截。"
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_320px]">
        <section className="min-w-0">
          <Card className="flex min-h-[560px] flex-col overflow-hidden p-0">
            <CardHeader className="mb-0 border-b border-gray-200 p-4">
              <div className="flex items-center gap-3">
                <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-50 text-blue-700">
                  <MessageSquareText className="h-5 w-5" />
                </span>
                <div>
                  <CardTitle className="text-base">对话</CardTitle>
                  <p className="mt-1 text-xs text-gray-500">{statusText}</p>
                </div>
              </div>
            </CardHeader>

            <CardContent className="flex flex-1 flex-col p-0">
              <div className="flex-1 space-y-4 p-4">
                {error && (
                  <StateBlock title="连接失败" tone="error">
                    <span className="break-words">{error}</span>
                  </StateBlock>
                )}

                {history.length === 0 && (
                  <div className="rounded-lg border border-dashed border-gray-200 bg-gray-50 p-5">
                    <p className="text-sm font-medium text-gray-900">可以先试这些信息查询</p>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {SUGGESTIONS.map((suggestion) => (
                        <button
                          key={suggestion}
                          className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 shadow-sm transition hover:border-blue-200 hover:bg-blue-50 hover:text-blue-700"
                          type="button"
                          onClick={() => setInput(suggestion)}
                        >
                          {suggestion}
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {history.map((m) => (
                  <ChatMessage key={m.id} message={m} streaming={streaming} />
                ))}
              </div>

              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  send();
                }}
                className="border-t border-gray-200 bg-white p-4"
              >
                <div className="flex gap-2">
                  <Input
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    placeholder="输入基金代码、指标或市场问题..."
                  />
                  <Button type="submit" disabled={!input.trim() || streaming}>
                    <Send className="mr-2 h-4 w-4" />
                    发送
                  </Button>
                </div>
              </form>
            </CardContent>
          </Card>
        </section>

        <aside className="space-y-4">
          <Card className="p-5">
            <CardHeader>
              <CardTitle className="text-base">服务状态</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex items-center justify-between rounded-lg bg-gray-50 p-3">
                <span className="inline-flex items-center gap-2 text-sm text-gray-600">
                  <Server className="h-4 w-4" />
                  LangGraph
                </span>
                <StatusPill loading={health.isLoading} online={health.data === true} />
              </div>
              <p className="text-xs leading-5 text-gray-500">
                本页使用 <code className="rounded bg-gray-100 px-1 py-0.5">{LANGGRAPH_ASSISTANT}</code> assistant，
                地址来自 <code className="rounded bg-gray-100 px-1 py-0.5">NEXT_PUBLIC_LANGGRAPH_URL</code>。
              </p>
            </CardContent>
          </Card>

          <Card className="p-5">
            <CardHeader>
              <CardTitle className="text-base">来源 / 数据日期</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-xs leading-5 text-gray-500">
                回答应保留工具返回的 source 与 as_of。这里展示最近助手消息摘要，便于回看。
              </p>
              <ul className="mt-4 space-y-3 text-xs">
                {history.filter((m) => m.role === "assistant" && m.content).length === 0 && (
                  <li className="rounded-lg bg-gray-50 p-3 text-gray-500">暂无助手回答。</li>
                )}
                {history
                  .filter((m) => m.role === "assistant" && m.content)
                  .map((m) => (
                    <li key={m.id} className="rounded-lg border border-gray-200 bg-white p-3">
                      <div className="mb-1 flex items-center gap-1 text-gray-500">
                        <Clock3 className="h-3.5 w-3.5" />
                        {formatDate(m.ts)}
                      </div>
                      <p className="text-gray-700">{m.content.slice(0, 80)}{m.content.length > 80 ? "..." : ""}</p>
                    </li>
                  ))}
              </ul>
            </CardContent>
          </Card>
        </aside>
      </div>
    </main>
  );
}

function MarkdownBody({ content }: { content: string }) {
  return (
    <div className="md-body">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
    </div>
  );
}

function ToolStepList({ steps }: { steps: ToolStep[] }) {
  if (steps.length === 0) return null;
  return (
    <div className="mt-3 space-y-2 border-t border-gray-100 pt-3">
      <div className="flex items-center gap-1.5 text-xs font-medium text-gray-500">
        <Database className="h-3.5 w-3.5" />
        数据来源 ({steps.length})
      </div>
      <ul className="space-y-1.5">
        {steps.map((s) => (
          <ToolStepItem key={s.id} step={s} />
        ))}
      </ul>
    </div>
  );
}

function ToolStepItem({ step }: { step: ToolStep }) {
  const [open, setOpen] = useState(false);
  const argsJson = JSON.stringify(step.args, null, 2);
  return (
    <li className="rounded-md border border-gray-200 bg-gray-50">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-xs text-gray-700 hover:bg-gray-100"
      >
        {open ? (
          <ChevronDown className="h-3.5 w-3.5 shrink-0 text-gray-400" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 shrink-0 text-gray-400" />
        )}
        {step.status === "pending" ? (
          <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-gray-400" />
        ) : (
          <Check className="h-3.5 w-3.5 shrink-0 text-green-600" />
        )}
        <span className="font-mono font-medium text-gray-800">{step.name}</span>
        <span className="ml-auto truncate font-mono text-[11px] text-gray-500">
          {truncate(argsJson, 80)}
        </span>
      </button>
      {open && (
        <div className="space-y-2 border-t border-gray-200 bg-white p-2.5">
          <div>
            <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-gray-500">参数</div>
            <pre className="overflow-x-auto rounded bg-gray-50 p-2 font-mono text-[11px] leading-5 text-gray-700">{argsJson}</pre>
          </div>
          {step.result !== undefined && (
            <div>
              <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-gray-500">返回</div>
              <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded bg-gray-50 p-2 font-mono text-[11px] leading-5 text-gray-700">{truncate(step.result, 4000)}</pre>
            </div>
          )}
        </div>
      )}
    </li>
  );
}

function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n) + "…" : s;
}

function ChatMessage({ message, streaming }: { message: UiMessage; streaming: boolean }) {
  const isUser = message.role === "user";
  const Icon = isUser ? User : Bot;

  return (
    <div className={`flex gap-3 ${isUser ? "justify-end" : "justify-start"}`}>
      {!isUser && (
        <span className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gray-100 text-gray-600">
          <Icon className="h-4 w-4" />
        </span>
      )}
      <div
        className={`max-w-[82%] rounded-lg px-4 py-3 text-sm shadow-sm ${
          isUser
            ? "bg-blue-600 text-white"
            : "border border-gray-200 bg-white text-gray-800"
        }`}
      >
        <div className={`mb-1 text-xs ${isUser ? "text-blue-100" : "text-gray-500"}`}>
          {isUser ? "你" : "助手"} · {formatDate(message.ts)}
        </div>
        <div className={isUser ? "whitespace-pre-wrap leading-6" : "leading-6"}>
          {isUser ? (
            <div className="whitespace-pre-wrap">{message.content}</div>
          ) : message.content ? (
            <MarkdownBody content={message.content} />
          ) : streaming ? (
            <span className="text-gray-400">▍</span>
          ) : null}
        </div>
        {!isUser && <ToolStepList steps={message.toolSteps} />}
      </div>
      {isUser && (
        <span className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-700">
          <Icon className="h-4 w-4" />
        </span>
      )}
    </div>
  );
}

function StatusPill({ loading, online }: { loading: boolean; online: boolean }) {
  if (loading) {
    return <span className="rounded-full bg-gray-100 px-2 py-1 text-xs font-medium text-gray-600">检查中</span>;
  }
  return (
    <span className={`rounded-full px-2 py-1 text-xs font-medium ${online ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"}`}>
      {online ? "在线" : "离线"}
    </span>
  );
}