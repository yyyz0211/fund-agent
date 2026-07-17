import type { Dispatch, FormEvent, SetStateAction } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useToast } from "@/components/Toast";
import { api } from "@/lib/api";
import type { AutoTransactionDraft } from "@/lib/auto-transaction";
import { queryKeys } from "@/lib/query-keys";
import type {
  WatchlistPatchPayload,
  WatchlistPreloadJob,
  WatchlistRow,
  WatchlistUpsertPayload,
} from "@/types/api";
import type { Mode, WatchlistFormState } from "../types";
import { useWatchlistPreloadPolling } from "./useWatchlistPreloadPolling";

export function useWatchlistSave({
  mode,
  form,
  submitting,
  setSubmitting,
  needsInitialHolding,
  selectedNavLoading,
  initialHoldingDraft,
  onSaved,
  onClose,
}: {
  mode: Mode;
  form: WatchlistFormState;
  submitting: boolean;
  setSubmitting: Dispatch<SetStateAction<boolean>>;
  needsInitialHolding: boolean;
  selectedNavLoading: boolean;
  initialHoldingDraft: AutoTransactionDraft | null;
  onSaved?: (row: WatchlistRow) => void;
  onClose: () => void;
}) {
  const toast = useToast();
  const qc = useQueryClient();
  const { startPreloadPolling } = useWatchlistPreloadPolling();

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (submitting) return;
    const fundCode = form.fund_code.trim();
    if (!fundCode) {
      toast.push("请填写基金代码", "error");
      return;
    }
    if (needsInitialHolding && selectedNavLoading) {
      toast.push("正在读取所选日期 NAV,请稍后再保存", "error");
      return;
    }
    if (needsInitialHolding && !initialHoldingDraft) {
      toast.push("请填写有效持仓金额，并确认所选日期本地已有 NAV", "error");
      return;
    }
    setSubmitting(true);
    try {
      let saved: WatchlistRow;
      let preloadJob: WatchlistPreloadJob | null | undefined;
      if (mode === "add") {
        if (needsInitialHolding && initialHoldingDraft) {
          const txResult = await api.watchlistSetInitialHolding(fundCode, {
            ...initialHoldingDraft.payload,
            is_focus: form.is_focus,
            watchlist_note: form.note || null,
          });
          saved = txResult.watchlist;
          preloadJob = txResult.preload_job;
          qc.invalidateQueries({ queryKey: queryKeys.watchlist.transactions(fundCode) });
          qc.invalidateQueries({ queryKey: queryKeys.fund.summaryForFund(fundCode) });
          qc.invalidateQueries({ queryKey: queryKeys.portfolio.pnl([fundCode]) });
          qc.invalidateQueries({ queryKey: queryKeys.portfolio.pnl([]) });
        } else {
          const payload: WatchlistUpsertPayload = {
            fund_code: fundCode,
            note: form.note || null,
            is_holding: form.is_holding,
            is_focus: form.is_focus,
            holding_amount: null,
          };
          const addResult = await api.watchlistAdd(payload);
          saved = addResult;
          preloadJob = addResult.preload_job;
        }
        toast.push(`${fundCode} 已加入自选池`, "success");
      } else {
        if (needsInitialHolding && initialHoldingDraft) {
          const txResult = await api.watchlistSetInitialHolding(fundCode, {
            ...initialHoldingDraft.payload,
            is_focus: form.is_focus,
            watchlist_note: form.note || null,
          });
          saved = txResult.watchlist;
          preloadJob = txResult.preload_job;
          qc.invalidateQueries({ queryKey: queryKeys.watchlist.transactions(fundCode) });
          qc.invalidateQueries({ queryKey: queryKeys.fund.summaryForFund(fundCode) });
          qc.invalidateQueries({ queryKey: queryKeys.portfolio.pnl([fundCode]) });
          qc.invalidateQueries({ queryKey: queryKeys.portfolio.pnl([]) });
        } else {
          const patch: WatchlistPatchPayload = {
            note: form.note || null,
            is_holding: form.is_holding,
            is_focus: form.is_focus,
          };
          saved = await api.watchlistUpdate(fundCode, patch);
        }
        toast.push(`已更新 ${fundCode}`, "success");
      }
      onSaved?.(saved);
      if (preloadJob) {
        toast.push(`${fundCode} 正在后台同步基金数据`, "info");
        startPreloadPolling(preloadJob);
      }
      onClose();
    } catch (err) {
      toast.push(`保存失败：${String(err)}`, "error");
    } finally {
      setSubmitting(false);
    }
  }

  const saveDisabled = submitting || (
    needsInitialHolding && (selectedNavLoading || initialHoldingDraft == null)
  );

  return { submit, saveDisabled };
}
