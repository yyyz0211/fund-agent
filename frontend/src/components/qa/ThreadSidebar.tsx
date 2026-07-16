import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatDate } from "@/lib/format";
import type { ThreadMeta } from "./types";

interface ThreadSidebarProps {
  threads: ThreadMeta[];
  threadId: string | null;
  onNew: () => void;
  onSwitch: (id: string) => void;
  onDelete: (id: string) => void;
}

export function ThreadSidebar({
  threads,
  threadId,
  onNew,
  onSwitch,
  onDelete,
}: ThreadSidebarProps) {
  return (
    <Card className="overflow-hidden p-0">
      <CardHeader className="mb-0 border-b border-gray-100 p-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <CardTitle className="text-base">对话</CardTitle>
            <p className="mt-1 text-xs text-gray-500">
              本地保存 UI 历史，服务端保留 thread 上下文。
            </p>
          </div>
          <Button variant="outline" size="sm" type="button" onClick={onNew}>
            <Plus className="mr-1.5 h-3.5 w-3.5" />
            新建
          </Button>
        </div>
      </CardHeader>
      <CardContent className="max-h-[420px] overflow-y-auto p-3">
        {threads.length === 0 ? (
          <p className="rounded-lg bg-gray-50 p-3 text-xs text-gray-500">
            尚无对话，发个问题开始。
          </p>
        ) : (
          <ul className="space-y-1.5">
            {threads.map((thread) => {
              const active = thread.id === threadId;
              return (
                <li
                  key={thread.id}
                  className={`group flex items-center gap-2 rounded-lg border px-3 py-2 text-sm transition ${
                    active
                      ? "border-blue-200 bg-blue-50 text-blue-800"
                      : "border-transparent bg-white text-gray-700 hover:border-gray-200 hover:bg-gray-50"
                  }`}
                >
                  <button
                    type="button"
                    onClick={() => onSwitch(thread.id)}
                    className="min-w-0 flex-1 text-left"
                    title={thread.title}
                  >
                    <span className="block truncate font-medium">{thread.title}</span>
                    <span className="mt-0.5 block text-[10px] text-gray-400">
                      {formatDate(thread.updatedAt)}
                    </span>
                  </button>
                  <button
                    type="button"
                    aria-label="删除对话"
                    onClick={() => onDelete(thread.id)}
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
  );
}
