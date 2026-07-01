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
import type {
  FundTransaction, TransactionUpsertPayload,
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
type Tab = "basic" | "transactions";

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

interface TxFormState {
  tx_date: string;
  amount: string;
  nav: string;
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

function blankTxForm(): TxFormState {
  return { tx_date: "", amount: "", nav: "", fee: "", note: "" };
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
  const qc = useQueryClient();
  const [form, setForm] = useState<FormState>(() =>
    row ? rowToForm(row) : blankForm(prefillFundCode ?? ""),
  );
  const [submitting, setSubmitting] = useState(false);
  const [activeTab, setActiveTab] = useState<Tab>("basic");
  const [txForm, setTxForm] = useState<TxFormState>(blankTxForm);
  const [txFormOpen, setTxFormOpen] = useState(false);

  // 每次打开抽屉或 row/prefill 变化时重置表单 —— 避免上一次的脏值
  // 留在字段里。
  useEffect(() => {
    if (!open) return;
    setForm(row ? rowToForm(row) : blankForm(prefillFundCode ?? ""));
    setActiveTab("basic");
    setTxForm(blankTxForm());
    setTxFormOpen(false);
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

  // 编辑模式 + is_holding=true 才挂交易表数据 —— 新增模式首次保存
  // 后再切到加仓 tab 时也会自然拿到。
  const showTxTab = mode === "edit" && row != null && form.is_holding;
  const fundCodeForTx = row?.fund_code ?? "";

  const txQuery = useQuery({
    queryKey: ["watchlistTransactions", fundCodeForTx],
    queryFn: () => api.watchlistTransactions(fundCodeForTx),
    enabled: showTxTab,
  });

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
      qc.invalidateQueries({ queryKey: ["portfolioPnl", [fundCodeForTx]] });
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
      qc.invalidateQueries({ queryKey: ["portfolioPnl", [fundCodeForTx]] });
      toast.push("已删除加仓记录", "success");
    },
    onError: (err) => toast.push(`删除加仓失败：${String(err)}`, "error"),
  });

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

  function setTxField<K extends keyof TxFormState>(key: K, value: TxFormState[K]) {
    setTxForm((prev) => ({ ...prev, [key]: value }));
  }

  function submitTx(e: React.FormEvent) {
    e.preventDefault();
    const amount = Number(txForm.amount);
    const nav = Number(txForm.nav);
    if (!txForm.tx_date) {
      toast.push("请选择加仓日期", "error");
      return;
    }
    if (!Number.isFinite(amount) || amount <= 0 || !Number.isFinite(nav) || nav <= 0) {
      toast.push("金额和 NAV 必须大于 0", "error");
      return;
    }
    addTx.mutate({
      tx_date: txForm.tx_date,
      amount,
      nav,
      fee: txForm.fee ? Number(txForm.fee) : null,
      note: txForm.note || null,
    });
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

        {showTxTab && (
          <div className="flex border-b border-gray-200 px-5">
            <TabButton
              active={activeTab === "basic"}
              onClick={() => setActiveTab("basic")}
            >
              基础
            </TabButton>
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
          </div>
        )}

        <form className="flex flex-1 flex-col" onSubmit={submit}>
          <div className="flex-1 space-y-4 overflow-y-auto px-5 py-4">
            {(!showTxTab || activeTab === "basic") && (
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
                  <p className="mt-1 text-[11px] text-gray-500">
                    添加加仓后,这里会显示首次建仓日期。
                  </p>
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
              </>
            )}

            {showTxTab && activeTab === "transactions" && (
              <TransactionsTab
                addTx={addTx}
                costNav={row?.cost_nav}
                holdingShare={row?.holding_share}
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

function TransactionsTab({
  addTx, costNav, holdingShare, isSubmitting, isTxFormOpen, onDelete, onOpenTxForm,
  onChangeTxField, onSubmitTx, removeTx, txForm, txs, txState,
}: {
  addTx: { isPending: boolean };
  costNav: number | null | undefined;
  holdingShare: number | null | undefined;
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
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="mb-1 block text-[11px] font-medium text-gray-700">日期</label>
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
            <div>
              <label className="mb-1 block text-[11px] font-medium text-gray-700">买入 NAV</label>
              <Input
                inputMode="decimal"
                min={0}
                onChange={(e) => onChangeTxField("nav", e.target.value)}
                placeholder="1.234"
                step="0.0001"
                type="number"
                value={txForm.nav}
              />
            </div>
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
            <div className="col-span-2">
              <label className="mb-1 block text-[11px] font-medium text-gray-700">备注(可选)</label>
              <Input
                onChange={(e) => onChangeTxField("note", e.target.value)}
                placeholder="如:大跌加仓"
                value={txForm.note}
              />
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
              disabled={isSubmitting}
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