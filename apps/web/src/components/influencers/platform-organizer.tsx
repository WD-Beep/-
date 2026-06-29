"use client";

import { Loader2 } from "lucide-react";

import { cn } from "@/lib/utils";
import {
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
  return (
    <button
      type="button"
      onClick={onSelect}
      disabled={loading}
      title={`${card.label}: 总数 ${card.stats.total}，可联络 ${card.stats.direct_contact}，高价值 ${card.stats.high_value}，缺联 ${card.stats.missing_contact}${card.hint ? `。${card.hint}` : ""}`}
      className={cn(
        "influencer-platform-card group flex min-h-12 min-w-[156px] shrink-0 items-center gap-3 rounded-md border px-3 py-2 text-left transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        active
          ? "border-blue-300 bg-blue-50/60 text-blue-900 ring-1 ring-blue-200"
          : "border-slate-200 bg-[hsl(210_30%_99%)] hover:border-slate-300 hover:bg-slate-50",
        loading && "pointer-events-none opacity-70",
      )}
      aria-pressed={active}
    >
      <span
        className={cn(
          "h-2 w-2 shrink-0 rounded-full",
          active ? "bg-blue-600" : "bg-slate-300 group-hover:bg-slate-400",
        )}
      />
      <span className="min-w-0 flex-1">
        <span className="flex items-center justify-between gap-2">
          <span className="truncate text-xs font-semibold">{card.label}</span>
          <span className="text-base font-semibold tabular-nums leading-none text-slate-950">
            {card.stats.total.toLocaleString("zh-CN")}
          </span>
        </span>
        <span className="mt-1 flex items-center gap-2 text-[11px] leading-none text-slate-500">
          <span>可联 {card.stats.direct_contact}</span>
          <span>高价值 {card.stats.high_value}</span>
          <span className="text-amber-700">缺联 {card.stats.missing_contact}</span>
        </span>
      </span>
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
    <section className="ops-panel influencer-platform-panel shrink-0 px-3 py-1.5">
      <div className="flex min-w-0 items-center gap-2">
        <div className="shrink-0 pr-1">
          <h2 className="text-sm font-semibold leading-5 text-slate-950">平台概览</h2>
        </div>
        <div className="flex min-w-0 flex-1 gap-2 overflow-x-auto [scrollbar-width:thin]">
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
        {loading ? (
          <span className="inline-flex shrink-0 items-center gap-1.5 text-xs text-muted-foreground">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            更新中
          </span>
        ) : null}
      </div>
    </section>
  );
}
