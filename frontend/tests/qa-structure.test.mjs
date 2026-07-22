import assert from "node:assert/strict";
import fs from "node:fs/promises";
import test from "node:test";

const root = new URL("../src/components/qa/", import.meta.url);
const required = [
  "index.ts",
  "QaWorkbench.tsx",
  "types.ts",
  "storage.ts",
  "stream-events.ts",
  "hooks/useQaThreads.ts",
  "hooks/useQaStream.ts",
  "ThreadSidebar.tsx",
  "ServiceStatusCard.tsx",
  "MessageList.tsx",
  "ChatMessage.tsx",
  "ToolStepList.tsx",
  "Composer.tsx",
];
const presentational = [
  "ThreadSidebar.tsx",
  "ServiceStatusCard.tsx",
  "MessageList.tsx",
  "ChatMessage.tsx",
  "ToolStepList.tsx",
  "Composer.tsx",
];

async function read(path) {
  return fs.readFile(new URL(path, root), "utf8");
}

async function sourceFiles(directory) {
  const entries = await fs.readdir(directory, { withFileTypes: true });
  const nested = await Promise.all(
    entries.map(async (entry) => {
      const url = new URL(`${entry.name}${entry.isDirectory() ? "/" : ""}`, directory);
      if (entry.isDirectory()) return sourceFiles(url);
      return /\.[cm]?[jt]sx?$/.test(entry.name) ? [url] : [];
    }),
  );
  return nested.flat();
}

test("qa hard cut removes the old store and creates every domain module", async () => {
  await assert.rejects(
    fs.access(new URL("../src/lib/qa-thread-store.ts", import.meta.url)),
    (error) => error?.code === "ENOENT",
  );
  await Promise.all(required.map((path) => fs.access(new URL(path, root))));
});

test("qa domain exposes one narrow public entry", async () => {
  assert.equal(
    (await read("index.ts")).trim(),
    [
      'export { QaWorkbench } from "./QaWorkbench";',
      'export type { QaWorkbenchProps } from "./types";',
    ].join("\n"),
  );
});

test("qa route is a thin client entry", async () => {
  const source = await fs.readFile(new URL("../app/qa/page.tsx", import.meta.url), "utf8");
  assert.match(source, /^"use client";/);
  assert.match(source, /from "@\/components\/qa"/);
  assert.match(source, /<QaWorkbench prefill=\{searchParams\.prefill\}/);
  assert.doesNotMatch(source, /localStorage|getLangGraphClient|useQuery|react-markdown/);
});

test("qa presentational components do not own service or storage effects", async () => {
  for (const path of presentational) {
    const source = await read(path);
    assert.doesNotMatch(
      source,
      /@\/lib\/langgraph|@tanstack\/react-query|(?:components\/qa|(?:\.\.\/)+qa)\/(?:storage|hooks)|(?:\.\.\/|\.\/)(?:storage|hooks)/,
    );
  }
});

test("production source does not import the removed qa store", async () => {
  const directories = [
    new URL("../app/", import.meta.url),
    new URL("../src/", import.meta.url),
  ];
  for (const directory of directories) {
    for (const file of await sourceFiles(directory)) {
      assert.doesNotMatch(
        await fs.readFile(file, "utf8"),
        /@\/lib\/qa-thread-store|src\/lib\/qa-thread-store/,
      );
    }
  }
});

test("useQaStream is fully typed and consumes the stream parser", async () => {
  const source = await read("hooks/useQaStream.ts");
  assert.doesNotMatch(source, /:\s*any\b/);
  assert.doesNotMatch(source, /\bas any\b/);
  assert.match(source, /parseStreamMessage/);
});
