// 文件说明：前端红人列表和详情组件；当前文件：influencers panel
"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Bot,
  ChevronLeft,
  ChevronRight,
  Copy,
  Download,
  ExternalLink,
  Loader2,
  Mail,
  Megaphone,
  RefreshCw,
  Search,
  Trash2,
  UserCheck,
  UserX,
} from "lucide-react";

import { OutreachEmailDialog } from "@/components/influencers/outreach-email-dialog";
import { PlatformOrganizer } from "@/components/influencers/platform-organizer";
import { ScriptRecommendDialog } from "@/components/influencers/script-recommend-dialog";
import { AdminShell } from "@/components/layout/admin-shell";
import { useActiveProductId } from "@/components/providers/product-provider";
import { EmptyState, ErrorAlert, LoadingState } from "@/components/shared/page-states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  buildInfluencersPageUrl,
  createOutreachCampaign,
  deleteInfluencers,
  downloadInfluencerExport,
  fetchInfluencerPlatformStats,
  fetchInfluencers,
  generateAndSendOutreachCampaign,
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
  translateErrorMessage,
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
import {
  INFLUENCER_ONE_CLICK_EMAIL_BUTTON_LABEL,
  buildOutreachCampaignResultUrl,
  buildOutreachCampaignsUrl,
  buildOneClickCampaignName,
  buildOneClickCampaignPayload,
  filterEmailableInfluencerIds,
  resolveBulkDeleteSelection,
  resolveBulkOutreachSelection,
  resolveCurrentPageSelectedIds,
  shouldPromotePageSelectionToFilterAll,
  type InfluencerSelectionMode,
} from "@/lib/influencer-selection-helpers";
import { INFLUENCER_EMAIL_SENT_EVENT } from "@/lib/influencer-email-sync";

type QuickFilter =
  | "all"
  | "recent_created_24h"
  | "recent_collected_7d"
  | "high_value"
  | "direct_contact"
  | "manual_research"
  | "skip"
  | "has_email"
  | "missing_contact"
  | "email_sent"
  | "email_unsent"
  | "travel_blogger"
  | "amazon_influencer"
  | "outreach_eligible";

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
  email_sent: "已发送邮件",
  email_unsent: "未发送邮件",
  travel_blogger: "旅游博主",
  amazon_influencer: "亚马逊红人",
  outreach_eligible: "可外联（排除已回复/无效）",
};

const FILTER_GROUPS: { label: string; items: QuickFilter[] }[] = [
  { label: "时间", items: ["all", "recent_created_24h", "recent_collected_7d"] },
  { label: "价值", items: ["high_value", "direct_contact", "manual_research", "skip"] },
  { label: "联系", items: ["has_email", "missing_contact", "outreach_eligible"] },
  { label: "外联", items: ["email_unsent", "email_sent"] },
  { label: "来源", items: ["travel_blogger", "amazon_influencer"] },
];

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
  if (filter === "email_sent") return { ...base, emailStatus: "sent" };
  if (filter === "email_unsent") return { ...base, emailStatus: "unsent" };
  if (filter === "travel_blogger") return { ...base, search: search.trim() || "travel", niche: "travel" };
  if (filter === "amazon_influencer") {
    return { ...base, search: search.trim() || "amazon", sourceDiscoveryType: "amazon_shop" };
  }
  if (filter === "outreach_eligible") return { ...base, excludeTerminalStatuses: true, hasEmail: true };
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
  return (
    item.final_email ||
    item.business_email ||
    item.public_email ||
    item.email
  );
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

function aiReasonPreview(item: Influencer): string {
  const raw = item.score_reason || item.ai_summary || "-";
  return raw === "-" ? raw : translateErrorMessage(raw);
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
  const [scriptRecommendTarget, setScriptRecommendTarget] = useState<Influencer | null>(null);
  const [outreachEmailTarget, setOutreachEmailTarget] = useState<Influencer | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [selectionMode, setSelectionMode] = useState<InfluencerSelectionMode>("none");
  const [undoLead, setUndoLead] = useState<{ id: number; status: string | null } | null>(null);
  const [oneClickSending, setOneClickSending] = useState(false);
  const [bulkDeleting, setBulkDeleting] = useState(false);

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
      queueMicrotask(() => setLoading(false));
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
    if (productId === null) return;
    const refreshSentStatus = () => {
      void load(apiFilters, page);
      void loadStats(statsFilters);
    };
    window.addEventListener(INFLUENCER_EMAIL_SENT_EVENT, refreshSentStatus);
    window.addEventListener("focus", refreshSentStatus);
    window.addEventListener("pageshow", refreshSentStatus);
    return () => {
      window.removeEventListener(INFLUENCER_EMAIL_SENT_EVENT, refreshSentStatus);
      window.removeEventListener("focus", refreshSentStatus);
      window.removeEventListener("pageshow", refreshSentStatus);
    };
  }, [apiFilters, load, loadStats, page, productId, statsFilters]);

  useEffect(() => {
    queueMicrotask(() => setPage(1));
  }, [activePlatform]);

  useEffect(() => {
    queueMicrotask(() => {
      setSelectionMode("none");
      setSelectedIds(new Set());
    });
  }, [activeFilter, searchQuery, activePlatform, taskId]);

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
    options?: { skipConfirm?: boolean; confirmMessage?: string },
  ) => {
    if (
      !options?.skipConfirm &&
      options?.confirmMessage &&
      !window.confirm(options.confirmMessage)
    ) {
      return;
    }
    const previousStatus = item.lead_status || item.follow_status || null;
    setActionId(item.id);
    setError(null);
    try {
      await updateInfluencerLead(item.id, {
        ...payload,
        operator_name: operatorName.trim() || undefined,
      });
      if (payload.lead_status && ["blacklisted", "invalid"].includes(payload.lead_status)) {
        setUndoLead({ id: item.id, status: previousStatus });
      }
      await Promise.all([load(apiFilters, page), loadStats(statsFilters)]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失败");
    } finally {
      setActionId(null);
    }
  };

  async function handleUndoLead() {
    if (!undoLead) return;
    setActionId(undoLead.id);
    try {
      await updateInfluencerLead(undoLead.id, {
        lead_status: undoLead.status || "new",
        operator_name: operatorName.trim() || undefined,
      });
      setUndoLead(null);
      await Promise.all([load(apiFilters, page), loadStats(statsFilters)]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "撤销失败");
    } finally {
      setActionId(null);
    }
  }

  const copyEmail = async (email: string | null) => {
    if (!email) return;
    try {
      await navigator.clipboard.writeText(email);
    } catch {
      setError("复制邮箱失败");
    }
  };

  const exportFilters = apiFilters;
  const currentPageSelectedIds = resolveCurrentPageSelectedIds(
    [...selectedIds],
    items.map((item) => item.id),
  );
  const currentPageEmailableSelectedIds = filterEmailableInfluencerIds(currentPageSelectedIds, items);
  const allPageSelected = items.length > 0 && items.every((item) => selectedIds.has(item.id));
  const hasSelection = selectionMode === "filter_all" || currentPageSelectedIds.length > 0;
  const bulkOutreachSelection = hasSelection
    ? resolveBulkOutreachSelection({
        mode: selectionMode,
        selectedIds: currentPageEmailableSelectedIds,
        total,
        filters: apiFilters,
      })
    : null;
  const selectedCount =
    selectionMode === "filter_all"
      ? total
      : bulkOutreachSelection?.count ?? currentPageSelectedIds.length;
  const bulkDeleteIds = resolveBulkDeleteSelection(currentPageSelectedIds, selectionMode);

  function clearSelection() {
    setSelectedIds(new Set());
    setSelectionMode("none");
  }

  function selectAllFiltered() {
    if (total <= 0) return;
    setSelectionMode("filter_all");
    setSelectedIds(new Set(items.map((item) => item.id)));
  }

  function cancelFilterAllSelection() {
    setSelectionMode("none");
    setSelectedIds(new Set());
  }

  function toggleSelect(id: number) {
    if (selectionMode === "filter_all") {
      setSelectionMode("page");
    }
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      if (next.size === 0) setSelectionMode("none");
      else if (selectionMode === "none") setSelectionMode("page");
      return next;
    });
  }

  function toggleSelectAllPage() {
    if (selectionMode === "filter_all") {
      cancelFilterAllSelection();
      return;
    }
    if (
      shouldPromotePageSelectionToFilterAll({
        total,
        currentPageCount: items.length,
        allPageSelected,
      })
    ) {
      selectAllFiltered();
      return;
    }
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (allPageSelected) {
        for (const item of items) next.delete(item.id);
        setSelectionMode("none");
      } else {
        for (const item of items) next.add(item.id);
        setSelectionMode("page");
      }
      return next;
    });
  }

  async function handleOneClickGenerateAndSend() {
    if (!bulkOutreachSelection) return;
    const label =
      selectionMode === "filter_all"
        ? `当前筛选全部 ${total} 个红人`
        : `已选 ${currentPageSelectedIds.length} 个红人`;
    if (
      !window.confirm(
        `确认对${label}一键生成并发送邮件？系统会自动跳过无邮箱、已发送、已回复、黑名单和无效红人，并为每位可发送红人生成不同邮件。`,
      )
    ) {
      return;
    }
    setOneClickSending(true);
    setError(null);
    try {
      if (!bulkOutreachSelection.selectAll && (bulkOutreachSelection.ids ?? []).length === 0) {
        setError("已勾选的红人没有可用邮箱，请改选有邮箱的红人或先补充邮箱。");
        return;
      }
      const campaign = await createOutreachCampaign(
        buildOneClickCampaignPayload({
          name: buildOneClickCampaignName(),
          ids: bulkOutreachSelection.ids,
          selectAll: bulkOutreachSelection.selectAll,
          filters: bulkOutreachSelection.filters,
        }),
      );
      const result = await generateAndSendOutreachCampaign(campaign.id);
      clearSelection();
      router.push(
        buildOutreachCampaignResultUrl({
          campaignId: campaign.id,
          message: result.message,
          ids: bulkOutreachSelection.ids,
          selectAll: bulkOutreachSelection.selectAll,
          filters: bulkOutreachSelection.filters,
          total: bulkOutreachSelection.count,
        }),
      );
    } catch (err) {
      setError(translateErrorMessage(err instanceof Error ? err.message : "一键生成并发送失败"));
    } finally {
      setOneClickSending(false);
    }
  }

  async function handleBulkDelete() {
    if (bulkDeleteIds.length === 0) {
      setError("请先勾选要删除的红人");
      return;
    }
    const note =
      selectionMode === "filter_all"
        ? "当前处于全筛选选择状态。为避免误删，本次只删除当前页已勾选的红人。"
        : "删除后，这些红人不会再出现在当前产品的红人库。";
    if (!window.confirm(`${note}\n\n确认删除 ${bulkDeleteIds.length} 个红人吗？`)) {
      return;
    }
    setBulkDeleting(true);
    setError(null);
    try {
      const result = await deleteInfluencers(bulkDeleteIds);
      clearSelection();
      await Promise.all([load(apiFilters, page), loadStats(statsFilters)]);
      if (result.deleted_count === 0) {
        setError("没有删除任何红人，可能这些数据已经被删除或不属于当前产品。");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除红人失败，请稍后再试");
    } finally {
      setBulkDeleting(false);
    }
  }

  const hasActiveFilters =
    activeFilter !== "all" || activePlatform !== "all" || Boolean(searchQuery) || taskFilterActive;
  const listTitle = platformListTitle(activePlatform);

  return (
    <AdminShell title="红人库" description="多平台线索跟进工作台：筛选、联系、记录跟进状态">
      <div className="ops-page influencer-workbench">
      {taskFilterActive ? (
        <div className="influencer-task-alert shrink-0 border-b border-amber-500/30 bg-amber-500/10 px-4 py-2 text-sm lg:px-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              正在查看采集任务入库红人
              {taskNameParam ? ` · ${taskNameParam}` : ""}
              {taskId ? `（任务 #${taskId}）` : ""}
            </div>
            <Button variant="outline" size="sm" asChild>
              <Link href="/influencers">清除任务筛选</Link>
            </Button>
          </div>
        </div>
      ) : null}

      <PlatformOrganizer
        cards={platformCards}
        activePlatform={activePlatform}
        loading={statsLoading}
        onSelect={handlePlatformChange}
      />

      <div className="ops-toolbar influencer-filter-panel shrink-0 !gap-2 !p-2">
        <div className="flex w-full min-w-0 flex-nowrap items-center gap-2 overflow-x-auto [scrollbar-width:thin]">
          {FILTER_GROUPS.map((group) => (
            <div key={group.label} className="ops-filter-group">
              <span className="text-xs font-medium text-slate-500">{group.label}</span>
              <select
                className="h-8 rounded-md border border-slate-200 bg-white px-2 text-xs font-medium text-slate-800 outline-none transition-colors hover:border-slate-300 focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
                value={group.items.includes(activeFilter) ? activeFilter : ""}
                onChange={(event) => {
                  const value = event.target.value as QuickFilter;
                  if (value) handleFilterChange(value);
                }}
                disabled={loading}
                aria-label={`${group.label}筛选`}
              >
                <option value="">全部</option>
                {group.items.map((key) => (
                  <option key={key} value={key}>
                    {FILTER_LABELS[key]}
                  </option>
                ))}
              </select>
            </div>
          ))}
        </div>
        <div className="flex min-w-[144px] items-center gap-2 sm:max-w-[160px]">
          <Input
            placeholder="操作人"
            value={operatorName}
            onChange={(e) => setOperatorName(e.target.value)}
          />
        </div>
        <div className="flex min-w-[280px] flex-1 items-center gap-2 lg:max-w-md">
          <Input
            placeholder="搜索昵称 / 用户名"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSearch()}
          />
          <Button variant="outline" size="icon" onClick={handleSearch} disabled={loading} title="搜索">
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
          variant="outline"
          onClick={() => {
            void downloadInfluencerExport(exportFilters).catch((err) =>
              setError(err instanceof Error ? err.message : "导出失败"),
            );
          }}
        >
          <Download className="h-4 w-4" />
          导出 Excel
        </Button>
        {hasActiveFilters ? (
          <Button variant="ghost" size="sm" onClick={clearAllFilters}>
            清除筛选
          </Button>
        ) : null}
      </div>

      <div className="min-h-0 flex-1 overflow-hidden">
      {error ? <ErrorAlert message={error} className="influencer-inline-message mb-3" /> : null}
      {undoLead ? (
        <div className="influencer-inline-message mb-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border bg-muted/40 px-4 py-2 text-sm">
          <span>状态已更新，可撤销最近一次黑名单/无效操作</span>
          <Button size="sm" variant="outline" onClick={() => void handleUndoLead()}>
            撤销
          </Button>
        </div>
      ) : null}
      {hasSelection ? (
        <div className="influencer-selection-bar mb-2 flex flex-wrap items-center justify-between gap-2 rounded-md border border-primary/25 bg-primary/5 px-3 py-2 text-sm">
          <div>
            {selectionMode === "filter_all" ? (
              <>已选择当前筛选全部 {total} 个红人</>
            ) : (
              <>已选择 {currentPageSelectedIds.length} 个红人（当前页）</>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              disabled={oneClickSending}
              onClick={() => void handleOneClickGenerateAndSend()}
            >
              {oneClickSending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Mail className="h-4 w-4" />}
              一键生成并发送邮件 ({selectedCount})
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                if (bulkOutreachSelection?.selectAll) {
                  clearSelection();
                  router.push(
                    buildOutreachCampaignsUrl({
                      selectAll: true,
                      filters: bulkOutreachSelection.filters,
                      total: bulkOutreachSelection.count,
                      productId,
                    }),
                  );
                } else {
                  const ids = bulkOutreachSelection?.ids ?? currentPageEmailableSelectedIds;
                  if (ids.length === 0) {
                    setError("已勾选的红人没有可用邮箱，请改选有邮箱的红人或先补充邮箱。");
                    return;
                  }
                  clearSelection();
                  router.push(buildOutreachCampaignsUrl({ ids, productId }));
                }
              }}
            >
              <Megaphone className="h-4 w-4" />
              {INFLUENCER_ONE_CLICK_EMAIL_BUTTON_LABEL} ({selectedCount})
            </Button>
            {selectionMode === "filter_all" ? (
              <Button size="sm" variant="outline" onClick={cancelFilterAllSelection}>
                取消当前筛选全选
              </Button>
            ) : null}
            <Button
              size="sm"
              variant="destructive"
              disabled={bulkDeleting || bulkDeleteIds.length === 0}
              onClick={() => void handleBulkDelete()}
            >
              {bulkDeleting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
              删除已选 ({bulkDeleteIds.length})
            </Button>
            <Button size="sm" variant="ghost" onClick={clearSelection}>
              清空选择
            </Button>
          </div>
        </div>
      ) : null}

      <Card className="influencer-list-panel flex h-full min-h-0 flex-col overflow-hidden">
        <CardHeader className="influencer-list-header flex shrink-0 flex-row items-center justify-between gap-3 border-b px-4 py-2">
          <div className="min-w-0">
            <CardTitle className="truncate text-base">{listTitle}</CardTitle>
            <CardDescription className="truncate text-xs">
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
          </div>
          {total > 0 ? (
            <Button
              size="sm"
              variant={selectionMode === "filter_all" ? "default" : "outline"}
              onClick={selectAllFiltered}
              disabled={loading}
              className="shrink-0"
            >
              全选 {total}
            </Button>
          ) : null}
        </CardHeader>
        <CardContent className="flex min-h-0 flex-1 flex-col p-0">
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
                      返回当前品牌全部平台
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
              <div className="ops-table-wrap influencer-table-wrap">
                <table className="ops-table influencer-workbench-table influencer-table min-w-[1120px] table-fixed">
                  <thead>
                    <tr>
                      <th className="w-9">
                        <input
                          type="checkbox"
                          checked={allPageSelected}
                          onChange={toggleSelectAllPage}
                          aria-label="全选当前页"
                        />
                      </th>
                      <th className="ops-sticky-left w-[160px]">账号</th>
                      <th className="w-[70px]">平台</th>
                      <th className="w-[92px]">粉丝 / 互动</th>
                      <th className="w-[160px]">联系方式</th>
                      <th className="w-[170px]">AI 推荐理由</th>
                      <th className="w-[64px]">优先级</th>
                      <th className="w-[96px]">跟进状态</th>
                      <th className="w-[64px]">负责人</th>
                      <th className="w-[80px]">下次跟进</th>
                      <th className="ops-sticky-actions w-[106px] text-right">操作</th>
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
                          className={`influencer-data-row group align-top ${
                            taskFilterActive ? "bg-amber-500/5" : ""
                          }`}
                        >
                          <td className="align-top">
                            <input
                              type="checkbox"
                              checked={selectedIds.has(item.id)}
                              onChange={() => toggleSelect(item.id)}
                              aria-label={`选择 ${item.username}`}
                            />
                          </td>
                          <td className="ops-sticky-left align-top">
                            <div className="flex min-w-0 items-center gap-1.5">
                              <div className="truncate font-medium">{item.display_name || item.username}</div>
                              {freshnessBadges.map((badge) => (
                                <Badge key={badge.label} variant={badge.variant} className="shrink-0 px-1.5 py-0 text-[10px]">
                                  {badge.label}
                                </Badge>
                              ))}
                            </div>
                            <div className="truncate text-xs text-muted-foreground">@{item.username}</div>
                            <div className="mt-0.5 truncate text-[11px] text-muted-foreground">
                              {item.source_discovery_type
                                ? SOURCE_DISCOVERY_LABELS[item.source_discovery_type] ??
                                  item.source_discovery_type
                                : "来源 -"} · 入库 {formatDateTime(item.created_at)}
                            </div>
                          </td>
                          <td className="align-top">
                            <span
                              className={cn(
                                "inline-flex rounded px-1.5 py-0.5 text-[11px] font-medium",
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
                          </td>
                          <td className="align-top tabular-nums">
                            <div className="font-medium">
                              {item.followers_count?.toLocaleString("zh-CN") ?? "-"}
                              <span className="ml-1 text-xs text-muted-foreground">
                                {followersAudienceLabel(item.platform)}
                              </span>
                            </div>
                            <div className="text-xs text-muted-foreground">
                              互动 {formatPercent(item.engagement_rate)}
                            </div>
                          </td>
                          <td className="align-top text-xs">
                            <span className={cn("line-clamp-1", email ? "" : "text-amber-700")}>
                              {resolveContactSummary(item)}
                            </span>
                            <div className="mt-1 truncate text-muted-foreground">
                              可信度 {resolveCredibility(item)}
                              {item.email_source ? ` · ${resolveEmailSource(item)}` : ""}
                            </div>
                          </td>
                          <td className="max-w-[220px] align-top">
                            <p className="line-clamp-2 text-xs text-muted-foreground">
                              {aiReasonPreview(item)}
                            </p>
                          </td>
                          <td className="align-top">
                            <span
                              className={`inline-flex rounded px-1.5 py-0.5 text-xs font-medium ${priorityBadgeClass(item.lead_priority || item.final_priority)}`}
                            >
                              {item.lead_priority || item.final_priority || "-"}
                            </span>
                          </td>
                          <td className="align-top">
                            <Badge variant={leadStatusVariant(status)}>
                              {leadStatusLabel(status)}
                            </Badge>
                            {item.email_sent ? (
                              <div className="mt-1">
                                <Badge variant="success" className="text-[10px] px-1.5 py-0">
                                  已发送邮件
                                </Badge>
                                {item.last_email_sent_at ? (
                                  <div className="mt-0.5 text-[11px] text-muted-foreground">
                                    {formatDateTime(item.last_email_sent_at)}
                                  </div>
                                ) : null}
                              </div>
                            ) : null}
                            {contacted ? (
                              <div className="mt-1 text-xs text-muted-foreground">已联系</div>
                            ) : null}
                          </td>
                          <td className="align-top text-xs">
                            {item.owner_name || item.owner || "-"}
                          </td>
                          <td className="align-top text-xs">{formatDate(item.next_follow_up_at)}</td>
                          <td className="ops-sticky-actions align-top">
                            <div className="influencer-row-actions flex justify-end gap-1">
                              <Button
                                size="icon"
                                variant="ghost"
                                className="ops-icon-button"
                                disabled={busy}
                                onClick={() => handleLeadAction(item, { lead_status: "to_contact" })}
                                title="待联系"
                              >
                                <UserCheck className="h-4 w-4" />
                              </Button>
                              <Button
                                size="icon"
                                variant="ghost"
                                className="ops-icon-button"
                                disabled={busy}
                                onClick={() => handleLeadAction(item, { lead_status: "contacted" })}
                                title="已联系"
                              >
                                <Mail className="h-4 w-4" />
                              </Button>
                              <Button
                                size="icon"
                                variant="ghost"
                                className="ops-icon-button"
                                disabled={busy}
                                onClick={() => handleLeadAction(item, { lead_status: "replied" })}
                                title="已回复"
                              >
                                <Megaphone className="h-4 w-4" />
                              </Button>
                              <Button
                                size="icon"
                                variant="ghost"
                                className="ops-icon-button"
                                disabled={busy}
                                onClick={() => handleLeadAction(item, { lead_status: "interested" })}
                                title="感兴趣"
                              >
                                <Bot className="h-4 w-4" />
                              </Button>
                              <Button
                                size="icon"
                                variant="ghost"
                                className="ops-icon-button text-red-600 hover:bg-red-50 hover:text-red-700"
                                disabled={busy}
                                onClick={() =>
                                  handleLeadAction(item, {
                                    lead_status: "invalid",
                                    invalid_reason: "业务标记无效",
                                  }, {
                                    confirmMessage: "确认将该红人标记为无效？后续邮件活动将跳过。",
                                  })
                                }
                                title="标记无效"
                              >
                                <UserX className="h-4 w-4" />
                              </Button>
                              <Button
                                size="icon"
                                variant="ghost"
                                className="ops-icon-button text-red-600 hover:bg-red-50 hover:text-red-700"
                                disabled={busy}
                                onClick={() =>
                                  handleLeadAction(item, {
                                    lead_status: "blacklisted",
                                    blacklist_reason: "业务标记黑名单",
                                  }, {
                                    confirmMessage: "确认将该红人加入黑名单？后续邮件活动将跳过。",
                                  })
                                }
                                title="加入黑名单"
                              >
                                <UserX className="h-4 w-4" />
                              </Button>
                              {email ? (
                                <Button
                                  size="icon"
                                  variant="ghost"
                                  className="ops-icon-button"
                                  onClick={() => copyEmail(email)}
                                  title="复制邮箱"
                                >
                                  <Copy className="h-3.5 w-3.5" />
                                </Button>
                              ) : null}
                              <Button
                                size="icon"
                                variant="ghost"
                                className="ops-icon-button"
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
                              {email ? (
                                <Button
                                  size="icon"
                                  variant="ghost"
                                  className="ops-icon-button"
                                  disabled={busy}
                                  onClick={() => setOutreachEmailTarget(item)}
                                  title="AI 定制邮件"
                                >
                                  <Mail className="h-4 w-4" />
                                </Button>
                              ) : null}
                              <Button
                                size="icon"
                                variant="ghost"
                                className="ops-icon-button"
                                disabled={busy}
                                onClick={() => setScriptRecommendTarget(item)}
                                title="AI 推荐话术"
                              >
                                <Bot className="h-4 w-4" />
                              </Button>
                              <Button variant="ghost" size="icon" className="ops-icon-button text-xs" asChild title="详情">
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
                <div className="flex shrink-0 items-center justify-between gap-3 border-t px-4 py-2">
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
      </div>

      {scriptRecommendTarget ? (
        <ScriptRecommendDialog
          influencer={scriptRecommendTarget}
          open
          onClose={() => setScriptRecommendTarget(null)}
        />
      ) : null}

      {outreachEmailTarget ? (
        <OutreachEmailDialog
          influencer={outreachEmailTarget}
          open
          onClose={() => setOutreachEmailTarget(null)}
          onSent={() => {
            void load(apiFilters, page);
            void loadStats(statsFilters);
          }}
        />
      ) : null}
      </div>
    </AdminShell>
  );
}
