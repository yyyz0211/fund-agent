/**
 * LangGraph SDK 配置。
 * 0.0.10 还没有 react hook；直接用 Client.runs.stream 走流式。
 */
import { Client } from "@langchain/langgraph-sdk";

export const LANGGRAPH_URL =
  process.env.NEXT_PUBLIC_LANGGRAPH_URL ?? "http://localhost:2024";
export const LANGGRAPH_ASSISTANT =
  process.env.NEXT_PUBLIC_LANGGRAPH_ASSISTANT ?? "fund_agent";

let _client: Client | null = null;
export function getLangGraphClient(): Client {
  if (!_client) _client = new Client({ apiUrl: LANGGRAPH_URL });
  return _client;
}
