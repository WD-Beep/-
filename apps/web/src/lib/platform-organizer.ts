import { platformLabel } from "@/lib/labels";

export const PRIMARY_PLATFORMS = ["tiktok", "youtube", "instagram", "facebook"] as const;

export type PlatformFilterKey = "all" | (typeof PRIMARY_PLATFORMS)[number] | "other";

export type PlatformStatCounts = {
  total: number;
  has_email: number;
  direct_contact: number;
  missing_contact: number;
  high_value: number;
};

export type PlatformStatItem = PlatformStatCounts & {
  platform: string;
};

export const PLATFORM_FILTER_LABELS: Record<PlatformFilterKey, string> = {
  all: "全部平台",
  tiktok: "TikTok",
  youtube: "YouTube",
  instagram: "Instagram",
  facebook: "Facebook",
  other: "其他平台",
};

export const PLATFORM_ACCENT: Record<
  PlatformFilterKey,
  { bar: string; badge: string; ring: string; activeBg: string }
> = {
  all: {
    bar: "bg-slate-500",
    badge: "text-slate-600",
    ring: "ring-slate-300",
    activeBg: "bg-slate-50",
  },
  tiktok: {
    bar: "bg-gradient-to-r from-slate-800 via-teal-500 to-pink-400",
    badge: "text-slate-800",
    ring: "ring-slate-300",
    activeBg: "bg-slate-50",
  },
  youtube: {
    bar: "bg-red-500",
    badge: "text-red-700",
    ring: "ring-red-200",
    activeBg: "bg-red-50/50",
  },
  instagram: {
    bar: "bg-gradient-to-r from-amber-500 via-pink-500 to-purple-500",
    badge: "text-pink-700",
    ring: "ring-pink-200",
    activeBg: "bg-pink-50/40",
  },
  facebook: {
    bar: "bg-blue-600",
    badge: "text-blue-700",
    ring: "ring-blue-200",
    activeBg: "bg-blue-50/50",
  },
  other: {
    bar: "bg-slate-400",
    badge: "text-slate-600",
    ring: "ring-slate-200",
    activeBg: "bg-muted/40",
  },
};

export function parsePlatformFilter(value: string | null): PlatformFilterKey {
  if (!value || value === "all") return "all";
  if (
    value === "tiktok" ||
    value === "youtube" ||
    value === "instagram" ||
    value === "facebook" ||
    value === "other"
  ) {
    return value;
  }
  return "all";
}

export function platformFilterToApi(platform: PlatformFilterKey): string | undefined {
  if (platform === "all") return undefined;
  return platform;
}

export function platformListTitle(platform: PlatformFilterKey): string {
  if (platform === "all") return "全部平台线索列表";
  return `${PLATFORM_FILTER_LABELS[platform]} 线索列表`;
}

export function aggregatePlatformStats(items: PlatformStatItem[]): PlatformStatCounts {
  return items.reduce(
    (acc, item) => ({
      total: acc.total + item.total,
      has_email: acc.has_email + item.has_email,
      direct_contact: acc.direct_contact + item.direct_contact,
      missing_contact: acc.missing_contact + item.missing_contact,
      high_value: acc.high_value + item.high_value,
    }),
    {
      total: 0,
      has_email: 0,
      direct_contact: 0,
      missing_contact: 0,
      high_value: 0,
    },
  );
}

export function buildPlatformCards(
  items: PlatformStatItem[],
): Array<{ key: PlatformFilterKey; stats: PlatformStatCounts; label: string }> {
  const byKey = new Map(items.map((item) => [item.platform as PlatformFilterKey, item]));
  const emptyStats: PlatformStatCounts = {
    total: 0,
    has_email: 0,
    direct_contact: 0,
    missing_contact: 0,
    high_value: 0,
  };
  const totals = aggregatePlatformStats(items);

  const cards: Array<{ key: PlatformFilterKey; stats: PlatformStatCounts; label: string }> = [
    { key: "all", stats: totals, label: PLATFORM_FILTER_LABELS.all },
  ];

  for (const key of PRIMARY_PLATFORMS) {
    const stats = byKey.get(key) ?? emptyStats;
    cards.push({ key, stats, label: PLATFORM_FILTER_LABELS[key] });
  }

  const other = byKey.get("other");
  if (other && other.total > 0) {
    cards.push({ key: "other", stats: other, label: PLATFORM_FILTER_LABELS.other });
  }

  return cards;
}

export function platformFilterLabel(platform: PlatformFilterKey): string {
  return PLATFORM_FILTER_LABELS[platform] ?? platformLabel(platform);
}
