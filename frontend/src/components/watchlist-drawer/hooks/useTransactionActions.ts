import type { Dispatch, FormEvent, SetStateAction } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useToast } from "@/components/Toast";
import { api } from "@/lib/api";
import type { AutoTransactionDraft } from "@/lib/auto-transaction";
import type { TransactionUpsertPayload, WatchlistRow } from "@/types/api";
import { blankTransactionForm } from "../form-state";
import type { TransactionFormState } from "../types";

export function useTransactionActions({
  fundCode,
  txDraft,
  selectedNavLoading,
  setTxForm,
  setTxFormOpen,
}: {
  fundCode: string;
  txDraft: AutoTransactionDraft | null;
  selectedNavLoading: boolean;
  setTxForm: Dispatch<SetStateAction<TransactionFormState>>;
  setTxFormOpen: Dispatch<SetStateAction<boolean>>;
}) {
  const toast = useToast();
  const qc = useQueryClient();

  const addTx = useMutation({
    mutationFn: (payload: TransactionUpsertPayload) =>
      api.watchlistAddTransaction(fundCode, payload),
    onSuccess: (res) => {
      qc.setQueryData<WatchlistRow[]>(["watchlist"], (prev) => {
        if (!prev) return prev;
        return prev.map((row) =>
          row.fund_code === res.watchlist.fund_code ? res.watchlist : row,
        );
      });
      qc.invalidateQueries({ queryKey: ["watchlist"] });
      qc.invalidateQueries({ queryKey: ["watchlistTransactions", fundCode] });
      qc.invalidateQueries({ queryKey: ["fundSummary", fundCode] });
      qc.invalidateQueries({ queryKey: ["portfolioPnl", [fundCode]] });
      qc.invalidateQueries({ queryKey: ["portfolioPnl", []] });
      setTxForm(blankTransactionForm());
      setTxFormOpen(false);
      toast.push(`已添加加仓 ¥${res.transaction.amount.toFixed(2)}`, "success");
    },
    onError: (err) => toast.push(`添加加仓失败：${String(err)}`, "error"),
  });

  const removeTx = useMutation({
    mutationFn: (txId: number) => api.watchlistRemoveTransaction(fundCode, txId),
    onSuccess: (res) => {
      qc.setQueryData<WatchlistRow[]>(["watchlist"], (prev) => {
        if (!prev) return prev;
        return prev.map((row) =>
          row.fund_code === fundCode && res.watchlist ? res.watchlist : row,
        );
      });
      qc.invalidateQueries({ queryKey: ["watchlist"] });
      qc.invalidateQueries({ queryKey: ["watchlistTransactions", fundCode] });
      qc.invalidateQueries({ queryKey: ["fundSummary", fundCode] });
      qc.invalidateQueries({ queryKey: ["portfolioPnl", [fundCode]] });
      qc.invalidateQueries({ queryKey: ["portfolioPnl", []] });
      toast.push("已删除加仓记录", "success");
    },
    onError: (err) => toast.push(`删除加仓失败：${String(err)}`, "error"),
  });

  function submitTx(event: FormEvent) {
    event.preventDefault();
    if (selectedNavLoading) {
      toast.push("正在读取所选日期 NAV,请稍后再提交", "error");
      return;
    }
    if (!txDraft) {
      toast.push("请填写有效投入金额，并确认所选日期本地已有 NAV", "error");
      return;
    }
    addTx.mutate(txDraft.payload);
  }

  return { addTx, removeTx, submitTx };
}
