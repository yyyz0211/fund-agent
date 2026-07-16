import assert from "node:assert/strict";
import fs from "node:fs/promises";
import test from "node:test";

test("watchlist drawer exposes pending buy tab and market value disclaimer", async () => {
  const source = await fs.readFile(
    new URL(
      "../src/components/watchlist-drawer/tabs/PendingBuysTab.tsx",
      import.meta.url,
    ),
    "utf8",
  );

  assert.match(source, /申购中/);
  assert.match(source, /申购中金额不计入当前市值/);
  assert.match(source, /pendingBuys/);
});

test("watchlist drawer explains T-day pending buy confirmation states", async () => {
  const source = await fs.readFile(
    new URL(
      "../src/components/watchlist-drawer/tabs/PendingBuysTab.tsx",
      import.meta.url,
    ),
    "utf8",
  );

  assert.match(source, /预计确认日/);
  assert.match(source, /等待净值\/刷新数据/);
  assert.match(source, /确认份额/);
});

test("investment plan tab can create a pending buy from one plan occurrence", async () => {
  const plansTab = await fs.readFile(
    new URL(
      "../src/components/watchlist-drawer/tabs/InvestmentPlansTab.tsx",
      import.meta.url,
    ),
    "utf8",
  );
  const planActions = await fs.readFile(
    new URL(
      "../src/components/watchlist-drawer/hooks/useInvestmentPlanActions.ts",
      import.meta.url,
    ),
    "utf8",
  );
  const source = `${plansTab}\n${planActions}`;

  assert.match(source, /记录本次申购/);
  assert.match(source, /startPendingBuyFromPlan/);
});
