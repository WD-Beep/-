import assert from "node:assert/strict";
import test from "node:test";

import {
  matchesLtkLinkImportUrl,
  matchesPinterestLinkImportUrl,
  matchesShopmyLinkImportUrl,
  parseLinkImportPreview,
} from "../src/lib/collection-sources.ts";

const AMAZON_ASIN_RE = /\/(?:dp|gp\/product|product)\/([A-Z0-9]{10})/i;
const AMAZON_URL =
  "https://www.amazon.com/Laundry-Washable-Organizer-Drawstring%EF%BC%8CLarge-Essentials/dp/B0CPF3W9B2/ref=zg_bs_g_3744371_d_sccl_2/138-2111992-2516563?psc=1";

test("Amazon tracked URL extracts ASIN B0CPF3W9B2", () => {
  const match = AMAZON_ASIN_RE.exec(AMAZON_URL);
  assert.equal(match?.[1]?.toUpperCase(), "B0CPF3W9B2");
});

test("url-only link import matchers accept backend-supported URLs", () => {
  assert.equal(matchesPinterestLinkImportUrl("https://www.pinterest.com/example_user/"), true);
  assert.equal(matchesPinterestLinkImportUrl("https://www.pinterest.com/pin/123/"), true);
  assert.equal(matchesLtkLinkImportUrl("https://www.shopltk.com/explore/example_user"), true);
  assert.equal(matchesShopmyLinkImportUrl("https://shopmy.us/example_user"), true);
  assert.equal(matchesShopmyLinkImportUrl("https://shopmy.us/shop/example_user"), true);
});

test("url-only link import matchers reject unsupported path shapes", () => {
  assert.equal(matchesPinterestLinkImportUrl("https://www.pinterest.com/some_user/some_board/"), false);
  assert.equal(matchesLtkLinkImportUrl("https://shopltk.com/not-explore/example_user"), false);
  assert.equal(matchesShopmyLinkImportUrl("https://shopmy.us/shop"), false);
});

test("parseLinkImportPreview rejects unsupported Pinterest LTK ShopMy URLs", () => {
  const preview = parseLinkImportPreview(
    [
      "https://www.pinterest.com/some_user/some_board/",
      "https://shopltk.com/not-explore/example_user",
      "https://shopmy.us/shop",
    ].join("\n"),
  );
  assert.equal(preview.validCount, 0);
  assert.equal(preview.invalidCount, 3);
});

test("parseLinkImportPreview accepts supported Pinterest LTK ShopMy URLs", () => {
  const preview = parseLinkImportPreview(
    [
      "https://www.pinterest.com/pin/123/",
      "https://www.pinterest.com/example_user/",
      "https://shopltk.com/explore/example_user",
      "https://shopmy.us/example_user",
      "https://shopmy.us/shop/example_user",
    ].join("\n"),
  );
  assert.equal(preview.counts.pinterest, 2);
  assert.equal(preview.counts.ltk, 1);
  assert.equal(preview.counts.shopmy, 2);
  assert.equal(preview.invalidCount, 0);
});
