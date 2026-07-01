"use client";
import { useState, useEffect, useCallback, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import {
  Bot,
  Check,
  ChevronDown,
  ChevronRight,
  Clock3,
  Database,
  ExternalLink,
  Loader2,
  MessageSquareText,
  Plus,
  Send,
  Server,
  Trash2,
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
import {
  type QaToolStep as ToolStep,
  type QaUiMessage as UiMessage,
  loadThreadHistory,
  removeThreadHistory,
  saveThreadHistory,
} from "@/lib/qa-thread-store";

interface ThreadMeta {
  id: string;
  title: string;
  updatedAt: string;
}

const THREADS_STORAGE_KEY = "qa_threads_v1";
const ACTIVE_THREAD_KEY = "qa_active_thread_v1";

// 已知带 fund_code 参数的工具 — 步骤上方会渲染"查看详情"链接。
// 新增工具含 fund_code 时需要在这里加。
const TOOLS_WITH_FUND_CODE = new Set([
  "refresh_fund",
  "get_fund_nav_history",
  "get_latest_fund_nav",
  "get_fund_basic_info",
  "calculate_holding_pnl",
]);

function extractFundCode(args: Record<string, unknown>): string | null {
  const raw = (args.fund_code ?? args.code) as unknown;
  if (typeof raw === "string" && raw.length > 0) return raw;
  return null;
}

function newThreadId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `t_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

function loadThreads(): ThreadMeta[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(THREADS_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (t: any) => t && typeof t.id === "string" && typeof t.title === "string",
    );
  } catch {
    return [];
  }
}

function saveThreads(threads: ThreadMeta[]): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(THREADS_STORAGE_KEY, JSON.stringify(threads));
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
  const [threadId, setThreadId] = useState<string | null>(null);
  const threadIdRef = useRef<string | null>(null);
  const [threads, setThreads] = useState<ThreadMeta[]>([]);

  const activateThread = useCallback((id: string | null, messages?: UiMessage[]) => {
    threadIdRef.current = id;
    setThreadId(id);
    setHistory(id ? messages ?? loadThreadHistory(id) : []);
    if (id) {
      window.localStorage.setItem(ACTIVE_THREAD_KEY, id);
    } else {
      window.localStorage.removeItem(ACTIVE_THREAD_KEY);
    }
  }, []);

  const updateThreadHistory = useCallback((id: string, updater: (history: UiMessage[]) => UiMessage[]) => {
    const next = updater(loadThreadHistory(id));
    saveThreadHistory(id, next);
    if (threadIdRef.current === id) setHistory(next);
    return next;
  }, []);

  // 启动时读 localStorage 的 threads + active
  useEffect(() => {
    const t = loadThreads();
    setThreads(t);
    const active = window.localStorage.getItem(ACTIVE_THREAD_KEY);
    if (active && t.some((x) => x.id === active)) {
      activateThread(active);
    } else if (t.length > 0) {
      // 兜底:用最近更新的一个
      const sorted = [...t].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
      activateThread(sorted[0].id);
    }
  }, [activateThread]);

  const upsertThread = useCallback(
    (id: string, title: string) => {
      setThreads((cur) => {
        const now = new Date().toISOString();
        const idx = cur.findIndex((t) => t.id === id);
        let next: ThreadMeta[];
        if (idx >= 0) {
          next = cur.map((t) =>
            t.id === id ? { ...t, title: title || t.title, updatedAt: now } : t,
          );
        } else {
          next = [...cur, { id, title: title || "新对话", updatedAt: now }];
        }
        next.sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
        saveThreads(next);
        return next;
      });
    },
    [],
  );

  function switchThread(id: string) {
    activateThread(id);
    setError(null);
  }

  function newThread() {
    const id = newThreadId();
    saveThreadHistory(id, []);
    activateThread(id, []);
    setError(null);
    upsertThread(id, "新对话");
  }

  function deleteThread(id: string) {
    const next = threads.filter((t) => t.id !== id);
    setThreads(next);
    saveThreads(next);
    removeThreadHistory(id);
    if (threadIdRef.current === id) {
      const remaining = next;
      if (remaining.length > 0) {
        switchThread(remaining[0].id);
      } else {
        activateThread(null, []);
      }
    }
  }

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
    // 第一次发问时若没有 thread 就建一个
    let activeId = threadId;
    if (!activeId) {
      activeId = newThreadId();
      saveThreadHistory(activeId, []);
      activateThread(activeId, []);
    }
    upsertThread(activeId, question.slice(0, 24));
    const userMsg: UiMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: question,
      ts: new Date().toISOString(),
      toolSteps: [],
    };
    setInput("");
    setStreaming(true);
    const assistantId = crypto.randomUUID();
    const assistantMsg: UiMessage = {
      id: assistantId,
      role: "assistant",
      content: "",
      ts: new Date().toISOString(),
      toolSteps: [],
    };
    updateThreadHistory(activeId, (h) => [...h, userMsg, assistantMsg]);
    try {
      const client = getLangGraphClient();
      // streamMode: "messages" — 每条 token-level 事件 data 是 [msg],
      // 我们保留这种结构因为它能拿到 AI 文本的流式 chunk。
      // 工具结果去重在 UI 层做(`status === 'done'` 时不再覆盖),
      // 因为 LangGraph 在某些情况下(例如中断/恢复/Checkpoint 重新)
      // 会回放同一条 ToolMessage,不能依赖 SDK 层只 emit 一次。
      // thread_id 透传,LangGraph server 用它做多轮上下文。
      const stream = client.runs.stream(activeId, LANGGRAPH_ASSISTANT, {
        input: { messages: [{ role: "human", content: question }] },
        streamMode: "messages",
      });
      for await (const ev of stream) {
        const data: any = ev.data;
        const msg = Array.isArray(data) ? data[data.length - 1] : data;
        if (!msg) continue;

        if ((msg.type === "ai" || msg.role === "assistant") && Array.isArray(msg.tool_calls) && msg.tool_calls.length > 0) {
          updateThreadHistory(activeId, (h) =>
            h.map((m) =>
              m.id === assistantId
                ? {
                    ...m,
                    toolSteps: [
                      ...m.toolSteps,
                      ...msg.tool_calls
                        .filter((tc: any) => !m.toolSteps.some((s) => s.id === tc.id))
                        .map((tc: any) => ({
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
          updateThreadHistory(activeId, (h) =>
            h.map((m) => {
              if (m.id !== assistantId) return m;
              // 工具结果去重:同 tool_call_id 已经 done 的不再覆盖,
              // 避免 LangGraph 在回放 ToolMessage 时重复 push 给 UI。
              const step = m.toolSteps.find((s) => s.id === msg.tool_call_id);
              if (step && step.status === "done") return m;
              return {
                ...m,
                toolSteps: m.toolSteps.map((s) =>
                  s.id === msg.tool_call_id
                    ? { ...s, status: "done", result: resultText }
                    : s,
                ),
              };
            }),
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
            updateThreadHistory(activeId, (h) =>
              h.map((m) => (m.id === assistantId ? { ...m, content: chunk } : m)),
            );
          }
        }
      }
    } catch (e) {
      const message = `连接 LangGraph Server 失败：${String(e)}`;
      setError(message);
      updateThreadHistory(activeId, (h) =>
        h.map((m) => (m.id === assistantId ? { ...m, content: message } : m)),
      );
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
            <CardHeader className="mb-0 flex-row items-center justify-between gap-3 border-b border-gray-200 p-4">
              <div className="flex items-center gap-3">
                <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-blue-50 text-blue-700">
                  <MessageSquareText className="h-5 w-5" />
                </span>
                <div>
                  <CardTitle className="text-base">
                    {threads.find((t) => t.id === threadId)?.title ?? "新对话"}
                  </CardTitle>
                  <p className="mt-1 text-xs text-gray-500">{statusText}</p>
                </div>
              </div>
              <Button variant="outline" size="sm" type="button" onClick={newThread}>
                <Plus className="mr-1.5 h-3.5 w-3.5" />
                新对话
              </Button>
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
              <CardTitle className="text-base">对话列表</CardTitle>
              <p className="mt-1 text-xs text-gray-500">
                thread_id 由前端管理,LangGraph Server 用它维持多轮上下文。
                重启服务或清缓存会清空。
              </p>
            </CardHeader>
            <CardContent>
              {threads.length === 0 ? (
                <p className="rounded-lg bg-gray-50 p-3 text-xs text-gray-500">尚无对话,发个问题开始。</p>
              ) : (
                <ul className="space-y-1.5">
                  {threads.map((t) => {
                    const active = t.id === threadId;
                    return (
                      <li
                        key={t.id}
                        className={`group flex items-center gap-2 rounded-lg border px-3 py-2 text-sm ${
                          active
                            ? "border-blue-200 bg-blue-50 text-blue-800"
                            : "border-gray-200 bg-white text-gray-700 hover:border-gray-300"
                        }`}
                      >
                        <button
                          type="button"
                          onClick={() => switchThread(t.id)}
                          className="flex-1 truncate text-left"
                          title={t.title}
                        >
                          {t.title}
                        </button>
                        <span className="text-[10px] text-gray-400">
                          {formatDate(t.updatedAt).slice(5)}
                        </span>
                        <button
                          type="button"
                          aria-label="删除对话"
                          onClick={() => deleteThread(t.id)}
                          className="rounded p-1 text-gray-400 opacity-0 transition hover:bg-gray-100 hover:text-red-500 group-hover:opacity-100"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </CardContent>
          </Card>

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
  const showLink = TOOLS_WITH_FUND_CODE.has(step.name);
  const fundCode = showLink ? extractFundCode(step.args) : null;
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
        {fundCode && (
          <span className="inline-flex items-center gap-1 rounded-full border border-blue-200 bg-blue-50 px-2 py-0.5 font-mono text-[10px] text-blue-700">
            {fundCode}
          </span>
        )}
        <span className="ml-auto truncate font-mono text-[11px] text-gray-500">
          {truncate(argsJson, 80)}
        </span>
      </button>
      {open && (
        <div className="space-y-2 border-t border-gray-200 bg-white p-2.5">
          {fundCode && (
            <Link
              href={`/funds/${encodeURIComponent(fundCode)}`}
              className="inline-flex items-center gap-1.5 rounded-md border border-blue-200 bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700 transition hover:border-blue-300 hover:bg-blue-100"
            >
              <ExternalLink className="h-3.5 w-3.5" />
              查看基金详情（{fundCode}）
            </Link>
          )}
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
