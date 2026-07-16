"use client";

import { useEffect } from "react";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { blankInvestmentPlanForm } from "@/lib/investment-plan";
import { useInvestmentPlanActions } from "./hooks/useInvestmentPlanActions";
import { usePendingBuyActions } from "./hooks/usePendingBuyActions";
import { useTransactionActions } from "./hooks/useTransactionActions";
import { useWatchlistDrawerData } from "./hooks/useWatchlistDrawerData";
import { useWatchlistDrawerState } from "./hooks/useWatchlistDrawerState";
import { useWatchlistSave } from "./hooks/useWatchlistSave";
import { TabButton } from "./shared/TabButton";
import { BasicTab } from "./tabs/BasicTab";
import { InvestmentPlansTab } from "./tabs/InvestmentPlansTab";
import { PendingBuysTab } from "./tabs/PendingBuysTab";
import { TransactionsTab } from "./tabs/TransactionsTab";
import type { WatchlistDrawerProps } from "./types";

export function WatchlistDrawer({
  row,
  prefillFundCode,
  open,
  onClose,
  onSaved,
}: WatchlistDrawerProps) {
  const state = useWatchlistDrawerState({ open, row, prefillFundCode });
  const data = useWatchlistDrawerData({
    open,
    row,
    form: state.form,
    txForm: state.txForm,
    txFormOpen: state.txFormOpen,
    activeTab: state.activeTab,
    planForm: state.planForm,
    setForm: state.setForm,
    setTxForm: state.setTxForm,
    setConfirmDates: state.setConfirmDates,
  });
  const transactions = useTransactionActions({
    fundCode: data.fundCodeForTx,
    txDraft: data.txDraft,
    selectedNavLoading: data.selectedNavQuery.isLoading,
    setTxForm: state.setTxForm,
    setTxFormOpen: state.setTxFormOpen,
  });
  const plans = useInvestmentPlanActions({
    fundCode: data.fundCodeForTx,
    planDraft: data.planDraft,
    editingPlanId: state.editingPlanId,
    setPlanForm: state.setPlanForm,
    setEditingPlanId: state.setEditingPlanId,
    setActiveTab: state.setActiveTab,
    setPendingForm: state.setPendingForm,
    setPendingFormOpen: state.setPendingFormOpen,
  });
  const pending = usePendingBuyActions({
    fundCode: data.fundCodeForTx,
    pendingForm: state.pendingForm,
    confirmDates: state.confirmDates,
    setPendingForm: state.setPendingForm,
    setPendingFormOpen: state.setPendingFormOpen,
    setConfirmDates: state.setConfirmDates,
  });
  const save = useWatchlistSave({
    mode: data.mode,
    form: state.form,
    submitting: state.submitting,
    setSubmitting: state.setSubmitting,
    needsInitialHolding: data.needsInitialHolding,
    selectedNavLoading: data.selectedNavQuery.isLoading,
    initialHoldingDraft: data.initialHoldingDraft,
    onSaved,
    onClose,
  });

  useEffect(() => {
    if (!open) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape" && !state.submitting) onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose, state.submitting]);

  if (!open) return null;

  return (
    <div
      aria-modal="true"
      className="fixed inset-0 z-40 flex"
      role="dialog"
    >
      <button
        aria-label="关闭"
        className="flex-1 bg-gray-950/30 backdrop-blur-sm"
        onClick={() => !state.submitting && onClose()}
        type="button"
      />
      <aside className="flex h-full w-full max-w-[460px] flex-col border-l border-gray-200 bg-white shadow-xl">
        <header className="flex items-center justify-between border-b border-gray-200 px-5 py-4">
          <div>
            <h2 className="text-base font-semibold text-gray-900">
              {data.mode === "add" ? "加入自选池" : `编辑 ${row?.fund_code ?? ""}`}
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
            disabled={state.submitting}
          >
            <X className="h-4 w-4" />
          </Button>
        </header>

        {data.hasTabs && (
          <div className="flex border-b border-gray-200 px-5">
            <TabButton
              active={state.activeTab === "basic"}
              onClick={() => state.setActiveTab("basic")}
            >
              基础
            </TabButton>
            {data.showTxTab && (
              <TabButton
                active={state.activeTab === "transactions"}
                onClick={() => state.setActiveTab("transactions")}
              >
                加仓记录
                {row && row.transaction_count != null && row.transaction_count > 0 && (
                  <span className="ml-1 inline-flex items-center rounded-full bg-blue-100 px-1.5 text-[10px] font-semibold text-blue-700">
                    {row.transaction_count}
                  </span>
                )}
              </TabButton>
            )}
            {data.showPlanTab && (
              <TabButton
                active={state.activeTab === "plans"}
                onClick={() => state.setActiveTab("plans")}
              >
                定投计划
              </TabButton>
            )}
            {data.showPendingTab && (
              <TabButton
                active={state.activeTab === "pending"}
                onClick={() => state.setActiveTab("pending")}
              >
                申购中
              </TabButton>
            )}
          </div>
        )}

        <form className="flex flex-1 flex-col" onSubmit={save.submit}>
          <div className="flex-1 space-y-4 overflow-y-auto px-5 py-4">
            {(!data.hasTabs || state.activeTab === "basic") && (
              <BasicTab
                form={state.form}
                initialHoldingDraft={data.initialHoldingDraft}
                isAlreadyHolding={data.isAlreadyHolding}
                mode={data.mode}
                needsInitialHolding={data.needsInitialHolding}
                onChangeField={state.setField}
                row={row}
                selectedNav={data.selectedNavQuery.data}
                selectedNavError={data.selectedNavQuery.error}
                selectedNavLoading={data.selectedNavQuery.isLoading}
              />
            )}

            {data.showTxTab && state.activeTab === "transactions" && (
              <TransactionsTab
                costNav={row?.cost_nav}
                holdingShare={row?.holding_share}
                latestNav={data.selectedNavQuery.data}
                navDraft={data.txDraft}
                navError={data.selectedNavQuery.error}
                navLoading={data.selectedNavQuery.isLoading}
                isSubmitting={transactions.addTx.isPending}
                isTxFormOpen={state.txFormOpen}
                onDelete={(id) => transactions.removeTx.mutate(id)}
                onOpenTxForm={() => state.setTxFormOpen((value) => !value)}
                onChangeTxField={state.setTxField}
                onSubmitTx={transactions.submitTx}
                removeTx={transactions.removeTx}
                txForm={state.txForm}
                txs={data.txQuery.data ?? []}
                txState={{
                  isLoading: data.txQuery.isLoading,
                  error: data.txQuery.error,
                }}
              />
            )}

            {data.showPlanTab && state.activeTab === "plans" && (
              <InvestmentPlansTab
                editingPlanId={state.editingPlanId}
                isSaving={plans.addPlan.isPending || plans.updatePlan.isPending}
                onCancelEdit={() => {
                  state.setEditingPlanId(null);
                  state.setPlanForm(blankInvestmentPlanForm());
                }}
                onChangePlanField={state.setPlanField}
                onDelete={(id) => {
                  if (typeof window !== "undefined") {
                    const ok = window.confirm("确认删除这条定投计划?");
                    if (!ok) return;
                  }
                  plans.removePlan.mutate(id);
                }}
                onEdit={plans.editPlan}
                onRecordPendingFromPlan={plans.startPendingBuyFromPlan}
                onSubmit={plans.submitPlan}
                onToggle={plans.togglePlanStatus.mutate}
                planDraft={data.planDraft}
                planForm={state.planForm}
                plans={data.plansQuery.data ?? []}
                removePending={plans.removePlan.isPending}
                togglePending={plans.togglePlanStatus.isPending}
                state={{
                  isLoading: data.plansQuery.isLoading,
                  error: data.plansQuery.error,
                }}
              />
            )}

            {data.showPendingTab && state.activeTab === "pending" && (
              <PendingBuysTab
                confirmDates={state.confirmDates}
                isAdding={pending.addPendingBuy.isPending}
                isCancelling={pending.cancelPendingBuy.isPending}
                isConfirming={pending.confirmPendingBuy.isPending}
                isPendingFormOpen={state.pendingFormOpen}
                onCancel={(id) => pending.cancelPendingBuy.mutate(id)}
                onChangeConfirmDate={(id, value) =>
                  state.setConfirmDates((prev) => ({ ...prev, [id]: value }))
                }
                onChangePendingField={state.setPendingField}
                onConfirm={pending.confirmPending}
                onOpenPendingForm={() => state.setPendingFormOpen((value) => !value)}
                onSubmitPending={() => pending.addPendingBuy.mutate()}
                pendingBuys={data.pendingBuysQuery.data ?? []}
                pendingForm={state.pendingForm}
                state={{
                  isLoading: data.pendingBuysQuery.isLoading,
                  error: data.pendingBuysQuery.error,
                }}
              />
            )}
          </div>

          <footer className="flex items-center justify-end gap-2 border-t border-gray-200 bg-gray-50 px-5 py-3">
            <Button onClick={onClose} type="button" variant="outline" disabled={state.submitting}>
              取消
            </Button>
            {(!data.hasTabs || state.activeTab === "basic") && (
              <Button disabled={save.saveDisabled} type="submit">
                {state.submitting ? "保存中..." : "保存"}
              </Button>
            )}
          </footer>
        </form>
      </aside>
    </div>
  );
}
