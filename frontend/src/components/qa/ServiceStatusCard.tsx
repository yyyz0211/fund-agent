import { Server } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface ServiceStatusCardProps {
  loading: boolean;
  online: boolean;
  assistant: string;
  url: string;
}

export function ServiceStatusCard({
  loading,
  online,
  assistant,
  url,
}: ServiceStatusCardProps) {
  return (
    <Card className="p-4">
      <CardHeader>
        <CardTitle className="text-base">服务状态</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-center justify-between rounded-lg bg-gray-50 p-3">
          <span className="inline-flex items-center gap-2 text-sm text-gray-600">
            <Server className="h-4 w-4" />
            LangGraph
          </span>
          <StatusPill loading={loading} online={online} />
        </div>
        <div className="rounded-lg bg-gray-50 p-3 text-xs leading-5 text-gray-500">
          <div>
            Assistant:
            <code className="ml-1 rounded bg-white px-1 py-0.5">{assistant}</code>
          </div>
          <div className="mt-1 truncate" title={url}>
            URL: <code className="rounded bg-white px-1 py-0.5">{url}</code>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function StatusPill({ loading, online }: { loading: boolean; online: boolean }) {
  if (loading) {
    return (
      <span className="rounded-full bg-gray-100 px-2 py-1 text-xs font-medium text-gray-600">
        检查中
      </span>
    );
  }
  return (
    <span
      className={`rounded-full px-2 py-1 text-xs font-medium ${
        online ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"
      }`}
    >
      {online ? "在线" : "离线"}
    </span>
  );
}
