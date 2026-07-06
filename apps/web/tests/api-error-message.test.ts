import assert from "node:assert/strict";
import test from "node:test";

import { cleanBackendErrorMessage } from "../src/lib/api.ts";

test("link import validation errors are shown as friendly task-form guidance", () => {
  assert.equal(
    cleanBackendErrorMessage("body: Value error, 链接导入至少需要一个链接"),
    "请先粘贴至少一个链接，或切回关键词发现模式。",
  );
});

