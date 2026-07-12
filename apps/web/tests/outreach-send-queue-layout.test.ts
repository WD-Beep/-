import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("outreach send queue page keeps the list scrollable inside admin shell", () => {
  const css = readFileSync(new URL("../src/app/globals.css", import.meta.url), "utf8");
  const queueWorkbenchRule = css.match(/\.queue-workbench\s*\{[^}]+\}/)?.[0] ?? "";
  const queueTablePanelRule = css.match(/\.queue-table-panel\s*\{[^}]+\}/)?.[0] ?? "";

  assert.match(queueWorkbenchRule, /height:\s*100%/);
  assert.match(queueWorkbenchRule, /min-height:\s*0/);
  assert.match(queueWorkbenchRule, /overflow-y:\s*auto/);
  assert.match(queueTablePanelRule, /min-height:\s*360px/);
});
