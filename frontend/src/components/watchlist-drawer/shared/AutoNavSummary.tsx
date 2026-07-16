import { StateBlock } from "@/components/StateBlock";
import type { AutoTransactionDraft } from "@/lib/auto-transaction";
import { formatDate, formatNav } from "@/lib/format";
import type { NavPoint } from "@/types/api";
import { SummaryItem } from "./HoldingSnapshot";

export function AutoNavSummary({
  draft,
  latestNav,
  navError,
  navLoading,
  purpose,
  selectedDate,
}: {
  draft: AutoTransactionDraft | null;
  latestNav: NavPoint | undefined;
  navError: unknown;
  navLoading: boolean;
  purpose: "initial" | "add";
  selectedDate?: string;
}) {
  if (navLoading) {
    return (
      <StateBlock title={selectedDate ? "读取所选日期 NAV" : "读取最新 NAV"} tone="loading">
        {selectedDate ? "正在读取所选日期的本地净值。" : "正在读取本地最新净值。"}
      </StateBlock>
    );
  }
  if (navError != null) {
    return (
      <StateBlock title={selectedDate ? "该日期无本地 NAV" : "缺少最新 NAV"} tone="error">
        {`${navError}`}。请刷新基金数据或选择有净值的交易日。
      </StateBlock>
    );
  }
  if (!latestNav || latestNav.accumulated_nav == null || latestNav.accumulated_nav <= 0) {
    return (
      <StateBlock title={selectedDate ? "等待所选日期 NAV" : "等待最新 NAV"} tone="empty">
        填写基金代码和交易日期后会自动读取本地 NAV；没有本地数据时请先刷新基金。
      </StateBlock>
    );
  }
  const label = purpose === "initial" ? "首笔持仓" : "本次加仓";
  return (
    <div className="rounded-lg bg-blue-50 p-3 text-xs text-blue-900">
      <div className="font-medium">{label}将使用本地 NAV</div>
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
