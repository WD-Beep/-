import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { fileURLToPath } from "node:url";

const sidebarSourcePath = fileURLToPath(new URL("../src/components/layout/sidebar.tsx", import.meta.url));

function readSidebarSource() {
  return readFileSync(sidebarSourcePath, "utf8");
}

test("deleting a product invalidates stale caches and reloads by id", () => {
  const source = readSidebarSource();

  assert.match(source, /clearCachedTenantProducts\(currentSession\?\.userId\)/);
  assert.match(source, /clearProductOptionsMemoryCache\(currentSession\?\.userId\)/);
  assert.match(source, /loadProducts\(currentSession,\s*\{\s*force:\s*true\s*\}\)/);
  assert.match(source, /filter\(\(product\) => product\.id !== deletedProductId\)/);
});

test("duplicate-looking product options show a stable id", () => {
  const source = readSidebarSource();

  assert.match(source, /ID #\{product\.id\}/);
  assert.match(source, /title=\{`ID #\$\{product\.id\}/);
});

test("normal login redirects without artificial delay or full refresh", () => {
  const sourcePath = fileURLToPath(new URL("../src/components/auth/login-form.tsx", import.meta.url));
  const source = readFileSync(sourcePath, "utf8");

  assert.doesNotMatch(source, /setTimeout/);
  assert.doesNotMatch(source, /router\.refresh\(\)/);
});
