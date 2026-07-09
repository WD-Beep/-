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
  assert.equal(formatTenantProductLabel("珺临", "EPEDAL24"), "珺临 / EPEDAL24");
  assert.equal(formatTenantProductLabel("OCE", "OCE GEAR"), "OCE / OCE GEAR");
});

test("brand product seeds match the sales1 to sales11 assignment list", () => {
  assert.deepEqual(
    BRAND_PRODUCT_SEEDS.map((item) => item.slug),
    [
      "junlin-epedal24",
      "duolaiwei-aquorix",
      "duolairui-recoverjoy",
      "qianyu-scandihome",
      "duolaida-acestrike",
      "baibo-p-travel",
      "oce-oce-gear",
      "junyu-p-travel-design",
      "duolaiji-homehive",
      "jiuyu-bbcreat",
      "hongbolang",
    ],
  );
  assert.equal(BRAND_PRODUCT_SEEDS.some((item) => item.slug === "duolairui-jourcraf"), false);
  assert.equal(BRAND_PRODUCT_SEEDS.at(-1)?.brand, "Hongbolang");
});
