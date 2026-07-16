import type { FormEvent } from "react";
import { Plus, Trash2 } from "lucide-react";
import { StateBlock } from "@/components/StateBlock";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import type { AutoTransactionDraft } from "@/lib/auto-transaction";
import { formatDate, formatMoney, formatNav } from "@/lib/format";
import type { FundTransaction, NavPoint } from "@/types/api";
import { AutoNavSummary } from "../shared/AutoNavSummary";
import type { TransactionFormState } from "../types";

export function TransactionsTab({
  costNav,
  holdingShare,
  isSubmitting,
  isTxFormOpen,
  latestNav,
  navDraft,
  navError,
  navLoading,
  onDelete,
  onOpenTxForm,
  onChangeTxField,
  onSubmitTx,
  removeTx,
  txForm,
  txs,
  txState,
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
  onChangeTxField: <K extends keyof TransactionFormState>(
    key: K,
    value: TransactionFormState[K],
  ) => void;
  onSubmitTx: (event: FormEvent) => void;
  removeTx: { isPending: boolean };
  txForm: TransactionFormState;
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
          {txs.length === 0 ? "暂无加仓记录" : `共 ${txs.length} 笔,按日期从早到晚`}
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
                onChange={(event) => onChangeTxField("tx_date", event.target.value)}
                type="date"
                value={txForm.tx_date}
              />
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-gray-700">投入金额 ¥</label>
              <Input
                inputMode="decimal"
                min={0}
                onChange={(event) => onChangeTxField("amount", event.target.value)}
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
                  onChange={(event) => onChangeTxField("fee", event.target.value)}
                  placeholder="0.00"
                  step="0.01"
                  type="number"
                  value={txForm.fee}
                />
              </div>
              <div>
                <label className="mb-1 block text-[11px] font-medium text-gray-700">备注(可选)</label>
                <Input
                  onChange={(event) => onChangeTxField("note", event.target.value)}
                  placeholder="如:大跌加仓"
                  value={txForm.note}
                />
              </div>
            </div>
          </div>
          <div className="mt-3 flex justify-end gap-2">
            <Button onClick={onOpenTxForm} size="sm" type="button" variant="ghost">
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
        <StateBlock title="加仓记录加载失败" tone="error">{`${txState.error}`}</StateBlock>
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
              {txs.map((transaction) => (
                <TR key={transaction.id} className="hover:bg-gray-50">
                  <TD className="text-xs text-gray-600">{formatDate(transaction.tx_date)}</TD>
                  <TD className="text-right text-xs">¥ {formatMoney(transaction.amount)}</TD>
                  <TD className="text-right text-xs">{formatNav(transaction.nav)}</TD>
                  <TD className="text-right text-xs">
                    {transaction.share != null ? transaction.share.toFixed(2) : "—"}
                  </TD>
                  <TD className="text-right">
                    <Button
                      aria-label="删除加仓"
                      disabled={removeTx.isPending}
                      onClick={() => {
                        if (typeof window !== "undefined") {
                          const ok = window.confirm(
                            `确认删除 ${formatDate(transaction.tx_date)} 投入 ¥${transaction.amount.toFixed(2)} 的加仓记录?`,
                          );
                          if (!ok) return;
                        }
                        onDelete(transaction.id);
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
