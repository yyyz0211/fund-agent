"use client";
import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { useToast } from "@/components/Toast";
import type {
  WatchlistPatchPayload, WatchlistRow, WatchlistUpsertPayload,
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

interface FormState {
  fund_code: string;
  note: string;
  is_holding: boolean;
  is_focus: boolean;
  holding_amount: string;
  holding_share: string;
  cost_nav: string;
  buy_date: string;
}

function rowToForm(row: WatchlistRow): FormState {
  return {
    fund_code: row.fund_code,
    note: row.note ?? "",
    is_holding: !!row.is_holding,
    is_focus: !!row.is_focus,
    holding_amount: row.holding_amount?.toString() ?? "",
    holding_share: row.holding_share?.toString() ?? "",
    cost_nav: row.cost_nav?.toString() ?? "",
    buy_date: row.buy_date ?? "",
  };
}

function blankForm(fundCode = ""): FormState {
  return {
    fund_code: fundCode,
    note: "",
    is_holding: false,
    is_focus: false,
    holding_amount: "",
    holding_share: "",
    cost_nav: "",
    buy_date: "",
  };
}

function toOptionalNumber(s: string): number | null {
  if (s.trim() === "") return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

export function WatchlistDrawer({
  row, prefillFundCode, open, onClose, onSaved,
}: WatchlistDrawerProps) {
  const mode: Mode = row ? "edit" : "add";
  const toast = useToast();
  const [form, setForm] = useState<FormState>(() =>
    row ? rowToForm(row) : blankForm(prefillFundCode ?? ""),
  );
  const [submitting, setSubmitting] = useState(false);

  // 每次打开抽屉或 row/prefill 变化时重置表单 —— 避免上一次的脏值
  // 留在字段里。
  useEffect(() => {
    if (!open) return;
    setForm(row ? rowToForm(row) : blankForm(prefillFundCode ?? ""));
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

  if (!open) return null;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (submitting) return;
    const fundCode = form.fund_code.trim();
    if (!fundCode) {
      toast.push("请填写基金代码", "error");
      return;
    }
    setSubmitting(true);
    try {
      let saved: WatchlistRow;
      if (mode === "add") {
        const payload: WatchlistUpsertPayload = {
          fund_code: fundCode,
          note: form.note || null,
          is_holding: form.is_holding,
          is_focus: form.is_focus,
          holding_amount: toOptionalNumber(form.holding_amount),
          holding_share: toOptionalNumber(form.holding_share),
          cost_nav: toOptionalNumber(form.cost_nav),
          buy_date: form.buy_date || null,
        };
        saved = await api.watchlistAdd(payload);
        toast.push(`${fundCode} 已加入自选池`, "success");
      } else {
        const patch: WatchlistPatchPayload = {
          note: form.note || null,
          is_holding: form.is_holding,
          is_focus: form.is_focus,
          holding_amount: toOptionalNumber(form.holding_amount),
          holding_share: toOptionalNumber(form.holding_share),
          cost_nav: toOptionalNumber(form.cost_nav),
          buy_date: form.buy_date || null,
        };
        saved = await api.watchlistUpdate(fundCode, patch);
        toast.push(`已更新 ${fundCode}`, "success");
      }
      onSaved?.(saved);
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
      <aside className="flex h-full w-full max-w-[420px] flex-col border-l border-gray-200 bg-white shadow-xl">
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

        <form className="flex flex-1 flex-col" onSubmit={submit}>
          <div className="flex-1 space-y-4 overflow-y-auto px-5 py-4">
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
                hint="标记为已持有"
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

            <div>
              <label className="mb-1 block text-xs font-medium text-gray-700">持仓金额</label>
              <Input
                inputMode="decimal"
                min={0}
                onChange={(e) => setField("holding_amount", e.target.value)}
                placeholder="例如 12000.50"
                step="0.0001"
                type="number"
                value={form.holding_amount}
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-700">持仓份额</label>
                <Input
                  inputMode="decimal"
                  min={0}
                  onChange={(e) => setField("holding_share", e.target.value)}
                  placeholder="1000.00"
                  step="0.0001"
                  type="number"
                  value={form.holding_share}
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-gray-700">成本净值</label>
                <Input
                  inputMode="decimal"
                  min={0}
                  onChange={(e) => setField("cost_nav", e.target.value)}
                  placeholder="1.234"
                  step="0.0001"
                  type="number"
                  value={form.cost_nav}
                />
              </div>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-gray-700">买入日期</label>
              <Input
                onChange={(e) => setField("buy_date", e.target.value)}
                type="date"
                value={form.buy_date}
              />
            </div>

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
          </div>

          <footer className="flex items-center justify-end gap-2 border-t border-gray-200 bg-gray-50 px-5 py-3">
            <Button onClick={onClose} type="button" variant="outline" disabled={submitting}>
              取消
            </Button>
            <Button disabled={submitting} type="submit">
              {submitting ? "保存中..." : "保存"}
            </Button>
          </footer>
        </form>
      </aside>
    </div>
  );
}

function CheckboxField({
  checked, onChange, label, hint,
}: { checked: boolean; onChange: (v: boolean) => void; label: string; hint?: string }) {
  return (
    <label className="flex cursor-pointer items-start gap-2 rounded-lg border border-gray-200 bg-white p-2.5 shadow-sm hover:bg-gray-50">
      <input
        checked={checked}
        className="mt-0.5 h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-200"
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