import { Plus } from "lucide-react";
import { StateBlock } from "@/components/StateBlock";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { formatDate, formatMoney, formatNav } from "@/lib/format";
import type { PendingBuy } from "@/types/api";
import type { PendingBuyFormState } from "../types";

function pendingStatusLabel(
  status: PendingBuy["status"],
  stage: PendingBuy["stage"],
): string {
  if (status === "confirmed") return "已确认";
  if (status === "cancelled") return "已取消";
  if (stage === "confirmable") return "可确认";
  if (stage === "submitted") return "等待净值";
  return "申购中";
}

export function PendingBuysTab({
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
    key: K,
    value: PendingBuyFormState[K],
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
                onChange={(event) => onChangePendingField("request_date", event.target.value)}
                type="date"
                value={pendingForm.request_date}
              />
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-gray-700">申购金额 ¥</label>
              <Input
                inputMode="decimal"
                min={0}
                onChange={(event) => onChangePendingField("amount", event.target.value)}
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
                onChange={(event) => onChangePendingField("fee", event.target.value)}
                placeholder="0.00"
                step="0.01"
                type="number"
                value={pendingForm.fee}
              />
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-gray-700">备注(可选)</label>
              <Input
                onChange={(event) => onChangePendingField("note", event.target.value)}
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
                  {row.message && <div className="mt-1 text-gray-500">{row.message}</div>}
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
                      onChange={(event) => onChangeConfirmDate(row.id, event.target.value)}
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
