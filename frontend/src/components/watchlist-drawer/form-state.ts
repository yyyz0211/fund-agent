import type { WatchlistRow } from "@/types/api";
import type {
  PendingBuyFormState,
  TransactionFormState,
  WatchlistFormState,
} from "./types";

export function rowToWatchlistForm(row: WatchlistRow): WatchlistFormState {
  return {
    fund_code: row.fund_code,
    note: row.note ?? "",
    is_holding: !!row.is_holding,
    is_focus: !!row.is_focus,
    holding_amount: row.holding_amount?.toString() ?? "",
    holding_date: row.buy_date ?? "",
  };
}

export function blankWatchlistForm(fundCode = ""): WatchlistFormState {
  return {
    fund_code: fundCode,
    note: "",
    is_holding: false,
    is_focus: false,
    holding_amount: "",
    holding_date: "",
  };
}

export function blankTransactionForm(): TransactionFormState {
  return { tx_date: "", amount: "", fee: "", note: "" };
}

export function blankPendingBuyForm(): PendingBuyFormState {
  return { request_date: "", amount: "", fee: "", note: "" };
}

export function parsePositiveNumber(value: string): number | null {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) return null;
  return number;
}

export function todayInputValue(): string {
  const now = new Date();
  now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
  return now.toISOString().slice(0, 10);
}
