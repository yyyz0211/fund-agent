"use client";
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StateBlock } from "@/components/StateBlock";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { api } from "@/lib/api";
import { useToast } from "@/components/Toast";
import { cn } from "@/lib/cn";
import { formatDate, formatNav, formatMoney } from "@/lib/format";
import {
  buildAutoTransactionDraft,
  isSixDigitFundCode,
  type AutoTransactionDraft,
} from "@/lib/auto-transaction";
import {
  blankInvestmentPlanForm,
  validateInvestmentPlanDraft,
  type InvestmentPlanFormState,
} from "@/lib/investment-plan";
import { shouldUseInitialHoldingEndpoint } from "@/lib/watchlist-guards";
import type {
  FundTransaction, InvestmentPlan, NavPoint, PendingBuy, TransactionUpsertPayload,
  WatchlistPatchPayload, WatchlistPreloadJob, WatchlistRow, WatchlistUpsertPayload,
} from "@/types/api";

interface WatchlistDrawerProps {
  /** 编辑模式时传入当前行;新增模式留空。 */
  row?: WatchlistRow | null;
  /** 新增模式时预填基金代码(从详情页跳过来)。 */
  prefillFundCode?: string;
  open: boolean;
  onClose: () => void;
  /** 保存成功后回调,用于让上层 invalidate query。 */
  onSaved?: (row: WatchlistRow) => void;
}

type Mode = "add" | "edit";
type Tab = "basic" | "transactions" | "plans" | "pending";

interface FormState {
  fund_code: string;
  note: string;
  is_holding: boolean;
  is_focus: boolean;
  holding_amount: string;
  holding_date: string;
}

interface TxFormState {
  tx_date: string;
  amount: string;
  fee: string;
  note: string;
}

interface PendingBuyFormState {
  request_date: string;
  amount: string;
  fee: string;
  note: string;
}

function rowToForm(row: WatchlistRow): FormState {
  return {
    fund_code: row.fund_code,
    note: row.note ?? "",
    is_holding: !!row.is_holding,
    is_focus: !!row.is_focus,
    holding_amount: row.holding_amount?.toString() ?? "",
    holding_date: row.buy_date ?? "",
  };
}

function blankForm(fundCode = ""): FormState {
  return {
    fund_code: fundCode,
    note: "",
    is_holding: false,
    is_focus: false,
    holding_amount: "",
    holding_date: "",
  };
}

function blankTxForm(): TxFormState {
  return { tx_date: "", amount: "", fee: "", note: "" };
}

function blankPendingBuyForm(): PendingBuyFormState {
  return { request_date: "", amount: "", fee: "", note: "" };
}

function parsePositiveNumber(value: string): number | null {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return null;
  return n;
}

function todayInputValue(): string {
  const now = new Date();
  now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
  return now.toISOString().slice(0, 10);
}

export function WatchlistDrawer({
  row, prefillFundCode, open, onClose, onSaved,
}: WatchlistDrawerProps) {
  const mode: Mode = row ? "edit" : "add";
  const toast = useToast();
  const qc = useQueryClient();
  const [form, setForm] = useState<FormState>(() =>
    row ? rowToForm(row) : blankForm(prefillFundCode ?? ""),
  );
  const [submitting, setSubmitting] = useState(false);
  const [activeTab, setActiveTab] = useState<Tab>("basic");
  const [txForm, setTxForm] = useState<TxFormState>(blankTxForm);
  const [txFormOpen, setTxFormOpen] = useState(false);
  const [pendingForm, setPendingForm] = useState<PendingBuyFormState>(blankPendingBuyForm);
  const [pendingFormOpen, setPendingFormOpen] = useState(false);
  const [confirmDates, setConfirmDates] = useState<Record<number, string>>({});
  const [planForm, setPlanForm] = useState<InvestmentPlanFormState>(blankInvestmentPlanForm);
  const [editingPlanId, setEditingPlanId] = useState<number | null>(null);

  // 每次打开抽屉或 row/prefill 变化时重置表单 —— 避免上一次的脏值
  // 留在字段里。
  useEffect(() => {
    if (!open) return;
    setForm(row ? rowToForm(row) : blankForm(prefillFundCode ?? ""));
    setActiveTab("basic");
    setTxForm(blankTxForm());
    setTxFormOpen(false);
    setPendingForm(blankPendingBuyForm());
    setPendingFormOpen(false);
    setConfirmDates({});
    setPlanForm(blankInvestmentPlanForm());
    setEditingPlanId(null);
  }, [open, row, prefillFundCode]);

  // Esc 关闭
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape" && !submitting) onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose, submitting]);

  // 只有已经保存为持仓的行才显示交易明细 tab;从关注切换为持仓时,
  // 先在基础表单里创建首笔交易,保存后再出现加仓 tab。
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
  }, [open, pendingBuysQuery.data]);

  useEffect(() => {
    const navDate = selectedNavQuery.data?.nav_date;
    if (!open || !needsInitialHolding || !navDate || form.holding_date) return;
    setForm((prev) => prev.holding_date ? prev : { ...prev, holding_date: navDate });
  }, [form.holding_date, needsInitialHolding, open, selectedNavQuery.data?.nav_date]);

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
    showTxTab,
    txForm.tx_date,
    txFormOpen,
  ]);

  const addTx = useMutation({
    mutationFn: (payload: TransactionUpsertPayload) =>
      api.watchlistAddTransaction(fundCodeForTx, payload),
    onSuccess: (res) => {
      qc.setQueryData<WatchlistRow[]>(["watchlist"], (prev) => {
        if (!prev) return prev;
        return prev.map((r) =>
          r.fund_code === res.watchlist.fund_code ? res.watchlist : r,
        );
      });
      qc.invalidateQueries({ queryKey: ["watchlist"] });
      qc.invalidateQueries({ queryKey: ["watchlistTransactions", fundCodeForTx] });
      qc.invalidateQueries({ queryKey: ["fundSummary", fundCodeForTx] });
      qc.invalidateQueries({ queryKey: ["portfolioPnl", [fundCodeForTx]] });
      qc.invalidateQueries({ queryKey: ["portfolioPnl", []] });
      setTxForm(blankTxForm());
      setTxFormOpen(false);
      toast.push(`已添加加仓 ¥${res.transaction.amount.toFixed(2)}`, "success");
    },
    onError: (err) => toast.push(`添加加仓失败：${String(err)}`, "error"),
  });

  const removeTx = useMutation({
    mutationFn: (txId: number) => api.watchlistRemoveTransaction(fundCodeForTx, txId),
    onSuccess: (res) => {
      qc.setQueryData<WatchlistRow[]>(["watchlist"], (prev) => {
        if (!prev) return prev;
        return prev.map((r) =>
          r.fund_code === fundCodeForTx && res.watchlist ? res.watchlist : r,
        );
      });
      qc.invalidateQueries({ queryKey: ["watchlist"] });
      qc.invalidateQueries({ queryKey: ["watchlistTransactions", fundCodeForTx] });
      qc.invalidateQueries({ queryKey: ["fundSummary", fundCodeForTx] });
      qc.invalidateQueries({ queryKey: ["portfolioPnl", [fundCodeForTx]] });
      qc.invalidateQueries({ queryKey: ["portfolioPnl", []] });
      toast.push("已删除加仓记录", "success");
    },
    onError: (err) => toast.push(`删除加仓失败：${String(err)}`, "error"),
  });

  const addPlan = useMutation({
    mutationFn: () => {
      if (!planDraft.ok) throw new Error(planDraft.error);
      return api.investmentPlanAdd(fundCodeForTx, planDraft.payload);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["investmentPlans", fundCodeForTx] });
      setPlanForm(blankInvestmentPlanForm());
      setEditingPlanId(null);
      toast.push("定投计划已保存", "success");
    },
    onError: (err) => toast.push(`保存定投计划失败：${String(err)}`, "error"),
  });

  const updatePlan = useMutation({
    mutationFn: ({ planId }: { planId: number }) => {
      if (!planDraft.ok) throw new Error(planDraft.error);
      const { status: _status, ...patch } = planDraft.payload;
      return api.investmentPlanUpdate(fundCodeForTx, planId, patch);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["investmentPlans", fundCodeForTx] });
      setPlanForm(blankInvestmentPlanForm());
      setEditingPlanId(null);
      toast.push("定投计划已更新", "success");
    },
    onError: (err) => toast.push(`更新定投计划失败：${String(err)}`, "error"),
  });

  const removePlan = useMutation({
    mutationFn: (planId: number) => api.investmentPlanRemove(fundCodeForTx, planId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["investmentPlans", fundCodeForTx] });
      toast.push("定投计划已删除", "success");
    },
    onError: (err) => toast.push(`删除定投计划失败：${String(err)}`, "error"),
  });

  const togglePlanStatus = useMutation({
    mutationFn: (plan: InvestmentPlan) =>
      api.investmentPlanUpdate(fundCodeForTx, plan.id, {
        status: plan.status === "active" ? "paused" : "active",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["investmentPlans", fundCodeForTx] });
      toast.push("定投计划状态已更新", "success");
    },
    onError: (err) => toast.push(`更新定投计划状态失败：${String(err)}`, "error"),
  });

  const addPendingBuy = useMutation({
    mutationFn: () => {
      const amount = parsePositiveNumber(pendingForm.amount);
      const fee = pendingForm.fee.trim() ? parsePositiveNumber(pendingForm.fee) : null;
      if (!pendingForm.request_date) throw new Error("请选择申购日期");
      if (amount == null) throw new Error("请填写大于 0 的申购金额");
      if (pendingForm.fee.trim() && fee == null) throw new Error("请填写有效手续费");
      return api.pendingBuyAdd(fundCodeForTx, {
        request_date: pendingForm.request_date,
        amount,
        fee,
        note: pendingForm.note.trim() || null,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pendingBuys", fundCodeForTx] });
      setPendingForm(blankPendingBuyForm());
      setPendingFormOpen(false);
      toast.push("已记录申购中金额", "success");
    },
    onError: (err) => toast.push(`记录申购中失败：${String(err)}`, "error"),
  });

  const confirmPendingBuy = useMutation({
    mutationFn: ({ pendingId, txDate }: { pendingId: number; txDate: string }) =>
      api.pendingBuyConfirm(fundCodeForTx, pendingId, { tx_date: txDate }),
    onSuccess: (res) => {
      qc.setQueryData<WatchlistRow[]>(["watchlist"], (prev) => {
        if (!prev) return prev;
        return prev.map((r) =>
          r.fund_code === res.watchlist.fund_code ? res.watchlist : r,
        );
      });
      qc.invalidateQueries({ queryKey: ["pendingBuys", fundCodeForTx] });
      qc.invalidateQueries({ queryKey: ["watchlistTransactions", fundCodeForTx] });
      qc.invalidateQueries({ queryKey: ["watchlist"] });
      qc.invalidateQueries({ queryKey: ["fundSummary", fundCodeForTx] });
      qc.invalidateQueries({ queryKey: ["portfolioPnl", [fundCodeForTx]] });
      qc.invalidateQueries({ queryKey: ["portfolioPnl", []] });
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
    mutationFn: (pendingId: number) => api.pendingBuyCancel(fundCodeForTx, pendingId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pendingBuys", fundCodeForTx] });
      toast.push("申购中记录已取消", "success");
    },
    onError: (err) => toast.push(`取消申购失败：${String(err)}`, "error"),
  });

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

  if (!open) return null;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (submitting) return;
    const fundCode = form.fund_code.trim();
    if (!fundCode) {
      toast.push("请填写基金代码", "error");
      return;
    }
    if (needsInitialHolding && selectedNavQuery.isLoading) {
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

  function setField<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function setTxField<K extends keyof TxFormState>(key: K, value: TxFormState[K]) {
    setTxForm((prev) => ({ ...prev, [key]: value }));
  }

  function setPendingField<K extends keyof PendingBuyFormState>(
    key: K,
    value: PendingBuyFormState[K],
  ) {
    setPendingForm((prev) => ({ ...prev, [key]: value }));
  }

  function confirmPending(id: number) {
    const txDate = confirmDates[id];
    if (!txDate) {
      toast.push("请选择确认日期", "error");
      return;
    }
    confirmPendingBuy.mutate({ pendingId: id, txDate });
  }

  function setPlanField<K extends keyof InvestmentPlanFormState>(
    key: K,
    value: InvestmentPlanFormState[K],
  ) {
    setPlanForm((prev) => ({ ...prev, [key]: value }));
  }

  function editPlan(plan: InvestmentPlan) {
    setEditingPlanId(plan.id);
    setPlanForm({
      amount: String(plan.amount),
      frequency: plan.frequency,
      day_rule: plan.day_rule,
      start_date: plan.start_date,
      end_date: plan.end_date ?? "",
      note: plan.note ?? "",
    });
  }

  function submitPlan() {
    if (!planDraft.ok) {
      toast.push(planDraft.error, "error");
      return;
    }
    if (editingPlanId != null) {
      updatePlan.mutate({ planId: editingPlanId });
    } else {
      addPlan.mutate();
    }
  }

  function startPendingBuyFromPlan(plan: InvestmentPlan) {
    setActiveTab("pending");
    setPendingFormOpen(true);
    setPendingForm({
      request_date: todayInputValue(),
      amount: String(plan.amount),
      fee: "",
      note: plan.note ? `定投计划: ${plan.note}` : "定投计划本次申购",
    });
    toast.push("已带入定投金额,请确认申购日期后保存", "info");
  }

  function submitTx(e: React.FormEvent) {
    e.preventDefault();
    if (selectedNavQuery.isLoading) {
      toast.push("正在读取所选日期 NAV,请稍后再提交", "error");
      return;
    }
    if (!txDraft) {
      toast.push("请填写有效投入金额，并确认所选日期本地已有 NAV", "error");
      return;
    }
    addTx.mutate(txDraft.payload);
  }

  const saveDisabled = submitting || (
    needsInitialHolding && (
      selectedNavQuery.isLoading || initialHoldingDraft == null
    )
  );

  return (
    <div
      aria-modal="true"
      className="fixed inset-0 z-40 flex"
      role="dialog"
    >
      <button
        aria-label="关闭"
        className="flex-1 bg-gray-950/30 backdrop-blur-sm"
        onClick={() => !submitting && onClose()}
        type="button"
      />
      <aside className="flex h-full w-full max-w-[460px] flex-col border-l border-gray-200 bg-white shadow-xl">
        <header className="flex items-center justify-between border-b border-gray-200 px-5 py-4">
          <div>
            <h2 className="text-base font-semibold text-gray-900">
              {mode === "add" ? "加入自选池" : `编辑 ${row?.fund_code ?? ""}`}
            </h2>
            <p className="mt-1 text-xs text-gray-500">
              持仓字段可空,只有勾选"持仓"时才会计入持仓汇总。
            </p>
          </div>
          <Button
            aria-label="关闭"
            onClick={onClose}
            size="sm"
            type="button"
            variant="ghost"
            disabled={submitting}
          >
            <X className="h-4 w-4" />
          </Button>
        </header>

        {hasTabs && (
          <div className="flex border-b border-gray-200 px-5">
            <TabButton
              active={activeTab === "basic"}
              onClick={() => setActiveTab("basic")}
            >
              基础
            </TabButton>
            {showTxTab && (
              <TabButton
                active={activeTab === "transactions"}
                onClick={() => setActiveTab("transactions")}
              >
                加仓记录
                {row && row.transaction_count != null && row.transaction_count > 0 && (
                  <span className="ml-1 inline-flex items-center rounded-full bg-blue-100 px-1.5 text-[10px] font-semibold text-blue-700">
                    {row.transaction_count}
                  </span>
                )}
              </TabButton>
            )}
            {showPlanTab && (
              <TabButton
                active={activeTab === "plans"}
                onClick={() => setActiveTab("plans")}
              >
                定投计划
              </TabButton>
            )}
            {showPendingTab && (
              <TabButton
                active={activeTab === "pending"}
                onClick={() => setActiveTab("pending")}
              >
                申购中
              </TabButton>
            )}
          </div>
        )}

        <form className="flex flex-1 flex-col" onSubmit={submit}>
          <div className="flex-1 space-y-4 overflow-y-auto px-5 py-4">
            {(!hasTabs || activeTab === "basic") && (
              <>
                <div>
                  <label className="mb-1 block text-xs font-medium text-gray-700">基金代码</label>
                  <Input
                    disabled={mode === "edit"}
                    onChange={(e) => setField("fund_code", e.target.value)}
                    placeholder="例如 110011"
                    value={form.fund_code}
                  />
                  <p className="mt-1 text-[11px] text-gray-500">
                    {mode === "edit" ? "代码为业务键,不可改。" : "代码是业务键,后续不可修改。"}
                  </p>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <CheckboxField
                    checked={form.is_holding}
                    disabled={isAlreadyHolding}
                    hint={
                      isAlreadyHolding
                        ? "已持仓,请用『加仓记录』tab 追加交易"
                        : "标记为已持有"
                    }
                    label="持仓"
                    onChange={(v) => setField("is_holding", v)}
                  />
                  <CheckboxField
                    checked={form.is_focus}
                    hint="重点观察,仅标记"
                    label="关注"
                    onChange={(v) => setField("is_focus", v)}
                  />
                </div>

                {isAlreadyHolding && (row?.transaction_count ?? 0) > 0 && (
                  <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">
                    该基金已有 {row?.transaction_count} 笔交易记录,无法再走"初始建仓"路径;
                    请切到"加仓记录"tab 继续追加。
                  </p>
                )}

                {needsInitialHolding && (
                  <>
                    <div>
                      <label className="mb-1 block text-xs font-medium text-gray-700">建仓日期</label>
                      <Input
                        onChange={(e) => setField("holding_date", e.target.value)}
                        type="date"
                        value={form.holding_date}
                      />
                      <p className="mt-1 text-[11px] text-gray-500">
                        系统会精确读取该日期的本地 NAV；该日无净值时不能保存。
                      </p>
                    </div>
                    <div>
                      <label className="mb-1 block text-xs font-medium text-gray-700">持仓金额</label>
                      <Input
                        inputMode="decimal"
                        min={0}
                        onChange={(e) => setField("holding_amount", e.target.value)}
                        placeholder="例如 12000.50"
                        step="0.01"
                        type="number"
                        value={form.holding_amount}
                      />
                    </div>
                    <AutoNavSummary
                      draft={initialHoldingDraft}
                      latestNav={selectedNavQuery.data}
                      navError={selectedNavQuery.error}
                      navLoading={selectedNavQuery.isLoading}
                      purpose="initial"
                      selectedDate={form.holding_date}
                    />
                  </>
                )}

                {form.is_holding && mode === "edit" && row?.is_holding && (
                  <HoldingSnapshot row={row} />
                )}

                {!form.is_holding && mode === "add" && (
                  <p className="rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-500">
                    未勾选持仓时只加入观察清单,不会写入持仓金额或交易记录。
                  </p>
                )}

                <div>
                  <label className="mb-1 block text-xs font-medium text-gray-700">备注</label>
                  <textarea
                    className="block w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-950 shadow-sm placeholder:text-gray-400 focus:border-blue-300 focus:outline-none focus:ring-2 focus:ring-blue-100"
                    onChange={(e) => setField("note", e.target.value)}
                    placeholder="可以写买入理由、计划关注指标等"
                    rows={3}
                    value={form.note}
                  />
                </div>
              </>
            )}

            {showTxTab && activeTab === "transactions" && (
              <TransactionsTab
                costNav={row?.cost_nav}
                holdingShare={row?.holding_share}
                latestNav={selectedNavQuery.data}
                navDraft={txDraft}
                navError={selectedNavQuery.error}
                navLoading={selectedNavQuery.isLoading}
                isSubmitting={addTx.isPending}
                isTxFormOpen={txFormOpen}
                onDelete={(id) => removeTx.mutate(id)}
                onOpenTxForm={() => setTxFormOpen((v) => !v)}
                onChangeTxField={setTxField}
                onSubmitTx={submitTx}
                removeTx={removeTx}
                txForm={txForm}
                txs={txQuery.data ?? []}
                txState={{
                  isLoading: txQuery.isLoading,
                  error: txQuery.error,
                }}
              />
            )}

            {showPlanTab && activeTab === "plans" && (
              <InvestmentPlansTab
                editingPlanId={editingPlanId}
                isSaving={addPlan.isPending || updatePlan.isPending}
                onCancelEdit={() => {
                  setEditingPlanId(null);
                  setPlanForm(blankInvestmentPlanForm());
                }}
                onChangePlanField={setPlanField}
                onDelete={(id) => {
                  if (typeof window !== "undefined") {
                    const ok = window.confirm("确认删除这条定投计划?");
                    if (!ok) return;
                  }
                  removePlan.mutate(id);
                }}
                onEdit={editPlan}
                onRecordPendingFromPlan={startPendingBuyFromPlan}
                onSubmit={submitPlan}
                onToggle={togglePlanStatus.mutate}
                planDraft={planDraft}
                planForm={planForm}
                plans={plansQuery.data ?? []}
                removePending={removePlan.isPending}
                togglePending={togglePlanStatus.isPending}
                state={{
                  isLoading: plansQuery.isLoading,
                  error: plansQuery.error,
                }}
              />
            )}

            {showPendingTab && activeTab === "pending" && (
              <PendingBuysTab
                confirmDates={confirmDates}
                isAdding={addPendingBuy.isPending}
                isCancelling={cancelPendingBuy.isPending}
                isConfirming={confirmPendingBuy.isPending}
                isPendingFormOpen={pendingFormOpen}
                onCancel={(id) => cancelPendingBuy.mutate(id)}
                onChangeConfirmDate={(id, value) =>
                  setConfirmDates((prev) => ({ ...prev, [id]: value }))
                }
                onChangePendingField={setPendingField}
                onConfirm={confirmPending}
                onOpenPendingForm={() => setPendingFormOpen((v) => !v)}
                onSubmitPending={() => addPendingBuy.mutate()}
                pendingBuys={pendingBuysQuery.data ?? []}
                pendingForm={pendingForm}
                state={{
                  isLoading: pendingBuysQuery.isLoading,
                  error: pendingBuysQuery.error,
                }}
              />
            )}
          </div>

          <footer className="flex items-center justify-end gap-2 border-t border-gray-200 bg-gray-50 px-5 py-3">
            <Button onClick={onClose} type="button" variant="outline" disabled={submitting}>
              取消
            </Button>
            {(!hasTabs || activeTab === "basic") && (
              <Button disabled={saveDisabled} type="submit">
                {submitting ? "保存中..." : "保存"}
              </Button>
            )}
          </footer>
        </form>
      </aside>
    </div>
  );
}

function TabButton({
  active, onClick, children,
}: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      className={cn(
        "-mb-px border-b-2 px-3 py-2 text-sm font-medium transition",
        active
          ? "border-blue-600 text-blue-700"
          : "border-transparent text-gray-500 hover:text-gray-700",
      )}
      onClick={onClick}
      type="button"
    >
      {children}
    </button>
  );
}

function HoldingSnapshot({ row }: { row: WatchlistRow }) {
  const isTxBasis = row.cost_nav_basis === "transactions";
  return (
    <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-xs text-gray-600">
      <div className="font-medium text-gray-900">
        {isTxBasis ? "持仓由交易记录维护" : "已有持仓信息"}
      </div>
      <div className="mt-2 grid grid-cols-2 gap-2">
        <SummaryItem label="投入金额" value={row.holding_amount != null ? `¥ ${formatMoney(row.holding_amount)}` : "—"} />
        <SummaryItem label="持仓份额" value={row.holding_share != null ? row.holding_share.toFixed(2) : "—"} />
        <SummaryItem label="成本 NAV" value={row.cost_nav != null ? formatNav(row.cost_nav) : "—"} />
        <SummaryItem label="建仓日期" value={row.buy_date ? formatDate(row.buy_date) : "—"} />
      </div>
      <p className="mt-2 text-[11px] text-gray-500">
        追加投入请使用“加仓记录”,系统会按所选交易日期 NAV 自动重算份额和成本。
      </p>
    </div>
  );
}

function AutoNavSummary({
  draft, latestNav, navError, navLoading, purpose, selectedDate,
}: {
  draft: AutoTransactionDraft | null;
  latestNav: NavPoint | undefined;
  navError: unknown;
  navLoading: boolean;
  purpose: "initial" | "add";
  selectedDate?: string;
}) {
  if (navLoading) {
    return (
      <StateBlock title={selectedDate ? "读取所选日期 NAV" : "读取最新 NAV"} tone="loading">
        {selectedDate ? "正在读取所选日期的本地净值。" : "正在读取本地最新净值。"}
      </StateBlock>
    );
  }
  if (navError != null) {
    return (
      <StateBlock title={selectedDate ? "该日期无本地 NAV" : "缺少最新 NAV"} tone="error">
        {`${navError}`}。请刷新基金数据或选择有净值的交易日。
      </StateBlock>
    );
  }
  if (!latestNav || latestNav.accumulated_nav == null || latestNav.accumulated_nav <= 0) {
    return (
      <StateBlock title={selectedDate ? "等待所选日期 NAV" : "等待最新 NAV"} tone="empty">
        填写基金代码和交易日期后会自动读取本地 NAV；没有本地数据时请先刷新基金。
      </StateBlock>
    );
  }
  const label = purpose === "initial" ? "首笔持仓" : "本次加仓";
  return (
    <div className="rounded-lg bg-blue-50 p-3 text-xs text-blue-900">
      <div className="font-medium">{label}将使用本地 NAV</div>
      <div className="mt-2 grid grid-cols-3 gap-2">
        <SummaryItem label="净值日期" value={formatDate(latestNav.nav_date)} />
        <SummaryItem label="成本 NAV" value={formatNav(latestNav.accumulated_nav)} />
        <SummaryItem
          label="预计份额"
          value={draft ? draft.estimatedShare.toFixed(2) : "填写金额后计算"}
        />
      </div>
      <p className="mt-2 text-[11px] text-blue-700">
        source/as_of: {latestNav.source} / {latestNav.as_of ?? "—"}
      </p>
    </div>
  );
}

function SummaryItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[11px] text-gray-500">{label}</div>
      <div className="mt-0.5 font-medium text-gray-900">{value}</div>
    </div>
  );
}

function TransactionsTab({
  costNav, holdingShare, isSubmitting, isTxFormOpen, latestNav, navDraft,
  navError, navLoading, onDelete, onOpenTxForm, onChangeTxField, onSubmitTx,
  removeTx, txForm, txs, txState,
}: {
  costNav: number | null | undefined;
  holdingShare: number | null | undefined;
  latestNav: NavPoint | undefined;
  navDraft: AutoTransactionDraft | null;
  navError: unknown;
  navLoading: boolean;
  isSubmitting: boolean;
  isTxFormOpen: boolean;
  onDelete: (id: number) => void;
  onOpenTxForm: () => void;
  onChangeTxField: <K extends keyof TxFormState>(k: K, v: TxFormState[K]) => void;
  onSubmitTx: (e: React.FormEvent) => void;
  removeTx: { isPending: boolean };
  txForm: TxFormState;
  txs: FundTransaction[];
  txState: { isLoading: boolean; error: unknown };
}) {
  return (
    <div className="space-y-4">
      <div className="rounded-lg bg-blue-50 p-3 text-xs text-blue-900">
        <span className="font-medium">加权成本</span>
        <span className="ml-2">¥ {costNav != null ? formatNav(costNav) : "—"}</span>
        <span className="mx-2 text-blue-300">·</span>
        <span className="font-medium">共</span>
        <span className="ml-1">
          {holdingShare != null ? `${holdingShare.toFixed(2)} 份` : "—"}
        </span>
        <p className="mt-1 text-[11px] text-blue-700">
          每次添加加仓会按加权平均自动重算上述数字。
        </p>
      </div>

      <div className="flex items-center justify-between">
        <div className="text-xs text-gray-500">
          {txs.length === 0
            ? "暂无加仓记录"
            : `共 ${txs.length} 笔,按日期从早到晚`}
        </div>
        <Button onClick={onOpenTxForm} size="sm" type="button" variant="outline">
          <Plus className="mr-1 h-3.5 w-3.5" />
          {isTxFormOpen ? "收起" : "添加加仓"}
        </Button>
      </div>

      {isTxFormOpen && (
        <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
          <div className="space-y-3">
            <div>
              <label className="mb-1 block text-[11px] font-medium text-gray-700">加仓日期</label>
              <Input
                onChange={(e) => onChangeTxField("tx_date", e.target.value)}
                type="date"
                value={txForm.tx_date}
              />
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-gray-700">投入金额 ¥</label>
              <Input
                inputMode="decimal"
                min={0}
                onChange={(e) => onChangeTxField("amount", e.target.value)}
                placeholder="1000"
                step="0.01"
                type="number"
                value={txForm.amount}
              />
            </div>
            <AutoNavSummary
              draft={navDraft}
              latestNav={latestNav}
              navError={navError}
              navLoading={navLoading}
              purpose="add"
              selectedDate={txForm.tx_date}
            />
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="mb-1 block text-[11px] font-medium text-gray-700">手续费(可选)</label>
                <Input
                  inputMode="decimal"
                  min={0}
                  onChange={(e) => onChangeTxField("fee", e.target.value)}
                  placeholder="0.00"
                  step="0.01"
                  type="number"
                  value={txForm.fee}
                />
              </div>
              <div>
                <label className="mb-1 block text-[11px] font-medium text-gray-700">备注(可选)</label>
                <Input
                  onChange={(e) => onChangeTxField("note", e.target.value)}
                  placeholder="如:大跌加仓"
                  value={txForm.note}
                />
              </div>
            </div>
          </div>
          <div className="mt-3 flex justify-end gap-2">
            <Button
              onClick={onOpenTxForm}
              size="sm"
              type="button"
              variant="ghost"
            >
              取消
            </Button>
            <Button
              disabled={isSubmitting || navLoading || navDraft == null}
              onClick={onSubmitTx}
              size="sm"
              type="button"
            >
              {isSubmitting ? "保存中..." : "确认加仓"}
            </Button>
          </div>
        </div>
      )}

      {txState.isLoading && (
        <StateBlock title="读取加仓记录" tone="loading">正在拉取交易明细。</StateBlock>
      )}
      {txState.error != null && (
        <StateBlock title="加仓记录加载失败" tone="error">
          {`${txState.error}`}
        </StateBlock>
      )}
      {!txState.isLoading && !txState.error && txs.length > 0 && (
        <div className="overflow-hidden rounded-lg border border-gray-200">
          <Table>
            <THead>
              <TR>
                <TH>日期</TH>
                <TH className="text-right">金额</TH>
                <TH className="text-right">NAV</TH>
                <TH className="text-right">份额</TH>
                <TH className="text-right" />
              </TR>
            </THead>
            <TBody>
              {txs.map((t) => (
                <TR key={t.id} className="hover:bg-gray-50">
                  <TD className="text-xs text-gray-600">{formatDate(t.tx_date)}</TD>
                  <TD className="text-right text-xs">¥ {formatMoney(t.amount)}</TD>
                  <TD className="text-right text-xs">{formatNav(t.nav)}</TD>
                  <TD className="text-right text-xs">
                    {t.share != null ? t.share.toFixed(2) : "—"}
                  </TD>
                  <TD className="text-right">
                    <Button
                      aria-label="删除加仓"
                      disabled={removeTx.isPending}
                      onClick={() => {
                        if (typeof window !== "undefined") {
                          const ok = window.confirm(
                            `确认删除 ${formatDate(t.tx_date)} 投入 ¥${t.amount.toFixed(2)} 的加仓记录?`,
                          );
                          if (!ok) return;
                        }
                        onDelete(t.id);
                      }}
                      size="sm"
                      type="button"
                      variant="ghost"
                    >
                      <Trash2 className="h-3.5 w-3.5 text-red-600" />
                    </Button>
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </div>
      )}
    </div>
  );
}

function pendingStatusLabel(status: PendingBuy["status"], stage: PendingBuy["stage"]): string {
  if (status === "confirmed") return "已确认";
  if (status === "cancelled") return "已取消";
  if (stage === "confirmable") return "可确认";
  if (stage === "submitted") return "等待净值";
  return "申购中";
}

function frequencyLabel(frequency: InvestmentPlan["frequency"]): string {
  if (frequency === "daily") return "每日";
  if (frequency === "weekly") return "每周";
  return "每月";
}

function PendingBuysTab({
  confirmDates,
  isAdding,
  isCancelling,
  isConfirming,
  isPendingFormOpen,
  onCancel,
  onChangeConfirmDate,
  onChangePendingField,
  onConfirm,
  onOpenPendingForm,
  onSubmitPending,
  pendingBuys,
  pendingForm,
  state,
}: {
  confirmDates: Record<number, string>;
  isAdding: boolean;
  isCancelling: boolean;
  isConfirming: boolean;
  isPendingFormOpen: boolean;
  onCancel: (id: number) => void;
  onChangeConfirmDate: (id: number, value: string) => void;
  onChangePendingField: <K extends keyof PendingBuyFormState>(
    k: K,
    v: PendingBuyFormState[K],
  ) => void;
  onConfirm: (id: number) => void;
  onOpenPendingForm: () => void;
  onSubmitPending: () => void;
  pendingBuys: PendingBuy[];
  pendingForm: PendingBuyFormState;
  state: { isLoading: boolean; error: unknown };
}) {
  const activePendingAmount = pendingBuys
    .filter((row) => row.status === "pending")
    .reduce((sum, row) => sum + (row.pending_amount ?? row.amount), 0);

  return (
    <div className="space-y-4">
      <div className="rounded-lg bg-amber-50 p-3 text-xs text-amber-900">
        <div className="font-medium">申购中金额不计入当前市值</div>
        <p className="mt-1 text-amber-800">
          等确认 NAV 和份额后,再从这里转成正式加仓记录,届时才进入持仓市值和浮盈浮亏。
        </p>
        {activePendingAmount > 0 && (
          <p className="mt-2 font-medium">当前申购中 ¥ {formatMoney(activePendingAmount)}</p>
        )}
      </div>

      <div className="flex items-center justify-between">
        <div className="text-xs text-gray-500">
          {pendingBuys.length === 0 ? "暂无申购中记录" : `共 ${pendingBuys.length} 条记录`}
        </div>
        <Button onClick={onOpenPendingForm} size="sm" type="button" variant="outline">
          <Plus className="mr-1 h-3.5 w-3.5" />
          {isPendingFormOpen ? "收起" : "记录申购中"}
        </Button>
      </div>

      {isPendingFormOpen && (
        <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="mb-1 block text-[11px] font-medium text-gray-700">申购日期</label>
              <Input
                onChange={(e) => onChangePendingField("request_date", e.target.value)}
                type="date"
                value={pendingForm.request_date}
              />
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-gray-700">申购金额 ¥</label>
              <Input
                inputMode="decimal"
                min={0}
                onChange={(e) => onChangePendingField("amount", e.target.value)}
                placeholder="1000"
                step="0.01"
                type="number"
                value={pendingForm.amount}
              />
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-gray-700">手续费(可选)</label>
              <Input
                inputMode="decimal"
                min={0}
                onChange={(e) => onChangePendingField("fee", e.target.value)}
                placeholder="0.00"
                step="0.01"
                type="number"
                value={pendingForm.fee}
              />
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-gray-700">备注(可选)</label>
              <Input
                onChange={(e) => onChangePendingField("note", e.target.value)}
                placeholder="如:定投发起"
                value={pendingForm.note}
              />
            </div>
          </div>
          <div className="mt-3 flex justify-end gap-2">
            <Button onClick={onOpenPendingForm} size="sm" type="button" variant="ghost">
              取消
            </Button>
            <Button
              disabled={isAdding}
              onClick={onSubmitPending}
              size="sm"
              type="button"
            >
              {isAdding ? "保存中..." : "保存申购中"}
            </Button>
          </div>
        </div>
      )}

      {state.isLoading && (
        <StateBlock title="读取申购中记录" tone="loading">正在拉取待确认申购。</StateBlock>
      )}
      {state.error != null && (
        <StateBlock title="申购中记录加载失败" tone="error">{`${state.error}`}</StateBlock>
      )}
      {!state.isLoading && !state.error && pendingBuys.length === 0 && (
        <StateBlock title="暂无申购中记录" tone="empty">
          记录后不会影响当前市值;确认后才会写入加仓记录。
        </StateBlock>
      )}
      {!state.isLoading && !state.error && pendingBuys.length > 0 && (
        <div className="space-y-2">
          {pendingBuys.map((row) => (
            <div className="rounded-lg border border-gray-200 bg-white p-3 text-xs" key={row.id}>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="font-medium text-gray-900">
                    ¥ {formatMoney(row.amount)} · {pendingStatusLabel(row.status, row.stage)}
                  </div>
                  <div className="mt-1 text-gray-500">
                    申购 {formatDate(row.request_date)}
                    {row.nav_date ? ` · 确认 ${formatDate(row.nav_date)}` : ""}
                  </div>
                  {row.expected_confirm_date && row.status === "pending" && (
                    <div className="mt-1 text-gray-500">
                      预计确认日 {formatDate(row.expected_confirm_date)}
                    </div>
                  )}
                  {row.message && (
                    <div className="mt-1 text-gray-500">{row.message}</div>
                  )}
                  {row.nav != null && (
                    <div className="mt-1 text-gray-500">
                      NAV {formatNav(row.nav)}
                      {row.share != null ? ` · ${row.share.toFixed(2)} 份` : ""}
                    </div>
                  )}
                  {row.note && <div className="mt-1 text-gray-500">{row.note}</div>}
                </div>
                {row.status === "pending" && (
                  <div className="flex shrink-0 items-center gap-1">
                    <Input
                      className="h-8 w-[132px]"
                      disabled={row.stage !== "confirmable"}
                      onChange={(e) => onChangeConfirmDate(row.id, e.target.value)}
                      type="date"
                      value={confirmDates[row.id] ?? row.expected_confirm_date ?? ""}
                    />
                    <Button
                      disabled={isConfirming || row.stage !== "confirmable"}
                      onClick={() => onConfirm(row.id)}
                      size="sm"
                      type="button"
                      variant="outline"
                    >
                      {row.stage === "confirmable" ? "确认份额" : "等待净值/刷新数据"}
                    </Button>
                    <Button
                      disabled={isCancelling}
                      onClick={() => onCancel(row.id)}
                      size="sm"
                      type="button"
                      variant="ghost"
                    >
                      取消
                    </Button>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function InvestmentPlansTab({
  editingPlanId,
  isSaving,
  onCancelEdit,
  onChangePlanField,
  onDelete,
  onEdit,
  onRecordPendingFromPlan,
  onSubmit,
  onToggle,
  planDraft,
  planForm,
  plans,
  removePending,
  state,
  togglePending,
}: {
  editingPlanId: number | null;
  isSaving: boolean;
  onCancelEdit: () => void;
  onChangePlanField: <K extends keyof InvestmentPlanFormState>(
    k: K,
    v: InvestmentPlanFormState[K],
  ) => void;
  onDelete: (id: number) => void;
  onEdit: (plan: InvestmentPlan) => void;
  onRecordPendingFromPlan: (plan: InvestmentPlan) => void;
  onSubmit: () => void;
  onToggle: (plan: InvestmentPlan) => void;
  planDraft: ReturnType<typeof validateInvestmentPlanDraft>;
  planForm: InvestmentPlanFormState;
  plans: InvestmentPlan[];
  removePending: boolean;
  state: { isLoading: boolean; error: unknown };
  togglePending: boolean;
}) {
  return (
    <div className="space-y-4">
      <div className="rounded-lg bg-blue-50 p-3 text-xs text-blue-900">
        <div className="font-medium">定投计划只保存规则</div>
        <p className="mt-1 text-blue-700">
          v1 不自动生成交易、不自动扣款；实际买入仍从“加仓记录”手动写入。
        </p>
      </div>

      <div className="rounded-lg border border-gray-200 bg-gray-50 p-3">
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="mb-1 block text-[11px] font-medium text-gray-700">定投金额 ¥</label>
            <Input
              inputMode="decimal"
              min={0}
              onChange={(e) => onChangePlanField("amount", e.target.value)}
              placeholder="1000"
              step="0.01"
              type="number"
              value={planForm.amount}
            />
          </div>
          <div>
            <label className="mb-1 block text-[11px] font-medium text-gray-700">频率</label>
            <select
              className="block h-9 w-full rounded-md border border-gray-200 bg-white px-3 text-sm text-gray-950 shadow-sm focus:border-blue-300 focus:outline-none focus:ring-2 focus:ring-blue-100"
              onChange={(e) => onChangePlanField("frequency", e.target.value)}
              value={planForm.frequency}
            >
              <option value="daily">每日</option>
              <option value="monthly">每月</option>
              <option value="weekly">每周</option>
            </select>
          </div>
          <div>
            <label className="mb-1 block text-[11px] font-medium text-gray-700">日期规则</label>
            <Input
              onChange={(e) => onChangePlanField("day_rule", e.target.value)}
              placeholder={
                planForm.frequency === "daily"
                  ? "例如 交易日"
                  : planForm.frequency === "weekly" ? "例如 周一" : "例如 5"
              }
              value={planForm.day_rule}
            />
          </div>
          <div>
            <label className="mb-1 block text-[11px] font-medium text-gray-700">开始日期</label>
            <Input
              onChange={(e) => onChangePlanField("start_date", e.target.value)}
              type="date"
              value={planForm.start_date}
            />
          </div>
          <div>
            <label className="mb-1 block text-[11px] font-medium text-gray-700">结束日期(可选)</label>
            <Input
              onChange={(e) => onChangePlanField("end_date", e.target.value)}
              type="date"
              value={planForm.end_date}
            />
          </div>
          <div>
            <label className="mb-1 block text-[11px] font-medium text-gray-700">备注(可选)</label>
            <Input
              onChange={(e) => onChangePlanField("note", e.target.value)}
              placeholder="如:工资日后定投"
              value={planForm.note}
            />
          </div>
        </div>
        {!planDraft.ok && (
          <p className="mt-2 text-[11px] text-amber-700">{planDraft.error}</p>
        )}
        <div className="mt-3 flex justify-end gap-2">
          {editingPlanId != null && (
            <Button onClick={onCancelEdit} size="sm" type="button" variant="ghost">
              取消编辑
            </Button>
          )}
          <Button
            disabled={isSaving || !planDraft.ok}
            onClick={onSubmit}
            size="sm"
            type="button"
          >
            {isSaving ? "保存中..." : editingPlanId != null ? "保存修改" : "保存计划"}
          </Button>
        </div>
      </div>

      {state.isLoading && (
        <StateBlock title="读取定投计划" tone="loading">正在拉取定投计划。</StateBlock>
      )}
      {state.error != null && (
        <StateBlock title="定投计划加载失败" tone="error">{`${state.error}`}</StateBlock>
      )}
      {!state.isLoading && !state.error && plans.length === 0 && (
        <StateBlock title="暂无定投计划" tone="empty">
          保存后会出现在这里；计划不会自动生成买入记录。
        </StateBlock>
      )}
      {!state.isLoading && !state.error && plans.length > 0 && (
        <div className="space-y-2">
          {plans.map((plan) => (
            <div
              className="rounded-lg border border-gray-200 bg-white p-3 text-xs"
              key={plan.id}
            >
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="font-medium text-gray-900">
                    ¥ {formatMoney(plan.amount)} · {frequencyLabel(plan.frequency)}
                    <span className="ml-1 text-gray-500">{plan.day_rule}</span>
                  </div>
                  <div className="mt-1 text-gray-500">
                    {formatDate(plan.start_date)}
                    {plan.end_date ? ` ~ ${formatDate(plan.end_date)}` : " 起长期"}
                    <span className="mx-1">·</span>
                    {plan.status === "active" ? "启用中" : "已暂停"}
                  </div>
                  {plan.note && <div className="mt-1 text-gray-500">{plan.note}</div>}
                </div>
                <div className="flex shrink-0 gap-1">
                  <Button
                    disabled={plan.status !== "active"}
                    onClick={() => onRecordPendingFromPlan(plan)}
                    size="sm"
                    type="button"
                    variant="outline"
                  >
                    记录本次申购
                  </Button>
                  <Button onClick={() => onEdit(plan)} size="sm" type="button" variant="ghost">
                    编辑
                  </Button>
                  <Button
                    disabled={togglePending}
                    onClick={() => onToggle(plan)}
                    size="sm"
                    type="button"
                    variant="ghost"
                  >
                    {plan.status === "active" ? "暂停" : "启用"}
                  </Button>
                  <Button
                    disabled={removePending}
                    onClick={() => onDelete(plan.id)}
                    size="sm"
                    type="button"
                    variant="ghost"
                  >
                    <Trash2 className="h-3.5 w-3.5 text-red-600" />
                  </Button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function CheckboxField({
  checked, onChange, label, hint, disabled,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  hint?: string;
  disabled?: boolean;
}) {
  return (
    <label
      className={cn(
        "flex items-start gap-2 rounded-lg border border-gray-200 bg-white p-2.5 shadow-sm",
        disabled
          ? "cursor-not-allowed opacity-60"
          : "cursor-pointer hover:bg-gray-50",
      )}
    >
      <input
        checked={checked}
        className="mt-0.5 h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-200 disabled:cursor-not-allowed"
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        type="checkbox"
      />
      <span>
        <span className="block text-sm font-medium text-gray-900">{label}</span>
        {hint && <span className="block text-[11px] text-gray-500">{hint}</span>}
      </span>
    </label>
  );
}
