interface LatestNavLike {
  nav_date?: string | null;
  accumulated_nav?: number | null;
}

export interface AutoTransactionDraft {
  payload: {
    tx_date: string;
    amount: number;
    nav: number;
    fee: number | null;
    note: string | null;
  };
  estimatedShare: number;
}

function parsePositiveNumber(value: string): number | null {
  const n = Number(value);
  if (!Number.isFinite(n) || n <= 0) return null;
  return n;
}

export function buildAutoTransactionDraft({
  amountInput,
  feeInput = "",
  note = "",
  latestNav,
}: {
  amountInput: string;
  feeInput?: string;
  note?: string;
  latestNav: LatestNavLike | null | undefined;
}): AutoTransactionDraft | null {
  const amount = parsePositiveNumber(amountInput);
  const nav = latestNav?.accumulated_nav ?? null;
  const navDate = latestNav?.nav_date ?? "";
  if (amount == null || nav == null || nav <= 0 || !navDate) return null;

  const fee = feeInput.trim() ? parsePositiveNumber(feeInput) : null;
  if (feeInput.trim() && fee == null) return null;

  return {
    payload: {
      tx_date: navDate,
      amount,
      nav,
      fee,
      note: note.trim() || null,
    },
    estimatedShare: amount / nav,
  };
}
