export interface QaWorkbenchProps {
  prefill?: string;
}

export interface ThreadMeta {
  id: string;
  title: string;
  updatedAt: string;
}

export interface QaToolStep {
  id: string;
  name: string;
  args: Record<string, unknown>;
  result?: string;
  status: "pending" | "done" | "error";
}

export interface QaUiMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  ts: string;
  toolSteps: QaToolStep[];
}
