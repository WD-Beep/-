import "./register-path-aliases.ts";
import assert from "node:assert/strict";
import test from "node:test";

import {
  ADMIN_AUTH_PASSWORD,
  AUTH_PASSWORD,
  resolveAdminAuthAccount,
  resolveAuthAccount,
  validateCredentials,
} from "../src/lib/auth.ts";

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

test("admin login only accepts the admin account with the admin password", () => {
  assert.equal(resolveAdminAuthAccount("admin", ADMIN_AUTH_PASSWORD)?.role, "admin");
  assert.equal(resolveAdminAuthAccount("sales1", ADMIN_AUTH_PASSWORD), null);
  assert.equal(resolveAdminAuthAccount("admin", AUTH_PASSWORD), null);
});

test("sales login form does not hard-code sales1 as the default username", async () => {
  const { readFileSync } = await import("node:fs");
  const { fileURLToPath } = await import("node:url");
  const source = readFileSync(
    fileURLToPath(new URL("../src/components/auth/login-form.tsx", import.meta.url)),
    "utf8",
  );

  assert.doesNotMatch(source, /DEFAULT_SALES_USERNAME/);
  assert.doesNotMatch(source, /setUsername\("sales1"\)/);
  assert.match(source, /LAST_LOGIN_USERNAME_STORAGE_KEY/);
});
