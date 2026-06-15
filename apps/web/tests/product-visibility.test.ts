import assert from "node:assert/strict";
import test from "node:test";

import type { TenantProduct } from "../src/lib/api.ts";
import {
  filterVisibleTenantProducts,
  looksLikeTestProduct,
  prepareTenantProductOptions,
  resolveStoredProductId,
} from "../src/lib/product-visibility.ts";
import { ALL_PRODUCTS_ID } from "../src/lib/product-context.ts";

function product(partial: Partial<TenantProduct> & Pick<TenantProduct, "id" | "name" | "slug">): TenantProduct {
  return {
    workspace_id: 1,
    ...partial,
  };
}

test("looksLikeTestProduct detects automation test names", () => {
  assert.equal(
    looksLikeTestProduct({ name: "测试产品B-f0548c4c", slug: "test-product-b-f0548c4c" }),
    true,
  );
  assert.equal(
    looksLikeTestProduct({ name: "Amazon跨产品B-a04dbb73", slug: "amazon-cross-b-a04dbb73" }),
    true,
  );
  assert.equal(
    looksLikeTestProduct({ name: "默认项目", slug: "default", brand: "默认品牌" }),
    false,
  );
  assert.equal(
    looksLikeTestProduct({ name: "珺临", slug: "junlin-epedal24", brand: "EPEDAL24" }),
    false,
  );
});

test("filterVisibleTenantProducts keeps real products only", () => {
  const items = [
    product({ id: 1, name: "默认项目", slug: "default", brand: "默认品牌", is_default: true }),
    product({ id: 2, name: "珺临", slug: "junlin-epedal24", brand: "EPEDAL24" }),
    product({ id: 3, name: "测试产品B-f0548c4c", slug: "test-product-b-f0548c4c", is_test: true }),
  ];
  const visible = filterVisibleTenantProducts(items);
  assert.deepEqual(
    visible.map((item) => item.slug),
    ["default", "junlin-epedal24"],
  );
});

test("prepareTenantProductOptions sorts default first", () => {
  const items = [
    product({ id: 2, name: "珺临", slug: "junlin-epedal24", brand: "EPEDAL24", display_order: 1 }),
    product({ id: 1, name: "默认项目", slug: "default", brand: "默认品牌", is_default: true, display_order: 0 }),
  ];
  const prepared = prepareTenantProductOptions(items);
  assert.equal(prepared[0]?.slug, "default");
});

test("resolveStoredProductId falls back when hidden test product selected", () => {
  const visible = [
    product({ id: 1, name: "默认项目", slug: "default", brand: "默认品牌", is_default: true }),
    product({ id: 2, name: "珺临", slug: "junlin-epedal24", brand: "EPEDAL24" }),
  ];
  assert.equal(resolveStoredProductId(999, visible), 1);
  assert.equal(resolveStoredProductId(2, visible), 2);
  assert.equal(resolveStoredProductId(ALL_PRODUCTS_ID, visible), ALL_PRODUCTS_ID);
});

test("resolveStoredProductId uses all-products when no visible products", () => {
  assert.equal(resolveStoredProductId(88, []), ALL_PRODUCTS_ID);
});
