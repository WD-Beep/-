import assert from "node:assert/strict";
import test from "node:test";

import type { CollectionTask } from "../src/lib/api.ts";
import {
  formatTaskKeywordsOrLinks,
  taskDisplayPlatforms,
  taskPlatformGroupLabel,
  taskProductClueGroupLabel,
  taskSourceLabelForMode,
} from "../src/lib/labels.ts";

function task(overrides: Partial<CollectionTask>): CollectionTask {
  return {
    id: 1,
    name: "test",
    collection_mode: "keyword",
    platform: "youtube",
    platforms: ["youtube"],
    keywords: [],
    input_urls: [],
    country: null,
    category: null,
    discovery_limit: 10,
    min_engagement_rate: 0,
    min_followers_count: null,
    max_followers_count: null,
    filter_include_keywords: [],
    filter_exclude_keywords: [],
    require_email: false,
    require_contact: false,
    strict_quality_filter: false,
    insert_qualified_only: false,
    export_qualified_only: false,
    status: "draft",
    schedule_enabled: false,
    schedule_cron: null,
    email_enabled: false,
    email_recipients: [],
    outreach_enabled: false,
    outreach_provider: "smtp",
    outreach_dry_run: true,
    outreach_templates: {},
    last_run_at: null,
    next_run_at: null,
    result_count: 0,
    email_count: 0,
    missing_contact_count: 0,
    discovered_count: 0,
    deduped_count: 0,
    profile_fetched_count: 0,
    profile_failed_count: 0,
    filtered_out_count: 0,
    inserted_count: 0,
    hashtag_count: 0,
    post_count: 0,
    comment_author_count: 0,
    filtered_below_min_followers_count: 0,
    filtered_excluded_keyword_count: 0,
    processed_count: 0,
    success_count: 0,
    failed_count: 0,
    skipped_count: 0,
    total_estimate: 0,
    current_stage: null,
    last_error: null,
    run_checkpoint: {},
    stale: false,
    recoverable: false,
    stale_after_seconds: 0,
    status_summary: null,
    error_message: null,
    comment_discovery_enabled: false,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

test("link import uses checkpoint platforms instead of instagram placeholder", () => {
  const item = task({
    collection_mode: "link_import",
    platform: "instagram",
    platforms: ["pinterest"],
    input_urls: ["https://www.pinterest.com/example_user/"],
    run_checkpoint: { link_import_platforms: ["pinterest"] },
  });
  assert.equal(taskPlatformGroupLabel(item.collection_mode), "链接来源平台");
  assert.deepEqual(taskDisplayPlatforms(item), ["pinterest"]);
  assert.match(formatTaskKeywordsOrLinks(item), /Pinterest/);
});

test("competitor product shows discovery platforms and product clues", () => {
  const item = task({
    collection_mode: "competitor_product",
    platform: "multi",
    platforms: ["instagram", "youtube", "tiktok", "facebook"],
    keywords: ["B0TEST1234"],
    run_checkpoint: {
      competitor_discovery_platforms: ["instagram", "youtube", "tiktok", "facebook"],
      amazon_product_seeds: [
        {
          asin: "B0TEST1234",
          normalized_url: "https://www.amazon.com/dp/B0TEST1234",
          url: "https://www.amazon.com/dp/B0TEST1234?ref=abc",
        },
      ],
    },
  });
  assert.equal(taskSourceLabelForMode(item.collection_mode), "竞品商品发现");
  assert.equal(taskPlatformGroupLabel(item.collection_mode), "后续发现平台");
  assert.equal(taskProductClueGroupLabel(item.collection_mode), "商品线索");
  assert.deepEqual(taskDisplayPlatforms(item), ["instagram", "youtube", "tiktok", "facebook"]);
  assert.match(formatTaskKeywordsOrLinks(item), /ASIN B0TEST1234/);
});

test("keyword discovery keeps collection platform label", () => {
  const item = task({
    collection_mode: "discovery",
    platform: "multi",
    platforms: ["instagram", "youtube"],
  });
  assert.equal(taskPlatformGroupLabel(item.collection_mode), "采集平台");
  assert.deepEqual(taskDisplayPlatforms(item), ["instagram", "youtube"]);
});
