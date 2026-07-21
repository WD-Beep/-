// 文件说明：前端公共工具和业务辅助函数；当前文件：instagram url
const POST_PATH_RE = /instagram\.com\/(p|reel|reels|tv)\/([^/?#]+)/i;
const PROFILE_RESERVED = new Set([
  "p",
  "reel",
  "reels",
  "tv",
  "explore",
  "stories",
  "accounts",
  "tags",
  "direct",
]);

export type ExternalLinkState = {
  ok: boolean;
  href: string;
  reason?: string;
};

function cleanText(raw: string | null | undefined): string {
  if (!raw) return "";
  return raw
    .trim()
    .replace(/：/g, ":")
    .replace(/／/g, "/")
    .replace(/．/g, ".");
}

export function sanitizeExternalUrl(raw: string | null | undefined): string {
  const text = cleanText(raw);
  if (!text || text.toLowerCase() === "undefined" || text.toLowerCase() === "null") {
    return "";
  }
  if (!/^https?:\/\//i.test(text)) {
    return `https://${text.replace(/^\/+/, "")}`;
  }
  return text;
}

export function resolveExternalLink(raw: string | null | undefined): ExternalLinkState {
  const href = sanitizeExternalUrl(raw);
  if (!href) {
    return { ok: false, href: "", reason: "无链接" };
  }
  try {
    const url = new URL(href);
    const host = url.hostname.toLowerCase();
    if (!host.includes("instagram.com")) {
      return { ok: true, href: url.toString() };
    }
    const segments = url.pathname.split("/").filter(Boolean);
    if (!segments.length) {
      return { ok: false, href, reason: "链接异常" };
    }
    const head = segments[0].toLowerCase();
    if (POST_PATH_RE.test(href)) {
      return { ok: true, href: url.toString() };
    }
    if (PROFILE_RESERVED.has(head)) {
      return { ok: false, href, reason: "链接异常（非主页/帖子）" };
    }
    return { ok: true, href: url.toString() };
  } catch {
    return { ok: false, href, reason: "链接格式无效" };
  }
}

export async function copyLinkText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}
