"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  ChevronLeft,
  ChevronRight,
  Copy,
  Download,
  ExternalLink,
  Loader2,
  RefreshCw,
  Search,
} from "lucide-react";

import { PlatformOrganizer } from "@/components/influencers/platform-organizer";
import { AdminShell } from "@/components/layout/admin-shell";
import { useActiveProductId } from "@/components/providers/product-provider";
import { EmptyState, ErrorAlert, LoadingState } from "@/components/shared/page-states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  buildInfluencersPageUrl,
  downloadInfluencerExport,
  fetchInfluencerPlatformStats,
  fetchInfluencers,
  updateInfluencerLead,
  type Influencer,
  type InfluencerListFilters,
  type InfluencerPlatformStatItem,
} from "@/lib/api";
import { resolveExternalLink } from "@/lib/instagram-url";
import {
  leadStatusLabel,
  leadStatusVariant,
  contactCredibilityLabel,
  emailSourceLabel,
  platformLabel,
  followersAudienceLabel,
  SOURCE_DISCOVERY_LABELS,
} from "@/lib/labels";
import {
  buildPlatformCards,
  parsePlatformFilter,
  platformFilterLabel,
  platformFilterToApi,
  platformListTitle,
  type PlatformFilterKey,
} from "@/lib/platform-organizer";
import { cn } from "@/lib/utils";

type QuickFilter =
  | "all"
  | "recent_created_24h"
  | "recent_collected_7d"
  | "high_value"
  | "direct_contact"
  | "manual_research"
  | "skip"
  | "has_email"
  | "missing_contact";

const FILTER_LABELS: Record<QuickFilter, string> = {
  all: "全部",
  recent_created_24h: "最近24小时入库",
  recent_collected_7d: "最近7天采集",
  high_value: "高价值",
  direct_contact: "可直接外联",
  manual_research: "值得人工找联系",
  skip: "暂时跳过",
  has_email: "有邮箱",
  missing_contact: "缺联系方式",
};

const PAGE_SIZE = 20;
const MS_24H = 24 * 60 * 60 * 1000;
const CONTACTED_STATUSES = new Set([
  "contacted",
  "replied",
  "interested",
  "quoted",
  "cooperating",
  "cooperated",
  "negotiating",
  "collaborated",
]);

function toApiFilters(
  filter: QuickFilter,
  search: string,
  taskId?: number,
  platform: PlatformFilterKey = "all",
): Omit<InfluencerListFilters, "page" | "pageSize"> {
  const base: Omit<InfluencerListFilters, "page" | "pageSize"> = {
    collectionTaskId: taskId,
  };
  const apiPlatform = platformFilterToApi(platform);
  if (apiPlatform) base.platform = apiPlatform;
  if (search.trim()) base.search = search.trim();
  if (filter === "recent_created_24h") return { ...base, createdWithinHours: 24 };
  if (filter === "recent_collected_7d") return { ...base, collectedWithinDays: 7 };
  if (filter === "high_value") return { ...base, highValue: true };
  if (filter === "direct_contact") return { ...base, valueTier: "direct_contact" };
  if (filter === "manual_research") return { ...base, valueTier: "manual_research" };
  if (filter === "skip") return { ...base, valueTier: "skip" };
  if (filter === "has_email") return { ...base, hasEmail: true };
  if (filter === "missing_contact") return { ...base, missingContact: true };
  return base;
}

function formatPercent(value: number | null | undefined): string {
  if (value == null) return "-";
  return `${value.toFixed(1)}%`;
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "-";
  return new Date(value).toLocaleDateString("zh-CN");
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  return new Date(value).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function getFreshnessBadges(item: Influencer, taskFilterActive: boolean) {
  const now = Date.now();
  const badges: { label: string; variant: "success" | "default" | "warning" }[] = [];
  const createdAt = item.created_at ? new Date(item.created_at).getTime() : null;
  const collectedAt = item.last_collected_at ? new Date(item.last_collected_at).getTime() : null;

  if (taskFilterActive) {
    badges.push({ label: "本次采集", variant: "warning" });
  } else if (createdAt && now - createdAt <= MS_24H) {
    badges.push({ label: "新入库", variant: "success" });
  } else if (collectedAt && now - collectedAt <= MS_24H) {
    badges.push({ label: "最近采集", variant: "default" });
  }

  return badges;
}

function valueTierBadgeVariant(
  tier: Influencer["value_tier"] | undefined,
): "success" | "default" | "secondary" {
  if (tier === "direct_contact") return "success";
  if (tier === "manual_research") return "default";
  return "secondary";
}

function priorityBadgeClass(priority: string | null | undefined): string {
  switch (priority) {
    case "P0":
      return "bg-emerald-100 text-emerald-800";
    case "P1":
      return "bg-blue-100 text-blue-800";
    case "P2":
      return "bg-amber-100 text-amber-800";
    case "P3":
      return "bg-muted text-muted-foreground";
    default:
      return "bg-muted text-muted-foreground";
  }
}

function resolveEmail(item: Influencer): string | null {
  return item.final_email || item.public_email || item.business_email || item.email;
}

function resolveContactSummary(item: Influencer): string {
  if (item.contact_summary && item.contact_summary !== "缺联系方式") {
    return item.contact_summary;
  }
  const email = resolveEmail(item);
  if (email) return email;

  const parts: string[] = [];
  if (item.website) parts.push("官网");
  if (item.contact_page) parts.push("联系页");
  if (item.linktree_url) parts.push("Linktree");
  if (item.whatsapp) parts.push(`WhatsApp: ${item.whatsapp}`);
  if (item.telegram) parts.push(`Telegram: ${item.telegram}`);

  const profileUrl = (item.profile_url || "").toLowerCase();
  if (profileUrl.includes("shopmy.us")) parts.push("ShopMy");
  if (profileUrl.includes("shopltk.com")) parts.push("LTK");
  if (profileUrl.includes("amazon.com/shop/") || profileUrl.includes("amazon.com/stores/") || profileUrl.includes("amzn.to/")) {
    parts.push("Amazon storefront");
  }

  for (const link of item.other_social_links ?? []) {
    const label = link.label?.trim();
    if (label && !parts.includes(label)) parts.push(label);
  }

  const bio = (item.bio || "").toLowerCase();
  if (
    bio.includes("dm for collab") ||
    bio.includes("business inquiry") ||
    bio.includes("合作请私信") ||
    bio.includes("商务合作")
  ) {
    parts.push("Bio 支持私信合作");
  }

  if (parts.length > 0) return parts.slice(0, 4).join(" · ");
  return item.contact_summary || "缺联系方式";
}

function hasExternalContactHub(item: Influencer): boolean {
  if (item.linktree_url || item.website || item.contact_page) return true;
  for (const link of item.other_social_links ?? []) {
    const type = (link.type || "").toLowerCase();
    const url = (link.url || "").toLowerCase();
    if (["linktree", "shopmy", "ltk", "amazon_storefront", "instagram", "facebook", "twitter", "tiktok"].includes(type)) {
      return true;
    }
    if (
      url.includes("lnktr.ee") ||
      url.includes("linktr.ee") ||
      url.includes("amzn.to") ||
      url.includes("shopmy.us") ||
      url.includes("shopltk.com")
    ) {
      return true;
    }
  }
  return false;
}

function aiReasonPreview(item: Influencer): string {
  return item.score_reason || item.ai_summary || "-";
}

function resolveEmailSource(item: Influencer): string {
  return emailSourceLabel(item.email_source);
}

function resolveCredibility(item: Influencer): string {
  return contactCredibilityLabel(item.contact_credibility_level);
}

function isContacted(item: Influencer): boolean {
  const status = item.lead_status || item.follow_status;
  return status ? CONTACTED_STATUSES.has(status) : false;
}

export function InfluencersPanel() {
  const productId = useActiveProductId();
  const router = useRouter();
  const searchParams = useSearchParams();
  const taskIdParam = searchParams.get("task_id");
  const taskNameParam = searchParams.get("task_name");
  const taskId = taskIdParam ? Number(taskIdParam) : undefined;
  const taskFilterActive = Boolean(taskId && Number.isFinite(taskId));
  const activePlatform = parsePlatformFilter(searchParams.get("platform"));

  const [items, setItems] = useState<Influencer[]>([]);
  const [total, setTotal] = useState(0);
  const [pages, setPages] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [statsLoading, setStatsLoading] = useState(true);
  const [platformStats, setPlatformStats] = useState<InfluencerPlatformStatItem[]>([]);
  const [actionId, setActionId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeFilter, setActiveFilter] = useState<QuickFilter>("all");
  const [searchInput, setSearchInput] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [operatorName, setOperatorName] = useState("");

  const statsFilters = useMemo(
    () => toApiFilters(activeFilter, searchQuery, taskFilterActive ? taskId : undefined, "all"),
    [activeFilter, searchQuery, taskFilterActive, taskId],
  );

  const apiFilters = useMemo(
    () =>
      toApiFilters(
        activeFilter,
        searchQuery,
        taskFilterActive ? taskId : undefined,
        activePlatform,
      ),
    [activeFilter, searchQuery, taskFilterActive, taskId, activePlatform],
  );

  const platformCards = useMemo(() => buildPlatformCards(platformStats), [platformStats]);

  const loadStats = useCallback(
    async (filters: Omit<InfluencerListFilters, "page" | "pageSize" | "platform">) => {
      setStatsLoading(true);
      try {
        const data = await fetchInfluencerPlatformStats(filters);
        setPlatformStats(data.items);
      } catch {
        setPlatformStats([]);
      } finally {
        setStatsLoading(false);
      }
    },
    [],
  );

  const load = useCallback(
    async (filters: Omit<InfluencerListFilters, "page" | "pageSize">, currentPage: number) => {
      setLoading(true);
      setError(null);
      try {
        const data = await fetchInfluencers(currentPage, PAGE_SIZE, filters);
        setItems(data.items);
        setTotal(data.total);
        setPages(data.pages);
      } catch (err) {
        setError(err instanceof Error ? err.message : "加载红人列表失败");
        setItems([]);
        setTotal(0);
        setPages(0);
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    if (productId === null) {
      setLoading(false);
      return;
    }
    queueMicrotask(() => {
      void load(apiFilters, page);
    });
  }, [apiFilters, page, load, productId]);

  useEffect(() => {
    if (productId === null) return;
    queueMicrotask(() => {
      void loadStats(statsFilters);
    });
  }, [statsFilters, loadStats, productId]);

  useEffect(() => {
    setPage(1);
  }, [activePlatform]);

  const handlePlatformChange = (platform: PlatformFilterKey) => {
    setPage(1);
    const params = new URLSearchParams(searchParams.toString());
    if (platform === "all") {
      params.delete("platform");
    } else {
      params.set("platform", platform);
    }
    const qs = params.toString();
    router.replace(qs ? `/influencers?${qs}` : "/influencers", { scroll: false });
  };

  const handleFilterChange = (filter: QuickFilter) => {
    setActiveFilter(filter);
    setPage(1);
  };

  const handleSearch = () => {
    setSearchQuery(searchInput.trim());
    setPage(1);
  };

  const handleRefresh = async () => {
    await Promise.all([load(apiFilters, page), loadStats(statsFilters)]);
  };

  const clearAllFilters = () => {
    setActiveFilter("all");
    setSearchInput("");
    setSearchQuery("");
    setPage(1);
    router.replace(taskFilterActive ? buildInfluencersPageUrl({ taskId, taskName: taskNameParam ?? undefined }) : "/influencers", {
      scroll: false,
    });
  };

  const handleLeadAction = async (
    item: Influencer,
    payload: Parameters<typeof updateInfluencerLead>[1],
  ) => {
    setActionId(item.id);
    setError(null);
    try {
      await updateInfluencerLead(item.id, {
        ...payload,
        operator_name: operatorName.trim() || undefined,
      });
      await Promise.all([load(apiFilters, page), loadStats(statsFilters)]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失败");
    } finally {
      setActionId(null);
    }
  };

  const copyEmail = async (email: string | null) => {
    if (!email) return;
    try {
      await navigator.clipboard.writeText(email);
    } catch {
      setError("复制邮箱失败");
    }
  };

  const exportFilters = apiFilters;
  const hasActiveFilters =
    activeFilter !== "all" || activePlatform !== "all" || Boolean(searchQuery) || taskFilterActive;
  const listTitle = platformListTitle(activePlatform);

  return (
    <AdminShell title="红人库" description="多平台线索跟进工作台：筛选、联系、记录跟进状态">
      {taskFilterActive ? (
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm">
          <div>
            正在查看采集任务入库红人
            {taskNameParam ? ` · ${taskNameParam}` : ""}
            {taskId ? `（任务 #${taskId}）` : ""}
          </div>
          <Button variant="outline" size="sm" asChild>
            <Link href="/influencers">清除任务筛选</Link>
          </Button>
        </div>
      ) : null}

      <PlatformOrganizer
        cards={platformCards}
        activePlatform={activePlatform}
        loading={statsLoading}
        onSelect={handlePlatformChange}
      />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="flex flex-wrap gap-2">
          {(Object.keys(FILTER_LABELS) as QuickFilter[]).map((key) => (
            <Button
              key={key}
              size="sm"
              variant={activeFilter === key ? "default" : "outline"}
              onClick={() => handleFilterChange(key)}
              disabled={loading}
            >
              {FILTER_LABELS[key]}
            </Button>
          ))}
        </div>
        <div className="flex min-w-[160px] items-center gap-2 sm:max-w-[180px]">
          <Input
            placeholder="操作人"
            value={operatorName}
            onChange={(e) => setOperatorName(e.target.value)}
          />
        </div>
        <div className="flex min-w-[220px] flex-1 items-center gap-2 sm:max-w-xs">
          <Input
            placeholder="搜索昵称 / 用户名"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSearch()}
          />
          <Button variant="outline" size="sm" onClick={handleSearch} disabled={loading}>
            <Search className="h-4 w-4" />
          </Button>
        </div>
        <Button variant="outline" onClick={() => void handleRefresh()} disabled={loading || statsLoading}>
          {loading || statsLoading ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <RefreshCw className="h-4 w-4" />
          )}
          刷新列表
        </Button>
        <Button
          variant="secondary"
          onClick={() => {
            void downloadInfluencerExport(exportFilters).catch((err) =>
              setError(err instanceof Error ? err.message : "导出失败"),
            );
          }}
        >
          <Download className="h-4 w-4" />
          导出 Excel
        </Button>
      </div>

      {error ? <ErrorAlert message={error} className="mb-4" /> : null}

      <Card>
        <CardHeader>
          <CardTitle>{listTitle}</CardTitle>
          <CardDescription>
            {taskFilterActive
              ? `任务入库 ${total} 条 · 第 ${page}/${Math.max(pages, 1)} 页 · 按最近采集/入库时间排序`
              : activeFilter === "all" && activePlatform === "all"
                ? `共 ${total} 条 · 第 ${page}/${Math.max(pages, 1)} 页 · 按最近采集/入库时间排序`
                : `筛选「${activePlatform !== "all" ? platformFilterLabel(activePlatform) : FILTER_LABELS[activeFilter]}」· 共 ${total} 条`}
            {searchQuery ? ` · 搜索「${searchQuery}」` : ""}
            {activePlatform !== "all" && activeFilter !== "all"
              ? ` · ${FILTER_LABELS[activeFilter]}`
              : ""}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <LoadingState label="加载红人数据..." />
          ) : items.length === 0 ? (
            <div className="space-y-4">
              <EmptyState
                title={
                  activePlatform !== "all"
                    ? "当前平台暂无符合条件的线索"
                    : activeFilter === "all" && !taskFilterActive
                      ? "暂无红人数据"
                      : "没有符合筛选条件的红人"
                }
                description={
                  activePlatform !== "all"
                    ? `「${platformFilterLabel(activePlatform)}」在当前筛选条件下没有匹配结果，可切换平台或放宽筛选。`
                    : taskFilterActive
                      ? "该任务尚未有入库红人，或入库红人未关联到候选池记录。"
                      : activeFilter === "all"
                        ? "请前往「采集任务」创建并运行任务，或在「链接导入」粘贴链接导入。"
                        : "请切换其他筛选条件，或先运行采集任务补充数据。"
                }
              />
              {hasActiveFilters ? (
                <div className="flex flex-wrap justify-center gap-2">
                  {activePlatform !== "all" ? (
                    <Button variant="outline" size="sm" onClick={() => handlePlatformChange("all")}>
                      返回全部平台
                    </Button>
                  ) : null}
                  <Button variant="secondary" size="sm" onClick={clearAllFilters}>
                    清除筛选
                  </Button>
                </div>
              ) : null}
            </div>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-left text-muted-foreground">
                      <th className="pb-3 pr-4 font-medium">账号</th>
                      <th className="pb-3 pr-4 font-medium">体量 / 互动</th>
                      <th className="pb-3 pr-4 font-medium">来源</th>
                      <th className="pb-3 pr-4 font-medium">联系方式</th>
                      <th className="pb-3 pr-4 font-medium">AI 推荐理由</th>
                      <th className="pb-3 pr-4 font-medium">优先级</th>
                      <th className="pb-3 pr-4 font-medium">跟进状态</th>
                      <th className="pb-3 pr-4 font-medium">负责人</th>
                      <th className="pb-3 pr-4 font-medium">下次跟进</th>
                      <th className="pb-3 font-medium">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((item) => {
                      const email = resolveEmail(item);
                      const profileLink = resolveExternalLink(item.profile_url);
                      const status = item.lead_status || item.follow_status || "new";
                      const contacted = isContacted(item);
                      const busy = actionId === item.id;
                      const freshnessBadges = getFreshnessBadges(item, taskFilterActive);

                      return (
                        <tr
                          key={item.id}
                          className={`border-b last:border-0 align-top ${
                            taskFilterActive ? "bg-amber-500/5" : ""
                          }`}
                        >
                          <td className="py-3 pr-4">
                            <div className="flex flex-wrap items-center gap-1.5">
                              <div className="font-medium">{item.display_name || item.username}</div>
                              {freshnessBadges.map((badge) => (
                                <Badge key={badge.label} variant={badge.variant} className="text-[10px] px-1.5 py-0">
                                  {badge.label}
                                </Badge>
                              ))}
                              {item.value_tier_label ? (
                                <Badge
                                  variant={valueTierBadgeVariant(item.value_tier)}
                                  className="text-[10px] px-1.5 py-0"
                                  title={item.value_tier_reason || undefined}
                                >
                                  {item.value_tier_label}
                                </Badge>
                              ) : null}
                            </div>
                            <div className="text-xs text-muted-foreground">@{item.username}</div>
                            <div className="mt-0.5 flex items-center gap-1.5 text-xs text-muted-foreground">
                              <span
                                className={cn(
                                  "inline-flex rounded px-1 py-0.5 text-[10px] font-medium",
                                  item.platform === "tiktok" && "bg-slate-100 text-slate-700",
                                  item.platform === "youtube" && "bg-red-50 text-red-700",
                                  item.platform === "instagram" && "bg-pink-50 text-pink-700",
                                  item.platform === "facebook" && "bg-blue-50 text-blue-700",
                                  !["tiktok", "youtube", "instagram", "facebook"].includes(item.platform) &&
                                    "bg-muted text-muted-foreground",
                                )}
                              >
                                {platformLabel(item.platform)}
                              </span>
                            </div>
                            <div className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
                              入库 {formatDateTime(item.created_at)}
                              {item.last_collected_at
                                ? ` · 最近采集 ${formatDateTime(item.last_collected_at)}`
                                : ""}
                            </div>
                          </td>
                          <td className="py-3 pr-4">
                            <div>
                              {item.followers_count?.toLocaleString("zh-CN") ?? "-"}
                              <span className="ml-1 text-xs text-muted-foreground">
                                {followersAudienceLabel(item.platform)}
                              </span>
                            </div>
                            <div className="text-xs text-muted-foreground">
                              互动 {formatPercent(item.engagement_rate)}
                            </div>
                          </td>
                          <td className="py-3 pr-4 text-xs">
                            {item.source_discovery_type
                              ? SOURCE_DISCOVERY_LABELS[item.source_discovery_type] ??
                                item.source_discovery_type
                              : "-"}
                          </td>
                          <td className="py-3 pr-4 text-xs">
                            <span className={email ? "" : "text-amber-700"}>
                              {resolveContactSummary(item)}
                            </span>
                            <div className="mt-1 text-muted-foreground">
                              可信度 {resolveCredibility(item)}
                              {item.email_source ? ` · ${resolveEmailSource(item)}` : ""}
                            </div>
                            {hasExternalContactHub(item) ? (
                              <div className="mt-0.5 text-muted-foreground">含 Linktree/官网</div>
                            ) : null}
                          </td>
                          <td className="py-3 pr-4 max-w-[180px]">
                            <p className="line-clamp-2 text-xs text-muted-foreground">
                              {aiReasonPreview(item)}
                            </p>
                          </td>
                          <td className="py-3 pr-4">
                            <span
                              className={`inline-flex rounded px-1.5 py-0.5 text-xs font-medium ${priorityBadgeClass(item.lead_priority || item.final_priority)}`}
                            >
                              {item.lead_priority || item.final_priority || "-"}
                            </span>
                          </td>
                          <td className="py-3 pr-4">
                            <Badge variant={leadStatusVariant(status)}>
                              {leadStatusLabel(status)}
                            </Badge>
                            {contacted ? (
                              <div className="mt-1 text-xs text-muted-foreground">已联系</div>
                            ) : null}
                          </td>
                          <td className="py-3 pr-4 text-xs">
                            {item.owner_name || item.owner || "-"}
                          </td>
                          <td className="py-3 pr-4 text-xs">{formatDate(item.next_follow_up_at)}</td>
                          <td className="py-3">
                            <div className="flex min-w-[220px] flex-wrap gap-1">
                              <Button
                                size="sm"
                                variant="outline"
                                disabled={busy}
                                onClick={() => handleLeadAction(item, { lead_status: "to_contact" })}
                              >
                                待联系
                              </Button>
                              <Button
                                size="sm"
                                variant="outline"
                                disabled={busy}
                                onClick={() => handleLeadAction(item, { lead_status: "contacted" })}
                              >
                                已联系
                              </Button>
                              <Button
                                size="sm"
                                variant="outline"
                                disabled={busy}
                                onClick={() => handleLeadAction(item, { lead_status: "replied" })}
                              >
                                已回复
                              </Button>
                              <Button
                                size="sm"
                                variant="outline"
                                disabled={busy}
                                onClick={() =>
                                  handleLeadAction(item, {
                                    lead_status: "invalid",
                                    invalid_reason: "业务标记无效",
                                  })
                                }
                              >
                                无效
                              </Button>
                              <Button
                                size="sm"
                                variant="outline"
                                disabled={busy}
                                onClick={() =>
                                  handleLeadAction(item, {
                                    lead_status: "blacklisted",
                                    blacklist_reason: "业务标记黑名单",
                                  })
                                }
                              >
                                黑名单
                              </Button>
                              {email ? (
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  onClick={() => copyEmail(email)}
                                  title="复制邮箱"
                                >
                                  <Copy className="h-3.5 w-3.5" />
                                </Button>
                              ) : null}
                              <Button
                                size="sm"
                                variant="ghost"
                                asChild={profileLink.ok}
                                disabled={!profileLink.ok}
                                title={profileLink.ok ? "打开主页" : profileLink.reason ?? "链接异常"}
                              >
                                {profileLink.ok ? (
                                  <a href={profileLink.href} target="_blank" rel="noreferrer">
                                    <ExternalLink className="h-3.5 w-3.5" />
                                  </a>
                                ) : (
                                  <span>
                                    <ExternalLink className="h-3.5 w-3.5 opacity-40" />
                                  </span>
                                )}
                              </Button>
                              <Button variant="link" className="h-auto px-1 py-0" asChild>
                                <Link href={`/influencers/${item.id}`}>详情</Link>
                              </Button>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              {pages > 1 ? (
                <div className="mt-4 flex items-center justify-between gap-3">
                  <p className="text-xs text-muted-foreground">
                    显示 {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, total)} / {total}
                  </p>
                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={page <= 1 || loading}
                      onClick={() => setPage((p) => Math.max(1, p - 1))}
                    >
                      <ChevronLeft className="h-4 w-4" />
                      上一页
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={page >= pages || loading}
                      onClick={() => setPage((p) => p + 1)}
                    >
                      下一页
                      <ChevronRight className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              ) : null}
            </>
          )}
        </CardContent>
      </Card>
    </AdminShell>
  );
}
