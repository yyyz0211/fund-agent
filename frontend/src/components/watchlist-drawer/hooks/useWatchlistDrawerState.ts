import { useEffect, useState } from "react";
import {
  blankPendingBuyForm,
  blankTransactionForm,
  blankWatchlistForm,
  rowToWatchlistForm,
} from "../form-state";
import {
  blankInvestmentPlanForm,
  type InvestmentPlanFormState,
} from "@/lib/investment-plan";
import type {
  PendingBuyFormState,
  TransactionFormState,
  WatchlistDrawerProps,
  WatchlistDrawerTab,
  WatchlistFormState,
} from "../types";

export function useWatchlistDrawerState({
  open,
  row,
  prefillFundCode,
}: Pick<WatchlistDrawerProps, "open" | "row" | "prefillFundCode">) {
  const [form, setForm] = useState<WatchlistFormState>(() =>
    row ? rowToWatchlistForm(row) : blankWatchlistForm(prefillFundCode ?? ""),
  );
  const [submitting, setSubmitting] = useState(false);
  const [activeTab, setActiveTab] = useState<WatchlistDrawerTab>("basic");
  const [txForm, setTxForm] = useState<TransactionFormState>(blankTransactionForm);
  const [txFormOpen, setTxFormOpen] = useState(false);
  const [pendingForm, setPendingForm] =
    useState<PendingBuyFormState>(blankPendingBuyForm);
  const [pendingFormOpen, setPendingFormOpen] = useState(false);
  const [confirmDates, setConfirmDates] = useState<Record<number, string>>({});
  const [planForm, setPlanForm] =
    useState<InvestmentPlanFormState>(blankInvestmentPlanForm);
  const [editingPlanId, setEditingPlanId] = useState<number | null>(null);

  useEffect(() => {
    if (!open) return;
    setForm(row ? rowToWatchlistForm(row) : blankWatchlistForm(prefillFundCode ?? ""));
    setActiveTab("basic");
    setTxForm(blankTransactionForm());
    setTxFormOpen(false);
    setPendingForm(blankPendingBuyForm());
    setPendingFormOpen(false);
    setConfirmDates({});
    setPlanForm(blankInvestmentPlanForm());
    setEditingPlanId(null);
  }, [open, row, prefillFundCode]);

  function setField<K extends keyof WatchlistFormState>(
    key: K,
    value: WatchlistFormState[K],
  ) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function setTxField<K extends keyof TransactionFormState>(
    key: K,
    value: TransactionFormState[K],
  ) {
    setTxForm((prev) => ({ ...prev, [key]: value }));
  }

  function setPendingField<K extends keyof PendingBuyFormState>(
    key: K,
    value: PendingBuyFormState[K],
  ) {
    setPendingForm((prev) => ({ ...prev, [key]: value }));
  }

  function setPlanField<K extends keyof InvestmentPlanFormState>(
    key: K,
    value: InvestmentPlanFormState[K],
  ) {
    setPlanForm((prev) => ({ ...prev, [key]: value }));
  }

  return {
    form,
    setForm,
    submitting,
    setSubmitting,
    activeTab,
    setActiveTab,
    txForm,
    setTxForm,
    txFormOpen,
    setTxFormOpen,
    pendingForm,
    setPendingForm,
    pendingFormOpen,
    setPendingFormOpen,
    confirmDates,
    setConfirmDates,
    planForm,
    setPlanForm,
    editingPlanId,
    setEditingPlanId,
    setField,
    setTxField,
    setPendingField,
    setPlanField,
  };
}
