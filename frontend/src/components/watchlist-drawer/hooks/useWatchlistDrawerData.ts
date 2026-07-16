import { useEffect, type Dispatch, type SetStateAction } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import {
  buildAutoTransactionDraft,
  isSixDigitFundCode,
} from "@/lib/auto-transaction";
import {
  validateInvestmentPlanDraft,
  type InvestmentPlanFormState,
} from "@/lib/investment-plan";
import { shouldUseInitialHoldingEndpoint } from "@/lib/watchlist-guards";
import type { WatchlistRow } from "@/types/api";
import type {
  TransactionFormState,
  WatchlistDrawerTab,
  WatchlistFormState,
} from "../types";

interface UseWatchlistDrawerDataInput {
  open: boolean;
  row?: WatchlistRow | null;
  form: WatchlistFormState;
  txForm: TransactionFormState;
  txFormOpen: boolean;
  activeTab: WatchlistDrawerTab;
  planForm: InvestmentPlanFormState;
  setForm: Dispatch<SetStateAction<WatchlistFormState>>;
  setTxForm: Dispatch<SetStateAction<TransactionFormState>>;
  setConfirmDates: Dispatch<SetStateAction<Record<number, string>>>;
}

export function useWatchlistDrawerData({
  open,
  row,
  form,
  txForm,
  txFormOpen,
  activeTab,
  planForm,
  setForm,
  setTxForm,
  setConfirmDates,
}: UseWatchlistDrawerDataInput) {
  const mode = row ? "edit" as const : "add" as const;
  const showTxTab = mode === "edit" && row != null && row.is_holding;
  const showPlanTab = mode === "edit" && row != null;
  const showPendingTab = mode === "edit" && row != null;
  const hasTabs = showTxTab || showPlanTab || showPendingTab;
  const fundCodeForTx = row?.fund_code ?? "";
  const currentFundCode = mode === "edit" ? fundCodeForTx : form.fund_code.trim();
  const needsInitialHolding = shouldUseInitialHoldingEndpoint({
    mode,
    formIsHolding: form.is_holding,
    rowIsHolding: row?.is_holding,
    rowTransactionCount: row?.transaction_count,
  });
  const isAlreadyHolding = mode === "edit" && row?.is_holding === true;
  const shouldLoadLatestNav = open && isSixDigitFundCode(currentFundCode) && (
    needsInitialHolding ||
    (showTxTab && activeTab === "transactions" && txFormOpen)
  );
  const selectedNavDate = needsInitialHolding
    ? form.holding_date
    : (showTxTab && activeTab === "transactions" && txFormOpen ? txForm.tx_date : "");

  const txQuery = useQuery({
    queryKey: ["watchlistTransactions", fundCodeForTx],
    queryFn: () => api.watchlistTransactions(fundCodeForTx),
    enabled: showTxTab,
  });

  const selectedNavQuery = useQuery({
    queryKey: ["nav", currentFundCode, selectedNavDate],
    queryFn: () => api.nav(currentFundCode, selectedNavDate),
    enabled: shouldLoadLatestNav,
  });

  const plansQuery = useQuery({
    queryKey: ["investmentPlans", fundCodeForTx],
    queryFn: () => api.investmentPlans(fundCodeForTx),
    enabled: showPlanTab && activeTab === "plans",
  });

  const pendingBuysQuery = useQuery({
    queryKey: ["pendingBuys", fundCodeForTx],
    queryFn: () => api.pendingBuys(fundCodeForTx),
    enabled: showPendingTab && activeTab === "pending",
  });

  const initialHoldingDraft = buildAutoTransactionDraft({
    amountInput: form.holding_amount,
    navPoint: selectedNavQuery.data,
    note: "初始持仓",
  });
  const txDraft = buildAutoTransactionDraft({
    amountInput: txForm.amount,
    feeInput: txForm.fee,
    note: txForm.note,
    navPoint: selectedNavQuery.data,
  });
  const planDraft = validateInvestmentPlanDraft(planForm);

  useEffect(() => {
    if (!open) return;
    const rows = pendingBuysQuery.data ?? [];
    if (rows.length === 0) return;
    setConfirmDates((prev) => {
      let changed = false;
      const next = { ...prev };
      for (const item of rows) {
        if (
          item.stage === "confirmable" &&
          item.expected_confirm_date &&
          !next[item.id]
        ) {
          next[item.id] = item.expected_confirm_date;
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [open, pendingBuysQuery.data, setConfirmDates]);

  useEffect(() => {
    const navDate = selectedNavQuery.data?.nav_date;
    if (!open || !needsInitialHolding || !navDate || form.holding_date) return;
    setForm((prev) => prev.holding_date ? prev : { ...prev, holding_date: navDate });
  }, [
    form.holding_date,
    needsInitialHolding,
    open,
    selectedNavQuery.data?.nav_date,
    setForm,
  ]);

  useEffect(() => {
    const navDate = selectedNavQuery.data?.nav_date;
    if (
      !open ||
      !showTxTab ||
      activeTab !== "transactions" ||
      !txFormOpen ||
      !navDate ||
      txForm.tx_date
    ) return;
    setTxForm((prev) => prev.tx_date ? prev : { ...prev, tx_date: navDate });
  }, [
    activeTab,
    open,
    selectedNavQuery.data?.nav_date,
    setTxForm,
    showTxTab,
    txForm.tx_date,
    txFormOpen,
  ]);

  return {
    mode,
    showTxTab,
    showPlanTab,
    showPendingTab,
    hasTabs,
    fundCodeForTx,
    currentFundCode,
    needsInitialHolding,
    isAlreadyHolding,
    txQuery,
    selectedNavQuery,
    plansQuery,
    pendingBuysQuery,
    initialHoldingDraft,
    txDraft,
    planDraft,
  };
}
