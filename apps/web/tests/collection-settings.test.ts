import assert from "node:assert/strict";
import test from "node:test";

import {
  formatPlatformCapabilityHint,
  formatCollectionSourceSummary,
} from "../src/lib/collection-sources.ts";

test("collection source summary shows apify for instagram youtube tiktok", () => {
  const summary = formatCollectionSourceSummary({
    instagram_data_provider: "apify",
    youtube_data_provider: "apify",
    tiktok_data_provider: "apify",
    apify_configured: true,
    api_direct_configured: false,
  });
  assert.match(summary, /Instagram.*apify/i);
  assert.match(summary, /TikTok.*apify/i);
  assert.match(summary, /Facebook.*apify/i);
});

test("platform capability hint prefers backend message", () => {
  const hint = formatPlatformCapabilityHint({
    platform: "tiktok",
    label: "TikTok",
    status: "supported",
    message: "TikTok 数据源：Apify TikTok Scraper（APIFY_TOKEN 已配置）",
    endpoints: [],
  });
  assert.match(hint, /Apify TikTok Scraper/);
});
