import assert from "node:assert/strict";
import test from "node:test";

import { shouldDisableProductSelector } from "../src/lib/sidebar-product-selector.ts";

test("product selector stays disabled before hydration even when cached products exist", () => {
  assert.equal(
    shouldDisableProductSelector({
      hasHydrated: false,
      productsLoading: true,
      productCount: 2,
    }),
    true,
  );
});

test("product selector is enabled after hydration when cached products exist", () => {
  assert.equal(
    shouldDisableProductSelector({
      hasHydrated: true,
      productsLoading: true,
      productCount: 2,
    }),
    false,
  );
});
