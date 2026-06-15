import assert from "node:assert/strict";
import test from "node:test";

import {
  BRAND_PRODUCT_SEEDS,
  formatTenantProductLabel,
} from "../src/lib/brand-products.ts";

test("brand product seeds include 11 real entries", () => {
  assert.equal(BRAND_PRODUCT_SEEDS.length, 11);
  const slugs = new Set(BRAND_PRODUCT_SEEDS.map((item) => item.slug));
  assert.equal(slugs.size, 11);
});

test("formatTenantProductLabel uses subject and brand", () => {
  assert.equal(formatTenantProductLabel("珺临", "EPEDAL24"), "珺临 · EPEDAL24");
  assert.equal(formatTenantProductLabel("OCE", "OCE GEAR"), "OCE · OCE GEAR");
});

test("duolairui has RecoverJoy and JourCraf as separate options", () => {
  const duolairui = BRAND_PRODUCT_SEEDS.filter((item) => item.name === "哆莱瑞");
  assert.equal(duolairui.length, 2);
  assert.deepEqual(
    duolairui.map((item) => item.brand).sort(),
    ["JourCraf", "RecoverJoy"],
  );
});
