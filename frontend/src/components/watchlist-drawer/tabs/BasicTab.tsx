import { Input } from "@/components/ui/input";
import type { AutoTransactionDraft } from "@/lib/auto-transaction";
import type { NavPoint, WatchlistRow } from "@/types/api";
import type { Mode, WatchlistFormState } from "../types";
import { AutoNavSummary } from "../shared/AutoNavSummary";
import { CheckboxField } from "../shared/CheckboxField";
import { HoldingSnapshot } from "../shared/HoldingSnapshot";

export function BasicTab({
  mode,
  row,
  form,
  isAlreadyHolding,
  needsInitialHolding,
  initialHoldingDraft,
  selectedNav,
  selectedNavError,
  selectedNavLoading,
  onChangeField,
}: {
  mode: Mode;
  row?: WatchlistRow | null;
  form: WatchlistFormState;
  isAlreadyHolding: boolean;
  needsInitialHolding: boolean;
  initialHoldingDraft: AutoTransactionDraft | null;
  selectedNav: NavPoint | undefined;
  selectedNavError: unknown;
  selectedNavLoading: boolean;
  onChangeField: <K extends keyof WatchlistFormState>(
    key: K,
    value: WatchlistFormState[K],
  ) => void;
}) {
  return (
    <>
      <div>
        <label className="mb-1 block text-xs font-medium text-gray-700">基金代码</label>
        <Input
          disabled={mode === "edit"}
          onChange={(event) => onChangeField("fund_code", event.target.value)}
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
          onChange={(value) => onChangeField("is_holding", value)}
        />
        <CheckboxField
          checked={form.is_focus}
          hint="重点观察,仅标记"
          label="关注"
          onChange={(value) => onChangeField("is_focus", value)}
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
              onChange={(event) => onChangeField("holding_date", event.target.value)}
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
              onChange={(event) => onChangeField("holding_amount", event.target.value)}
              placeholder="例如 12000.50"
              step="0.01"
              type="number"
              value={form.holding_amount}
            />
          </div>
          <AutoNavSummary
            draft={initialHoldingDraft}
            latestNav={selectedNav}
            navError={selectedNavError}
            navLoading={selectedNavLoading}
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
          onChange={(event) => onChangeField("note", event.target.value)}
          placeholder="可以写买入理由、计划关注指标等"
          rows={3}
          value={form.note}
        />
      </div>
    </>
  );
}
