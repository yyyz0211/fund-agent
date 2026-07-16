import type { WatchlistRow } from "@/types/api";

export interface WatchlistDrawerProps {
  /** 编辑模式时传入当前行;新增模式留空。 */
  row?: WatchlistRow | null;
  /** 新增模式时预填基金代码(从详情页跳过来)。 */
  prefillFundCode?: string;
  open: boolean;
  onClose: () => void;
  /** 保存成功后回调,用于让上层 invalidate query。 */
  onSaved?: (row: WatchlistRow) => void;
}

export type Mode = "add" | "edit";
export type WatchlistDrawerTab = "basic" | "transactions" | "plans" | "pending";

export interface WatchlistFormState {
  fund_code: string;
  note: string;
  is_holding: boolean;
  is_focus: boolean;
  holding_amount: string;
  holding_date: string;
}

export interface TransactionFormState {
  tx_date: string;
  amount: string;
  fee: string;
  note: string;
}

export interface PendingBuyFormState {
  request_date: string;
  amount: string;
  fee: string;
  note: string;
}
