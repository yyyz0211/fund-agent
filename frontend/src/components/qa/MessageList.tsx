import { StateBlock } from "@/components/StateBlock";
import { ChatMessage } from "./ChatMessage";
import type { QaUiMessage } from "./types";

const SUGGESTIONS = [
  "110011 最新净值",
  "110011 近一个月最大回撤",
  "沪深300 今天怎么样",
];

interface MessageListProps {
  error: string | null;
  history: QaUiMessage[];
  streaming: boolean;
  onSuggestion: (suggestion: string) => void;
}

export function MessageList({
  error,
  history,
  streaming,
  onSuggestion,
}: MessageListProps) {
  return (
    <div className="min-h-0 flex-1 space-y-5 overflow-y-auto bg-gray-50/70 p-4 sm:p-6">
      {error && (
        <StateBlock title="连接失败" tone="error">
          <span className="break-words">{error}</span>
        </StateBlock>
      )}

      {history.length === 0 && (
        <div className="rounded-xl border border-dashed border-gray-200 bg-white p-5 shadow-sm">
          <p className="text-sm font-semibold text-gray-950">常用查询</p>
          <p className="mt-1 text-xs leading-5 text-gray-500">
            适合查公开信息、历史净值、市场和本地体检结果；买卖、推荐和收益预测会被拒答。
          </p>
          <div className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-3">
            {SUGGESTIONS.map((suggestion) => (
              <button
                key={suggestion}
                className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-3 text-left text-sm text-gray-700 transition hover:border-blue-200 hover:bg-blue-50 hover:text-blue-700"
                type="button"
                onClick={() => onSuggestion(suggestion)}
              >
                {suggestion}
              </button>
            ))}
          </div>
        </div>
      )}

      {history.map((message) => (
        <ChatMessage key={message.id} message={message} streaming={streaming} />
      ))}
    </div>
  );
}
