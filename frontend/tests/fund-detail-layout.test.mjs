import assert from "node:assert/strict";
import fs from "node:fs/promises";
import test from "node:test";

test("fund detail shows nav trend section before diagnosis card", async () => {
  const source = await fs.readFile(new URL("../app/funds/[code]/page.tsx", import.meta.url), "utf8");

  assert.ok(
    source.indexOf('title="净值走势与区间涨跌"') < source.indexOf("<FundDiagnosisCard"),
  );
});

test("fund detail places holding info under the nav chart", async () => {
  const source = await fs.readFile(new URL("../app/funds/[code]/page.tsx", import.meta.url), "utf8");

  assert.match(source, /data-testid="nav-holding-column"/);
  assert.ok(source.indexOf("<HoldingCard") < source.indexOf("<RecentDailyReturns"));
});

test("fund detail keeps diagnosis as a full standalone section", async () => {
  const source = await fs.readFile(new URL("../app/funds/[code]/page.tsx", import.meta.url), "utf8");

  assert.ok(source.indexOf("<RecentDailyReturns") < source.indexOf("<FundDiagnosisCard"));
  assert.doesNotMatch(source, /<FundDiagnosisCard[\s\S]*compact/);
});
