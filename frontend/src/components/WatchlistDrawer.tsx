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
import type {
  FundTransaction, NavPoint, TransactionUpsertPayload,
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
}

interface TxFormState {
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
  };
}

function blankForm(fundCode = ""): FormState {
  return {
    fund_code: fundCode,
    note: "",
    is_holding: false,
    is_focus: false,
    holding_amount: "",
  };
}

function blankTxForm(): TxFormState {
  return { amount: "", fee: "", note: "" };
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

  // 只有已经保存为持仓的行才显示交易明细 tab;从关注切换为持仓时,
  // 先在基础表单里创建首笔交易,保存后再出现加仓 tab。
  const showTxTab = mode === "edit" && row != null && row.is_holding;
  const fundCodeForTx = row?.fund_code ?? "";
  const currentFundCode = mode === "edit" ? fundCodeForTx : form.fund_code.trim();
  const needsInitialHolding = form.is_holding && (mode === "add" || row?.is_holding === false);
  const shouldLoadLatestNav = open && isSixDigitFundCode(currentFundCode) && (
    needsInitialHolding ||
    (showTxTab && activeTab === "transactions" && txFormOpen)
  );

  const txQuery = useQuery({
    queryKey: ["watchlistTransactions", fundCodeForTx],
    queryFn: () => api.watchlistTransactions(fundCodeForTx),
    enabled: showTxTab,
  });

  const latestNavQuery = useQuery({
    queryKey: ["nav", currentFundCode],
    queryFn: () => api.nav(currentFundCode),
    enabled: shouldLoadLatestNav,
  });

  const initialHoldingDraft = buildAutoTransactionDraft({
    amountInput: form.holding_amount,
    latestNav: latestNavQuery.data,
    note: "初始持仓",
  });
  const txDraft = buildAutoTransactionDraft({
    amountInput: txForm.amount,
    feeInput: txForm.fee,
    note: txForm.note,
    latestNav: latestNavQuery.data,
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
    if (needsInitialHolding && latestNavQuery.isLoading) {
      toast.push("正在读取最新 NAV,请稍后再保存", "error");
      return;
    }
    if (needsInitialHolding && !initialHoldingDraft) {
      toast.push("请填写有效持仓金额，并确认本地已有最新 NAV", "error");
      return;
    }
    setSubmitting(true);
    try {
      let saved: WatchlistRow;
      if (mode === "add") {
        if (needsInitialHolding && initialHoldingDraft) {
          const txResult = await api.watchlistSetInitialHolding(fundCode, {
            ...initialHoldingDraft.payload,
            is_focus: form.is_focus,
            watchlist_note: form.note || null,
          });
          saved = txResult.watchlist;
          qc.invalidateQueries({ queryKey: ["watchlistTransactions", fundCode] });
          qc.invalidateQueries({ queryKey: ["portfolioPnl", [fundCode]] });
        } else {
          const payload: WatchlistUpsertPayload = {
            fund_code: fundCode,
            note: form.note || null,
            is_holding: form.is_holding,
            is_focus: form.is_focus,
            holding_amount: null,
          };
          saved = await api.watchlistAdd(payload);
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
          qc.invalidateQueries({ queryKey: ["watchlistTransactions", fundCode] });
          qc.invalidateQueries({ queryKey: ["portfolioPnl", [fundCode]] });
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
    if (latestNavQuery.isLoading) {
      toast.push("正在读取最新 NAV,请稍后再提交", "error");
      return;
    }
    if (!txDraft) {
      toast.push("请填写有效投入金额，并确认本地已有最新 NAV", "error");
      return;
    }
    addTx.mutate(txDraft.payload);
  }

  const saveDisabled = submitting || (
    needsInitialHolding && (
      latestNavQuery.isLoading || initialHoldingDraft == null
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

                {needsInitialHolding && (
                  <>
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
                      latestNav={latestNavQuery.data}
                      navError={latestNavQuery.error}
                      navLoading={latestNavQuery.isLoading}
                      purpose="initial"
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
                latestNav={latestNavQuery.data}
                navDraft={txDraft}
                navError={latestNavQuery.error}
                navLoading={latestNavQuery.isLoading}
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
            <Button disabled={saveDisabled} type="submit">
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
        追加投入请使用“加仓记录”,系统会按最新 NAV 自动重算份额和成本。
      </p>
    </div>
  );
}

function AutoNavSummary({
  draft, latestNav, navError, navLoading, purpose,
}: {
  draft: AutoTransactionDraft | null;
  latestNav: NavPoint | undefined;
  navError: unknown;
  navLoading: boolean;
  purpose: "initial" | "add";
}) {
  if (navLoading) {
    return (
      <StateBlock title="读取最新 NAV" tone="loading">
        正在读取本地最新净值。
      </StateBlock>
    );
  }
  if (navError != null) {
    return (
      <StateBlock title="缺少最新 NAV" tone="error">
        {`${navError}`}。请先刷新基金数据。
      </StateBlock>
    );
  }
  if (!latestNav || latestNav.accumulated_nav == null || latestNav.accumulated_nav <= 0) {
    return (
      <StateBlock title="等待最新 NAV" tone="empty">
        填写基金代码后会自动读取最新 NAV；没有本地数据时请先刷新基金。
      </StateBlock>
    );
  }
  const label = purpose === "initial" ? "首笔持仓" : "本次加仓";
  return (
    <div className="rounded-lg bg-blue-50 p-3 text-xs text-blue-900">
      <div className="font-medium">{label}将使用本地最新 NAV</div>
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
