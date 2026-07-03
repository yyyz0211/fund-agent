import type { InvestmentPlanPayload, InvestmentPlanFrequency } from "@/types/api";

export interface InvestmentPlanFormState {
  amount: string;
  frequency: string;
  day_rule: string;
  start_date: string;
  end_date: string;
  note: string;
}

export type InvestmentPlanDraft =
  | { ok: true; payload: InvestmentPlanPayload }
  | { ok: false; error: string };

function parsePositiveNumber(value: string): number | null {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return null;
  return n;
}

function isIsoDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const time = Date.parse(`${value}T00:00:00Z`);
  return Number.isFinite(time);
}

function isFrequency(value: string): value is InvestmentPlanFrequency {
  return value === "daily" || value === "weekly" || value === "monthly";
}

export function blankInvestmentPlanForm(): InvestmentPlanFormState {
  return {
    amount: "",
    frequency: "monthly",
    day_rule: "5",
    start_date: "",
    end_date: "",
    note: "",
  };
}

export function validateInvestmentPlanDraft(
  form: InvestmentPlanFormState,
): InvestmentPlanDraft {
  const amount = parsePositiveNumber(form.amount);
  if (amount == null) return { ok: false, error: "请填写大于 0 的定投金额" };
  if (!isFrequency(form.frequency)) return { ok: false, error: "请选择定投频率" };
  const dayRule = form.day_rule.trim();
  if (!dayRule) return { ok: false, error: "请填写定投日期规则" };
  if (!isIsoDate(form.start_date)) return { ok: false, error: "请填写有效开始日期" };
  const endDate = form.end_date.trim();
  if (endDate && !isIsoDate(endDate)) return { ok: false, error: "请填写有效结束日期" };
  if (endDate && endDate < form.start_date) {
    return { ok: false, error: "结束日期不能早于开始日期" };
  }

  return {
    ok: true,
    payload: {
      amount,
      frequency: form.frequency,
      day_rule: dayRule,
      start_date: form.start_date,
      end_date: endDate || null,
      status: "active",
      note: form.note.trim() || null,
    },
  };
}
