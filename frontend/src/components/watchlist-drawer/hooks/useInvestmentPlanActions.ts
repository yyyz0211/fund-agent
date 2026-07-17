import type { Dispatch, SetStateAction } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useToast } from "@/components/Toast";
import { api } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import {
  blankInvestmentPlanForm,
  validateInvestmentPlanDraft,
  type InvestmentPlanFormState,
} from "@/lib/investment-plan";
import type { InvestmentPlan } from "@/types/api";
import { todayInputValue } from "../form-state";
import type {
  PendingBuyFormState,
  WatchlistDrawerTab,
} from "../types";

export function useInvestmentPlanActions({
  fundCode,
  planDraft,
  editingPlanId,
  setPlanForm,
  setEditingPlanId,
  setActiveTab,
  setPendingForm,
  setPendingFormOpen,
}: {
  fundCode: string;
  planDraft: ReturnType<typeof validateInvestmentPlanDraft>;
  editingPlanId: number | null;
  setPlanForm: Dispatch<SetStateAction<InvestmentPlanFormState>>;
  setEditingPlanId: Dispatch<SetStateAction<number | null>>;
  setActiveTab: Dispatch<SetStateAction<WatchlistDrawerTab>>;
  setPendingForm: Dispatch<SetStateAction<PendingBuyFormState>>;
  setPendingFormOpen: Dispatch<SetStateAction<boolean>>;
}) {
  const toast = useToast();
  const qc = useQueryClient();

  const addPlan = useMutation({
    mutationFn: () => {
      if (!planDraft.ok) throw new Error(planDraft.error);
      return api.investmentPlanAdd(fundCode, planDraft.payload);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.watchlist.investmentPlans(fundCode) });
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
      return api.investmentPlanUpdate(fundCode, planId, patch);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.watchlist.investmentPlans(fundCode) });
      setPlanForm(blankInvestmentPlanForm());
      setEditingPlanId(null);
      toast.push("定投计划已更新", "success");
    },
    onError: (err) => toast.push(`更新定投计划失败：${String(err)}`, "error"),
  });

  const removePlan = useMutation({
    mutationFn: (planId: number) => api.investmentPlanRemove(fundCode, planId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.watchlist.investmentPlans(fundCode) });
      toast.push("定投计划已删除", "success");
    },
    onError: (err) => toast.push(`删除定投计划失败：${String(err)}`, "error"),
  });

  const togglePlanStatus = useMutation({
    mutationFn: (plan: InvestmentPlan) =>
      api.investmentPlanUpdate(fundCode, plan.id, {
        status: plan.status === "active" ? "paused" : "active",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.watchlist.investmentPlans(fundCode) });
      toast.push("定投计划状态已更新", "success");
    },
    onError: (err) => toast.push(`更新定投计划状态失败：${String(err)}`, "error"),
  });

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

  return {
    addPlan,
    updatePlan,
    removePlan,
    togglePlanStatus,
    editPlan,
    submitPlan,
    startPendingBuyFromPlan,
  };
}
