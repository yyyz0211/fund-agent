import { Trash2 } from "lucide-react";
import { StateBlock } from "@/components/StateBlock";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  validateInvestmentPlanDraft,
  type InvestmentPlanFormState,
} from "@/lib/investment-plan";
import { formatDate, formatMoney } from "@/lib/format";
import type { InvestmentPlan } from "@/types/api";

function frequencyLabel(frequency: InvestmentPlan["frequency"]): string {
  if (frequency === "daily") return "每日";
  if (frequency === "weekly") return "每周";
  return "每月";
}

export function InvestmentPlansTab({
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
    key: K,
    value: InvestmentPlanFormState[K],
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
              onChange={(event) => onChangePlanField("amount", event.target.value)}
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
              onChange={(event) => onChangePlanField("frequency", event.target.value)}
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
              onChange={(event) => onChangePlanField("day_rule", event.target.value)}
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
              onChange={(event) => onChangePlanField("start_date", event.target.value)}
              type="date"
              value={planForm.start_date}
            />
          </div>
          <div>
            <label className="mb-1 block text-[11px] font-medium text-gray-700">结束日期(可选)</label>
            <Input
              onChange={(event) => onChangePlanField("end_date", event.target.value)}
              type="date"
              value={planForm.end_date}
            />
          </div>
          <div>
            <label className="mb-1 block text-[11px] font-medium text-gray-700">备注(可选)</label>
            <Input
              onChange={(event) => onChangePlanField("note", event.target.value)}
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
