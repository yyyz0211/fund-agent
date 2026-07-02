import assert from "node:assert/strict";
import fs from "node:fs/promises";
import test from "node:test";

test("fund detail shows nav trend section before diagnosis card", async () => {
  const source = await fs.readFile(new URL("../app/funds/[code]/page.tsx", import.meta.url), "utf8");

  assert.ok(
    source.indexOf('title="净值走势与区间涨跌"') < source.indexOf("<FundDiagnosisCard"),
  );
});
