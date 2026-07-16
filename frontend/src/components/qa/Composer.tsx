import { Loader2, Send } from "lucide-react";
import { Button } from "@/components/ui/button";

interface ComposerProps {
  input: string;
  streaming: boolean;
  onInputChange: (value: string) => void;
  onSend: () => void;
}

export function Composer({
  input,
  streaming,
  onInputChange,
  onSend,
}: ComposerProps) {
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        onSend();
      }}
      className="border-t border-gray-200 bg-white p-4"
    >
      <div className="rounded-xl border border-gray-200 bg-white p-2 shadow-sm focus-within:border-blue-300 focus-within:ring-2 focus-within:ring-blue-50">
        <textarea
          value={input}
          onChange={(event) => onInputChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              onSend();
            }
          }}
          rows={2}
          placeholder="输入基金代码、指标或市场问题，Shift+Enter 换行..."
          className="max-h-40 min-h-[56px] w-full resize-y border-0 bg-transparent px-2 py-2 text-sm leading-6 text-gray-900 outline-none placeholder:text-gray-400"
        />
        <div className="flex items-center justify-between gap-3 border-t border-gray-100 px-2 pt-2">
          <span className="text-xs text-gray-400">
            仅整理公开信息与历史数据，不构成投资建议。
          </span>
          <Button type="submit" disabled={!input.trim() || streaming}>
            {streaming ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Send className="mr-2 h-4 w-4" />
            )}
            发送
          </Button>
        </div>
      </div>
    </form>
  );
}
