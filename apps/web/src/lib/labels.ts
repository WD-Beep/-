import type { CollectionMode, CollectionTaskStatus, EmailLogStatus, TaskSourceMethod } from "@/lib/api";

/** 侧边栏导航 */
export const NAV_ITEMS = [
  { href: "/", label: "数据概览" },
  { href: "/influencers", label: "红人库" },
  { href: "/collection-tasks", label: "采集任务" },
  { href: "/link-import", label: "链接导入" },
  { href: "/message-templates", label: "话术库" },
  { href: "/email-logs", label: "邮件日志" },
  { href: "/settings", label: "系统设置" },
] as const;

export const PLATFORM_LABELS: Record<string, string> = {
  instagram: "Instagram",
  tiktok: "TikTok",
  youtube: "YouTube",
  facebook: "Facebook",
  general: "通用",
  pinterest: "Pinterest",
  ltk: "LTK",
  shopmy: "ShopMy",
  multi: "多平台",
  amazon: "Amazon",
};

export const COUNTRY_OPTIONS = [
  { value: "", label: "All countries / No limit" },
  { value: "US", label: "United States" },
  { value: "DE", label: "Germany" },
  { value: "GB", label: "United Kingdom" },
  { value: "AU", label: "Australia" },
  { value: "CA", label: "Canada" },
] as const;

export const PLATFORM_CAPABILITY_STATUS_LABELS: Record<string, string> = {
  supported: "API Direct 已支持",
  not_configured: "API Direct 未配置",
  not_available: "API Direct 未接入",
  url_only: "链接导入 / 外部 seed 发现",
};

export const PLATFORM_DISCOVERY_CATEGORY_LABELS: Record<string, string> = {
  search_discovery: "可搜索发现",
  external_seed_discovery: "外部 seed 发现",
  external_link_discovery: "外链发现",
  link_completion: "链接补全",
};

export const PLATFORM_DISCOVERY_CATEGORY_HINTS: Record<string, string> = {
  search_discovery:
    "支持关键词、话题/标签、竞品商品词扩展，以及从帖子/视频/评论/主页发现红人。",
  external_seed_discovery:
    "支持链接导入、公共网页/商品词 seed 自动发现，以及从已采集社媒主页反向外链扩展；站内关键词直采尚未稳定接入。",
  external_link_discovery:
    "可从 Instagram/TikTok/YouTube/Facebook 的 bio、视频描述、主页外链，或已采集红人的 other_social_links 中识别。",
  link_completion:
    "主要通过链接导入定向补全资料，也可从其他社媒外链反向发现；不保证粉丝/互动/联系方式完整。",
};

/** 支持普通关键词直采或导购 seed 自动发现快捷入口的平台 */
export const KEYWORD_SEED_DISCOVERY_PLATFORMS = ["pinterest", "ltk", "shopmy"] as const;
export const KEYWORD_DISCOVERY_PLATFORMS = [
  "instagram",
  "youtube",
  "tiktok",
  "facebook",
  ...KEYWORD_SEED_DISCOVERY_PLATFORMS,
] as const;

/** 链接导入模式支持的平台（含支持链接导入的导购/灵感平台） */
export const LINK_IMPORT_PLATFORMS = [
  "instagram",
  "youtube",
  "tiktok",
  "facebook",
  "pinterest",
  "ltk",
  "shopmy",
] as const;

/** 导购/灵感平台：支持链接导入、外部 seed 发现、反向外链扩展；不代表完整站内关键词直采 */
export const URL_ONLY_PLATFORMS = ["pinterest", "ltk", "shopmy"] as const;

export const URL_ONLY_PLATFORM_VALIDATION_MSG =
  "Pinterest / LTK / ShopMy 普通关键词直采尚未接入；请使用「导购 seed 自动发现」或「链接导入」。";

export const NO_CONFIGURED_KEYWORD_PLATFORMS_MSG =
  "没有已配置的关键词采集平台，请先完成 Instagram / YouTube / TikTok / Facebook 的配置";

/** 已验证可主动关键词采集的平台说明 */
export const VERIFIED_KEYWORD_PLATFORM_HINT = "支持关键词发现和链接导入";

/** 链接补全 / 外链发现平台说明 */
export const LINK_ONLY_PENDING_KEYWORD_HINT =
  "支持链接导入、外部 seed 自动发现和反向外链扩展；站内关键词直采暂未接入";

/** 链接补全平台卡片说明（分行展示） */
export const LINK_ONLY_PLATFORM_CARD_LINES = [
  "支持手动链接导入，用于定向录入和资料补全",
  "支持 Amazon / 商品词驱动的公共网页 seed 自动发现",
  "支持从 Instagram / YouTube / TikTok / Facebook 红人主页反向扩展外链",
  "站内关键词直采尚未稳定接入；低信息量 seed 会标记为待补全",
] as const;

/** Amazon 链接导入说明 */
export const AMAZON_LINK_ONLY_HINT =
  "Amazon 商品链接用于竞品商品发现线索；主要通过链接导入，不是红人主页平台";

/** 链接导入模式使用说明 */
export const LINK_IMPORT_USAGE_LINES = [
  "无需手动选择平台，系统会根据 URL 自动识别",
  "想采集某个平台，请粘贴该平台主页/频道/创作者/Pin/商品链接",
  "LTK / ShopMy / Pinterest 也可通过导购 seed 自动发现或已采集红人反向外链扩展获得入口",
  "链接导入用于定向补全资料，不保证能获取完整粉丝、互动和联系方式",
  "Amazon 是商品链接线索，仅用于竞品商品发现，不要与红人主页链接混在同一任务",
] as const;

/** 链接导入 URL 示例（可尝试，采集成功率仍在验证中） */
export const LINK_IMPORT_URL_EXAMPLES: { platform: string; url: string }[] = [
  { platform: "Pinterest", url: "https://www.pinterest.com/example_user/" },
  { platform: "LTK", url: "https://www.shopltk.com/explore/example_user" },
  { platform: "ShopMy", url: "https://shopmy.us/example_user" },
  { platform: "Instagram", url: "https://www.instagram.com/creator/" },
];

/** 导购 seed 自动发现支持的平台 */
export const SEED_DISCOVERY_PLATFORMS = ["ltk", "shopmy", "pinterest"] as const;

export const COLLECTION_MODE_LABELS: Record<CollectionMode, string> = {
  discovery: "自动发现",
  keyword: "关键词采集",
  category_discovery: "类目采集",
  clustering: "相似账号",
  urls: "链接采集",
  mixed: "混合采集",
  comment_authors: "链接采集",
  competitor_product: "竞品商品发现",
  link_import: "链接导入",
  link_seed_discovery: "导购 seed 自动发现",
};

export const TASK_SOURCE_METHOD_OPTIONS: {
  value: TaskSourceMethod;
  label: string;
  hint: string;
}[] = [
  {
    value: "keyword_discovery",
    label: "关键词发现",
    hint: "按关键词、类目、链接种子或多平台自动发现红人",
  },
  {
    value: "link_import",
    label: "链接导入",
    hint: "粘贴红人主页、导购平台或 Amazon 商品链接；用于定向补全资料，也可配合外链发现",
  },
  {
    value: "shopping_seed_auto",
    label: "导购 seed 自动发现",
    hint: "输入主题 / 品牌 / 商品词 / ASIN / Amazon 线索，先找 LTK / ShopMy / Pinterest seed 链接，再批量采集补全",
  },
];

export function taskSourceMethodForMode(mode: CollectionMode | string): TaskSourceMethod {
  if (mode === "link_seed_discovery") return "shopping_seed_auto";
  return mode === "link_import" ? "link_import" : "keyword_discovery";
}

export function taskSourceLabelForMode(mode: CollectionMode | string): string {
  if (mode === "link_import") return "链接导入";
  if (mode === "competitor_product") return "竞品商品发现";
  const sourceMethod = taskSourceMethodForMode(mode);
  return TASK_SOURCE_METHOD_OPTIONS.find((item) => item.value === sourceMethod)?.label ?? "关键词发现";
}

export function taskModeBadgeLabel(mode: CollectionMode | string): string {
  return COLLECTION_MODE_LABELS[mode as CollectionMode] ?? String(mode);
}

export const SOURCE_DISCOVERY_LABELS: Record<string, string> = {
  comment_author: "评论区",
  post_author: "帖子作者",
  url_profile: "链接主页",
  competitor_product: "竞品商品发现",
};

export const CANDIDATE_SOURCE_TYPE_LABELS: Record<string, string> = {
  keyword_post_author: "关键词帖子作者",
  hashtag_post_author: "Hashtag 帖子作者",
  comment_author: "评论区用户",
  input_profile: "输入主页",
  input_post: "输入帖子",
  input_reel: "输入 Reel",
  related_profile: "相似账号",
  competitor_product_post_author: "竞品商品帖子作者",
  keyword_video_author: "关键词视频作者",
  amazon_product_page_video: "Amazon 商品页视频作者",
  keyword_channel: "关键词频道",
  keyword_video_channel: "关键词视频频道",
  input_url: "URL 导入",
  link_import: "链接导入",
  unknown: "未知来源",
};

export const CANDIDATE_STATUS_LABELS: Record<
  string,
  { label: string; variant: "default" | "secondary" | "success" | "warning" | "destructive" }
> = {
  discovered: { label: "已发现", variant: "secondary" },
  pending_profile: { label: "待补采", variant: "warning" },
  profile_fetched: { label: "已补采", variant: "default" },
  profile_failed: { label: "补采失败", variant: "destructive" },
  filtered_out: { label: "已过滤", variant: "warning" },
  not_inserted: { label: "未入库", variant: "warning" },
  inserted: { label: "已入库", variant: "success" },
  duplicate: { label: "重复账号", variant: "secondary" },
};

export const CANDIDATE_FAILURE_LABELS: Record<string, string> = {
  below_min_followers: "粉丝未达标",
  below_min_engagement_rate: "互动率未达标",
  above_max_followers: "粉丝超过上限",
  missing_engagement_rate: "互动率缺失",
  missing_email: "未发现邮箱",
  missing_contact: "未发现联系方式",
  excluded_keyword: "命中排除词",
  profile_fetch_failed: "主页补采失败",
  private_account: "私密账号",
  disabled_or_deleted: "账号不存在",
  invalid_username: "无效用户名",
  missing_profile_detail: "主页数据缺失",
  low_value_seed: "资料不足（seed）",
  no_same_product_match: "未命中同款商品",
  amazon_product_page_strong_lead: "Amazon 商品页强线索",
  duplicate: "重复",
  api_failed: "API 失败",
  unknown: "未知原因",
};

/** 主模式选项（评论区发现已并入统一流水线开关） */
export const COLLECTION_MODE_OPTIONS: {
  value: CollectionMode;
  label: string;
  hint: string;
}[] = [
  {
    value: "keyword",
    label: "关键词采集",
    hint: "手动输入关键词 → 扩展 hashtag / 平台搜索 → 发现帖子作者与链接",
  },
  {
    value: "category_discovery",
    label: "类目采集",
    hint: "填写类目后系统自动扩展平台关键词与链接种子，可补充偏好关键词",
  },
  {
    value: "link_seed_discovery",
    label: "导购 seed 自动发现",
    hint: "输入 Amazon URL / ASIN / 品牌关键词，自动发现 LTK / ShopMy / Pinterest 导购主页，再补全到 Instagram / TikTok / YouTube / Facebook",
  },
  {
    value: "discovery",
    label: "自动发现（Hashtag）",
    hint: "与关键词采集相同，适合直接输入 hashtag 或关键词",
  },
  {
    value: "urls",
    label: "链接导入",
    hint: "主页 / 帖子 / Reel 链接或用户名：自动识别并抓取评论区用户",
  },
  {
    value: "mixed",
    label: "混合采集",
    hint: "关键词与链接合并去重，统一走评论区增强与主页补采",
  },
  {
    value: "clustering",
    label: "相似账号（可选）",
    hint: "从种子主页扩展相似账号，并可对种子近期帖子抓评论",
  },
  {
    value: "competitor_product",
    label: "竞品商品发现",
    hint: "输入 Amazon 链接/ASIN/关键词，搜索 Instagram 上疑似推广该商品或竞品的红人",
  },
];

export const TASK_STATUS_LABELS: Record<
  CollectionTaskStatus,
  { label: string; variant: "default" | "secondary" | "success" | "warning" | "destructive" }
> = {
  pending: { label: "待运行", variant: "warning" },
  queued: { label: "排队中", variant: "warning" },
  running: { label: "运行中", variant: "default" },
  completed: { label: "成功", variant: "success" },
  completed_with_results: { label: "有结果", variant: "success" },
  completed_no_results: { label: "无结果", variant: "warning" },
  partial_failed: { label: "部分成功", variant: "warning" },
  failed: { label: "失败", variant: "destructive" },
  paused: { label: "已暂停", variant: "secondary" },
  draft: { label: "草稿", variant: "secondary" },
};

export const EMAIL_LOG_STATUS_LABELS: Record<
  EmailLogStatus,
  { label: string; variant: "default" | "secondary" | "success" | "warning" | "destructive" }
> = {
  pending: { label: "待发送", variant: "warning" },
  sent: { label: "已发送", variant: "success" },
  failed: { label: "失败", variant: "destructive" },
};

export const OUTREACH_PROVIDER_LABELS: Record<string, string> = {
  smtp: "SMTP",
  mailchimp: "Mailchimp",
};

export const PROFILE_FAILURE_REASON_LABELS: Record<string, string> = {
  profile_not_found: "主页不存在",
  private_account: "私密账号",
  missing_profile_detail: "主页详情缺失",
  scraper_blocked: "采集被拦截",
  invalid_username: "无效用户名",
  excluded_keyword: "命中排除词",
  below_min_followers: "粉丝未达 3 万",
  invalid_profile: "无效主页",
};

export function platformLabel(platform: string): string {
  return PLATFORM_LABELS[platform] ?? platform;
}

const SEED_PLATFORMS = new Set(["ltk", "shopmy", "pinterest"]);

export type LinkSeedEnrichmentMeta = {
  link_seed_platform?: string;
  link_seed_profile_url?: string;
  link_seed_username?: string;
  primary_platform?: string;
  enriched_platform?: string;
  enrichment_attempted?: boolean;
  instagram_detail_fetched?: boolean;
  platform_detail_fetched?: boolean;
  social_profiles_found?: number;
  contact_found?: boolean;
  is_valuable?: boolean;
  enrichment_notes?: string[];
  search_keywords?: string[];
  enrichment_candidates?: Array<{
    platform?: string;
    profile_url?: string | null;
    status?: string;
    followers_count?: number | null;
    has_email?: boolean;
    score?: number;
    error?: string;
  }>;
  selected_reason?: string;
};

export function candidateLinkSeedMeta(candidate: {
  source_meta?: Record<string, unknown> | null;
}): LinkSeedEnrichmentMeta | null {
  const enrichment = candidate.source_meta?.link_seed_enrichment;
  if (!enrichment || typeof enrichment !== "object") return null;
  return enrichment as LinkSeedEnrichmentMeta;
}

export function candidateSeedPlatformLabel(candidate: {
  platform: string;
  source_meta?: Record<string, unknown> | null;
  source_input_url?: string | null;
}): string | null {
  const enrichment = candidateLinkSeedMeta(candidate);
  if (enrichment?.link_seed_platform) return platformLabel(enrichment.link_seed_platform);
  const plat = candidate.platform?.toLowerCase();
  if (plat && SEED_PLATFORMS.has(plat)) return platformLabel(plat);
  const url = (candidate.source_input_url || "").toLowerCase();
  if (url.includes("shopltk.com")) return platformLabel("ltk");
  if (url.includes("shopmy")) return platformLabel("shopmy");
  if (url.includes("pinterest.com")) return platformLabel("pinterest");
  return null;
}

export function candidateSeedEnrichmentStatus(candidate: {
  platform: string;
  source_meta?: Record<string, unknown> | null;
  source_input_url?: string | null;
  failure_reason?: string | null;
}): string | null {
  const seedLabel = candidateSeedPlatformLabel(candidate);
  if (!seedLabel) return null;
  if (candidate.failure_reason === "low_value_seed") {
    return `未补全（${seedLabel} seed 资料不足）`;
  }
  const enrichment = candidateLinkSeedMeta(candidate);
  const meta = candidate.source_meta ?? {};
  const selectedReason =
    enrichment?.selected_reason ??
    (typeof meta.selected_reason === "string" ? meta.selected_reason : null);
  const seedKey = enrichment?.link_seed_platform?.toLowerCase() || "";
  const finalKey =
    candidate.platform?.toLowerCase() ||
    enrichment?.primary_platform?.toLowerCase() ||
    enrichment?.enriched_platform?.toLowerCase() ||
    "";
  const detailFetched =
    enrichment?.platform_detail_fetched || enrichment?.instagram_detail_fetched;

  const parts: string[] = [];
  if (enrichment?.enrichment_attempted || (finalKey && seedKey)) {
    if (finalKey && seedKey && finalKey !== seedKey) {
      const finalLabel = platformLabel(finalKey);
      if (detailFetched) {
        parts.push(`已通过 ${seedLabel} 补全为 ${finalLabel}，并完成详情采集`);
      } else {
        parts.push(`已通过 ${seedLabel} seed 补全为 ${finalLabel}`);
      }
    } else if (finalKey === seedKey) {
      parts.push(`${seedLabel} seed（未找到其他社媒主页）`);
    }
  }
  if (selectedReason) parts.push(selectedReason);
  return parts.length ? parts.join("；") : null;
}

export function candidateEnrichmentCandidatesSummary(candidate: {
  source_meta?: Record<string, unknown> | null;
}): string | null {
  const enrichment = candidateLinkSeedMeta(candidate);
  const meta = candidate.source_meta ?? {};
  const candidates =
    enrichment?.enrichment_candidates ??
    (Array.isArray(meta.enrichment_candidates) ? meta.enrichment_candidates : null);
  if (!candidates || candidates.length === 0) return null;
  return candidates
    .map((row) => {
      const plat = platformLabel(String(row.platform ?? ""));
      const status = row.status ?? "unknown";
      const err = row.error ? ` (${row.error})` : "";
      return `${plat}:${status}${err}`;
    })
    .join(" · ");
}

export function candidateProfileSnapshotSummary(candidate: {
  platform: string;
  source_meta?: Record<string, unknown> | null;
}): string | null {
  const snap = candidate.source_meta?.profile_snapshot;
  if (!snap || typeof snap !== "object") return null;
  const record = snap as Record<string, unknown>;
  const parts: string[] = [];
  if (record.display_name) parts.push(String(record.display_name));
  const plat = String(record.platform ?? candidate.platform ?? "");
  if (record.followers_count != null) {
    parts.push(`${followersAudienceLabel(plat)} ${String(record.followers_count)}`);
  }
  if (record.bio) parts.push(String(record.bio).slice(0, 80));
  return parts.length ? parts.join(" · ") : null;
}

/** 粉丝/订阅者展示文案：YouTube 用订阅者，其余平台保持粉丝。 */
export function followersAudienceLabel(platform: string): string {
  return platform === "youtube" ? "订阅者" : "粉丝";
}

/** 竞品商品发现默认后续发现平台（与后端 COMPETITOR_DISCOVERY_PLATFORMS 一致） */
export const COMPETITOR_DISCOVERY_PLATFORMS = ["instagram", "youtube", "tiktok", "facebook"] as const;

export function taskPlatforms(task: {
  platform: string;
  platforms?: string[];
  collection_mode?: CollectionMode | string;
  run_checkpoint?: Record<string, unknown>;
}): string[] {
  if (task.collection_mode === "competitor_product") {
    const discovery = task.run_checkpoint?.competitor_discovery_platforms;
    if (Array.isArray(discovery) && discovery.length) {
      return discovery.filter((item): item is string => typeof item === "string");
    }
    if (task.platforms?.length) return task.platforms;
    return [...COMPETITOR_DISCOVERY_PLATFORMS];
  }
  const checkpointPlatforms = task.run_checkpoint?.link_import_platforms;
  if (task.collection_mode === "link_import" && Array.isArray(checkpointPlatforms) && checkpointPlatforms.length) {
    return checkpointPlatforms.filter((item): item is string => typeof item === "string");
  }
  if (task.platforms?.length) return task.platforms;
  if (task.platform === "multi") return [];
  if (task.platform) return [task.platform];
  return [];
}

export function taskPlatformGroupLabel(mode: CollectionMode | string): string | null {
  if (mode === "link_import") return "链接来源平台";
  if (mode === "competitor_product") return "后续发现平台";
  if (
    mode === "keyword" ||
    mode === "discovery" ||
    mode === "category_discovery" ||
    mode === "mixed" ||
    mode === "urls" ||
    mode === "clustering" ||
    mode === "comment_authors"
  ) {
    return "采集平台";
  }
  return null;
}

export function taskProductClueGroupLabel(mode: CollectionMode | string): string | null {
  return mode === "competitor_product" ? "商品线索" : null;
}

export function taskDisplayPlatforms(task: {
  platform: string;
  platforms?: string[];
  collection_mode?: CollectionMode | string;
  run_checkpoint?: Record<string, unknown>;
}): string[] {
  const mode = task.collection_mode;
  const platforms = taskPlatforms(task);
  if (mode === "competitor_product") {
    return platforms.filter((name) => name !== "amazon");
  }
  if (mode === "link_import") {
    return platforms.filter((name) => name !== "amazon" && name !== "multi");
  }
  if (task.platform === "multi" && task.platforms?.length) {
    return task.platforms;
  }
  return platforms.filter((name) => name !== "multi");
}

export function taskPlatformSummaryLabel(task: {
  platform: string;
  platforms?: string[];
  collection_mode?: CollectionMode | string;
  run_checkpoint?: Record<string, unknown>;
}): string | null {
  const platforms = taskDisplayPlatforms(task);
  if (platforms.length === 0) return null;
  if (platforms.length === 1) return platformLabel(platforms[0]!);
  return `多平台 · ${platforms.map(platformLabel).join(" / ")}`;
}

export type AmazonProductSeed = {
  url?: string;
  normalized_url?: string;
  asin?: string;
  marketplace?: string;
};

export function extractAmazonProductSeeds(
  checkpoint: Record<string, unknown> | undefined,
): AmazonProductSeed[] {
  const raw = checkpoint?.amazon_product_seeds;
  if (!Array.isArray(raw)) return [];
  return raw.filter(
    (item): item is AmazonProductSeed => typeof item === "object" && item !== null,
  );
}

export function formatAmazonProductClueLine(seed: AmazonProductSeed): string {
  const parts: string[] = [];
  if (seed.asin) parts.push(`ASIN ${seed.asin}`);
  if (seed.normalized_url) parts.push(seed.normalized_url);
  if (seed.url && seed.url !== seed.normalized_url) parts.push(`原始 ${seed.url}`);
  return parts.join(" · ") || "-";
}

export function formatTaskKeywordsOrLinks(task: {
  platform: string;
  platforms?: string[];
  collection_mode: CollectionMode | string;
  keywords?: string[];
  input_urls?: string[];
  run_checkpoint?: Record<string, unknown>;
}): string {
  const mode = task.collection_mode;
  const keywords = task.keywords ?? [];
  const urls = task.input_urls ?? [];

  if (mode === "link_import") {
    const summary = taskPlatformSummaryLabel(task);
    const count = urls.length;
    return summary ? `${count} 条链接 · ${summary}` : `${count} 条链接`;
  }

  if (mode === "competitor_product") {
    const seeds = extractAmazonProductSeeds(task.run_checkpoint);
    if (seeds.length) {
      return seeds.map(formatAmazonProductClueLine).join("；");
    }
    if (keywords.length) return keywords.join(", ");
    if (urls.length) return urls.join(", ");
    return "-";
  }

  if (keywords.length) return keywords.join(", ");
  if (urls.length) return `${urls.length} 条链接种子`;
  return "-";
}

export function outreachLabel(provider: string): string {
  return OUTREACH_PROVIDER_LABELS[provider] ?? provider;
}

export function aiModeLabel(mode: string): string {
  if (mode === "deepseek") return "DeepSeek";
  if (mode === "openai") return "OpenAI";
  if (mode === "kimi") return "Kimi AI（兼容）";
  if (mode === "heuristic") return "规则评分（未配置 AI）";
  if (mode === "heuristic_fallback") return "规则评分（AI 失败降级）";
  return mode;
}

const ERROR_TRANSLATIONS: Array<[RegExp, string]> = [
  [/Timed out connecting to smtp\.gmail\.com|无法连接邮件服务器/i, "连不上邮件服务器（Gmail SMTP 超时）。本机可连通 smtp.qq.com / smtp.exmail.qq.com，请把 .env 的 SMTP_HOST 改成可用邮箱后再发。"],
  [
    /429\s*Too Many Requests|Client error '429/i,
    "网页抓取被限流（如 Amazon 429）。请稍后重试、换商品详情页链接，或手动填写摘要/结构化知识后保存再生成话术。",
  ],
  [
    /insufficient balance|exceeded_current_quota|quota|account suspended|额度|余额不足|充值/i,
    "AI 账户余额不足或额度受限，请充值 DeepSeek/API 账户或更换可用密钥后重试。",
  ],
  [/OpenAI API Key 无效或已过期/i, "DeepSeek API Key 无效或已过期，请检查 OPENAI_API_KEY（当前对接 DeepSeek）。"],
  [/无法连接 OpenAI API/i, "无法连接 DeepSeek API，请检查 OPENAI_API_BASE 与网络。"],
  [/OpenAI API 错误/i, "DeepSeek API 错误，请检查密钥、模型与账户状态。"],
  [/OpenAI 模型不可用/i, "DeepSeek 模型不可用，请检查 OPENAI_MODEL 环境变量"],
  [/OPENAI_API_KEY/i, "未配置 AI API Key，请在 .env 中设置 OPENAI_API_KEY 与 OPENAI_MODEL（当前对接 DeepSeek）后重启后端"],
  [/OPENAI_MODEL/i, "AI 模型不可用，请检查 OPENAI_MODEL 环境变量"],
  [/SMTP 认证失败/i, "SMTP 认证失败：请在腾讯企业邮箱后台生成「客户端专用密码」，更新 .env 的 SMTP_PASSWORD 后重启后端"],
  [/535.*authentication failed/i, "SMTP 认证失败：请使用企业邮箱「客户端专用密码」，不要用网页登录密码"],
  [/API_DIRECT_API_KEY/i, "未配置 API Direct 密钥（API_DIRECT_API_KEY）"],
  [/Apify 采集失败/i, "Instagram 采集 API 失败"],
  [/APIFY_TOKEN/i, "未配置 Apify Token（APIFY_TOKEN）"],
  [/APIFY_INSTAGRAM/i, "未配置 Instagram Apify Actor"],
  [/评论发现/i, "评论区 API 步骤失败"],
  [/Hashtag #/i, "Hashtag 采集失败"],
  [/not configured/i, "服务未配置"],
  [/Discovery mode requires hashtags or keywords/i, "自动发现模式需填写关键词"],
];

export function translateErrorMessage(message: string | null | undefined): string {
  if (!message) return "";
  for (const [pattern, replacement] of ERROR_TRANSLATIONS) {
    if (pattern.test(message)) return replacement;
  }
  return message;
}

export function translateBackendMessage(message: string | null | undefined): string {
  if (!message) return "";
  return translateErrorMessage(message);
}

export function healthStatusLabel(status: string): string {
  if (status === "ok") return "正常";
  return status;
}

export function collectorModeLabel(mode: string): string {
  if (mode === "apify") return "Apify 真实采集";
  if (mode === "mock") return "Mock（已禁用）";
  return mode;
}

export const LEAD_STATUS_LABELS: Record<
  string,
  { label: string; variant: "default" | "secondary" | "success" | "warning" | "destructive" }
> = {
  new: { label: "新线索", variant: "secondary" },
  to_contact: { label: "待联系", variant: "warning" },
  contacted: { label: "已联系", variant: "default" },
  replied: { label: "已回复", variant: "default" },
  interested: { label: "有意向", variant: "success" },
  quoted: { label: "已报价", variant: "success" },
  cooperating: { label: "合作中", variant: "success" },
  cooperated: { label: "已合作", variant: "success" },
  invalid: { label: "无效", variant: "destructive" },
  blacklisted: { label: "黑名单", variant: "destructive" },
  negotiating: { label: "洽谈中", variant: "default" },
  collaborated: { label: "已合作", variant: "success" },
  rejected: { label: "已拒绝", variant: "destructive" },
};

export const FOLLOWUP_ACTION_LABELS: Record<string, string> = {
  note: "备注",
  email_sent: "发送邮件",
  dm_sent: "发送 DM",
  replied: "收到回复",
  status_changed: "状态变更",
  quote_sent: "发送报价",
  cooperation_started: "开始合作",
  cooperation_done: "合作完成",
  invalid_marked: "标记无效",
  blacklisted: "加入黑名单",
};

export const CONTACT_CHANNEL_LABELS: Record<string, string> = {
  email: "邮件",
  instagram_dm: "Instagram DM",
  whatsapp: "WhatsApp",
  website_form: "官网表单",
  other: "其他",
};

export function leadStatusLabel(status: string | null | undefined): string {
  if (!status) return "新线索";
  return LEAD_STATUS_LABELS[status]?.label ?? status;
}

export function leadStatusVariant(
  status: string | null | undefined,
): "default" | "secondary" | "success" | "warning" | "destructive" {
  if (!status) return "secondary";
  return LEAD_STATUS_LABELS[status]?.variant ?? "secondary";
}

export const EMAIL_SOURCE_LABELS: Record<string, string> = {
  bio: "Instagram 简介",
  instagram_bio: "Instagram 简介",
  business_email: "商务邮箱",
  business_profile: "商务主页",
  public_email: "公开邮箱",
  website_contact: "官网联系页",
  linktree: "Linktree",
  beacons: "Beacons",
  stan_store: "Stan Store",
  carrd: "Carrd",
  website: "官网",
  other_page: "外链页面",
  public_profile: "公开主页",
  manual: "人工录入",
};

export const CONTACT_CREDIBILITY_LABELS: Record<string, string> = {
  high: "高",
  medium: "中",
  low: "低",
  unknown: "未知",
};

export const CONTACT_FETCH_STATUS_LABELS: Record<string, string> = {
  not_started: "未开始",
  success: "成功",
  partial_failed: "部分失败",
  failed: "失败",
};

export function emailSourceLabel(source: string | null | undefined): string {
  if (!source) return "-";
  return EMAIL_SOURCE_LABELS[source] ?? source;
}

export function contactCredibilityLabel(level: string | null | undefined): string {
  if (!level) return "未知";
  return CONTACT_CREDIBILITY_LABELS[level] ?? level;
}

export const MESSAGE_TEMPLATE_SCENARIO_OPTIONS = [
  { value: "first_contact", label: "首次联系" },
  { value: "quote", label: "报价沟通" },
  { value: "follow_up_replied", label: "已回复跟进" },
  { value: "follow_up_no_reply", label: "未回复二次跟进" },
  { value: "sample_shipping", label: "样品寄送" },
  { value: "collaboration_confirm", label: "合作确认" },
  { value: "reject", label: "拒绝/暂不合作" },
  { value: "after_sales", label: "售后维护" },
  { value: "custom", label: "自定义场景" },
] as const;

export const MESSAGE_TEMPLATE_SCENARIO_LABELS: Record<string, string> = Object.fromEntries(
  MESSAGE_TEMPLATE_SCENARIO_OPTIONS.map((item) => [item.value, item.label]),
);

export const MESSAGE_TEMPLATE_LANGUAGE_OPTIONS = [
  { value: "zh", label: "中文" },
  { value: "en", label: "英文" },
  { value: "other", label: "其他" },
] as const;

export const MESSAGE_TEMPLATE_LANGUAGE_LABELS: Record<string, string> = Object.fromEntries(
  MESSAGE_TEMPLATE_LANGUAGE_OPTIONS.map((item) => [item.value, item.label]),
);

export const MESSAGE_TEMPLATE_PLATFORM_OPTIONS = [
  { value: "", label: "不限" },
  { value: "instagram", label: "Instagram" },
  { value: "tiktok", label: "TikTok" },
  { value: "youtube", label: "YouTube" },
  { value: "facebook", label: "Facebook" },
  { value: "general", label: "通用" },
] as const;

export function messageTemplateScenarioLabel(value: string | null | undefined): string {
  if (!value) return "-";
  return MESSAGE_TEMPLATE_SCENARIO_LABELS[value] ?? value;
}

export function messageTemplateLanguageLabel(value: string | null | undefined): string {
  if (!value) return "-";
  return MESSAGE_TEMPLATE_LANGUAGE_LABELS[value] ?? value;
}
