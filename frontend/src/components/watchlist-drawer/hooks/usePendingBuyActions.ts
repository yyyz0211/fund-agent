import type { Dispatch, SetStateAction } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useToast } from "@/components/Toast";
import { api } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import type { WatchlistRow } from "@/types/api";
import {
  blankPendingBuyForm,
  parsePositiveNumber,
} from "../form-state";
import type { PendingBuyFormState } from "../types";

export function usePendingBuyActions({
  fundCode,
  pendingForm,
  confirmDates,
  setPendingForm,
  setPendingFormOpen,
  setConfirmDates,
}: {
  fundCode: string;
  pendingForm: PendingBuyFormState;
  confirmDates: Record<number, string>;
  setPendingForm: Dispatch<SetStateAction<PendingBuyFormState>>;
  setPendingFormOpen: Dispatch<SetStateAction<boolean>>;
  setConfirmDates: Dispatch<SetStateAction<Record<number, string>>>;
}) {
  const toast = useToast();
  const qc = useQueryClient();

  const addPendingBuy = useMutation({
    mutationFn: () => {
      const amount = parsePositiveNumber(pendingForm.amount);
      const fee = pendingForm.fee.trim() ? parsePositiveNumber(pendingForm.fee) : null;
      if (!pendingForm.request_date) throw new Error("请选择申购日期");
      if (amount == null) throw new Error("请填写大于 0 的申购金额");
      if (pendingForm.fee.trim() && fee == null) throw new Error("请填写有效手续费");
      return api.pendingBuyAdd(fundCode, {
        request_date: pendingForm.request_date,
        amount,
        fee,
        note: pendingForm.note.trim() || null,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.watchlist.pendingBuys(fundCode) });
      setPendingForm(blankPendingBuyForm());
      setPendingFormOpen(false);
      toast.push("已记录申购中金额", "success");
    },
    onError: (err) => toast.push(`记录申购中失败：${String(err)}`, "error"),
  });

  const confirmPendingBuy = useMutation({
    mutationFn: ({ pendingId, txDate }: { pendingId: number; txDate: string }) =>
      api.pendingBuyConfirm(fundCode, pendingId, { tx_date: txDate }),
    onSuccess: (res) => {
      qc.setQueryData<WatchlistRow[]>(queryKeys.watchlist.all, (prev) => {
        if (!prev) return prev;
        return prev.map((row) =>
          row.fund_code === res.watchlist.fund_code ? res.watchlist : row,
        );
      });
      qc.invalidateQueries({ queryKey: queryKeys.watchlist.pendingBuys(fundCode) });
      qc.invalidateQueries({ queryKey: queryKeys.watchlist.transactions(fundCode) });
      qc.invalidateQueries({ queryKey: queryKeys.watchlist.all });
      qc.invalidateQueries({ queryKey: queryKeys.fund.summaryForFund(fundCode) });
      qc.invalidateQueries({ queryKey: queryKeys.portfolio.pnl([fundCode]) });
      qc.invalidateQueries({ queryKey: queryKeys.portfolio.pnl([]) });
      setConfirmDates((prev) => {
        const next = { ...prev };
        delete next[res.pending_buy.id];
        return next;
      });
      toast.push("申购已确认并写入持仓", "success");
    },
    onError: (err) => toast.push(`确认申购失败：${String(err)}`, "error"),
  });

  const cancelPendingBuy = useMutation({
    mutationFn: (pendingId: number) => api.pendingBuyCancel(fundCode, pendingId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.watchlist.pendingBuys(fundCode) });
      toast.push("申购中记录已取消", "success");
    },
    onError: (err) => toast.push(`取消申购失败：${String(err)}`, "error"),
  });

  function confirmPending(id: number) {
    const txDate = confirmDates[id];
    if (!txDate) {
      toast.push("请选择确认日期", "error");
      return;
    }
    confirmPendingBuy.mutate({ pendingId: id, txDate });
  }

  return { addPendingBuy, confirmPendingBuy, cancelPendingBuy, confirmPending };
}
