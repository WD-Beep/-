import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { SHOW_MONTHLY_REPORT_ENTRY } from "../src/lib/monthly-report-visibility.ts";

test("monthly report entry is hidden for the default sales navigation", () => {
  assert.equal(SHOW_MONTHLY_REPORT_ENTRY, false);
});

test("dashboard route does not render the monthly report panel while the entry is hidden", () => {
  const pageSource = readFileSync(new URL("../src/app/page.tsx", import.meta.url), "utf8");

  assert.doesNotMatch(pageSource, /DashboardPanel/);
});

test("sidebar only keeps the monthly report label behind the hidden feature switch", () => {
  const sidebarSource = readFileSync(
    new URL("../src/components/layout/sidebar.tsx", import.meta.url),
    "utf8",
  );

  assert.match(sidebarSource, /SHOW_MONTHLY_REPORT_ENTRY \? \[\{ href: "\/", label: "月度报告"/);
});
