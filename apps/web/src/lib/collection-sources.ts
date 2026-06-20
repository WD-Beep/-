import type { PlatformCapabilitiesResponse, PlatformCapability } from "./api.ts";
import { PLATFORM_LABELS, URL_ONLY_PLATFORMS } from "./labels.ts";

export function formatCollectionSourceSummary(
  meta: Pick<
    PlatformCapabilitiesResponse,
    | "instagram_data_provider"
    | "youtube_data_provider"
    | "tiktok_data_provider"
    | "facebook_data_provider"
    | "apify_configured"
    | "api_direct_configured"
  >,
): string {
  const ig = meta.instagram_data_provider;
  const yt = meta.youtube_data_provider;
  const tt = meta.tiktok_data_provider ?? "apify";
  const fb = meta.facebook_data_provider ?? "apify";
  const apifyNote = meta.apify_configured ? "" : "（Apify 未配置密钥）";
  return (
    `Instagram 默认 ${ig}；YouTube 默认 ${yt}；TikTok 默认 ${tt}；` +
    `Facebook 默认 ${fb}${apifyNote}`
  );
}

export function formatPlatformCapabilityHint(cap: PlatformCapability | undefined, fallback = ""): string {
  if (!cap) return fallback;
  return cap.message || fallback;
}

export type LinkImportPreview = {
  counts: Record<string, number>;
  invalidCount: number;
  invalidLines: string[];
  validCount: number;
  hasAmazon: boolean;
  hasProfiles: boolean;
  mixedAmazonAndProfiles: boolean;
  recognizedLines: string[];
  unrecognizedLines: string[];
};

const AMAZON_RE = /amazon\.[a-z.]+/i;
const HANDLE_RE = /^[A-Za-z0-9_.-]{2,80}$/;
const PINTEREST_PIN_ID_RE = /^[A-Za-z0-9_-]{1,64}$/;
const PINTEREST_RESERVED = new Set([
  "about",
  "business",
  "categories",
  "ideas",
  "login",
  "pin",
  "privacy",
  "search",
  "settings",
  "today",
]);
const SHOPMY_RESERVED = new Set(["collections", "discover", "explore", "login", "products", "shop", "stores"]);

const PLATFORM_DETECTORS: { platform: string; pattern: RegExp; validate?: RegExp }[] = [
  { platform: "instagram", pattern: /instagram\.com/i },
  {
    platform: "youtube",
    pattern: /(youtube\.com|youtu\.be)/i,
    validate: /youtube\.com\/(?:channel\/UC[\w-]{10,}|@[\w.-]+)|youtu\.be\//i,
  },
  {
    platform: "tiktok",
    pattern: /tiktok\.com/i,
    validate: /tiktok\.com\/@[A-Za-z0-9_.-]{2,80}/i,
  },
  { platform: "facebook", pattern: /(facebook\.com|fb\.com|fb\.me)/i },
];

const LINK_RECOGNITION_LABELS: Record<string, string> = {
  instagram: "Instagram 主页链接",
  youtube: "YouTube 频道链接",
  tiktok: "TikTok 主页链接",
  facebook: "Facebook 主页/Page 链接",
  pinterest: "Pinterest 主页/Pin 链接",
  ltk: "LTK 创作者链接（/explore/{username}）",
  shopmy: "ShopMy 创作者链接（/{username}）",
  amazon: "Amazon 商品链接",
};

const AMAZON_ASIN_RE = /\/(?:dp|gp\/product|product)\/([A-Z0-9]{10})/i;

function recognitionLabel(platform: string, line: string): string {
  const base = LINK_RECOGNITION_LABELS[platform] ?? platform;
  if (platform !== "amazon") return base;
  const normalized = normalizeUrlLine(line);
  const match = AMAZON_ASIN_RE.exec(normalized);
  return match ? `${base}（ASIN ${match[1].toUpperCase()}）` : base;
}

const PREVIEW_PLATFORM_LABELS: Record<string, string> = {
  instagram: "Instagram",
  youtube: "YouTube",
  tiktok: "TikTok",
  facebook: "Facebook",
  pinterest: "Pinterest",
  ltk: "LTK",
  shopmy: "ShopMy",
  amazon: "Amazon 商品",
};

function normalizeUrlLine(raw: string): string {
  const text = raw.trim();
  if (!text) return "";
  if (!/^https?:\/\//i.test(text)) return `https://${text}`;
  return text;
}

function urlPathParts(raw: string): string[] {
  try {
    const parsed = new URL(normalizeUrlLine(raw));
    return parsed.pathname.split("/").filter(Boolean);
  } catch {
    return [];
  }
}

function urlHost(raw: string): string {
  try {
    return new URL(normalizeUrlLine(raw)).hostname.toLowerCase();
  } catch {
    return "";
  }
}

function hostIn(raw: string, hosts: string[]): boolean {
  const host = urlHost(raw);
  return Boolean(host && hosts.includes(host));
}

/** Mirrors backend url_only._parse_pinterest acceptance rules. */
export function matchesPinterestLinkImportUrl(raw: string): boolean {
  if (!hostIn(raw, ["pinterest.com", "www.pinterest.com"])) return false;
  const parts = urlPathParts(raw);
  if (parts.length === 2 && parts[0].toLowerCase() === "pin") {
    return PINTEREST_PIN_ID_RE.test(parts[1]);
  }
  if (parts.length !== 1) return false;
  const username = parts[0];
  return !PINTEREST_RESERVED.has(username.toLowerCase()) && HANDLE_RE.test(username);
}

/** Mirrors backend url_only._parse_ltk acceptance rules. */
export function matchesLtkLinkImportUrl(raw: string): boolean {
  if (!hostIn(raw, ["shopltk.com", "www.shopltk.com"])) return false;
  const parts = urlPathParts(raw);
  if (parts.length < 2 || parts[0].toLowerCase() !== "explore") return false;
  return HANDLE_RE.test(parts[1]);
}

/** Mirrors backend url_only._parse_shopmy acceptance rules. */
export function matchesShopmyLinkImportUrl(raw: string): boolean {
  if (!hostIn(raw, ["shopmy.us", "www.shopmy.us"])) return false;
  const parts = urlPathParts(raw);
  if (parts.length !== 1 && !(parts.length === 2 && parts[0].toLowerCase() === "shop")) return false;
  const username = parts.length === 2 ? parts[1] : parts[0];
  return !SHOPMY_RESERVED.has(username.toLowerCase()) && HANDLE_RE.test(username);
}

function detectLinkPlatform(line: string): string | null {
  const normalized = normalizeUrlLine(line);
  if (!normalized) return null;
  if (AMAZON_RE.test(normalized) && /\/(dp\/|gp\/product\/|product\/)/i.test(normalized)) {
    return "amazon";
  }
  if (matchesPinterestLinkImportUrl(normalized)) return "pinterest";
  if (matchesLtkLinkImportUrl(normalized)) return "ltk";
  if (matchesShopmyLinkImportUrl(normalized)) return "shopmy";
  for (const detector of PLATFORM_DETECTORS) {
    if (detector.pattern.test(normalized)) {
      if (detector.validate && !detector.validate.test(normalized)) return null;
      return detector.platform;
    }
  }
  return null;
}

export function parseLinkImportPreview(text: string): LinkImportPreview {
  const counts: Record<string, number> = {};
  const invalidLines: string[] = [];
  const recognizedLines: string[] = [];
  const unrecognizedLines: string[] = [];
  const seen = new Set<string>();
  let hasAmazon = false;
  let hasProfiles = false;

  for (const [lineNo, line] of text.split(/\r?\n/).entries()) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const linePrefix = `第 ${lineNo + 1} 行`;
    const platform = detectLinkPlatform(trimmed);
    if (!platform) {
      const message = `${linePrefix}: ${trimmed}（无法识别平台）`;
      invalidLines.push(message);
      unrecognizedLines.push(message);
      continue;
    }
    const key = `${platform}:${normalizeUrlLine(trimmed).toLowerCase()}`;
    if (seen.has(key)) continue;
    seen.add(key);
    counts[platform] = (counts[platform] ?? 0) + 1;
    recognizedLines.push(`已识别：${recognitionLabel(platform, trimmed)}`);
    if (platform === "amazon") hasAmazon = true;
    else hasProfiles = true;
  }

  return {
    counts,
    invalidCount: invalidLines.length,
    invalidLines,
    validCount: Object.values(counts).reduce((sum, n) => sum + n, 0),
    hasAmazon,
    hasProfiles,
    mixedAmazonAndProfiles: hasAmazon && hasProfiles,
    recognizedLines,
    unrecognizedLines,
  };
}

export function formatLinkImportPreviewLines(preview: LinkImportPreview): string[] {
  const lines: string[] = [];
  const orderedPlatforms = [
    "instagram",
    "youtube",
    "tiktok",
    "facebook",
    "pinterest",
    "ltk",
    "shopmy",
    "amazon",
  ];
  for (const platform of orderedPlatforms) {
    const count = preview.counts[platform];
    if (!count) continue;
    const label = PREVIEW_PLATFORM_LABELS[platform] ?? PLATFORM_LABELS[platform] ?? platform;
    lines.push(`${label} ${count} 条`);
  }
  for (const [platform, count] of Object.entries(preview.counts)) {
    if (orderedPlatforms.includes(platform)) continue;
    const label = PREVIEW_PLATFORM_LABELS[platform] ?? PLATFORM_LABELS[platform] ?? platform;
    lines.push(`${label} ${count} 条`);
  }
  if (preview.invalidCount > 0) {
    lines.push(`无法识别 ${preview.invalidCount} 条`);
  }
  return lines;
}

export type LinkImportPlatformGroup = {
  title: string;
  items: string[];
};

export function buildLinkImportPlatformGroups(caps: PlatformCapability[]): LinkImportPlatformGroup[] {
  const byPlatform = new Map(caps.map((cap) => [cap.platform, cap]));
  const socialItems = ["instagram", "youtube", "tiktok", "facebook"].map((platform) => {
    const cap = byPlatform.get(platform);
    return cap?.link_import_hint ?? `${PLATFORM_LABELS[platform]}：主页/频道链接`;
  });
  const guideItems = URL_ONLY_PLATFORMS.map((platform) => {
    const cap = byPlatform.get(platform);
    const label = PLATFORM_LABELS[platform] ?? platform;
    return cap?.link_import_hint ?? `${label}：可尝试链接导入，关键词采集待验证`;
  });
  const amazonCap = byPlatform.get("amazon");
  return [
    {
      title: "社媒主页链接",
      items: socialItems,
    },
    {
      title: "导购/灵感平台（链接导入 / 外部 seed 发现 / 反向外链扩展）",
      items: guideItems,
    },
    {
      title: "商品线索（Amazon 商品链接需单独任务，勿与红人主页链接混合）",
      items: [
        amazonCap?.link_import_hint ??
          "Amazon：商品链接（/dp、/gp/product、/product），不是红人主页平台",
      ],
    },
  ];
}

export function formatLinkImportPlatformHints(caps: PlatformCapability[]): LinkImportPlatformGroup[] {
  if (caps.length === 0) return [];
  return buildLinkImportPlatformGroups(caps);
}

export const URL_ONLY_PLATFORM_NOTE =
  "以下平台支持链接导入、外部 seed 自动发现和反向外链扩展；站内关键词直采暂未接入。";
