import "./register-path-aliases.ts";
import assert from "node:assert/strict";
import test from "node:test";

import { AUTH_PASSWORD, resolveAuthAccount, validateCredentials } from "../src/lib/auth.ts";

test("demo login maps admin and sales users to distinct user ids", () => {
  assert.equal(resolveAuthAccount("admin", AUTH_PASSWORD)?.userId, 1);
  assert.equal(resolveAuthAccount("sales1", AUTH_PASSWORD)?.userId, 2);
  assert.equal(resolveAuthAccount("sales10", AUTH_PASSWORD)?.userId, 11);
  assert.equal(resolveAuthAccount("sales11", AUTH_PASSWORD), null);
});

test("credential validation accepts seeded sales accounts", () => {
  assert.equal(validateCredentials("sales2", AUTH_PASSWORD), true);
  assert.equal(validateCredentials("sales2", "wrong"), false);
});
