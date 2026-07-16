import { Bot, Loader2, User } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { formatDate } from "@/lib/format";
import { ToolStepList } from "./ToolStepList";
import type { QaUiMessage } from "./types";

export function ChatMessage({
  message,
  streaming,
}: {
  message: QaUiMessage;
  streaming: boolean;
}) {
  const isUser = message.role === "user";
  const Icon = isUser ? User : Bot;

  return (
    <div className={`flex gap-3 ${isUser ? "justify-end" : "justify-start"}`}>
      {!isUser && (
        <span className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-white text-gray-700 shadow-sm ring-1 ring-gray-200">
          <Icon className="h-4 w-4" />
        </span>
      )}
      <div
        className={`max-w-[88%] rounded-2xl px-4 py-3 text-sm shadow-sm ${
          isUser
            ? "rounded-br-md bg-blue-600 text-white"
            : "rounded-bl-md border border-gray-200 bg-white text-gray-800"
        }`}
      >
        <div
          className={`mb-1 text-[11px] ${isUser ? "text-blue-100" : "text-gray-500"}`}
        >
          {isUser ? "你" : "助手"} · {formatDate(message.ts)}
        </div>
        <div className={isUser ? "whitespace-pre-wrap leading-6" : "leading-6"}>
          {isUser ? (
            <div className="whitespace-pre-wrap">{message.content}</div>
          ) : message.content ? (
            <MarkdownBody content={message.content} />
          ) : streaming ? (
            <span className="inline-flex items-center gap-2 text-gray-400">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              正在生成
            </span>
          ) : null}
        </div>
        {!isUser && <ToolStepList steps={message.toolSteps} />}
      </div>
      {isUser && (
        <span className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-700 ring-1 ring-blue-100">
          <Icon className="h-4 w-4" />
        </span>
      )}
    </div>
  );
}

function MarkdownBody({ content }: { content: string }) {
  return (
    <div className="md-body">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
    </div>
  );
}
