import assert from "node:assert/strict";
import fs from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

function findViolations(source, path) {
  const file = ts.createSourceFile(path, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const violations = [];
  const cacheMethods = new Set([
    "getQueryData",
    "setQueryData",
    "invalidateQueries",
    "refetchQueries",
    "removeQueries",
    "cancelQueries",
  ]);

  function visit(node) {
    if (
      ts.isPropertyAssignment(node) &&
      node.name.getText(file) === "queryKey" &&
      ts.isArrayLiteralExpression(node.initializer)
    ) {
      const line = file.getLineAndCharacterOfPosition(node.getStart(file)).line + 1;
      violations.push(`${path}:${line}: raw queryKey`);
    }
    if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression)) {
      const method = node.expression.name.text;
      if (cacheMethods.has(method)) {
        const first = node.arguments[0];
        if (first && ts.isArrayLiteralExpression(first)) {
          const line = file.getLineAndCharacterOfPosition(first.getStart(file)).line + 1;
          violations.push(`${path}:${line}: raw ${method}`);
        }
        if (first && ts.isObjectLiteralExpression(first)) {
          for (const property of first.properties) {
            if (
              ts.isPropertyAssignment(property) &&
              property.name.getText(file) === "queryKey" &&
              ts.isArrayLiteralExpression(property.initializer)
            ) {
              const line = file.getLineAndCharacterOfPosition(property.getStart(file)).line + 1;
              violations.push(`${path}:${line}: raw ${method} queryKey`);
            }
          }
        }
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(file);
  return violations;
}

async function sourceFiles(directory) {
  const entries = await fs.readdir(directory, { withFileTypes: true });
  const nested = await Promise.all(
    entries.map(async (entry) => {
      const url = new URL(`${entry.name}${entry.isDirectory() ? "/" : ""}`, directory);
      if (entry.isDirectory()) return sourceFiles(url);
      return /\.(?:ts|tsx)$/.test(entry.name) ? [url] : [];
    }),
  );
  return nested.flat();
}

test("production query consumers use the central key factory", async () => {
  const roots = [new URL("../app/", import.meta.url), new URL("../src/", import.meta.url)];
  const files = (await Promise.all(roots.map(sourceFiles))).flat().filter(
    (file) => !file.pathname.endsWith("/src/lib/query-keys.ts"),
  );
  const violations = [];
  for (const file of files) {
    const source = await fs.readFile(file, "utf8");
    violations.push(...findViolations(source, file.pathname));
    if (
      /queryKey\s*:|\.(?:getQueryData|setQueryData|invalidateQueries|refetchQueries|removeQueries|cancelQueries)\s*\(/.test(source)
    ) {
      assert.match(source, /from "@\/lib\/query-keys"/);
    }
  }
  assert.deepEqual(violations, []);
});

test("handwritten polling timers are removed", async () => {
  const market = await fs.readFile(new URL("../src/lib/market.ts", import.meta.url), "utf8");
  const save = await fs.readFile(
    new URL("../src/components/watchlist-drawer/hooks/useWatchlistSave.ts", import.meta.url),
    "utf8",
  );
  assert.doesNotMatch(market, /while\s*\(|window\.setTimeout/);
  assert.doesNotMatch(save, /setInterval|clearInterval/);
});

test("market refresh polling pins the target when each request starts", async () => {
  const market = await fs.readFile(new URL("../src/lib/market.ts", import.meta.url), "utf8");
  assert.match(market, /snapshotTargetRef\.current = date/);
  assert.match(market, /const target = snapshotTargetRef\.current/);
  assert.match(market, /evidenceTargetRef\.current = date/);
  assert.match(market, /const target = evidenceTargetRef\.current/);
});
