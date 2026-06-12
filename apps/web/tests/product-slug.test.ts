import { describe, it } from "node:test";
import assert from "node:assert/strict";

import { slugifyProductName } from "../src/lib/product-slug.ts";

describe("slugifyProductName", () => {
  it("converts ascii names to slug", () => {
    assert.equal(slugifyProductName("Summer Travel Bag"), "summer-travel-bag");
  });

  it("falls back when name has no ascii letters", () => {
    const slug = slugifyProductName("夏季旅行包");
    assert.match(slug, /^product-/);
  });
});
