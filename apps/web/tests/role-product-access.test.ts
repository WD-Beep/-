import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { fileURLToPath } from "node:url";

import type { TenantProduct } from "../src/lib/api.ts";
import {
  AUTH_PASSWORD,
  buildAuthSession,
  defaultPathForSession,
  getStoredAuthSession,
  setAuthSession,
  type AuthSession,
} from "../src/lib/auth.ts";
import {
  ALL_PRODUCTS_ID,
  assertConcreteProductSelected,
  setStoredProductId,
  tenantHeaders,
} from "../src/lib/product-context.ts";
import {
  buildProductSwitcherOptions,
  canSelectAllProducts,
  hasNoAccessibleProducts,
  resolveProductIdForSession,
} from "../src/lib/product-visibility.ts";
import {
  canCreateCollectionTaskForProduct,
  collectionTaskCreateDisabledReason,
} from "../src/lib/task-form-payload.ts";

function product(partial: Partial<TenantProduct> & Pick<TenantProduct, "id" | "name" | "slug">): TenantProduct {
  return {
    workspace_id: 1,
    ...partial,
  };
}

function session(overrides: Partial<AuthSession> = {}): AuthSession {
  return {
    token: "token-admin",
    userId: 1,
    username: "admin",
    role: "admin",
    isAdmin: true,
    accessibleProducts: [
      product({ id: 1, name: "Default", slug: "default", is_default: true }),
      product({ id: 2, name: "Brand B", slug: "brand-b" }),
    ],
    ...overrides,
  };
}

test("admin product switcher includes all-products and every accessible product", () => {
  const options = buildProductSwitcherOptions(session());

  assert.deepEqual(
    options.map((item) => item.id),
    [ALL_PRODUCTS_ID, 1, 2],
  );
  assert.equal(options[0]?.label, "全部品牌");
});

test("sales product switcher only includes assigned products and never all-products", () => {
  const options = buildProductSwitcherOptions(
    session({
      token: "token-sales",
      userId: 2,
      username: "sales1",
      role: "sales",
      isAdmin: false,
      accessibleProducts: [product({ id: 2, name: "Brand B", slug: "brand-b" })],
    }),
  );

  assert.deepEqual(
    options.map((item) => item.id),
    [2],
  );
  assert.equal(options.some((item) => item.id === ALL_PRODUCTS_ID), false);
});

test("sales product switcher hides the system default brand even if backend cache contains it", () => {
  const sales = session({
    token: "token-sales",
    userId: 2,
    username: "sales1",
    role: "sales",
    isAdmin: false,
    accessibleProducts: [
      product({ id: 1, name: "Default", slug: "default", is_default: true }),
      product({ id: 9, name: "Assigned", slug: "assigned" }),
    ],
  });
  const options = buildProductSwitcherOptions(sales);

  assert.deepEqual(options.map((item) => item.id), [9]);
  assert.equal(resolveProductIdForSession(1, sales), 9);
});

test("missing auth session is not treated as admin", () => {
  const options = buildProductSwitcherOptions(null, [product({ id: 2, name: "Brand B", slug: "brand-b" })]);

  assert.equal(canSelectAllProducts(null), false);
  assert.deepEqual(
    options.map((item) => item.id),
    [2],
  );
  assert.equal(options.some((item) => item.id === ALL_PRODUCTS_ID), false);
});

test("sales without products resolves to no-brand empty state", () => {
  const noProductSales = session({
    token: "token-sales",
    userId: 3,
    username: "sales2",
    role: "sales",
    isAdmin: false,
    accessibleProducts: [],
  });

  assert.equal(hasNoAccessibleProducts(noProductSales), true);
  assert.equal(resolveProductIdForSession(ALL_PRODUCTS_ID, noProductSales), null);
  assert.equal(defaultPathForSession(noProductSales), "/");
});

test("sales cannot keep all-products or unauthorized product selected", () => {
  const sales = session({
    token: "token-sales",
    userId: 2,
    username: "sales1",
    role: "sales",
    isAdmin: false,
    accessibleProducts: [product({ id: 9, name: "Assigned", slug: "assigned" })],
  });

  assert.equal(resolveProductIdForSession(ALL_PRODUCTS_ID, sales), 9);
  assert.equal(resolveProductIdForSession(99, sales), 9);
  assert.equal(resolveProductIdForSession(9, sales), 9);
});

test("auth session stores backend role products and tenant headers include token", () => {
  const storage = new Map<string, string>();
  const originalWindow = globalThis.window;
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      localStorage: {
        getItem: (key: string) => storage.get(key) ?? null,
        setItem: (key: string, value: string) => {
          storage.set(key, value);
        },
        removeItem: (key: string) => {
          storage.delete(key);
        },
      },
    },
  });
  try {
    const built = buildAuthSession(
      { username: "sales1", password: AUTH_PASSWORD, userId: 2, role: "sales", label: "Sales 1" },
      { id: 2, username: "sales1", is_admin: false },
      [product({ id: 5, name: "Assigned", slug: "assigned" })],
      "backend-token",
    );
    setAuthSession(built);
    setStoredProductId(5);

    assert.equal(getStoredAuthSession()?.role, "sales");
    assert.deepEqual(getStoredAuthSession()?.accessibleProducts.map((item) => item.id), [5]);
    assert.deepEqual(tenantHeaders(), {
      Authorization: "Bearer backend-token",
      "X-User-Id": "2",
      "X-Product-Id": "5",
    });
  } finally {
    Object.defineProperty(globalThis, "window", {
      configurable: true,
      value: originalWindow,
    });
  }
});

test("tenant headers prefer the current auth session user over a stale stored user id", () => {
  const storage = new Map<string, string>();
  const originalWindow = globalThis.window;
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      localStorage: {
        getItem: (key: string) => storage.get(key) ?? null,
        setItem: (key: string, value: string) => {
          storage.set(key, value);
        },
        removeItem: (key: string) => {
          storage.delete(key);
        },
      },
    },
  });
  try {
    const built = buildAuthSession(
      { username: "admin", password: AUTH_PASSWORD, userId: 1, role: "admin", label: "Admin" },
      { id: 1, username: "admin", is_admin: true },
      [product({ id: 5, name: "Assigned", slug: "assigned" })],
      "admin-token",
    );
    setAuthSession(built);
    window.localStorage.setItem("influencer_intel_user_id", "17");
    setStoredProductId(0);

    assert.deepEqual(tenantHeaders(), {
      Authorization: "Bearer admin-token",
      "X-User-Id": "1",
      "X-Product-Id": "0",
    });
  } finally {
    Object.defineProperty(globalThis, "window", {
      configurable: true,
      value: originalWindow,
    });
  }
});

test("collection task creation is disabled for all-products selection", () => {
  setStoredProductId(ALL_PRODUCTS_ID);
  assert.equal(canCreateCollectionTaskForProduct(ALL_PRODUCTS_ID), false);
  assert.match(collectionTaskCreateDisabledReason(ALL_PRODUCTS_ID) ?? "", /具体产品|具体品牌/);
  assert.throws(() => assertConcreteProductSelected("创建采集任务"), /具体产品|具体品牌/);
  assert.equal(canCreateCollectionTaskForProduct(3), true);
});

test("collection task create entry remains clickable so it can explain missing product selection", () => {
  const sourcePath = fileURLToPath(
    new URL("../src/components/collection-tasks/collection-tasks-panel.tsx", import.meta.url),
  );
  const source = readFileSync(sourcePath, "utf8");
  const createButton = source.match(
    /<Button\s+onClick=\{\(\) => openCreateDialog\("keyword_discovery"\)\}[\s\S]*?<\/Button>/,
  )?.[0];

  assert.ok(createButton);
  assert.doesNotMatch(createButton, /\sdisabled=/);
  assert.match(createButton, /aria-disabled=\{!canCreateCollectionTaskForProduct\(productId\)\}/);
});

test("collapsed sidebar uses role-filtered mini navigation", () => {
  const sourcePath = fileURLToPath(new URL("../src/components/layout/sidebar.tsx", import.meta.url));
  const source = readFileSync(sourcePath, "utf8");

  assert.match(source, /\{visibleMiniItems\.map\(\(item\) =>/);
  assert.doesNotMatch(source, /\{miniItems\.map\(\(item\) =>/);
});

test("sales can access the create product dialog from the sidebar", () => {
  const sourcePath = fileURLToPath(new URL("../src/components/layout/sidebar.tsx", import.meta.url));
  const source = readFileSync(sourcePath, "utf8");

  assert.doesNotMatch(source, /\{isAdmin \? \(\s*<ProductCreateDialog/);
  assert.match(source, /<ProductCreateDialog[\s\S]*onCreated=\{handleProductCreated\}/);
});

test("no-brand empty state lets sales create their own brand", () => {
  const sourcePath = fileURLToPath(new URL("../src/components/layout/admin-shell.tsx", import.meta.url));
  const source = readFileSync(sourcePath, "utf8");

  assert.match(source, /<ProductCreateDialog[\s\S]*onCreated=\{handleProductCreated\}/);
  assert.match(source, /新增品牌/);
  assert.doesNotMatch(source, /请联系管理员分配后再使用/);
});

test("sidebar exposes delete brand action for concrete products", () => {
  const sourcePath = fileURLToPath(new URL("../src/components/layout/sidebar.tsx", import.meta.url));
  const source = readFileSync(sourcePath, "utf8");

  assert.match(source, /deleteTenantProduct/);
  assert.match(source, /删除/);
  assert.match(source, /productId !== ALL_PRODUCTS_ID/);
});
