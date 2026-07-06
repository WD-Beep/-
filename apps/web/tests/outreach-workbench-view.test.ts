import assert from "node:assert/strict";
import test from "node:test";

import { outreachWorkbenchStatusLabel } from "../src/lib/outreach-workbench-view.ts";

test("workbench status does not show unconfigured when loading failed before data arrived", () => {
  assert.equal(
    outreachWorkbenchStatusLabel({
      loading: false,
      hasWorkbench: false,
      hasError: true,
    }),
    "检查失败",
  );
});

test("workbench status shows real configuration status after data arrives", () => {
  assert.equal(
    outreachWorkbenchStatusLabel({
      status: "normal",
      loading: false,
      hasWorkbench: true,
      hasError: false,
    }),
    "正常",
  );
});
