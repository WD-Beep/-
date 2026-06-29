import type { CollectionMode, CollectionTask, CollectionTaskPayload, PlatformCapability, TaskSourceMethod } from "./api.ts";
import { COLLECTION_MODE_LABELS, KEYWORD_DISCOVERY_PLATFORMS, KEYWORD_SEED_DISCOVERY_PLATFORMS, NO_CONFIGURED_KEYWORD_PLATFORMS_MSG, PLATFORM_LABELS, SEED_DISCOVERY_PLATFORMS, taskSourceMethodForMode, URL_ONLY_PLATFORM_VALIDATION_MSG, URL_ONLY_PLATFORMS } from "./labels.ts";
import { parseLinkImportPreview } from "./collection-sources.ts";

export const TEMPLATE_STORAGE_KEY = "influencer-intel:collection-task-template";
export type DiscoverySource = "keyword_hashtag" | "link_import" | "shopping_seed_auto" | "multi_platform_auto";

const DEFAULT_PLATFORMS = ["youtube"];
export const KEYWORD_HIGH_VALUE_DEFAULTS = {
  min_followers_count: "10000",
  min_engagement_rate: "",
  require_email: false,
  require_contact: false,
  strict_quality_filter: false,
  insert_qualified_only: true,
  export_qualified_only: true,
} as const;

export type TaskFormValues = {
  stable_collection_mode: boolean;
  sourceMethod: TaskSourceMethod;
  name: string;
  collection_mode: CollectionMode;
  platform: string;
  platforms: string[];
  keywordsText: string;
  inputUrlsText: string;
  country: string;
  category: string;
  discovery_limit: string;
  min_engagement_rate: string;
  min_followers_count: string;
  max_followers_count: string;
  filterIncludeKeywordsText: string;
  filterExcludeKeywordsText: string;
  require_email: boolean;
  require_contact: boolean;
  strict_quality_filter: boolean;
  insert_qualified_only: boolean;
  export_qualified_only: boolean;
  schedule_enabled: boolean;
  schedule_cron: string;
  email_enabled: boolean;
  email_recipientsText: string;
  outreach_enabled: boolean;
  outreach_provider: string;
  outreach_dry_run: boolean;
  micro_subject: string;
  micro_body: string;
  mid_subject: string;
  mid_body: string;
  macro_subject: string;
  macro_body: string;
  comment_discovery_enabled: boolean;
  competitorInputText: string;
  competitorBrandText: string;
  competitorWebsiteText: string;
};

const emptyForm: TaskFormValues = {
  stable_collection_mode: false,
  sourceMethod: "keyword_discovery",
  name: "",
  collection_mode: "discovery",
  platform: "youtube",
  platforms: [...DEFAULT_PLATFORMS],
  keywordsText: "",
  inputUrlsText: "",
  country: "",
  category: "",
  discovery_limit: "50",
  min_engagement_rate: KEYWORD_HIGH_VALUE_DEFAULTS.min_engagement_rate,
  min_followers_count: KEYWORD_HIGH_VALUE_DEFAULTS.min_followers_count,
  max_followers_count: "",
  filterIncludeKeywordsText: "",
  filterExcludeKeywordsText: "",
  require_email: KEYWORD_HIGH_VALUE_DEFAULTS.require_email,
  require_contact: KEYWORD_HIGH_VALUE_DEFAULTS.require_contact,
  strict_quality_filter: KEYWORD_HIGH_VALUE_DEFAULTS.strict_quality_filter,
  insert_qualified_only: KEYWORD_HIGH_VALUE_DEFAULTS.insert_qualified_only,
  export_qualified_only: KEYWORD_HIGH_VALUE_DEFAULTS.export_qualified_only,
  schedule_enabled: false,
  schedule_cron: "",
  email_enabled: false,
  email_recipientsText: "",
  outreach_enabled: false,
  outreach_provider: "mailchimp",
  outreach_dry_run: true,
  micro_subject: "",
  micro_body: "",
  mid_subject: "",
  mid_body: "",
  macro_subject: "",
  macro_body: "",
  comment_discovery_enabled: false,
  competitorInputText: "",
  competitorBrandText: "",
  competitorWebsiteText: "",
};

export function createEmptyTaskForm(): TaskFormValues {
  return { ...emptyForm, platforms: [...DEFAULT_PLATFORMS] };
}

const STABLE_COLLECTION_DEFAULT_TARGET = "20";

function stablePrimaryPlatform(platforms: string[]): string {
  const preferred = platforms.find((platform) =>
    (KEYWORD_DISCOVERY_PLATFORMS as readonly string[]).includes(platform),
  );
  return preferred ?? "youtube";
}

export function applyStableCollectionMode(values: TaskFormValues): TaskFormValues {
  const platform = stablePrimaryPlatform(values.platforms);
  return {
    ...values,
    stable_collection_mode: true,
    discovery_limit: STABLE_COLLECTION_DEFAULT_TARGET,
    require_email: false,
    require_contact: false,
    strict_quality_filter: false,
    insert_qualified_only: false,
    export_qualified_only: false,
    platform,
    platforms: [platform],
  };
}

export function clearStableCollectionMode(values: TaskFormValues): TaskFormValues {
  return { ...values, stable_collection_mode: false };
}

function withKeywordHighValueDefaults(values: TaskFormValues): TaskFormValues {
  return {
    ...values,
    min_followers_count: values.min_followers_count.trim()
      ? values.min_followers_count
      : KEYWORD_HIGH_VALUE_DEFAULTS.min_followers_count,
    min_engagement_rate: values.min_engagement_rate.trim()
      ? values.min_engagement_rate
      : KEYWORD_HIGH_VALUE_DEFAULTS.min_engagement_rate,
    require_email: values.require_email || KEYWORD_HIGH_VALUE_DEFAULTS.require_email,
    require_contact: values.require_contact || KEYWORD_HIGH_VALUE_DEFAULTS.require_contact,
    strict_quality_filter: values.strict_quality_filter || KEYWORD_HIGH_VALUE_DEFAULTS.strict_quality_filter,
    insert_qualified_only: values.insert_qualified_only || KEYWORD_HIGH_VALUE_DEFAULTS.insert_qualified_only,
    export_qualified_only: values.export_qualified_only || KEYWORD_HIGH_VALUE_DEFAULTS.export_qualified_only,
  };
}

type TaskFormTemplate = Omit<
  TaskFormValues,
  | "name"
  | "sourceMethod"
  | "collection_mode"
  | "platform"
  | "platforms"
  | "keywordsText"
  | "inputUrlsText"
  | "competitorInputText"
  | "competitorBrandText"
  | "competitorWebsiteText"
>;

export function extractFormTemplate(values: TaskFormValues): TaskFormTemplate {
  /* Mode-specific fields are intentionally excluded from reusable templates. */
  const excluded = {
    name: true,
    sourceMethod: true,
    collection_mode: true,
    platform: true,
    platforms: true,
    keywordsText: true,
    inputUrlsText: true,
    competitorInputText: true,
    competitorBrandText: true,
    competitorWebsiteText: true,
  } as const;
  const template = {} as TaskFormTemplate;
  for (const [key, value] of Object.entries(values) as [keyof TaskFormValues, TaskFormValues[keyof TaskFormValues]][]) {
    if (key in excluded) continue;
    (template as Record<string, unknown>)[key] = value;
  }
  return template;
}

export function applyFormTemplate(base: TaskFormValues, template: Partial<TaskFormTemplate>): TaskFormValues {
  return { ...base, ...template };
}

export function loadSavedFormTemplate(): Partial<TaskFormTemplate> | null {
  try {
    const raw = localStorage.getItem(TEMPLATE_STORAGE_KEY);
    if (!raw) return null;
    const saved = JSON.parse(raw) as Partial<TaskFormValues>;
    return extractFormTemplate({ ...emptyForm, ...saved });
  } catch {
    return null;
  }
}

export function saveFormTemplate(values: TaskFormValues) {
  localStorage.setItem(TEMPLATE_STORAGE_KEY, JSON.stringify(extractFormTemplate(values)));
}

function clearKeywordDiscoveryFields(): Partial<TaskFormValues> {
  return {
    keywordsText: "",
    competitorInputText: "",
    competitorBrandText: "",
    competitorWebsiteText: "",
    category: "",
    country: "",
    filterIncludeKeywordsText: "",
    filterExcludeKeywordsText: "",
    comment_discovery_enabled: false,
  };
}

function clearLinkImportFields(): Partial<TaskFormValues> {
  return {
    inputUrlsText: "",
  };
}

function keywordDiscoveryInputUrls(values: TaskFormValues): string[] {
  const mode = values.collection_mode === "comment_authors" ? "urls" : values.collection_mode;
  if (mode === "urls" || mode === "mixed" || mode === "clustering") {
    return splitLines(values.inputUrlsText);
  }
  return [];
}

export function isLinkImportTaskForm(
  values: Pick<TaskFormValues, "sourceMethod" | "collection_mode">,
): boolean {
  if (values.collection_mode === "link_seed_discovery") return false;
  return values.collection_mode === "link_import" || values.sourceMethod === "link_import";
}

function templatesToForm(templates: Record<string, string> = {}): Pick<
  TaskFormValues,
  "micro_subject" | "micro_body" | "mid_subject" | "mid_body" | "macro_subject" | "macro_body"
> {
  return {
    micro_subject: templates.micro_subject ?? "",
    micro_body: templates.micro_body ?? "",
    mid_subject: templates.mid_subject ?? "",
    mid_body: templates.mid_body ?? "",
    macro_subject: templates.macro_subject ?? "",
    macro_body: templates.macro_body ?? "",
  };
}

function formToTemplates(values: TaskFormValues): Record<string, string> {
  const templates: Record<string, string> = {};
  const pairs: [string, string][] = [
    ["micro_subject", values.micro_subject],
    ["micro_body", values.micro_body],
    ["mid_subject", values.mid_subject],
    ["mid_body", values.mid_body],
    ["macro_subject", values.macro_subject],
    ["macro_body", values.macro_body],
  ];
  for (const [key, value] of pairs) {
    if (value.trim()) templates[key] = value.trim();
  }
  return templates;
}

function splitLines(text: string): string[] {
  return text
    .split(/[\n,，]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function isAmazonOrHttpUrl(text: string): boolean {
  return /amazon\.[a-z.]+/i.test(text) || /^[A-Z0-9]{10}$/i.test(text) || /^https?:\/\//i.test(text);
}

function parseCompetitorFormInput(text: string): { keywords: string[]; input_urls: string[] } {
  const keywords: string[] = [];
  const input_urls: string[] = [];
  for (const line of splitLines(text)) {
    if (isAmazonOrHttpUrl(line)) {
      input_urls.push(line);
    } else {
      keywords.push(line);
    }
  }
  return { keywords, input_urls };
}

function isUrlOnlyPlatform(platform: string): boolean {
  return (URL_ONLY_PLATFORMS as readonly string[]).includes(platform);
}

function isKeywordSeedPlatform(platform: string): boolean {
  return (KEYWORD_SEED_DISCOVERY_PLATFORMS as readonly string[]).includes(platform);
}

function isSeedOnlyDiscoverySelection(platforms: string[]): boolean {
  return platforms.length > 0 && platforms.every((platform) => isKeywordSeedPlatform(platform));
}

function seedOnlyDiscoveryMessage(platforms: string[]): string {
  const labels = platforms.map((platform) => PLATFORM_LABELS[platform] ?? platform);
  return `${labels.join(" / ")} 关键词采集请使用“导购 seed 自动发现”，不要用普通关键词发现。`;
}

function stripUrlOnlyPlatforms(platforms: string[]): string[] {
  return platforms.filter((platform) => !isUrlOnlyPlatform(platform) || isKeywordSeedPlatform(platform));
}

export function isKeywordDiscoveryPlatform(
  platform: string,
  cap: PlatformCapability | undefined,
): boolean {
  if (isKeywordSeedPlatform(platform)) return true;
  if (cap) {
    return cap.keyword_discovery && cap.status !== "not_configured" && cap.status !== "not_available";
  }
  return (KEYWORD_DISCOVERY_PLATFORMS as readonly string[]).includes(platform);
}

export function isKeywordPlatformSelectable(
  platform: string,
  cap: PlatformCapability | undefined,
): boolean {
  if (isKeywordSeedPlatform(platform)) return true;
  if (!isKeywordDiscoveryPlatform(platform, cap)) return false;
  if (!cap) return true;
  return cap.status === "supported" || (cap.status === "url_only" && cap.keyword_discovery);
}

export function filterKeywordSubmissionPlatforms(
  platforms: string[],
  caps: PlatformCapability[] = [],
): string[] {
  if (caps.length === 0) return stripUrlOnlyPlatforms(platforms);
  return platforms.filter((platform) => {
    const cap = caps.find((item) => item.platform === platform);
    return isKeywordDiscoveryPlatform(platform, cap);
  });
}

export function resolvePlatformFields(platforms: string[]): Pick<TaskFormValues, "platform" | "platforms"> {
  const selected = [...platforms];
  if (selected.length === 0) {
    return { platform: "youtube", platforms: [] };
  }
  if (selected.length === 1) {
    return { platform: selected[0]!, platforms: selected };
  }
  return { platform: "multi", platforms: selected };
}

export function getKeywordDiscoveryDefaultPlatforms(caps: PlatformCapability[] = []): string[] {
  const configured = KEYWORD_DISCOVERY_PLATFORMS.filter((platform) =>
    !isKeywordSeedPlatform(platform) &&
    isKeywordPlatformSelectable(platform, caps.find((item) => item.platform === platform)),
  );
  if (caps.length > 0) return [...configured];
  return configured.length ? [...configured] : ["youtube"];
}

export function getMultiPlatformAutoPlatforms(caps: PlatformCapability[] = []): string[] {
  return getKeywordDiscoveryDefaultPlatforms(caps);
}

function isVerifiedKeywordPlatform(platform: string): boolean {
  return (KEYWORD_DISCOVERY_PLATFORMS as readonly string[]).includes(platform);
}

function invalidKeywordPlatformMessage(
  platform: string,
  cap: PlatformCapability | undefined,
): string | null {
  if (isKeywordDiscoveryPlatform(platform, cap)) return null;
  if (isUrlOnlyPlatform(platform)) return URL_ONLY_PLATFORM_VALIDATION_MSG;
  if (isVerifiedKeywordPlatform(platform)) {
    if (cap?.message) return cap.message;
    return `${PLATFORM_LABELS[platform] ?? platform} 当前不可采集，请检查 Apify / API Direct 配置`;
  }
  return `${PLATFORM_LABELS[platform] ?? platform} 当前不支持关键词采集`;
}

export function toggleSeedPlatformSelection(prev: TaskFormValues, platform: string): TaskFormValues {
  if (!(SEED_DISCOVERY_PLATFORMS as readonly string[]).includes(platform)) return prev;
  const checked = prev.platforms.includes(platform);
  const next = checked ? prev.platforms.filter((p) => p !== platform) : [...prev.platforms, platform];
  const platforms = next.filter((p) => (SEED_DISCOVERY_PLATFORMS as readonly string[]).includes(p));
  return { ...prev, ...resolvePlatformFields(platforms) };
}

export function toggleKeywordPlatformSelection(
  prev: TaskFormValues,
  platform: string,
  caps: PlatformCapability[] = [],
): TaskFormValues {
  const cap = caps.find((item) => item.platform === platform);
  if (!isKeywordPlatformSelectable(platform, cap)) return prev;

  const checked = prev.platforms.includes(platform);
  const next = checked ? prev.platforms.filter((p) => p !== platform) : [...prev.platforms, platform];
  const platforms = filterKeywordSubmissionPlatforms(next, caps);
  if (isSeedOnlyDiscoverySelection(platforms)) {
    return {
      ...prev,
      sourceMethod: "shopping_seed_auto",
      collection_mode: "link_seed_discovery",
      comment_discovery_enabled: false,
      ...resolvePlatformFields(platforms),
    };
  }
  return {
    ...prev,
    sourceMethod: "keyword_discovery",
    collection_mode:
      prev.collection_mode === "link_import" || prev.collection_mode === "link_seed_discovery"
        ? "discovery"
        : prev.collection_mode,
    ...resolvePlatformFields(platforms),
  };
}

export { stripUrlOnlyPlatforms };

function validateQualityAndDelivery(values: TaskFormValues): string | null {
  if (values.email_enabled && splitLines(values.email_recipientsText).length === 0) {
    return "启用邮件发送时请填写收件人邮箱";
  }
  const discoveryLimit = Number(values.discovery_limit);
  if (!Number.isFinite(discoveryLimit) || discoveryLimit < 1 || discoveryLimit > 500) {
    return "采集数量上限需在 1-500 之间";
  }
  const minEngagementText = values.min_engagement_rate.trim();
  if (minEngagementText) {
    const minEngagement = Number(minEngagementText);
    if (!Number.isFinite(minEngagement) || minEngagement < 0 || minEngagement > 100) {
      return "最低互动率需在 0-100 之间";
    }
  }
  const minFollowers = values.min_followers_count.trim();
  const maxFollowers = values.max_followers_count.trim();
  if (minFollowers) {
    const n = Number(minFollowers);
    if (!Number.isFinite(n) || n < 0 || !Number.isInteger(n)) {
      return "最低粉丝数需为非负整数";
    }
  }
  if (maxFollowers) {
    const n = Number(maxFollowers);
    if (!Number.isFinite(n) || n < 0 || !Number.isInteger(n)) {
      return "最高粉丝数需为非负整数";
    }
  }
  if (minFollowers && maxFollowers && Number(minFollowers) > Number(maxFollowers)) {
    return "最低粉丝数不能大于最高粉丝数";
  }
  return null;
}

export function validateForm(values: TaskFormValues, platformCapabilities: PlatformCapability[]): string | null {
  const keywords = splitLines(values.keywordsText);
  const urls = splitLines(values.inputUrlsText);
  const taskName = values.name.trim() || suggestTaskName(values);

  if (!taskName) return "请填写任务名";

  if (isLinkImportTaskForm(values)) {
    if (urls.length === 0) return "请至少粘贴一行红人主页或 Amazon 商品链接";
    const preview = parseLinkImportPreview(values.inputUrlsText);
    if (preview.invalidCount > 0) {
      return preview.invalidLines[0] ?? "存在无法识别的链接";
    }
    if (preview.validCount === 0) {
      return "未识别到任何有效链接";
    }
    if (preview.mixedAmazonAndProfiles) {
      return "Amazon 商品链接请单独创建商品发现任务，不要与红人主页链接混在同一任务中";
    }
    return null;
  }

  if (values.collection_mode === "link_seed_discovery") {
    const competitor = parseCompetitorFormInput(values.competitorInputText);
    if (!keywords.length && !competitor.keywords.length && !competitor.input_urls.length && !values.category.trim()) {
      return "导购 seed 自动发现需填写关键词或类目";
    }
    const seedPlatforms = values.platforms.filter((p) =>
      (SEED_DISCOVERY_PLATFORMS as readonly string[]).includes(p),
    );
    if (seedPlatforms.length === 0) {
      return "请至少选择 LTK、ShopMy 或 Pinterest 作为 seed 来源平台";
    }
    return validateQualityAndDelivery(values);
  }

  if (!values.platforms.length) {
    if (platformCapabilities.length > 0 && getMultiPlatformAutoPlatforms(platformCapabilities).length === 0) {
      return NO_CONFIGURED_KEYWORD_PLATFORMS_MSG;
    }
    return "请至少选择一个采集平台";
  }

  for (const platform of values.platforms) {
    const cap = platformCapabilities.find((item) => item.platform === platform);
    const invalidMessage = invalidKeywordPlatformMessage(platform, cap);
    if (invalidMessage) return invalidMessage;
  }

  const submissionPlatforms = filterKeywordSubmissionPlatforms(values.platforms, platformCapabilities);
  if (isSeedOnlyDiscoverySelection(submissionPlatforms)) {
    return seedOnlyDiscoveryMessage(submissionPlatforms);
  }
  if (submissionPlatforms.length === 0) {
    if (platformCapabilities.length > 0 && getMultiPlatformAutoPlatforms(platformCapabilities).length === 0) {
      return NO_CONFIGURED_KEYWORD_PLATFORMS_MSG;
    }
    return "请至少选择一个已验证的关键词采集平台";
  }
  for (const platform of submissionPlatforms) {
    const cap = platformCapabilities.find((item) => item.platform === platform);
    if (cap && (cap.status === "not_configured" || cap.status === "not_available")) {
      return cap.message || `${platform} 当前不可采集，请检查 Apify / API Direct 配置`;
    }
  }
  const mode =
    values.collection_mode === "comment_authors" ? "urls" : values.collection_mode;
  if ((mode === "keyword" || mode === "discovery") && keywords.length === 0) {
    return "关键词采集至少填写一个关键词";
  }
  if (mode === "category_discovery") {
    if (!values.category.trim()) return "类目采集必须填写类目";
  }
  if ((mode === "urls" || mode === "clustering") && urls.length === 0) {
    return "请至少填写一个平台主页/帖子/Reel 链接或用户名";
  }
  if (values.collection_mode === "mixed" && keywords.length === 0 && urls.length === 0) {
    return "混合模式需填写关键词或链接至少一项";
  }
  if (values.collection_mode === "competitor_product") {
    const competitor = parseCompetitorFormInput(values.competitorInputText);
    if (
      competitor.keywords.length === 0 &&
      competitor.input_urls.length === 0 &&
      !values.competitorBrandText.trim()
    ) {
      return "竞品商品发现需填写 Amazon 链接、ASIN 或商品关键词";
    }
  }
  if (values.email_enabled && splitLines(values.email_recipientsText).length === 0) {
    return "启用邮件发送时请填写收件人邮箱";
  }
  const discoveryLimit = Number(values.discovery_limit);
  if (!Number.isFinite(discoveryLimit) || discoveryLimit < 1 || discoveryLimit > 500) {
    return "采集数量上限需在 1-500 之间";
  }
  const minEngagementText = values.min_engagement_rate.trim();
  if (minEngagementText) {
    const minEngagement = Number(minEngagementText);
    if (!Number.isFinite(minEngagement) || minEngagement < 0 || minEngagement > 100) {
      return "最低互动率需在 0-100 之间";
    }
  }
  const minFollowers = values.min_followers_count.trim();
  const maxFollowers = values.max_followers_count.trim();
  if (minFollowers) {
    const n = Number(minFollowers);
    if (!Number.isFinite(n) || n < 0 || !Number.isInteger(n)) {
      return "最低粉丝数需为非负整数";
    }
  }
  if (maxFollowers) {
    const n = Number(maxFollowers);
    if (!Number.isFinite(n) || n < 0 || !Number.isInteger(n)) {
      return "最高粉丝数需为非负整数";
    }
  }
  if (minFollowers && maxFollowers && Number(minFollowers) > Number(maxFollowers)) {
    return "最低粉丝数不能大于最高粉丝数";
  }
  return null;
}

function parseOptionalInt(text: string): number | null {
  const trimmed = text.trim();
  if (!trimmed) return null;
  return Number(trimmed);
}

function parseOptionalEngagementRate(text: string): number | null {
  const trimmed = text.trim();
  if (!trimmed) return null;
  return Number(trimmed);
}

function buildQualityFilterPayload(values: TaskFormValues) {
  return {
    min_engagement_rate: parseOptionalEngagementRate(values.min_engagement_rate),
    min_followers_count: parseOptionalInt(values.min_followers_count),
    max_followers_count: parseOptionalInt(values.max_followers_count),
    filter_include_keywords: splitLines(values.filterIncludeKeywordsText),
    filter_exclude_keywords: splitLines(values.filterExcludeKeywordsText),
    require_email: values.require_email,
    require_contact: values.require_contact,
    strict_quality_filter: values.strict_quality_filter,
    insert_qualified_only: values.insert_qualified_only,
    export_qualified_only: values.export_qualified_only,
  };
}

export { buildQualityFilterPayload };

function withStablePayloadDefaults(
  payload: CollectionTaskPayload,
  values: TaskFormValues,
): CollectionTaskPayload {
  if (!values.stable_collection_mode) return payload;
  const platform = stablePrimaryPlatform(payload.platforms.length ? payload.platforms : values.platforms);
  return {
    ...payload,
    stable_collection_mode: true,
    discovery_limit: 20,
    require_email: false,
    require_contact: false,
    strict_quality_filter: false,
    insert_qualified_only: false,
    export_qualified_only: false,
    platform,
    platforms: [platform],
  };
}

export function formValuesToPayload(
  values: TaskFormValues,
  platformCapabilities: PlatformCapability[] = [],
): CollectionTaskPayload {
  const taskName = values.name.trim() || suggestTaskName(values);
  if (isLinkImportTaskForm(values)) {
    return withStablePayloadDefaults({
      name: taskName,
      collection_mode: "link_import",
      platform: "instagram",
      platforms: [],
      keywords: [],
      input_urls: splitLines(values.inputUrlsText),
      country: null,
      category: null,
      discovery_limit: Number(values.discovery_limit) || 100,
      ...buildQualityFilterPayload(values),
      schedule_enabled: values.schedule_enabled,
      schedule_cron: values.schedule_enabled ? values.schedule_cron.trim() || null : null,
      email_enabled: values.email_enabled,
      email_recipients: values.email_enabled ? splitLines(values.email_recipientsText) : [],
      outreach_enabled: values.outreach_enabled,
      outreach_provider: values.outreach_provider,
      outreach_dry_run: values.outreach_dry_run,
      outreach_templates: formToTemplates(values),
      comment_discovery_enabled: false,
    }, values);
  }

  if (values.collection_mode === "competitor_product") {
    const competitor = parseCompetitorFormInput(values.competitorInputText);
    const keywords = [...competitor.keywords];
    const input_urls = [...competitor.input_urls];
    const brand = values.competitorBrandText.trim();
    if (brand) keywords.unshift(`brand:${brand}`);
    const website = values.competitorWebsiteText.trim();
    if (website) input_urls.push(website);
    const platforms = filterKeywordSubmissionPlatforms(values.platforms, platformCapabilities);
    const { platform, platforms: selectedPlatforms } = resolvePlatformFields(platforms);
    return withStablePayloadDefaults({
      name: taskName,
      collection_mode: values.collection_mode,
      platform,
      platforms: selectedPlatforms,
      keywords,
      input_urls,
      country: values.country.trim() || null,
      category: values.category.trim() || null,
      discovery_limit: Number(values.discovery_limit),
      ...buildQualityFilterPayload(values),
      schedule_enabled: values.schedule_enabled,
      schedule_cron: values.schedule_enabled ? values.schedule_cron.trim() || null : null,
      email_enabled: values.email_enabled,
      email_recipients: values.email_enabled ? splitLines(values.email_recipientsText) : [],
      outreach_enabled: values.outreach_enabled,
      outreach_provider: values.outreach_provider,
      outreach_dry_run: values.outreach_dry_run,
      outreach_templates: formToTemplates(values),
      comment_discovery_enabled: false,
    }, values);
  }

  if (values.collection_mode === "link_seed_discovery") {
    const competitor = parseCompetitorFormInput(values.competitorInputText);
    const seedPlatforms = values.platforms.filter((p) =>
      (SEED_DISCOVERY_PLATFORMS as readonly string[]).includes(p),
    );
    const resolvedSeedPlatforms =
      seedPlatforms.length > 0 ? seedPlatforms : [...SEED_DISCOVERY_PLATFORMS];
    const { platform, platforms: selectedPlatforms } = resolvePlatformFields(resolvedSeedPlatforms);
    return withStablePayloadDefaults({
      name: taskName,
      collection_mode: "link_seed_discovery",
      platform,
      platforms: selectedPlatforms,
      keywords: Array.from(new Set([...competitor.keywords, ...splitLines(values.keywordsText)])),
      input_urls: competitor.input_urls,
      country: values.country.trim() || null,
      category: values.category.trim() || null,
      discovery_limit: Number(values.discovery_limit),
      ...buildQualityFilterPayload(values),
      schedule_enabled: values.schedule_enabled,
      schedule_cron: values.schedule_enabled ? values.schedule_cron.trim() || null : null,
      email_enabled: values.email_enabled,
      email_recipients: values.email_enabled ? splitLines(values.email_recipientsText) : [],
      outreach_enabled: values.outreach_enabled,
      outreach_provider: values.outreach_provider,
      outreach_dry_run: values.outreach_dry_run,
      outreach_templates: formToTemplates(values),
      comment_discovery_enabled: false,
    }, values);
  }

  const platforms = filterKeywordSubmissionPlatforms(values.platforms, platformCapabilities);
  if (isSeedOnlyDiscoverySelection(platforms)) {
    const { platform, platforms: selectedPlatforms } = resolvePlatformFields(platforms);
    return withStablePayloadDefaults({
      name: taskName,
      collection_mode: "link_seed_discovery",
      platform,
      platforms: selectedPlatforms,
      keywords: splitLines(values.keywordsText),
      input_urls: [],
      country: values.country.trim() || null,
      category: values.category.trim() || null,
      discovery_limit: Number(values.discovery_limit),
      ...buildQualityFilterPayload(values),
      schedule_enabled: values.schedule_enabled,
      schedule_cron: values.schedule_enabled ? values.schedule_cron.trim() || null : null,
      email_enabled: values.email_enabled,
      email_recipients: values.email_enabled ? splitLines(values.email_recipientsText) : [],
      outreach_enabled: values.outreach_enabled,
      outreach_provider: values.outreach_provider,
      outreach_dry_run: values.outreach_dry_run,
      outreach_templates: formToTemplates(values),
      comment_discovery_enabled: false,
    }, values);
  }
  const { platform, platforms: selectedPlatforms } = resolvePlatformFields(platforms);

  return withStablePayloadDefaults({
    name: taskName,
    collection_mode: values.collection_mode,
    platform,
    platforms: selectedPlatforms,
    keywords: splitLines(values.keywordsText),
    input_urls: keywordDiscoveryInputUrls(values),
    country: values.country.trim() || null,
    category: values.category.trim() || null,
    discovery_limit: Number(values.discovery_limit),
    ...buildQualityFilterPayload(values),
    schedule_enabled: values.schedule_enabled,
    schedule_cron: values.schedule_enabled ? values.schedule_cron.trim() || null : null,
    email_enabled: values.email_enabled,
    email_recipients: values.email_enabled ? splitLines(values.email_recipientsText) : [],
    outreach_enabled: values.outreach_enabled,
    outreach_provider: values.outreach_provider,
    outreach_dry_run: values.outreach_dry_run,
    outreach_templates: formToTemplates(values),
    comment_discovery_enabled: values.comment_discovery_enabled,
  }, values);
}

export function taskToFormValues(task: CollectionTask): TaskFormValues {
  let competitorInputText = "";
  let competitorBrandText = "";
  let competitorWebsiteText = "";
  if (task.collection_mode === "competitor_product") {
    const rawKeywords = [...(task.keywords ?? [])];
    const rawUrls = [...(task.input_urls ?? [])];
    const productKeywords: string[] = [];
    for (const kw of rawKeywords) {
      if (kw.toLowerCase().startsWith("brand:")) {
        competitorBrandText = kw.split(":").slice(1).join(":").trim();
      } else {
        productKeywords.push(kw);
      }
    }
    const amazonUrls: string[] = [];
    for (const url of rawUrls) {
      if (/amazon\.[a-z.]+/i.test(url)) {
        amazonUrls.push(url);
      } else {
        competitorWebsiteText = url;
      }
    }
    competitorInputText = [...amazonUrls, ...productKeywords].join("\n");
  }

  const sourceMethod = taskSourceMethodForMode(task.collection_mode);
  const rawPlatforms = task.platforms?.length ? task.platforms : [task.platform || "instagram"];
  const platforms =
    sourceMethod === "keyword_discovery" && task.collection_mode !== "link_seed_discovery"
      ? rawPlatforms.filter((platform) => !isUrlOnlyPlatform(platform) || isKeywordSeedPlatform(platform))
      : rawPlatforms;
  const seedOnly = isSeedOnlyDiscoverySelection(platforms);

  return {
    stable_collection_mode: Boolean(task.run_checkpoint?.stable_collection_mode),
    sourceMethod: seedOnly ? "shopping_seed_auto" : sourceMethod,
    name: task.name,
    collection_mode:
      seedOnly
        ? "link_seed_discovery"
        : task.collection_mode === "comment_authors"
          ? "urls"
          : (task.collection_mode ?? "discovery"),
    comment_discovery_enabled: task.comment_discovery_enabled ?? true,
    platform: platforms.length === 1 ? platforms[0] : platforms.length > 1 ? "multi" : task.platform,
    platforms: platforms.length ? platforms : [...DEFAULT_PLATFORMS],
    keywordsText: (task.keywords ?? []).join("\n"),
    inputUrlsText: (task.input_urls ?? []).join("\n"),
    country: task.country ?? "",
    category: task.category ?? "",
    discovery_limit: String(task.discovery_limit ?? 100),
    min_engagement_rate: task.min_engagement_rate != null ? String(task.min_engagement_rate) : "",
    min_followers_count: task.min_followers_count != null ? String(task.min_followers_count) : "",
    max_followers_count: task.max_followers_count != null ? String(task.max_followers_count) : "",
    filterIncludeKeywordsText: (task.filter_include_keywords ?? []).join("\n"),
    filterExcludeKeywordsText: (task.filter_exclude_keywords ?? []).join("\n"),
    require_email: task.require_email ?? false,
    require_contact: task.require_contact ?? false,
    strict_quality_filter: task.strict_quality_filter ?? false,
    insert_qualified_only: task.insert_qualified_only ?? false,
    export_qualified_only: task.export_qualified_only ?? false,
    schedule_enabled: task.schedule_enabled,
    schedule_cron: task.schedule_cron ?? "",
    email_enabled: task.email_enabled,
    email_recipientsText: (task.email_recipients ?? []).join(", "),
    outreach_enabled: task.outreach_enabled ?? false,
    outreach_provider: task.outreach_provider ?? "mailchimp",
    outreach_dry_run: task.outreach_dry_run ?? true,
    ...templatesToForm(task.outreach_templates ?? {}),
    competitorInputText,
    competitorBrandText,
    competitorWebsiteText,
  };
}

export function getInitialForm(
  open: boolean,
  initialTask?: CollectionTask | null,
  defaultSourceMethod: TaskSourceMethod = "keyword_discovery",
): TaskFormValues {
  if (!open) return createEmptyTaskForm();
  if (initialTask) return taskToFormValues(initialTask);
  const base: TaskFormValues = {
    ...createEmptyTaskForm(),
    sourceMethod: defaultSourceMethod,
    collection_mode:
      defaultSourceMethod === "link_import"
        ? "link_import"
        : defaultSourceMethod === "shopping_seed_auto"
          ? "link_seed_discovery"
          : "discovery",
  };
  const template = loadSavedFormTemplate();
  const initial = template ? applyFormTemplate(base, template) : base;
  return defaultSourceMethod === "link_import" ? initial : withKeywordHighValueDefaults(initial);
}

export function discoverySourceFromForm(form: TaskFormValues): DiscoverySource {
  if (form.sourceMethod === "shopping_seed_auto" || form.collection_mode === "link_seed_discovery") {
    return "shopping_seed_auto";
  }
  if (isLinkImportTaskForm(form)) return "link_import";
  if (isSeedOnlyDiscoverySelection(form.platforms)) return "shopping_seed_auto";
  if (form.collection_mode === "discovery" && form.platforms.length > 1) return "multi_platform_auto";
  return "keyword_hashtag";
}

export function applyDiscoverySource(
  source: DiscoverySource,
  prev: TaskFormValues,
  platformCapabilities: PlatformCapability[],
): TaskFormValues {
  if (source === "link_import") {
    return {
      ...prev,
      stable_collection_mode: false,
      ...clearKeywordDiscoveryFields(),
      sourceMethod: "link_import",
      collection_mode: "link_import",
      platforms: [],
      platform: "instagram",
    };
  }
  if (source === "shopping_seed_auto") {
    return {
      ...prev,
      stable_collection_mode: false,
      ...KEYWORD_HIGH_VALUE_DEFAULTS,
      ...clearLinkImportFields(),
      sourceMethod: "shopping_seed_auto",
      collection_mode: "link_seed_discovery",
      ...resolvePlatformFields([...SEED_DISCOVERY_PLATFORMS]),
      comment_discovery_enabled: false,
    };
  }
  const configured = getMultiPlatformAutoPlatforms(platformCapabilities);
  if (source === "multi_platform_auto") {
    return withKeywordHighValueDefaults({
      ...prev,
      stable_collection_mode: false,
      ...clearLinkImportFields(),
      sourceMethod: "keyword_discovery",
      collection_mode: "discovery",
      ...resolvePlatformFields([...configured]),
    });
  }
  const platforms = prev.platforms.length
    ? filterKeywordSubmissionPlatforms(prev.platforms, platformCapabilities)
    : getKeywordDiscoveryDefaultPlatforms(platformCapabilities);
  return withKeywordHighValueDefaults({
    ...prev,
    stable_collection_mode: false,
    ...clearLinkImportFields(),
    sourceMethod: "keyword_discovery",
    collection_mode:
      prev.collection_mode === "link_import" ||
      prev.collection_mode === "competitor_product" ||
      prev.collection_mode === "link_seed_discovery"
        ? "discovery"
        : prev.collection_mode,
    ...resolvePlatformFields(platforms),
  });
}

export function suggestTaskName(form: TaskFormValues): string {
  if (isLinkImportTaskForm(form)) {
    const lines = splitLines(form.inputUrlsText);
    if (lines.length === 0) return "链接导入任务";
    if (lines.length === 1) {
      const preview = parseLinkImportPreview(form.inputUrlsText);
      const platform = Object.keys(preview.counts)[0];
      if (platform === "amazon") return "Amazon 商品发现";
      if (platform) return `${PLATFORM_LABELS[platform] ?? platform} 链接导入`;
    }
    return `链接导入 - ${lines.length} 条`;
  }
  if (form.collection_mode === "link_seed_discovery") {
    const topic =
      form.category.trim() || splitLines(form.keywordsText)[0]?.replace(/^#/, "") || "导购 seed";
    const seedLabels = form.platforms
      .filter((p) => (SEED_DISCOVERY_PLATFORMS as readonly string[]).includes(p))
      .map((p) => PLATFORM_LABELS[p] ?? p);
    const platformLabel =
      seedLabels.length === 0
        ? "导购 seed"
        : seedLabels.length === 1
          ? seedLabels[0]!
          : seedLabels.join("+");
    return `${topic} - ${platformLabel}`;
  }
  const keywords = splitLines(form.keywordsText);
  const topic = keywords[0]?.replace(/^#/, "") || "红人发现";
  const platformLabel =
    form.platforms.length === 1
      ? PLATFORM_LABELS[form.platforms[0]] ?? form.platforms[0]
      : form.platforms.length > 1
        ? "多平台"
        : "采集";
  return `${topic} - ${platformLabel}`;
}

export function advancedFilterSummary(form: TaskFormValues): string {
  const parts: string[] = [];
  if (form.category.trim()) parts.push(`类目 ${form.category.trim()}`);
  if (form.min_followers_count.trim()) parts.push(`最低粉丝 ${form.min_followers_count.trim()}`);
  if (form.max_followers_count.trim()) parts.push(`最高粉丝 ${form.max_followers_count.trim()}`);
  if (form.min_engagement_rate.trim()) parts.push(`互动率 ${form.min_engagement_rate.trim()}%`);
  if (form.filterIncludeKeywordsText.trim()) parts.push("偏好关键词");
  if (form.filterExcludeKeywordsText.trim()) parts.push("排除关键词");
  if (form.require_email) parts.push("要求邮箱");
  if (form.require_contact) parts.push("要求联系方式");
  if (form.insert_qualified_only) parts.push("仅入库达标");
  if (form.strict_quality_filter) parts.push("严格过滤");
  if (form.export_qualified_only) parts.push("仅导出达标");
  if (form.comment_discovery_enabled) parts.push("评论区发现");
  if (form.stable_collection_mode) parts.push("稳定采集模式");
  if (form.collection_mode !== "discovery" && !isLinkImportTaskForm(form)) {
    parts.push(COLLECTION_MODE_LABELS[form.collection_mode] ?? form.collection_mode);
  }
  return parts.length ? `已设置：${parts.join("、")}` : "使用默认筛选";
}

export function hasAdvancedSettings(form: TaskFormValues): boolean {
  return (
    Boolean(form.category.trim()) ||
    Boolean(form.min_followers_count.trim()) ||
    Boolean(form.max_followers_count.trim()) ||
    Boolean(form.min_engagement_rate.trim()) ||
    Boolean(form.filterIncludeKeywordsText.trim()) ||
    Boolean(form.filterExcludeKeywordsText.trim()) ||
    form.require_email ||
    form.require_contact ||
    form.strict_quality_filter ||
    form.insert_qualified_only ||
    form.export_qualified_only ||
    form.comment_discovery_enabled ||
    form.stable_collection_mode ||
    form.collection_mode !== "discovery" ||
    form.schedule_enabled ||
    form.email_enabled ||
    form.outreach_enabled
  );
}
