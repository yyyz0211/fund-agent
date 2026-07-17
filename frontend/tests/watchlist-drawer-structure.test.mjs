import assert from "node:assert/strict";
import fs from "node:fs/promises";
import test from "node:test";

const componentRoot = new URL("../src/components/watchlist-drawer/", import.meta.url);
const requiredFiles = [
  "index.ts",
  "WatchlistDrawer.tsx",
  "types.ts",
  "form-state.ts",
  "hooks/useWatchlistDrawerState.ts",
  "hooks/useWatchlistDrawerData.ts",
  "hooks/useWatchlistSave.ts",
  "hooks/useWatchlistPreloadPolling.ts",
  "hooks/useTransactionActions.ts",
  "hooks/useInvestmentPlanActions.ts",
  "hooks/usePendingBuyActions.ts",
  "tabs/BasicTab.tsx",
  "tabs/TransactionsTab.tsx",
  "tabs/InvestmentPlansTab.tsx",
  "tabs/PendingBuysTab.tsx",
  "shared/AutoNavSummary.tsx",
  "shared/HoldingSnapshot.tsx",
  "shared/TabButton.tsx",
  "shared/CheckboxField.tsx",
];

async function read(relativePath) {
  return fs.readFile(new URL(relativePath, componentRoot), "utf8");
}

test("watchlist drawer hard cut removes the legacy entry and creates every domain module", async () => {
  await assert.rejects(
    fs.access(new URL("../src/components/WatchlistDrawer.tsx", import.meta.url)),
    (error) => error?.code === "ENOENT",
  );
  await Promise.all(requiredFiles.map((path) => fs.access(new URL(path, componentRoot))));
});

test("watchlist drawer exposes one narrow public entry", async () => {
  const source = (await read("index.ts")).trim();
  assert.equal(
    source,
    [
      'export { WatchlistDrawer } from "./WatchlistDrawer";',
      'export type { WatchlistDrawerProps } from "./types";',
    ].join("\n"),
  );
});

test("production consumers use the directory entry only", async () => {
  for (const path of ["../app/watchlist/page.tsx", "../app/funds/[code]/page.tsx"]) {
    const source = await fs.readFile(new URL(path, import.meta.url), "utf8");
    assert.match(source, /from "@\/components\/watchlist-drawer"/);
    assert.doesNotMatch(source, /@\/components\/WatchlistDrawer/);
  }
});

test("presentational modules cannot own api query or toast side effects", async () => {
  const paths = requiredFiles.filter(
    (path) => path.startsWith("tabs/") || path.startsWith("shared/"),
  );
  for (const path of paths) {
    const source = await read(path);
    assert.doesNotMatch(source, /@\/lib\/api|@tanstack\/react-query|@\/components\/Toast/);
  }
});

test("new hooks do not depend on the removed entry", async () => {
  const paths = requiredFiles.filter((path) => path.startsWith("hooks/"));
  for (const path of paths) {
    assert.doesNotMatch(await read(path), /@\/components\/WatchlistDrawer/);
  }
});

test("watchlist preload polling is owned by a React Query hook", async () => {
  const polling = await read("hooks/useWatchlistPreloadPolling.ts");
  const save = await read("hooks/useWatchlistSave.ts");
  assert.match(polling, /useQuery/);
  assert.match(polling, /queryKeys\.watchlist\.preloadJob/);
  assert.match(polling, /queryPolicy\.watchlistPreload/);
  assert.match(save, /useWatchlistPreloadPolling/);
  assert.doesNotMatch(save, /setInterval|clearInterval/);
});
