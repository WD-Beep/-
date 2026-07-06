import assert from "node:assert/strict";
import test from "node:test";

import type { TenantProduct } from "../src/lib/api.ts";
import { resolveInitialProductIdFromCache } from "../src/lib/product-provider-state.ts";

function product(partial: Partial<TenantProduct> & Pick<TenantProduct, "id" | "name" | "slug">): TenantProduct {
  return {
    workspace_id: 1,
    ...partial,
  };
}

test("initial product id falls back when stored product is no longer in cached options", () => {
  const cached = [
    product({ id: 1, name: "默认项目", slug: "default", is_default: true }),
    product({ id: 105, name: "珺临", slug: "junlin-epedal24" }),
  ];

  assert.equal(resolveInitialProductIdFromCache(13, cached), 1);
});

test("initial product id keeps stored product when it is still available", () => {
  const cached = [
    product({ id: 1, name: "默认项目", slug: "default", is_default: true }),
    product({ id: 105, name: "珺临", slug: "junlin-epedal24" }),
  ];

  assert.equal(resolveInitialProductIdFromCache(105, cached), 105);
});
