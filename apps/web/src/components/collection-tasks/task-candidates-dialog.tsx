"use client";

import { useCallback, useEffect, useState } from "react";
import { Copy, Download, ExternalLink, Loader2, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  COLLECTION_TASK_POLL_INTERVAL_MS,
  downloadCollectionTaskCandidatesExport,
  enrichLinkSeedProfiles,
  enrichYoutubeCandidateEmail,
  enrichYoutubeCandidateEmails,
  fetchCollectionTaskCandidates,
  isCollectionTaskRunning,
  recrawlCollectionTaskCandidate,
  recrawlCollectionTaskFailedCandidates,
  type CollectionTask,
  type CollectionTaskCandidate,
} from "@/lib/api";
import {
  CANDIDATE_FAILURE_LABELS,
  CANDIDATE_SOURCE_TYPE_LABELS,
  CANDIDATE_STATUS_LABELS,
  candidateEnrichmentCandidatesSummary,
  candidateProfileSnapshotSummary,
  candidateSeedEnrichmentStatus,
  candidateSeedPlatformLabel,
  platformLabel,
} from "@/lib/labels";
import { buildTaskResultBreakdown } from "@/lib/collection-task-progress";

type TaskCandidatesDialogProps = {
  task: CollectionTask | null;
  open: boolean;
  onClose: () => void;
};

const STATUS_FILTER_OPTIONS = [
  { value: "", label: "全部状态" },
  { value: "inserted", label: "已入库" },
  { value: "not_inserted", label: "未入库" },
  { value: "pending_profile", label: "待补采" },
  { value: "profile_failed", label: "补采失败" },
  { value: "filtered_out", label: "已过滤" },
  { value: "duplicate", label: "重复" },
];

const QUALITY_FILTER_OPTIONS = [
  { value: "", label: "高价值 / 全部" },
  { value: "high", label: "仅高价值" },
  { value: "low", label: "非高价值" },
];

const CONTACT_FILTER_OPTIONS = [
  { value: "", label: "联系方式 / 全部" },
  { value: "email", label: "有邮箱" },
  { value: "contact", label: "有联系方式" },
  { value: "pending", label: "待补采" },
  { value: "missing", label: "无联系方式" },
];

const PLATFORM_FILTER_OPTIONS = [
  { value: "", label: "全部平台" },
  { value: "instagram", label: "Instagram" },
  { value: "youtube", label: "YouTube" },
  { value: "tiktok", label: "TikTok" },
  { value: "facebook", label: "Facebook" },
  { value: "pinterest", label: "Pinterest" },
  { value: "ltk", label: "LTK" },
  { value: "shopmy", label: "ShopMy" },
];

const SOURCE_TYPE_FILTER_OPTIONS = [
  { value: "", label: "全部来源类型" },
  { value: "hashtag_post_author", label: "Hashtag 帖子作者" },
  { value: "keyword_post_author", label: "关键词帖子作者" },
  { value: "comment_author", label: "评论区用户" },
  { value: "input_profile", label: "输入主页" },
  { value: "input_post", label: "输入帖子" },
  { value: "input_reel", label: "输入 Reel" },
  { value: "related_profile", label: "相似账号" },
  { value: "competitor_product_post_author", label: "竞品商品帖子作者" },
];

const SOURCE_DISCOVERY_FILTER_OPTIONS = [
  { value: "", label: "全部发现方式" },
  { value: "post_author", label: "post_author" },
  { value: "comment_author", label: "comment_author" },
  { value: "url_profile", label: "url_profile" },
];

const FAILURE_FILTER_OPTIONS = [
  { value: "", label: "全部原因" },
  { value: "below_min_followers", label: "粉丝未达标" },
  { value: "below_min_engagement_rate", label: "互动率未达标" },
  { value: "above_max_followers", label: "粉丝超过上限" },
  { value: "missing_engagement_rate", label: "互动率缺失" },
  { value: "missing_email", label: "未发现邮箱" },
  { value: "missing_contact", label: "未发现联系方式" },
  { value: "excluded_keyword", label: "排除词" },
  { value: "profile_fetch_failed", label: "补采失败" },
  { value: "private_account", label: "私密账号" },
  { value: "missing_profile_detail", label: "数据缺失" },
  { value: "duplicate", label: "重复" },
];

function contactStatusLabel(candidate: CollectionTaskCandidate): string {
  if (candidate.contact_status === "pending") return "待补采";
  if (candidate.has_email) return "有邮箱";
  if (candidate.has_contact) return "有联系方式";
  if (candidate.contact_status === "missing") return "无联系方式";
  return "-";
}

function blockedReason(candidate: CollectionTaskCandidate): string {
  if (candidate.insert_blocked_reason) return candidate.insert_blocked_reason;
  if (candidate.failure_reason) {
    return CANDIDATE_FAILURE_LABELS[candidate.failure_reason] ?? candidate.failure_reason;
  }
  return "-";
}

function formatFollowers(value: number | null): string {
  if (value == null) return "-";
  return value.toLocaleString("zh-CN");
}

function metaValue(meta: CollectionTaskCandidate["source_meta"], key: string): unknown {
  return meta ? (meta as Record<string, unknown>)[key] : undefined;
}

function metaString(meta: CollectionTaskCandidate["source_meta"], key: string): string | null {
  const value = metaValue(meta, key);
  return typeof value === "string" ? value : null;
}

function metaStringList(meta: CollectionTaskCandidate["source_meta"], key: string): string[] {
  const value = metaValue(meta, key);
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function metaBoolean(meta: CollectionTaskCandidate["source_meta"], key: string): boolean {
  return metaValue(meta, key) === true;
}

function formatEngagement(value: number | null): string {
  if (value == null) return "-";
  return `${value.toFixed(2)}%`;
}

function sourceLabel(candidate: CollectionTaskCandidate): string {
  if (candidate.source_type) {
    return CANDIDATE_SOURCE_TYPE_LABELS[candidate.source_type] ?? candidate.source_type;
  }
  if (candidate.source_hashtag) return `Hashtag ${candidate.source_hashtag}`;
  if (candidate.source_keyword) return `关键词 ${candidate.source_keyword}`;
  return candidate.source_discovery_type ?? "-";
}

const RECOVERABLE_RECRAWL_REASONS = new Set([
  "missing_profile_detail",
  "profile_fetch_failed",
  "api_failed",
  "unknown",
  "scraper_blocked",
  "provider_timeout",
  "timeout",
]);

const UNRECOVERABLE_RECRAWL_REASONS = new Set([
  "private_account",
  "disabled_or_deleted",
  "invalid_username",
  "below_min_followers",
  "below_min_engagement_rate",
  "above_max_followers",
  "duplicate",
]);

function canRecrawlCandidate(candidate: CollectionTaskCandidate): boolean {
  if (!candidate.profile_url) return false;
  if (!["profile_failed", "not_inserted", "pending_profile"].includes(candidate.status)) {
    return false;
  }
  const reason = (candidate.failure_reason ?? "").toLowerCase();
  const detail = (candidate.failure_detail ?? "").toLowerCase();
  if (UNRECOVERABLE_RECRAWL_REASONS.has(reason)) return false;
  if (/private|invalid url|invalid username|duplicate|below_min_followers/.test(detail)) return false;
  return (
    RECOVERABLE_RECRAWL_REASONS.has(reason) ||
    /主页数据缺失|未获取到主页数据|补采失败|missing_profile_detail|profile_failed|provider timeout|timeout|post_author_missing/i.test(
      detail,
    )
  );
}

function canEnrichYoutubeEmail(candidate: CollectionTaskCandidate): boolean {
  return (
    (candidate.platform ?? "").toLowerCase() === "youtube" &&
    Boolean(candidate.profile_url) &&
    candidate.has_email !== true
  );
}

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    /* ignore */
  }
}

export function TaskCandidatesDialog({ task, open, onClose }: TaskCandidatesDialogProps) {
  const [items, setItems] = useState<CollectionTaskCandidate[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(1);
  const [loading, setLoading] = useState(false);
  const [filtersReady, setFiltersReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState("");
  const [failureFilter, setFailureFilter] = useState("");
  const [sourceTypeFilter, setSourceTypeFilter] = useState("");
  const [sourceDiscoveryFilter, setSourceDiscoveryFilter] = useState("");
  const [qualityFilter, setQualityFilter] = useState("");
  const [contactFilter, setContactFilter] = useState("");
  const [platformFilter, setPlatformFilter] = useState("");
  const [minFollowersFilter, setMinFollowersFilter] = useState("");
  const [maxFollowersFilter, setMaxFollowersFilter] = useState("");
  const [minEngagementFilter, setMinEngagementFilter] = useState("");
  const [maxEngagementFilter, setMaxEngagementFilter] = useState("");
  const [search, setSearch] = useState("");
  const [exportError, setExportError] = useState<string | null>(null);
  const [statsMismatch, setStatsMismatch] = useState<string | null>(null);
  const [recrawlError, setRecrawlError] = useState<string | null>(null);
  const [recrawlingCandidateId, setRecrawlingCandidateId] = useState<number | null>(null);
  const [recrawlingBatch, setRecrawlingBatch] = useState(false);
  const [enrichingEmailCandidateId, setEnrichingEmailCandidateId] = useState<number | null>(null);
  const [enrichingEmailBatch, setEnrichingEmailBatch] = useState(false);
  const taskId = task?.id;
  const taskResultCount = task?.inserted_count ?? task?.result_count ?? 0;

  useEffect(() => {
    let cancelled = false;
    queueMicrotask(() => {
      if (cancelled) return;
      if (!open || !taskId) {
        setFiltersReady(false);
        return;
      }
      setFiltersReady(false);
      setExportError(null);
      setRecrawlError(null);
      setStatsMismatch(null);
      setPage(1);
      setStatusFilter(taskResultCount > 0 ? "inserted" : "");
      setFiltersReady(true);
    });
    return () => {
      cancelled = true;
    };
  }, [open, taskId]);

  const buildCandidateQuery = useCallback((pageNumber = page) => {
    const minFollowers = minFollowersFilter.trim() ? Number(minFollowersFilter) : undefined;
    const maxFollowers = maxFollowersFilter.trim() ? Number(maxFollowersFilter) : undefined;
    const minEngagement = minEngagementFilter.trim() ? Number(minEngagementFilter) : undefined;
    const maxEngagement = maxEngagementFilter.trim() ? Number(maxEngagementFilter) : undefined;
    return {
      page: pageNumber,
      page_size: 20,
      status: statusFilter || undefined,
      failure_reason: failureFilter || undefined,
      source_type: sourceTypeFilter || undefined,
      source_discovery_type: sourceDiscoveryFilter || undefined,
      platform: platformFilter || undefined,
      high_value: qualityFilter === "high" ? true : qualityFilter === "low" ? false : undefined,
      has_email: contactFilter === "email" ? true : undefined,
      has_contact: contactFilter === "contact" ? true : undefined,
      contact_status:
        contactFilter === "pending" ? "pending" : contactFilter === "missing" ? "missing" : undefined,
      min_followers_count:
        minFollowers != null && Number.isFinite(minFollowers) ? minFollowers : undefined,
      max_followers_count:
        maxFollowers != null && Number.isFinite(maxFollowers) ? maxFollowers : undefined,
      min_engagement_rate:
        minEngagement != null && Number.isFinite(minEngagement) ? minEngagement : undefined,
      max_engagement_rate:
        maxEngagement != null && Number.isFinite(maxEngagement) ? maxEngagement : undefined,
      search: search.trim() || undefined,
    };
  }, [
    page,
    statusFilter,
    failureFilter,
    sourceTypeFilter,
    sourceDiscoveryFilter,
    platformFilter,
    qualityFilter,
    contactFilter,
    minFollowersFilter,
    maxFollowersFilter,
    minEngagementFilter,
    maxEngagementFilter,
    search,
  ]);

  const buildExportQuery = useCallback(() => {
    const { page: droppedPage, page_size: droppedPageSize, ...rest } = buildCandidateQuery(1);
    void droppedPage;
    void droppedPageSize;
    return rest;
  }, [buildCandidateQuery]);

  const refreshCandidates = useCallback(async () => {
    if (!task) return;
    setError(null);
    const result = await fetchCollectionTaskCandidates(task.id, buildCandidateQuery());
    setItems(result.items);
    setTotal(result.total);
    setPages(result.pages);
  }, [task, buildCandidateQuery]);

  useEffect(() => {
    if (!open || !task || !filtersReady) return;
    const activeTask = task;
    let cancelled = false;

    async function loadCandidates(silent = false) {
      if (!silent) setLoading(true);
      setError(null);
      try {
        const result = await fetchCollectionTaskCandidates(activeTask.id, buildCandidateQuery());
        if (cancelled) return;
        setItems(result.items);
        setTotal(result.total);
        setPages(result.pages);
        const insertedExpected = activeTask.inserted_count ?? activeTask.result_count ?? 0;
        if (
          statusFilter === "inserted" &&
          insertedExpected > 0 &&
          result.total === 0
        ) {
          setStatsMismatch(
            "顶部「已入库」是任务统计数字；当前候选池明细表为空。常见于手动停止时还在解析主页、尚未真正写入候选明细。请到红人库查看，或重新运行任务完成入库；切换「全部状态」若仍为 0，说明这次没有可展示明细。",
          );
        } else {
          setStatsMismatch(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "加载候选列表失败");
        }
      } finally {
        if (!cancelled && !silent) setLoading(false);
      }
    }

    void loadCandidates(items.length > 0);
    const pollId = isCollectionTaskRunning(activeTask) || activeTask.status === "paused"
      ? window.setInterval(() => {
          void loadCandidates(true);
        }, COLLECTION_TASK_POLL_INTERVAL_MS)
      : undefined;

    return () => {
      cancelled = true;
      if (pollId !== undefined) window.clearInterval(pollId);
    };
  }, [
    taskId,
    open,
    filtersReady,
    page,
    statusFilter,
    failureFilter,
    sourceTypeFilter,
    sourceDiscoveryFilter,
    qualityFilter,
    contactFilter,
    platformFilter,
    minFollowersFilter,
    maxFollowersFilter,
    minEngagementFilter,
    maxEngagementFilter,
    search,
    task?.status,
    buildCandidateQuery,
  ]);
  function resetFilters() {
    setPage(1);
  }

  async function handleRecrawlCandidate(candidate: CollectionTaskCandidate) {
    if (!task) return;
    setRecrawlError(null);
    setRecrawlingCandidateId(candidate.id);
    try {
      await recrawlCollectionTaskCandidate(task.id, candidate.id);
      await refreshCandidates();
    } catch (err) {
      setRecrawlError(err instanceof Error ? err.message : "重采失败");
    } finally {
      setRecrawlingCandidateId(null);
    }
  }

  async function handleRecrawlFailedCandidates() {
    if (!task) return;
    setRecrawlError(null);
    setRecrawlingBatch(true);
    try {
      await recrawlCollectionTaskFailedCandidates(task.id, { concurrency: 3 });
      await refreshCandidates();
    } catch (err) {
      setRecrawlError(err instanceof Error ? err.message : "批量重采失败");
    } finally {
      setRecrawlingBatch(false);
    }
  }

  async function handleEnrichYoutubeEmail(candidate: CollectionTaskCandidate) {
    if (!task) return;
    setRecrawlError(null);
    setEnrichingEmailCandidateId(candidate.id);
    try {
      await enrichYoutubeCandidateEmail(task.id, candidate.id);
      await refreshCandidates();
    } catch (err) {
      setRecrawlError(err instanceof Error ? err.message : "补邮箱失败");
    } finally {
      setEnrichingEmailCandidateId(null);
    }
  }

  async function handleBatchEnrichYoutubeEmails() {
    if (!task) return;
    setRecrawlError(null);
    setEnrichingEmailBatch(true);
    try {
      await enrichYoutubeCandidateEmails(task.id, { limit: 20 });
      await refreshCandidates();
    } catch (err) {
      setRecrawlError(err instanceof Error ? err.message : "批量补 YouTube 邮箱失败");
    } finally {
      setEnrichingEmailBatch(false);
    }
  }

  if (!open || !task) return null;

  const showCompetitorColumns = task.collection_mode === "competitor_product";
  const seedEnrichment = (task.run_checkpoint?.link_seed_enrichment ?? null) as
    | { attempted?: number; social_profiles_found?: number; low_value_seed_count?: number }
    | null;
  const canEnrichLinkSeeds =
    task.collection_mode === "link_import" &&
    (task.platforms ?? []).some((p) => ["ltk", "shopmy", "pinterest"].includes(String(p).toLowerCase()));
  const breakdown = buildTaskResultBreakdown(task);

  const exportQuery = buildExportQuery();

  const statusMeta = (status: string) =>
    CANDIDATE_STATUS_LABELS[status] ?? { label: status, variant: "secondary" as const };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="task-candidates-title"
        className="flex h-[90vh] max-h-[760px] w-full max-w-6xl flex-col rounded-lg border bg-background shadow-lg"
      >
        <div className="flex items-start justify-between gap-4 border-b px-4 py-3">
          <div>
            <h2 id="task-candidates-title" className="text-lg font-semibold">
              候选池 · {task.name}
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              {isCollectionTaskRunning(task) ? (
                <span className="inline-flex items-center gap-1.5">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  采集中，数据自动刷新…
                </span>
              ) : null}{" "}
              <span className="inline-flex flex-wrap items-center gap-1.5">
                {breakdown.primary[0]}
                {breakdown.highValue ? (
                  <Badge variant="success" className="text-[10px]">高价值</Badge>
                ) : null}
                {breakdown.singleLinkImport ? (
                  <Badge variant="outline" className="text-[10px]">单条链接导入</Badge>
                ) : null}
              </span>
              {" · "}
              {breakdown.funnel.join(" → ")}
              {(task.email_count ?? 0) > 0 || (task.missing_contact_count ?? 0) > 0 || (task.failed_count ?? task.profile_failed_count ?? 0) > 0 ? (
                <> · {breakdown.contacts.join(" / ")}</>
              ) : null}
              {(task.filtered_below_min_followers_count ?? 0) > 0
                ? ` · 粉丝未达标 ${task.filtered_below_min_followers_count}`
                : ""}
              {(task.filtered_excluded_keyword_count ?? 0) > 0
                ? ` · 排除词 ${task.filtered_excluded_keyword_count}`
                : ""}
              {seedEnrichment?.attempted
                ? ` · 导购 seed 补全：尝试 ${seedEnrichment.attempted} 条，找到社媒 ${seedEnrichment.social_profiles_found ?? 0} 个`
                : ""}
              {canEnrichLinkSeeds && !isCollectionTaskRunning(task)
                ? " · 仅有导购 seed 链接无法判断红人价值，可继续补采 Instagram/TikTok/YouTube/Facebook"
                : ""}
              {breakdown.reason ? (
                <span className="ml-1 line-clamp-2" title={breakdown.reason}>{breakdown.reason}</span>
              ) : null}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {canEnrichLinkSeeds ? (
              <Button
                size="sm"
                variant="secondary"
                className="h-8 gap-1.5"
                disabled={isCollectionTaskRunning(task)}
                title="通过 Instagram/TikTok/YouTube/Facebook 反查补全导购 seed 资料"
                onClick={() => {
                  void enrichLinkSeedProfiles(task.id).catch(() => undefined);
                }}
              >
                继续补采社媒资料
              </Button>
            ) : null}
            <Button
              size="sm"
              variant="secondary"
              className="h-8 gap-1.5"
              disabled={isCollectionTaskRunning(task) || enrichingEmailBatch}
              title="批量补当前任务下 YouTube 缺邮箱候选，默认最多 20 条"
              onClick={() => {
                void handleBatchEnrichYoutubeEmails();
              }}
            >
              {enrichingEmailBatch ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
              批量补 YouTube 邮箱
            </Button>
            <Button
              size="sm"
              variant="secondary"
              className="h-8 gap-1.5"
              disabled={isCollectionTaskRunning(task) || recrawlingBatch}
              title="批量重采当前任务下可恢复的补采失败候选"
              onClick={() => {
                void handleRecrawlFailedCandidates();
              }}
            >
              {recrawlingBatch ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
              批量重采失败候选
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="h-8 gap-1.5"
              title="导出当前筛选条件下的候选池 Excel"
              onClick={() => {
                setExportError(null);
                void downloadCollectionTaskCandidatesExport(task.id, exportQuery).catch((err) => {
                  setExportError(
                    err instanceof Error
                      ? err.message
                      : "导出失败，请清空筛选或切换到「全部状态」后重试",
                  );
                });
              }}
            >
              <Download className="h-3.5 w-3.5" />
              导出 Excel
            </Button>
            <Button variant="ghost" size="sm" className="h-8 w-8 p-0" onClick={onClose} aria-label="关闭">
              <X className="h-4 w-4" />
            </Button>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2 border-b px-4 py-3">
          <Input
            className="h-8 w-48"
            placeholder="搜索用户名/链接"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              resetFilters();
            }}
          />
          <select
            className="h-8 rounded-md border bg-background px-2 text-sm"
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value);
              resetFilters();
            }}
          >
            {STATUS_FILTER_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          <select
            className="h-8 rounded-md border bg-background px-2 text-sm"
            value={failureFilter}
            onChange={(e) => {
              setFailureFilter(e.target.value);
              resetFilters();
            }}
          >
            {FAILURE_FILTER_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          <select
            className="h-8 rounded-md border bg-background px-2 text-sm"
            value={sourceTypeFilter}
            onChange={(e) => {
              setSourceTypeFilter(e.target.value);
              resetFilters();
            }}
          >
            {SOURCE_TYPE_FILTER_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          <select
            className="h-8 rounded-md border bg-background px-2 text-sm"
            value={sourceDiscoveryFilter}
            onChange={(e) => {
              setSourceDiscoveryFilter(e.target.value);
              resetFilters();
            }}
          >
            {SOURCE_DISCOVERY_FILTER_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          <select
            className="h-8 rounded-md border bg-background px-2 text-sm"
            value={qualityFilter}
            onChange={(e) => {
              setQualityFilter(e.target.value);
              resetFilters();
            }}
          >
            {QUALITY_FILTER_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          <select
            className="h-8 rounded-md border bg-background px-2 text-sm"
            value={contactFilter}
            onChange={(e) => {
              setContactFilter(e.target.value);
              resetFilters();
            }}
          >
            {CONTACT_FILTER_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          <select
            className="h-8 rounded-md border bg-background px-2 text-sm"
            value={platformFilter}
            onChange={(e) => {
              setPlatformFilter(e.target.value);
              resetFilters();
            }}
          >
            {PLATFORM_FILTER_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          <Input
            className="h-8 w-28"
            type="number"
            min={0}
            placeholder="最低粉丝"
            value={minFollowersFilter}
            onChange={(e) => {
              setMinFollowersFilter(e.target.value);
              resetFilters();
            }}
          />
          <Input
            className="h-8 w-28"
            type="number"
            min={0}
            placeholder="最高粉丝"
            value={maxFollowersFilter}
            onChange={(e) => {
              setMaxFollowersFilter(e.target.value);
              resetFilters();
            }}
          />
          <Input
            className="h-8 w-24"
            type="number"
            min={0}
            step={0.01}
            placeholder="最低互动率%"
            value={minEngagementFilter}
            onChange={(e) => {
              setMinEngagementFilter(e.target.value);
              resetFilters();
            }}
          />
          <Input
            className="h-8 w-24"
            type="number"
            min={0}
            step={0.01}
            placeholder="最高互动率%"
            value={maxEngagementFilter}
            onChange={(e) => {
              setMaxEngagementFilter(e.target.value);
              resetFilters();
            }}
          />
          <span className="text-xs text-muted-foreground">共 {total} 条</span>
        </div>

        <div className="min-h-0 flex-1 overflow-auto px-4 py-2">
          {exportError ? <p className="py-2 text-sm text-destructive">{exportError}</p> : null}
          {recrawlError ? <p className="py-2 text-sm text-destructive">{recrawlError}</p> : null}
          {statsMismatch ? (
            <p className="mb-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
              {statsMismatch}
            </p>
          ) : null}
          {error ? <p className="py-4 text-sm text-destructive">{error}</p> : null}
          {loading ? (
            <div className="flex items-center justify-center py-12 text-muted-foreground">
              <Loader2 className="mr-2 h-5 w-5 animate-spin" />
              加载中…
            </div>
          ) : items.length === 0 ? (
            <p className="py-8 text-center text-sm text-muted-foreground">
              {statusFilter
                ? "当前筛选无候选记录。请清空筛选或切换到「全部状态」。"
                : "暂无候选记录。任务运行完成后会写入发现、补采失败与过滤账号。"}
            </p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <th className="py-2 pr-2 font-medium">账号</th>
                  <th className="py-2 pr-2 font-medium">来源</th>
                  {showCompetitorColumns ? (
                    <th className="py-2 pr-2 font-medium">竞品命中</th>
                  ) : null}
                  <th className="py-2 pr-2 font-medium">粉丝</th>
                  <th className="py-2 pr-2 font-medium">互动率</th>
                  <th className="py-2 pr-2 font-medium">联系方式</th>
                  <th className="py-2 pr-2 font-medium">高价值</th>
                  <th className="py-2 pr-2 font-medium">状态</th>
                  <th className="py-2 pr-2 font-medium">未入库原因</th>
                  <th className="py-2 pr-2 font-medium">来源帖/评论</th>
                  <th className="py-2 pr-2 font-medium">来源输入链接</th>
                  <th className="py-2 font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {items.map((c) => {
                  const sm = statusMeta(c.status);
                  const meta = c.source_meta;
                  const reasonLabel = blockedReason(c);
                  const sourceCaption = metaString(meta, "source_caption");
                  const asin = metaString(meta, "amazon_asin") ?? metaString(meta, "asin");
                  const brand = metaString(meta, "amazon_brand") ?? metaString(meta, "brand");
                  const selectedReason = metaString(meta, "selected_reason");
                  const matchType = metaString(meta, "match_type");
                  const matchedPhrases = metaStringList(meta, "matched_phrases");
                  const matchedKeywords = matchedPhrases.length ? matchedPhrases : metaStringList(meta, "matched_keywords");
                  const matchReasons = metaStringList(meta, "match_reasons");
                  const sourceRef =
                    sourceCaption?.slice(0, 80) ||
                    c.source_caption?.slice(0, 80) ||
                    c.source_comment_text?.slice(0, 40) ||
                    c.source_post_url ||
                    c.source_comment_url ||
                    "-";
                  return (
                    <tr key={c.id} className="border-b align-top last:border-0">
                      <td className="py-2 pr-2">
                        <div className="font-medium">@{c.username}</div>
                        <div className="text-xs text-muted-foreground">
                          平台: {platformLabel(c.platform)}
                          {candidateSeedPlatformLabel(c)
                            ? ` · 来源: ${candidateSeedPlatformLabel(c)}`
                            : ""}
                        </div>
                        {candidateSeedEnrichmentStatus(c) ? (
                          <div className="mt-0.5 text-xs text-muted-foreground">
                            {candidateSeedEnrichmentStatus(c)}
                          </div>
                        ) : null}
                        {candidateEnrichmentCandidatesSummary(c) ? (
                          <div
                            className="mt-0.5 text-xs text-muted-foreground"
                            title={candidateEnrichmentCandidatesSummary(c) ?? ""}
                          >
                            补全尝试: {candidateEnrichmentCandidatesSummary(c)}
                          </div>
                        ) : null}
                        {candidateProfileSnapshotSummary(c) ? (
                          <div
                            className="mt-0.5 line-clamp-2 text-xs text-muted-foreground"
                            title={candidateProfileSnapshotSummary(c) ?? ""}
                          >
                            详情快照: {candidateProfileSnapshotSummary(c)}
                          </div>
                        ) : null}
                        <div
                          className="max-w-[140px] truncate text-xs text-muted-foreground"
                          title={c.profile_url}
                        >
                          {c.profile_url}
                        </div>
                      </td>
                      <td className="py-2 pr-2 text-xs">{sourceLabel(c)}</td>
                      {showCompetitorColumns ? (
                        <td className="max-w-[220px] py-2 pr-2 text-xs">
                          {meta ? (
                            <div className="space-y-1">
                              {asin ? <div>ASIN: {asin}</div> : null}
                              {brand ? <div>品牌: {brand}</div> : null}
                              {matchType ? (
                                <div className="text-muted-foreground">匹配: {matchType}</div>
                              ) : null}
                              {matchedKeywords.length ? (
                                <div className="text-muted-foreground">
                                  命中: {matchedKeywords.slice(0, 4).join("、")}
                                </div>
                              ) : null}
                              {selectedReason ? (
                                <div className="text-muted-foreground">{selectedReason}</div>
                              ) : null}
                              {matchReasons.length ? (
                                <div className="text-muted-foreground">
                                  {matchReasons.slice(0, 3).join("；")}
                                </div>
                              ) : null}
                              {metaBoolean(meta, "suspected_collab") ? (
                                <Badge variant="outline" className="text-[10px]">
                                  疑似合作
                                </Badge>
                              ) : null}
                            </div>
                          ) : (
                            "-"
                          )}
                        </td>
                      ) : null}
                      <td className="py-2 pr-2 whitespace-nowrap">{formatFollowers(c.followers_count)}</td>
                      <td className="py-2 pr-2 whitespace-nowrap">{formatEngagement(c.engagement_rate)}</td>
                      <td className="py-2 pr-2 text-xs whitespace-nowrap">{contactStatusLabel(c)}</td>
                      <td className="py-2 pr-2">
                        {c.is_high_value == null ? (
                          <span className="text-xs text-muted-foreground">-</span>
                        ) : c.is_high_value ? (
                          <Badge variant="success" className="text-xs">
                            高价值
                          </Badge>
                        ) : (
                          <Badge variant="secondary" className="text-xs">
                            未达标
                          </Badge>
                        )}
                      </td>
                      <td className="py-2 pr-2">
                        <Badge variant={sm.variant} className="text-xs">
                          {sm.label}
                        </Badge>
                      </td>
                      <td className="max-w-[200px] py-2 pr-2">
                        <div className="text-xs">{reasonLabel}</div>
                        {c.failure_detail ? (
                          <div className="mt-0.5 line-clamp-2 text-xs text-muted-foreground" title={c.failure_detail}>
                            {c.failure_detail}
                          </div>
                        ) : null}
                      </td>
                      <td className="max-w-[160px] py-2 pr-2">
                        <div className="line-clamp-2 text-xs text-muted-foreground" title={sourceRef}>
                          {sourceRef}
                        </div>
                      </td>
                      <td className="max-w-[180px] py-2 pr-2">
                        {c.source_input_url ? (
                          <div
                            className="line-clamp-2 break-all text-xs text-muted-foreground"
                            title={c.source_input_url}
                          >
                            {c.source_input_url}
                          </div>
                        ) : (
                          <span className="text-xs text-muted-foreground">-</span>
                        )}
                      </td>
                      <td className="py-2">
                        <div className="flex flex-wrap gap-1">
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 px-2"
                            title="打开 Instagram 主页"
                            onClick={() => window.open(c.profile_url, "_blank", "noopener,noreferrer")}
                          >
                            <ExternalLink className="h-3.5 w-3.5" />
                          </Button>
                          {c.source_post_url ? (
                            <Button
                              size="sm"
                              variant="ghost"
                              className="h-7 px-2"
                              title="打开来源作品链接"
                              onClick={() =>
                                window.open(c.source_post_url!, "_blank", "noopener,noreferrer")
                              }
                            >
                              帖
                            </Button>
                          ) : null}
                          {c.source_input_url ? (
                            <Button
                              size="sm"
                              variant="ghost"
                              className="h-7 px-2"
                              title="打开来源输入链接"
                              onClick={() =>
                                window.open(c.source_input_url!, "_blank", "noopener,noreferrer")
                              }
                            >
                              入
                            </Button>
                          ) : null}
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 px-2"
                            title="复制用户名"
                            onClick={() => void copyText(c.username)}
                          >
                            <Copy className="h-3.5 w-3.5" />
                          </Button>
                          {canEnrichYoutubeEmail(c) ? (
                            <Button
                              size="sm"
                              variant="ghost"
                              className="h-7 px-2 text-xs"
                              disabled={enrichingEmailCandidateId === c.id}
                              title="调用 YouTube 邮箱 Actor 补采该候选邮箱"
                              onClick={() => {
                                void handleEnrichYoutubeEmail(c);
                              }}
                            >
                              {enrichingEmailCandidateId === c.id ? (
                                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                              ) : (
                                "补邮箱"
                              )}
                            </Button>
                          ) : null}
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 px-2 text-xs"
                            disabled={!canRecrawlCandidate(c) || recrawlingCandidateId === c.id}
                            title={canRecrawlCandidate(c) ? "重新拉取主页详情" : "该候选不适合自动重采"}
                            onClick={() => {
                              void handleRecrawlCandidate(c);
                            }}
                          >
                            {recrawlingCandidateId === c.id ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : (
                              "重采"
                            )}
                          </Button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        <div className="flex items-center justify-between border-t px-4 py-3">
          <Button
            size="sm"
            variant="outline"
            disabled={page <= 1 || loading}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
          >
            上一页
          </Button>
          <span className="text-xs text-muted-foreground">
            第 {page} / {pages} 页
          </span>
          <Button
            size="sm"
            variant="outline"
            disabled={page >= pages || loading}
            onClick={() => setPage((p) => p + 1)}
          >
            下一页
          </Button>
        </div>
      </div>
    </div>
  );
}
