/** UI 守卫:判断 WatchlistDrawer 在当前编辑状态下是否应调用
 *  `api.watchlistSetInitialHolding`。
 *
 *  规则:
 *  - 用户把基金标记为 `is_holding` 时,只有"全新加入"或"从关注转持仓"
 *    才走 initial-holding —— "已经持有"再调一次,会把首笔 buy 静默
 *    合并到已有持仓,导致平均成本被错算。
 *  - 已有 `transaction_count > 0` 的行,**永远**不要再走 initial-holding,
 *    请改用 `/transactions` 端点加仓(后端 409 也会兜底,但前端能避免
 *    一次失败请求 + 一次误提交)。
 */

export interface InitialHoldingEligibilityInput {
  mode: "add" | "edit";
  formIsHolding: boolean;
  rowIsHolding?: boolean | null;
  rowTransactionCount?: number | null;
}

export function shouldUseInitialHoldingEndpoint(
  input: InitialHoldingEligibilityInput,
): boolean {
  if (!input.formIsHolding) return false;
  if ((input.rowTransactionCount ?? 0) > 0) return false;
  if (input.mode === "add") return true;
  // mode === "edit"
  return input.rowIsHolding === false;
}
