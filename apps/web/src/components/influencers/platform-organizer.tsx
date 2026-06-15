"use client";

import { Loader2 } from "lucide-react";

import { cn } from "@/lib/utils";
import {
  PLATFORM_ACCENT,
  type PlatformFilterKey,
  type PlatformStatCounts,
} from "@/lib/platform-organizer";

type PlatformCard = {
  key: PlatformFilterKey;
  stats: PlatformStatCounts;
  label: string;
  hint?: string;
};

type PlatformOrganizerProps = {
  cards: PlatformCard[];
  activePlatform: PlatformFilterKey;
  loading?: boolean;
  onSelect: (platform: PlatformFilterKey) => void;
};

function StatChip({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: number;
  tone?: "default" | "success" | "warning" | "muted";
}) {
  const toneClass =
    tone === "success"
      ? "text-emerald-700"
      : tone === "warning"
        ? "text-amber-700"
        : tone === "muted"
          ? "text-muted-foreground"
          : "text-foreground";

  return (
    <span className="inline-flex items-center gap-0.5 whitespace-nowrap text-[10px] leading-none">
      <span className="text-muted-foreground">{label}</span>
      <span className={cn("font-medium tabular-nums", toneClass)}>{value}</span>
    </span>
  );
}

function PlatformCardButton({
  card,
  active,
  loading,
  onSelect,
}: {
  card: PlatformCard;
  active: boolean;
  loading?: boolean;
  onSelect: () => void;
}) {
  const accent = PLATFORM_ACCENT[card.key];

  return (
    <button
      type="button"
      onClick={onSelect}
      disabled={loading}
      className={cn(
        "group relative min-w-[132px] shrink-0 rounded-lg border px-3 py-2.5 text-left transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        active
          ? cn("border-primary/40 shadow-sm ring-1", accent.ring, accent.activeBg)
          : "border-border bg-card hover:border-primary/20 hover:bg-muted/30",
        loading && "pointer-events-none opacity-70",
      )}
      aria-pressed={active}
    >
      <div className={cn("mb-2 h-0.5 w-8 rounded-full", accent.bar)} />
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className={cn("truncate text-xs font-medium", active ? "text-foreground" : accent.badge)}>
            {card.label}
          </p>
          <p className="mt-0.5 text-lg font-semibold tabular-nums leading-none">
            {card.stats.total.toLocaleString("zh-CN")}
          </p>
        </div>
        {active ? (
          <span className="mt-0.5 rounded bg-primary/10 px-1.5 py-0.5 text-[10px] font-medium text-primary">
            当前
          </span>
        ) : null}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-2 gap-y-1">
        <StatChip label="邮箱" value={card.stats.has_email} tone="success" />
        <StatChip label="可联" value={card.stats.direct_contact} />
        <StatChip label="缺联" value={card.stats.missing_contact} tone="warning" />
        <StatChip label="高价值" value={card.stats.high_value} tone="muted" />
      </div>
      {card.hint ? (
        <p className="mt-2 line-clamp-2 text-[10px] leading-snug text-muted-foreground">{card.hint}</p>
      ) : null}
    </button>
  );
}

export function PlatformOrganizer({
  cards,
  activePlatform,
  loading,
  onSelect,
}: PlatformOrganizerProps) {
  return (
    <section className="mb-4 rounded-lg border bg-card/60 p-3 sm:p-4">
      <div className="mb-2.5 flex items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-medium">平台整理</h2>
          <p className="text-xs text-muted-foreground">
            按平台查看线索分布 · 统计随当前筛选条件刷新
          </p>
        </div>
        {loading ? (
          <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            更新中
          </span>
        ) : null}
      </div>

      <div className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-0.5 [scrollbar-width:thin]">
        {cards.map((card) => (
          <PlatformCardButton
            key={card.key}
            card={card}
            active={activePlatform === card.key}
            loading={loading}
            onSelect={() => onSelect(card.key)}
          />
        ))}
      </div>
    </section>
  );
}
