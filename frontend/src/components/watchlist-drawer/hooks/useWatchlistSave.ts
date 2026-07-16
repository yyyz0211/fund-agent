import type { Dispatch, FormEvent, SetStateAction } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useToast } from "@/components/Toast";
import { api } from "@/lib/api";
import type { AutoTransactionDraft } from "@/lib/auto-transaction";
import type {
  WatchlistPatchPayload,
  WatchlistPreloadJob,
  WatchlistRow,
  WatchlistUpsertPayload,
} from "@/types/api";
import type { Mode, WatchlistFormState } from "../types";

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

  function invalidateFundCaches(code: string) {
    qc.invalidateQueries({ queryKey: ["watchlist"] });
    qc.invalidateQueries({ queryKey: ["fundSummary", code] });
    qc.invalidateQueries({ queryKey: ["fund", code] });
    qc.invalidateQueries({ queryKey: ["nav", code] });
    qc.invalidateQueries({ queryKey: ["navHistory", code] });
    qc.invalidateQueries({ queryKey: ["metrics", code] });
    qc.invalidateQueries({ queryKey: ["portfolioPnl", [code]] });
    qc.invalidateQueries({ queryKey: ["portfolioPnl", []] });
    qc.invalidateQueries({ queryKey: ["fundDiagnosis", code] });
  }

  function startPreloadPolling(job: WatchlistPreloadJob | null | undefined) {
    if (!job || typeof window === "undefined") return;
    const terminal = new Set(["done", "partial", "failed", "missing"]);
    let attempts = 0;
    const maxAttempts = 120;
    const code = job.fund_code;
    const timer = window.setInterval(async () => {
      attempts += 1;
      try {
        const snapshot = await api.watchlistPreloadJob(code, job.job_id);
        if (!terminal.has(snapshot.status) && attempts < maxAttempts) return;
        window.clearInterval(timer);
        invalidateFundCaches(code);
        if (snapshot.status === "done") {
          toast.push(`${code} 基金数据已同步`, "success");
        } else if (snapshot.status === "partial") {
          toast.push(`${code} 基金数据部分同步完成，仍有字段缺失`, "info");
        } else if (snapshot.status === "failed") {
          toast.push(`${code} 自动同步失败，可稍后刷新`, "error");
        }
      } catch (err) {
        window.clearInterval(timer);
        invalidateFundCaches(code);
        toast.push(`同步状态查询失败：${String(err)}`, "error");
      }
    }, 1500);
  }

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
          qc.invalidateQueries({ queryKey: ["watchlistTransactions", fundCode] });
          qc.invalidateQueries({ queryKey: ["fundSummary", fundCode] });
          qc.invalidateQueries({ queryKey: ["portfolioPnl", [fundCode]] });
          qc.invalidateQueries({ queryKey: ["portfolioPnl", []] });
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
          qc.invalidateQueries({ queryKey: ["watchlistTransactions", fundCode] });
          qc.invalidateQueries({ queryKey: ["fundSummary", fundCode] });
          qc.invalidateQueries({ queryKey: ["portfolioPnl", [fundCode]] });
          qc.invalidateQueries({ queryKey: ["portfolioPnl", []] });
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
