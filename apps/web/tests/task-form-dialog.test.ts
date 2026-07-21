import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import type { CollectionTask, PlatformCapability } from "../src/lib/api.ts";
import { formatLinkImportPlatformHints, parseLinkImportPreview } from "../src/lib/collection-sources.ts";
import {
  applyStableCollectionMode,
  calculateBatchRoundCount,
  applyDiscoverySource,
  applyFormTemplate,
  createEmptyTaskForm,
  extractFormTemplate,
  formValuesToPayload,
  getCreatedCollectionTaskMessage,
  getInitialForm,
  getMultiPlatformAutoPlatforms,
  isKeywordPlatformSelectable,
  saveFormTemplate,
  TEMPLATE_STORAGE_KEY,
  toggleKeywordPlatformSelection,
  validateForm,
} from "../src/lib/task-form-payload.ts";
import {
  COUNTRY_OPTIONS,
  LINK_IMPORT_USAGE_LINES,
  LINK_ONLY_PLATFORM_CARD_LINES,
  SEED_DISCOVERY_PLATFORMS,
  URL_ONLY_PLATFORM_VALIDATION_MSG,
} from "../src/lib/labels.ts";

function mockPlatformCapability(
  platform: string,
  label: string,
  status: PlatformCapability["status"],
  link_import_hint: string,
  flags: Pick<PlatformCapability, "keyword_discovery" | "link_import" | "product_seed">,
): PlatformCapability {
  return {
    platform,
    label,
    status,
    message: "ok",
    endpoints: [],
    link_import_hint,
    ...flags,
  };
}

const noopCaps: PlatformCapability[] = [
  mockPlatformCapability("instagram", "Instagram", "supported", "Instagram 主页", {
    keyword_discovery: true,
    link_import: true,
    product_seed: false,
  }),
  mockPlatformCapability("youtube", "YouTube", "supported", "YouTube 频道", {
    keyword_discovery: true,
    link_import: true,
    product_seed: false,
  }),
  mockPlatformCapability("tiktok", "TikTok", "supported", "TikTok 主页", {
    keyword_discovery: true,
    link_import: true,
    product_seed: false,
  }),
  mockPlatformCapability("facebook", "Facebook", "supported", "Facebook 主页", {
    keyword_discovery: true,
    link_import: true,
    product_seed: false,
  }),
  mockPlatformCapability("pinterest", "Pinterest", "url_only", "Pinterest Pin", {
    keyword_discovery: false,
    link_import: true,
    product_seed: false,
  }),
  mockPlatformCapability("ltk", "LTK", "url_only", "LTK 商品", {
    keyword_discovery: false,
    link_import: true,
    product_seed: false,
  }),
  mockPlatformCapability("shopmy", "ShopMy", "url_only", "ShopMy 链接", {
    keyword_discovery: false,
    link_import: true,
    product_seed: false,
  }),
  mockPlatformCapability("amazon", "Amazon", "url_only", "Amazon 商品链接", {
    keyword_discovery: false,
    link_import: true,
    product_seed: true,
  }),
];

const youtubeOnlyCaps: PlatformCapability[] = [
  mockPlatformCapability("instagram", "Instagram", "not_configured", "Instagram 主页", {
    keyword_discovery: true,
    link_import: true,
    product_seed: false,
  }),
  mockPlatformCapability("youtube", "YouTube", "supported", "YouTube 频道", {
    keyword_discovery: true,
    link_import: true,
    product_seed: false,
  }),
  mockPlatformCapability("tiktok", "TikTok", "not_available", "TikTok 主页", {
    keyword_discovery: true,
    link_import: true,
    product_seed: false,
  }),
  mockPlatformCapability("facebook", "Facebook", "not_configured", "Facebook 主页", {
    keyword_discovery: true,
    link_import: true,
    product_seed: false,
  }),
  mockPlatformCapability("pinterest", "Pinterest", "url_only", "Pinterest Pin", {
    keyword_discovery: false,
    link_import: true,
    product_seed: false,
  }),
  mockPlatformCapability("ltk", "LTK", "url_only", "LTK 商品", {
    keyword_discovery: false,
    link_import: true,
    product_seed: false,
  }),
  mockPlatformCapability("shopmy", "ShopMy", "url_only", "ShopMy 链接", {
    keyword_discovery: false,
    link_import: true,
    product_seed: false,
  }),
];

const allUnavailableCaps: PlatformCapability[] = [
  mockPlatformCapability("instagram", "Instagram", "not_configured", "Instagram 主页", {
    keyword_discovery: true,
    link_import: true,
    product_seed: false,
  }),
  mockPlatformCapability("youtube", "YouTube", "not_configured", "YouTube 频道", {
    keyword_discovery: true,
    link_import: true,
    product_seed: false,
  }),
  mockPlatformCapability("tiktok", "TikTok", "not_available", "TikTok 主页", {
    keyword_discovery: true,
    link_import: true,
    product_seed: false,
  }),
  mockPlatformCapability("facebook", "Facebook", "not_configured", "Facebook 主页", {
    keyword_discovery: true,
    link_import: true,
    product_seed: false,
  }),
];

function collectionTask(overrides: Partial<CollectionTask> = {}): CollectionTask {
  return {
    id: 1,
    name: "seed discovery edit",
    collection_mode: "discovery",
    platform: "youtube",
    platforms: ["youtube"],
    keywords: ["home decor"],
    input_urls: [],
    country: null,
    category: null,
    discovery_limit: 50,
    min_engagement_rate: null,
    min_followers_count: null,
    max_followers_count: null,
    filter_include_keywords: [],
    filter_exclude_keywords: [],
    require_email: false,
    require_contact: false,
    strict_quality_filter: false,
    insert_qualified_only: false,
    export_qualified_only: false,
    schedule_enabled: false,
    schedule_cron: null,
    email_enabled: false,
    email_recipients: [],
    outreach_enabled: false,
    outreach_provider: "mailchimp",
    outreach_dry_run: true,
    outreach_templates: {},
    comment_discovery_enabled: false,
    status: "pending",
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
    stale_after_seconds: 300,
    status_summary: null,
    error_message: null,
    last_run_at: null,
    next_run_at: null,
    created_at: "2026-06-16T00:00:00Z",
    updated_at: "2026-06-16T00:00:00Z",
    ...overrides,
  };
}

test("switching back from link import omits stale input_urls in payload", () => {
  const dirty = {
    ...createEmptyTaskForm(),
    sourceMethod: "link_import" as const,
    collection_mode: "link_import" as const,
    inputUrlsText: "https://www.instagram.com/hidden/\nhttps://www.youtube.com/@hidden",
    keywordsText: "",
  };
  const cleaned = applyDiscoverySource("keyword_hashtag", dirty, noopCaps);
  cleaned.keywordsText = "amazon finds creator";
  cleaned.name = "test task";

  const payload = formValuesToPayload(cleaned, noopCaps);
  assert.deepEqual(payload.input_urls, []);
  assert.equal(payload.collection_mode, "discovery");
  assert.ok(payload.keywords.includes("amazon finds creator"));
});

test("collection task payload stores post-collection AI outreach settings", () => {
  const form = {
    ...createEmptyTaskForm(),
    name: "auto outreach task",
    keywordsText: "home finds creator",
    outreach_enabled: true,
    outreach_dry_run: false,
    outreach_subject_template: "Collaboration with {红人名称}",
    outreach_body_template: "Introduce our brand and invite the creator.",
    outreach_product_name: "Travel Home Lamp",
    outreach_selling_points: "Portable warm light, Amazon-ready",
    outreach_collaboration_offer: "Create a video and join our Amazon affiliate plan.",
    outreach_note: "Mention 10%-30% commission when appropriate.",
    outreach_daily_limit: "25",
    outreach_hourly_limit: "5",
    outreach_send_interval_minutes: "8",
    outreach_require_high_value: true,
    outreach_allow_resend: false,
  };

  const payload = formValuesToPayload(form, noopCaps);

  assert.equal(payload.outreach_enabled, true);
  assert.equal(payload.outreach_dry_run, false);
  assert.deepEqual(payload.outreach_templates, {
    subject_template: "Collaboration with {红人名称}",
    body_template: "Introduce our brand and invite the creator.",
    product_name: "Travel Home Lamp",
    selling_points: "Portable warm light, Amazon-ready",
    collaboration_offer: "Create a video and join our Amazon affiliate plan.",
    note: "Mention 10%-30% commission when appropriate.",
    daily_limit: "25",
    hourly_limit: "5",
    send_interval_minutes: "8",
    require_high_value: "true",
    allow_resend: "false",
  });
});

test("switching to link import omits stale keywords and discovery fields but keeps quality filters", () => {
  const dirty = {
    ...createEmptyTaskForm(),
    keywordsText: "old keyword",
    min_followers_count: "10000",
    min_engagement_rate: "0.5",
    filterExcludeKeywordsText: "spam",
    filterIncludeKeywordsText: "collab",
    category: "美妆",
    inputUrlsText: "https://www.pinterest.com/example/",
  };
  const cleaned = applyDiscoverySource("link_import", dirty, noopCaps);
  cleaned.name = "link import task";

  const payload = formValuesToPayload(cleaned, noopCaps);
  assert.deepEqual(payload.keywords, []);
  assert.deepEqual(payload.filter_include_keywords, []);
  assert.deepEqual(payload.filter_exclude_keywords, []);
  assert.equal(payload.min_followers_count, 10000);
  assert.equal(payload.min_engagement_rate, 0.5);
  assert.equal(payload.category, null);
  assert.ok(payload.input_urls.length > 0);
});

test("saved template excludes mode-specific fields", () => {
  const saved = extractFormTemplate({
    ...createEmptyTaskForm(),
    name: "链接导入任务",
    sourceMethod: "link_import",
    collection_mode: "link_import",
    inputUrlsText: "https://www.pinterest.com/example/",
    keywordsText: "hidden",
    min_followers_count: "5000",
    discovery_limit: "80",
    email_enabled: true,
    email_recipientsText: "ops@example.com",
  });

  assert.equal("name" in saved, false);
  assert.equal("sourceMethod" in saved, false);
  assert.equal("collection_mode" in saved, false);
  assert.equal("inputUrlsText" in saved, false);
  assert.equal(saved.discovery_limit, "80");
  assert.equal(saved.email_enabled, true);

  const restored = applyFormTemplate(createEmptyTaskForm(), saved);
  assert.equal(restored.sourceMethod, "keyword_discovery");
  assert.equal(restored.collection_mode, "discovery");
  assert.equal(restored.inputUrlsText, "");
  assert.equal(restored.discovery_limit, "80");
});

test("link import platform hints cover all supported platforms", () => {
  const groups = formatLinkImportPlatformHints(noopCaps);
  const text = groups.flatMap((group) => group.items).join("\n");
  assert.match(text, /Instagram/i);
  assert.match(text, /YouTube/i);
  assert.match(text, /TikTok/i);
  assert.match(text, /Facebook/i);
  assert.match(text, /Pinterest/i);
  assert.match(text, /LTK/i);
  assert.match(text, /ShopMy/i);
  assert.match(text, /Amazon/i);
});

test("opening normal create after link import template keeps default discovery mode", () => {
  const storage = new Map<string, string>();
  const original = globalThis.localStorage;
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    value: {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => {
        storage.set(key, value);
      },
      removeItem: (key: string) => {
        storage.delete(key);
      },
    },
  });
  try {
    saveFormTemplate({
      ...createEmptyTaskForm(),
      name: "链接导入任务",
      sourceMethod: "link_import",
      collection_mode: "link_import",
      inputUrlsText: "https://www.pinterest.com/example/",
      keywordsText: "hidden keyword",
      min_followers_count: "5000",
      email_enabled: true,
      email_recipientsText: "ops@example.com",
    });
    assert.ok(storage.has(TEMPLATE_STORAGE_KEY));

    const initial = getInitialForm(true, null, "keyword_discovery");
    assert.equal(initial.sourceMethod, "keyword_discovery");
    assert.equal(initial.collection_mode, "discovery");
    assert.equal(initial.inputUrlsText, "");
    assert.equal(initial.keywordsText, "");
    assert.equal(initial.email_enabled, true);
    assert.equal(initial.email_recipientsText, "ops@example.com");
  } finally {
    Object.defineProperty(globalThis, "localStorage", {
      configurable: true,
      value: original,
    });
  }
});

function keywordForm(overrides: Partial<ReturnType<typeof createEmptyTaskForm>> = {}) {
  return {
    ...createEmptyTaskForm(),
    keywordsText: "amazon finds creator",
    name: "platform test",
    ...overrides,
  };
}

test("default keyword mode selects at least one verified platform", () => {
  const initial = createEmptyTaskForm();
  assert.ok(initial.platforms.length >= 1);
  assert.ok(initial.platforms.every((platform) => ["instagram", "youtube", "tiktok", "facebook"].includes(platform)));
});

test("country options display English labels while submitting country codes", () => {
  assert.deepEqual(
    COUNTRY_OPTIONS.map((country) => country.label),
    [
      "All countries / No limit",
      "United States",
      "Germany",
      "United Kingdom",
      "Australia",
      "Canada",
    ],
  );
  assert.deepEqual(
    COUNTRY_OPTIONS.map((country) => country.value),
    ["", "US", "DE", "GB", "AU", "CA"],
  );
});

test("default keyword collection captures candidates before quality filtering", () => {
  const initial = getInitialForm(true, null, "keyword_discovery");
  const payload = formValuesToPayload(
    {
      ...initial,
      name: "candidate first default",
      keywordsText: "amazon finds creator",
    },
    noopCaps,
  );

  assert.equal(payload.min_followers_count, null);
  assert.equal(payload.min_engagement_rate, null);
  assert.equal(payload.require_email, false);
  assert.equal(payload.require_contact, false);
  assert.equal(payload.strict_quality_filter, false);
  assert.equal(payload.insert_qualified_only, false);
  assert.equal(payload.export_qualified_only, false);
});

test("stable collection mode relaxes filters and submits one conservative platform", () => {
  const stable = applyStableCollectionMode({
    ...keywordForm({
      platforms: ["youtube", "tiktok", "facebook"],
      platform: "multi",
      discovery_limit: "100",
      require_email: true,
      require_contact: true,
      strict_quality_filter: true,
      insert_qualified_only: true,
    }),
  });
  const payload = formValuesToPayload(stable, noopCaps);

  assert.equal(stable.stable_collection_mode, true);
  assert.equal(payload.stable_collection_mode, true);
  assert.equal(payload.discovery_limit, 20);
  assert.equal(payload.require_email, false);
  assert.equal(payload.require_contact, false);
  assert.equal(payload.strict_quality_filter, false);
  assert.equal(payload.insert_qualified_only, false);
  assert.equal(payload.platform, "youtube");
  assert.deepEqual(payload.platforms, ["youtube"]);
});

test("new keyword task defaults to disabled batch rounds with suggested round values", () => {
  const form = getInitialForm(true, null, "keyword_discovery");

  assert.equal(form.batch_round_enabled, false);
  assert.equal(form.batch_total_limit, "");
  assert.equal(form.batch_round_size, "50");
  assert.equal(form.batch_round_count, "3");
  assert.equal(form.max_runtime_minutes, "60");
});

test("collection task submits and validates the configured runtime limit", () => {
  const form = keywordForm({
    name: "bounded collection",
    keywordsText: "makeup bag",
    max_runtime_minutes: "45",
  });
  assert.equal(validateForm(form, noopCaps), null);
  assert.equal(formValuesToPayload(form, noopCaps).max_runtime_minutes, 45);
  assert.match(validateForm({ ...form, max_runtime_minutes: "2" }, noopCaps) ?? "", /5-1440/);
});

test("batch round collection submits batch payload fields", () => {
  const payload = formValuesToPayload(
    keywordForm({
      name: "EPEDAL24-化妆包",
      keywordsText: "makeup bag\ncosmetic bag",
      discovery_limit: "50",
      batch_round_enabled: true,
      batch_total_limit: "200",
      batch_round_size: "50",
      batch_round_count: "4",
    }),
    noopCaps,
  );

  assert.equal(payload.batch_round_enabled, true);
  assert.equal(payload.batch_total_limit, 200);
  assert.equal(payload.batch_round_size, 50);
  assert.equal(payload.batch_round_count, 4);
});

test("batch round count is calculated from total and round size", () => {
  const form = keywordForm({
    name: "large batch",
    keywordsText: "makeup bag",
    discovery_limit: "50",
    batch_round_enabled: true,
    batch_total_limit: "10000",
    batch_round_size: "500",
    batch_round_count: "1",
  });
  const payload = formValuesToPayload(form, noopCaps);

  assert.equal(calculateBatchRoundCount(form), 20);
  assert.equal(validateForm(form, noopCaps), null);
  assert.equal(payload.batch_round_enabled, true);
  assert.equal(payload.batch_total_limit, 10000);
  assert.equal(payload.batch_round_size, 500);
  assert.equal(payload.batch_round_count, 20);
});

test("keyword task allows discovery limit up to 10000", () => {
  const form = keywordForm({
    name: "large single run",
    keywordsText: "amazon finds creator",
    discovery_limit: "10000",
  });
  const payload = formValuesToPayload(form, noopCaps);

  assert.equal(validateForm(form, noopCaps), null);
  assert.equal(payload.discovery_limit, 10000);
});

test("keyword task rejects discovery limit above 10000", () => {
  const form = keywordForm({
    name: "too large single run",
    keywordsText: "amazon finds creator",
    discovery_limit: "10001",
  });

  assert.match(validateForm(form, noopCaps) ?? "", /1-10000/);
});

test("editing batch parent initializes and submits calculated batch fields", () => {
  const form = getInitialForm(
    true,
    collectionTask({
      parent_task_id: null,
      batch_round_count: 3,
      discovery_limit: 120,
      child_tasks: [
        {
          id: 11,
          name: "round 1",
          status: "draft",
          batch_round_index: 1,
          batch_round_count: 3,
          discovery_limit: 50,
          keywords: ["home decor"],
          result_count: 0,
          inserted_count: 0,
          deduped_count: 0,
          failed_count: 0,
          skipped_count: 0,
          last_run_at: null,
          status_summary: null,
          error_message: null,
        },
      ],
    }),
    "keyword_discovery",
  );
  const payload = formValuesToPayload(
    {
      ...form,
      batch_round_count: "1",
    },
    noopCaps,
  );

  assert.equal(form.batch_round_enabled, true);
  assert.equal(form.batch_total_limit, "120");
  assert.equal(form.batch_round_size, "50");
  assert.equal(calculateBatchRoundCount(form), 3);
  assert.equal(payload.batch_round_enabled, true);
  assert.equal(payload.batch_total_limit, 120);
  assert.equal(payload.batch_round_size, 50);
  assert.equal(payload.batch_round_count, 3);
});

test("single round collection omits batch payload fields", () => {
  const payload = formValuesToPayload(
    keywordForm({
      name: "single run",
      keywordsText: "makeup bag",
      batch_round_enabled: false,
      batch_total_limit: "10000",
      batch_round_size: "500",
      batch_round_count: "20",
    }),
    noopCaps,
  );

  assert.equal("batch_round_enabled" in payload, false);
  assert.equal("batch_total_limit" in payload, false);
  assert.equal("batch_round_size" in payload, false);
  assert.equal("batch_round_count" in payload, false);
});

test("created batch task message reports generated round count", () => {
  assert.equal(
    getCreatedCollectionTaskMessage({ batch_round_count: 4, parent_task_id: null }),
    "批次任务创建成功，已生成 4 个轮次",
  );
});

test("switching back to keyword collection keeps candidate-first defaults", () => {
  const relaxedLinkImport = {
    ...createEmptyTaskForm(),
    sourceMethod: "link_import" as const,
    collection_mode: "link_import" as const,
    min_followers_count: "10000",
    insert_qualified_only: true,
    export_qualified_only: true,
  };
  const form = applyDiscoverySource("keyword_hashtag", relaxedLinkImport, noopCaps);

  assert.equal(form.min_followers_count, "");
  assert.equal(form.insert_qualified_only, false);
  assert.equal(form.export_qualified_only, false);
});

test("selecting only YouTube maps to single-platform payload", () => {
  let form = keywordForm({ platforms: ["youtube", "tiktok"], platform: "multi" });
  form = toggleKeywordPlatformSelection(form, "tiktok", noopCaps);
  const payload = formValuesToPayload(form, noopCaps);
  assert.equal(payload.platform, "youtube");
  assert.deepEqual(payload.platforms, ["youtube"]);
});

test("selecting YouTube and TikTok maps to multi-platform payload", () => {
  let form = keywordForm({ platforms: ["youtube"], platform: "youtube" });
  form = toggleKeywordPlatformSelection(form, "tiktok", noopCaps);
  const payload = formValuesToPayload(form, noopCaps);
  assert.equal(payload.platform, "multi");
  assert.deepEqual(payload.platforms, ["youtube", "tiktok"]);
});

test("deselecting a platform removes it from payload", () => {
  let form = keywordForm({ platforms: ["youtube", "tiktok"], platform: "multi" });
  form = toggleKeywordPlatformSelection(form, "tiktok", noopCaps);
  const payload = formValuesToPayload(form, noopCaps);
  assert.deepEqual(payload.platforms, ["youtube"]);
  assert.equal(payload.platforms.includes("tiktok"), false);
});

test("multi platform auto defaults to verified keyword platforms", () => {
  const form = applyDiscoverySource("multi_platform_auto", createEmptyTaskForm(), noopCaps);
  assert.deepEqual(form.platforms, getMultiPlatformAutoPlatforms(noopCaps));
  assert.deepEqual(form.platforms, ["instagram", "youtube", "tiktok", "facebook"]);
  assert.equal(form.platform, "multi");
});

test("shopping seed auto source switches directly to seed discovery mode", () => {
  const form = applyDiscoverySource("shopping_seed_auto", createEmptyTaskForm(), noopCaps);
  assert.equal(form.sourceMethod, "shopping_seed_auto");
  assert.equal(form.collection_mode, "link_seed_discovery");
  assert.deepEqual(form.platforms, [...SEED_DISCOVERY_PLATFORMS]);
  assert.equal(form.platform, "multi");
});

test("shopping seed auto source accepts amazon asin without link import mode", () => {
  const form = applyDiscoverySource("shopping_seed_auto", createEmptyTaskForm(), noopCaps);
  const payload = formValuesToPayload(
    {
      ...form,
      name: "HOMEHIVE seed",
      competitorInputText: "B0D9W576KQ\nHOMEHIVE jewelry storage bags",
    },
    noopCaps,
  );
  assert.equal(payload.collection_mode, "link_seed_discovery");
  assert.notEqual(payload.collection_mode, "link_import");
  assert.ok(payload.input_urls.includes("B0D9W576KQ"));
  assert.ok(payload.keywords.includes("HOMEHIVE jewelry storage bags"));
});

test("editing link seed discovery initializes shopping seed auto mode", () => {
  const initial = getInitialForm(
    true,
    collectionTask({
      collection_mode: "link_seed_discovery",
      platform: "multi",
      platforms: ["ltk", "shopmy"],
      keywords: ["home decor"],
      input_urls: [],
    }),
  );

  assert.equal(initial.sourceMethod, "shopping_seed_auto");
  assert.equal(initial.collection_mode, "link_seed_discovery");
  assert.deepEqual(initial.platforms, ["ltk", "shopmy"]);
  assert.equal(initial.inputUrlsText, "");
});

test("link seed discovery submit ignores stale link import source method", () => {
  const form = {
    ...keywordForm({ name: "seed discovery stale source" }),
    sourceMethod: "link_import" as const,
    collection_mode: "link_seed_discovery" as const,
    platforms: ["ltk", "shopmy"],
    platform: "multi",
    keywordsText: "home decor",
    inputUrlsText: "",
  };

  assert.equal(validateForm(form, noopCaps), null);
  const payload = formValuesToPayload(form, noopCaps);
  assert.equal(payload.collection_mode, "link_seed_discovery");
  assert.deepEqual(payload.input_urls, []);
  assert.ok(payload.keywords.includes("home decor"));
});

test("keyword discovery submit ignores stale link import source method", () => {
  const form = {
    ...keywordForm({ name: "keyword stale source" }),
    sourceMethod: "link_import" as const,
    collection_mode: "discovery" as const,
    platforms: ["youtube"],
    platform: "youtube",
    keywordsText: "Makeup Bag",
    inputUrlsText: "",
  };

  assert.equal(validateForm(form, noopCaps), null);
  const payload = formValuesToPayload(form, noopCaps);
  assert.equal(payload.collection_mode, "discovery");
  assert.deepEqual(payload.input_urls, []);
  assert.ok(payload.keywords.includes("Makeup Bag"));
});

test("multi platform auto selects only configured platforms when others are unavailable", () => {
  const form = applyDiscoverySource("multi_platform_auto", createEmptyTaskForm(), youtubeOnlyCaps);
  assert.deepEqual(getMultiPlatformAutoPlatforms(youtubeOnlyCaps), ["youtube"]);
  assert.deepEqual(form.platforms, ["youtube"]);
  assert.equal(form.platform, "youtube");
  assert.equal(form.platforms.includes("instagram"), false);
  assert.equal(form.platforms.includes("tiktok"), false);
});

test("multi platform auto no longer falls back to seed-only platforms", () => {
  const form = applyDiscoverySource("multi_platform_auto", createEmptyTaskForm(), allUnavailableCaps);
  assert.deepEqual(form.platforms, []);
  assert.deepEqual(getMultiPlatformAutoPlatforms(allUnavailableCaps), []);
  assert.match(validateForm({ ...keywordForm(), platforms: ["pinterest", "shopmy"] }, allUnavailableCaps) ?? "", /导购 seed 自动发现/);
});

test("validateForm uses platform message for unavailable core platforms", () => {
  const form = keywordForm({ platforms: ["instagram"], platform: "instagram" });
  assert.equal(validateForm(form, allUnavailableCaps), "ok");
});

test("validateForm allows Pinterest keyword seed discovery", () => {
  const form = keywordForm({ platforms: ["pinterest"], platform: "pinterest" });
  assert.match(validateForm(form, youtubeOnlyCaps) ?? "", /导购 seed 自动发现/);
});

test("keyword seed platforms are submitted for keyword discovery", () => {
  const form = keywordForm({
    platforms: ["youtube", "pinterest", "ltk", "shopmy"],
    platform: "multi",
  });
  const payload = formValuesToPayload(form, noopCaps);
  assert.deepEqual(payload.platforms, ["youtube", "pinterest", "ltk", "shopmy"]);
  assert.equal(payload.platform, "multi");
});

test("seed-only keyword platform selection switches to shopping seed mode", () => {
  let form = keywordForm({ platforms: ["youtube"], platform: "youtube" });
  form = toggleKeywordPlatformSelection(form, "youtube", noopCaps);
  form = toggleKeywordPlatformSelection(form, "pinterest", noopCaps);
  form = toggleKeywordPlatformSelection(form, "shopmy", noopCaps);
  assert.equal(form.sourceMethod, "shopping_seed_auto");
  assert.equal(form.collection_mode, "link_seed_discovery");
  assert.deepEqual(form.platforms, ["pinterest", "shopmy"]);
});

test("seed-only keyword payload is normalized to link seed discovery", () => {
  const payload = formValuesToPayload(
    keywordForm({
      collection_mode: "discovery",
      platforms: ["pinterest", "shopmy"],
      platform: "multi",
      name: "seed only legacy payload",
    }),
    noopCaps,
  );
  assert.equal(payload.collection_mode, "link_seed_discovery");
  assert.deepEqual(payload.platforms, ["pinterest", "shopmy"]);
});

test("link import recognizes valid Pinterest LTK ShopMy URLs", () => {
  const preview = parseLinkImportPreview(
    "https://www.pinterest.com/pin/123/\nhttps://www.pinterest.com/example_user/\nhttps://shopltk.com/explore/user\nhttps://shopmy.us/example_user",
  );
  assert.equal(preview.counts.pinterest, 2);
  assert.equal(preview.counts.ltk, 1);
  assert.equal(preview.counts.shopmy, 1);
  assert.equal(preview.mixedAmazonAndProfiles, false);
});

test("link import preview rejects unsupported Pinterest LTK ShopMy path shapes", () => {
  const preview = parseLinkImportPreview(
    [
      "https://www.pinterest.com/some_user/some_board/",
      "https://shopltk.com/not-explore/user",
      "https://shopmy.us/shop",
    ].join("\n"),
  );
  assert.equal(preview.validCount, 0);
  assert.equal(preview.invalidCount, 3);
});

test("Amazon product links cannot mix with profile links in link import", () => {
  const preview = parseLinkImportPreview(
    "https://www.instagram.com/creator/\nhttps://www.amazon.com/dp/B0CPF3W9B2/",
  );
  assert.equal(preview.mixedAmazonAndProfiles, true);
});

test("Pinterest LTK and ShopMy are selectable keyword seed platforms", () => {
  assert.equal(isKeywordPlatformSelectable("pinterest", noopCaps.find((cap) => cap.platform === "pinterest")), true);
  assert.equal(isKeywordPlatformSelectable("shopmy", noopCaps.find((cap) => cap.platform === "shopmy")), true);
  assert.equal(isKeywordPlatformSelectable("ltk", noopCaps.find((cap) => cap.platform === "ltk")), true);
});

test("clicking keyword seed platform toggle keeps it in payload", () => {
  let form = keywordForm({ platforms: ["youtube"], platform: "youtube" });
  form = toggleKeywordPlatformSelection(form, "pinterest", noopCaps);
  form = toggleKeywordPlatformSelection(form, "ltk", noopCaps);
  form = toggleKeywordPlatformSelection(form, "shopmy", noopCaps);
  assert.deepEqual(form.platforms, ["youtube", "pinterest", "ltk", "shopmy"]);
  assert.equal(form.platform, "multi");
});

test("link import mode does not require manual platform selection", () => {
  const form = applyDiscoverySource(
    "link_import",
    keywordForm({ platforms: ["youtube", "tiktok"], platform: "multi" }),
    noopCaps,
  );
  assert.deepEqual(form.platforms, []);
  const payload = formValuesToPayload(
    {
      ...form,
      inputUrlsText: "https://www.pinterest.com/example_user/",
      name: "pinterest link import",
    },
    noopCaps,
  );
  assert.deepEqual(payload.platforms, []);
  assert.deepEqual(payload.keywords, []);
  assert.deepEqual(payload.filter_include_keywords, []);
  assert.deepEqual(payload.filter_exclude_keywords, []);
  assert.ok(payload.input_urls.some((url) => url.includes("pinterest.com")));
});

test("link import usage copy covers auto-detect and Amazon separation", () => {
  const text = LINK_IMPORT_USAGE_LINES.join("\n");
  assert.match(text, /无需手动选择平台/);
  assert.match(text, /粘贴该平台/);
  assert.match(text, /Amazon.*商品链接/);
  assert.match(text, /不要与红人主页链接混/);
});

test("pending platform card copy explains link completion and external discovery", () => {
  const text = LINK_ONLY_PLATFORM_CARD_LINES.join("\n");
  assert.match(text, /公共网页 seed 自动发现/);
  assert.match(text, /反向扩展外链/);
  assert.match(text, /低信息量 seed/);
  assert.match(text, /链接导入/);
  assert.doesNotMatch(URL_ONLY_PLATFORM_VALIDATION_MSG, /请切换到「链接导入」/);
  assert.match(URL_ONLY_PLATFORM_VALIDATION_MSG, /导购 seed 自动发现/);
});

test("quality filter fields are included in keyword discovery payload", () => {
  const payload = formValuesToPayload(
    {
      ...keywordForm({ name: "quality task" }),
      min_followers_count: "10000",
      min_engagement_rate: "1.5",
      require_email: true,
      require_contact: true,
      insert_qualified_only: true,
      strict_quality_filter: false,
      export_qualified_only: true,
    },
    noopCaps,
  );
  assert.equal(payload.min_followers_count, 10000);
  assert.equal(payload.min_engagement_rate, 1.5);
  assert.equal(payload.require_email, true);
  assert.equal(payload.require_contact, true);
  assert.equal(payload.insert_qualified_only, true);
  assert.equal(payload.strict_quality_filter, false);
  assert.equal(payload.export_qualified_only, true);
});

test("link import payload carries quality filters without mode-specific pollution", () => {
  const form = applyDiscoverySource(
    "link_import",
    keywordForm({
      keywordsText: "should-clear",
      min_followers_count: "20000",
      require_email: true,
      insert_qualified_only: true,
    }),
    noopCaps,
  );
  const payload = formValuesToPayload(
    {
      ...form,
      inputUrlsText: "https://www.instagram.com/creator/",
      name: "link quality",
    },
    noopCaps,
  );
  assert.deepEqual(payload.keywords, []);
  assert.equal(payload.min_followers_count, 20000);
  assert.equal(payload.require_email, true);
  assert.equal(payload.insert_qualified_only, true);
});

test("link seed discovery payload uses seed platforms and keywords", () => {
  const form = {
    ...keywordForm({ name: "seed discovery task" }),
    collection_mode: "link_seed_discovery" as const,
    platforms: ["ltk", "shopmy"],
    platform: "multi",
    keywordsText: "fashion creator",
    category: "Fashion",
  };
  const payload = formValuesToPayload(form, noopCaps);
  assert.equal(payload.collection_mode, "link_seed_discovery");
  assert.deepEqual(payload.platforms, ["ltk", "shopmy"]);
  assert.ok(payload.keywords.includes("fashion creator"));
  assert.equal(payload.category, "Fashion");
  assert.deepEqual(payload.input_urls, []);
});

test("link seed discovery payload keeps amazon input for automatic seed search", () => {
  const form = {
    ...keywordForm({ name: "amazon seed discovery" }),
    collection_mode: "link_seed_discovery" as const,
    platforms: ["ltk", "shopmy"],
    platform: "multi",
    competitorInputText:
      "https://www.amazon.com/dp/B0D9W576KQ/\nB0CPF3W9B2\nHOMEHIVE jewelry storage bags",
    keywordsText: "Amazon finds creator",
    category: "",
  };
  const payload = formValuesToPayload(form, noopCaps);
  assert.equal(payload.collection_mode, "link_seed_discovery");
  assert.ok(payload.input_urls.some((url) => url.includes("B0D9W576KQ")));
  assert.ok(payload.input_urls.includes("B0CPF3W9B2"));
  assert.ok(payload.keywords.includes("HOMEHIVE jewelry storage bags"));
  assert.ok(payload.keywords.includes("Amazon finds creator"));
});

test("validateForm requires keywords or category for link seed discovery", () => {
  const form = {
    ...keywordForm(),
    collection_mode: "link_seed_discovery" as const,
    platforms: ["ltk"],
    keywordsText: "",
    category: "",
    name: "seed task",
  };
  assert.match(validateForm(form, noopCaps) ?? "", /关键词或类目/);
});

test("validateForm accepts category-only link seed discovery", () => {
  const form = {
    ...keywordForm(),
    collection_mode: "link_seed_discovery" as const,
    platforms: ["pinterest"],
    keywordsText: "",
    category: "Home Decor",
    name: "seed category task",
  };
  assert.equal(validateForm(form, noopCaps), null);
});

test("validateForm accepts amazon asin-only link seed discovery", () => {
  const form = {
    ...keywordForm(),
    collection_mode: "link_seed_discovery" as const,
    platforms: ["ltk"],
    competitorInputText: "B0D9W576KQ",
    keywordsText: "",
    category: "",
    name: "seed asin task",
  };
  assert.equal(validateForm(form, noopCaps), null);
});

test("validateForm applies quality filters to link seed discovery", () => {
  const form = {
    ...keywordForm(),
    collection_mode: "link_seed_discovery" as const,
    platforms: ["pinterest"],
    keywordsText: "home decor",
    min_followers_count: "abc",
    name: "seed quality task",
  };
  assert.notEqual(validateForm(form, noopCaps), null);
});

test("saved template keeps quality filters but not mode-specific fields", () => {
  const form = {
    ...keywordForm({ name: "template source" }),
    min_followers_count: "15000",
    require_contact: true,
    export_qualified_only: true,
  };
  const template = extractFormTemplate(form);
  assert.equal(template.min_followers_count, "15000");
  assert.equal(template.require_contact, true);
  assert.equal(template.export_qualified_only, true);
  assert.equal("keywordsText" in template, false);
  assert.equal("platforms" in template, false);

  const applied = applyFormTemplate(createEmptyTaskForm(), template);
  assert.equal(applied.min_followers_count, "15000");
  assert.equal(applied.require_contact, true);
  assert.equal(applied.keywordsText, "");
});

test("task form explains auto outreach success visibility to sales users", () => {
  const source = readFileSync(
    new URL("../src/components/collection-tasks/task-form-dialog.tsx", import.meta.url),
    "utf8",
  );

  assert.match(source, /发送成功后/);
  assert.match(source, /发送记录/);
  assert.match(source, /发送出去的邮件/);
});
