import assert from "node:assert/strict";
import test from "node:test";

import type { PlatformCapability } from "../src/lib/api.ts";
import { formatLinkImportPlatformHints, parseLinkImportPreview } from "../src/lib/collection-sources.ts";
import {
  applyDiscoverySource,
  applyFormTemplate,
  createEmptyTaskForm,
  extractFormTemplate,
  formValuesToPayload,
  getInitialForm,
  getMultiPlatformAutoPlatforms,
  isKeywordPlatformSelectable,
  saveFormTemplate,
  TEMPLATE_STORAGE_KEY,
  toggleKeywordPlatformSelection,
  validateForm,
} from "../src/lib/task-form-payload.ts";
import {
  KEYWORD_DISCOVERY_PLATFORMS,
  LINK_IMPORT_USAGE_LINES,
  LINK_ONLY_PLATFORM_CARD_LINES,
  NO_CONFIGURED_KEYWORD_PLATFORMS_MSG,
  URL_ONLY_PLATFORMS,
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
  assert.deepEqual(form.platforms, [...KEYWORD_DISCOVERY_PLATFORMS]);
  assert.equal(form.platform, "multi");
});

test("multi platform auto selects only configured platforms when others are unavailable", () => {
  const form = applyDiscoverySource("multi_platform_auto", createEmptyTaskForm(), youtubeOnlyCaps);
  assert.deepEqual(getMultiPlatformAutoPlatforms(youtubeOnlyCaps), ["youtube"]);
  assert.deepEqual(form.platforms, ["youtube"]);
  assert.equal(form.platform, "youtube");
  assert.equal(form.platforms.includes("instagram"), false);
  assert.equal(form.platforms.includes("tiktok"), false);
});

test("multi platform auto does not select unavailable platforms when none are configured", () => {
  const form = applyDiscoverySource("multi_platform_auto", createEmptyTaskForm(), allUnavailableCaps);
  assert.deepEqual(form.platforms, []);
  assert.deepEqual(getMultiPlatformAutoPlatforms(allUnavailableCaps), []);
  assert.equal(
    validateForm({ ...keywordForm(), platforms: [] }, allUnavailableCaps),
    NO_CONFIGURED_KEYWORD_PLATFORMS_MSG,
  );
});

test("validateForm uses platform message for unavailable core platforms", () => {
  const form = keywordForm({ platforms: ["instagram"], platform: "instagram" });
  assert.equal(validateForm(form, allUnavailableCaps), "ok");
});

test("validateForm uses link-only message for Pinterest", () => {
  const form = keywordForm({ platforms: ["pinterest"], platform: "pinterest" });
  assert.match(validateForm(form, youtubeOnlyCaps) ?? "", /链接导入/);
});

test("url-only platforms are not submitted for keyword discovery", () => {
  const form = keywordForm({
    platforms: ["youtube", "pinterest", "ltk", "shopmy"],
    platform: "multi",
  });
  const payload = formValuesToPayload(form, noopCaps);
  assert.deepEqual(payload.platforms, ["youtube"]);
  assert.equal(payload.platform, "youtube");
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
      "https://shopmy.us/shop/example",
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

test("url-only platforms are visible in keyword mode but not selectable", () => {
  for (const platform of URL_ONLY_PLATFORMS) {
    assert.equal(isKeywordPlatformSelectable(platform, noopCaps.find((cap) => cap.platform === platform)), false);
  }
});

test("clicking url-only platform toggle does not change platforms", () => {
  let form = keywordForm({ platforms: ["youtube"], platform: "youtube" });
  for (const platform of URL_ONLY_PLATFORMS) {
    const next = toggleKeywordPlatformSelection(form, platform, noopCaps);
    assert.deepEqual(next.platforms, ["youtube"]);
    assert.equal(next.platform, "youtube");
    form = next;
  }
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
  assert.match(text, /链接导入或其他社媒外链发现/);
  assert.match(text, /低信息量结果/);
  assert.match(text, /链接导入/);
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
