import assert from "node:assert/strict";
import test from "node:test";

import type { TenantProduct } from "../src/lib/api.ts";
import {
  readCachedTenantProducts,
  writeCachedTenantProducts,
} from "../src/lib/product-options-cache.ts";

const storage = new Map<string, string>();

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

function product(partial: Partial<TenantProduct> & Pick<TenantProduct, "id" | "name" | "slug">): TenantProduct {
  return {
    workspace_id: 1,
    ...partial,
  };
}

test("cached tenant products restore the previous brand list immediately", () => {
  storage.clear();
  const products = [
    product({ id: 1, name: "默认项目", slug: "default", brand: "默认品牌", is_default: true }),
    product({ id: 105, name: "珺临", slug: "junlin-epedal24", brand: "EPEDAL24" }),
  ];

  writeCachedTenantProducts(products);

  assert.deepEqual(
    readCachedTenantProducts().map((item) => item.slug),
    ["default", "junlin-epedal24"],
  );
});

test("cached tenant products are isolated per user", () => {
  storage.clear();

  writeCachedTenantProducts([product({ id: 1, name: "Admin Brand", slug: "admin-brand" })], 1);

  assert.deepEqual(readCachedTenantProducts(2), []);
  assert.deepEqual(
    readCachedTenantProducts(1).map((item) => item.slug),
    ["admin-brand"],
  );
});

test("empty tenant product list replaces stale cached products", () => {
  storage.clear();

  writeCachedTenantProducts([product({ id: 1, name: "Old Brand", slug: "old-brand" })], 2);
  writeCachedTenantProducts([], 2);

  assert.deepEqual(readCachedTenantProducts(2), []);
});

test("invalid cached tenant products are ignored", () => {
  storage.clear();
  storage.set("influencer_intel_tenant_products", JSON.stringify([{ id: "bad" }]));

  assert.deepEqual(readCachedTenantProducts(), []);
});
