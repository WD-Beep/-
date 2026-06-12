"use client";

import { useEffect, useState } from "react";
import { Copy, Download, ExternalLink, Loader2, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  COLLECTION_TASK_POLL_INTERVAL_MS,
  downloadCollectionTaskCandidatesExport,
  fetchCollectionTaskCandidates,
  isCollectionTaskRunning,
  type CollectionTask,
  type CollectionTaskCandidate,
} from "@/lib/api";
import {
  CANDIDATE_FAILURE_LABELS,
  CANDIDATE_SOURCE_TYPE_LABELS,
  CANDIDATE_STATUS_LABELS,
} from "@/lib/labels";

type TaskCandidatesDialogProps = {
  task: CollectionTask | null;
  open: boolean;
  onClose: () => void;
};

const STATUS_FILTER_OPTIONS = [
  { value: "", label: "全部状态" },
  { value: "inserted", label: "已入库" },
  { value: "pending_profile", label: "待补采" },
  { value: "profile_failed", label: "补采失败" },
  { value: "filtered_out", label: "已过滤" },
  { value: "duplicate", label: "重复" },
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
  { value: "excluded_keyword", label: "排除词" },
  { value: "profile_fetch_failed", label: "补采失败" },
  { value: "private_account", label: "私密账号" },
  { value: "missing_profile_detail", label: "数据缺失" },
  { value: "duplicate", label: "重复" },
];

function formatFollowers(value: number | null): string {
  if (value == null) return "-";
  return value.toLocaleString("zh-CN");
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
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState("");
  const [failureFilter, setFailureFilter] = useState("");
  const [sourceTypeFilter, setSourceTypeFilter] = useState("");
  const [sourceDiscoveryFilter, setSourceDiscoveryFilter] = useState("");
  const [search, setSearch] = useState("");

  useEffect(() => {
    if (!open || !task) return;
    const activeTask = task;
    let cancelled = false;

    async function loadCandidates(silent = false) {
      if (!silent) setLoading(true);
      setError(null);
      try {
        const result = await fetchCollectionTaskCandidates(activeTask.id, {
          page,
          page_size: 20,
          status: statusFilter || undefined,
          failure_reason: failureFilter || undefined,
          source_type: sourceTypeFilter || undefined,
          source_discovery_type: sourceDiscoveryFilter || undefined,
          search: search.trim() || undefined,
        });
        if (cancelled) return;
        setItems(result.items);
        setTotal(result.total);
        setPages(result.pages);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "加载候选列表失败");
        }
      } finally {
        if (!cancelled && !silent) setLoading(false);
      }
    }

    void loadCandidates();
    const pollId = isCollectionTaskRunning(activeTask)
      ? window.setInterval(() => {
          void loadCandidates(true);
        }, COLLECTION_TASK_POLL_INTERVAL_MS)
      : undefined;

    return () => {
      cancelled = true;
      if (pollId !== undefined) window.clearInterval(pollId);
    };
  }, [
    task,
    open,
    page,
    statusFilter,
    failureFilter,
    sourceTypeFilter,
    sourceDiscoveryFilter,
    search,
    task?.status,
    task?.updated_at,
    task?.discovered_count,
    task?.inserted_count,
  ]);
  function resetFilters() {
    setPage(1);
  }

  if (!open || !task) return null;

  const showCompetitorColumns = task.collection_mode === "competitor_product";

  const exportQuery = {
    status: statusFilter || undefined,
    failure_reason: failureFilter || undefined,
    source_type: sourceTypeFilter || undefined,
    source_discovery_type: sourceDiscoveryFilter || undefined,
    search: search.trim() || undefined,
  };

  const statusMeta = (status: string) =>
    CANDIDATE_STATUS_LABELS[status] ?? { label: status, variant: "secondary" as const };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div
        role="dialog"
        aria-modal="true"
        className="flex max-h-[90vh] w-full max-w-6xl flex-col rounded-lg border bg-background shadow-lg"
      >
        <div className="flex items-start justify-between gap-4 border-b px-4 py-3">
          <div>
            <h2 className="text-lg font-semibold">候选池 · {task.name}</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              {isCollectionTaskRunning(task) ? (
                <span className="inline-flex items-center gap-1.5">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  采集中，数据自动刷新…
                </span>
              ) : null}{" "}
              发现 {task.discovered_count ?? 0} → 去重 {task.deduped_count ?? 0} → 补采成功{" "}
              {task.profile_fetched_count ?? 0} / 失败 {task.profile_failed_count ?? 0} → 入库{" "}
              {task.inserted_count ?? task.result_count ?? 0}
              {(task.filtered_below_min_followers_count ?? 0) > 0
                ? ` · 粉丝未达标 ${task.filtered_below_min_followers_count}`
                : ""}
              {(task.filtered_excluded_keyword_count ?? 0) > 0
                ? ` · 排除词 ${task.filtered_excluded_keyword_count}`
                : ""}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              className="h-8 gap-1.5"
              title="导出当前筛选条件下的候选池 Excel"
              onClick={() => {
                void downloadCollectionTaskCandidatesExport(task.id, exportQuery);
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
          <span className="text-xs text-muted-foreground">共 {total} 条</span>
        </div>

        <div className="min-h-0 flex-1 overflow-auto px-4 py-2">
          {error ? <p className="py-4 text-sm text-destructive">{error}</p> : null}
          {loading ? (
            <div className="flex items-center justify-center py-12 text-muted-foreground">
              <Loader2 className="mr-2 h-5 w-5 animate-spin" />
              加载中…
            </div>
          ) : items.length === 0 ? (
            <p className="py-8 text-center text-sm text-muted-foreground">
              暂无候选记录。任务运行完成后会写入发现、补采失败与过滤账号。
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
                  <th className="py-2 pr-2 font-medium">状态</th>
                  <th className="py-2 pr-2 font-medium">未入库原因</th>
                  <th className="py-2 pr-2 font-medium">来源帖/评论</th>
                  <th className="py-2 font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {items.map((c) => {
                  const sm = statusMeta(c.status);
                  const meta = c.source_meta;
                  const reasonLabel = c.failure_reason
                    ? (CANDIDATE_FAILURE_LABELS[c.failure_reason] ?? c.failure_reason)
                    : "-";
                  const sourceRef =
                    meta?.source_caption?.slice(0, 80) ||
                    c.source_caption?.slice(0, 80) ||
                    c.source_comment_text?.slice(0, 40) ||
                    c.source_post_url ||
                    c.source_comment_url ||
                    "-";
                  return (
                    <tr key={c.id} className="border-b align-top last:border-0">
                      <td className="py-2 pr-2">
                        <div className="font-medium">@{c.username}</div>
                        <div className="max-w-[140px] truncate text-xs text-muted-foreground" title={c.profile_url}>
                          {c.profile_url}
                        </div>
                      </td>
                      <td className="py-2 pr-2 text-xs">{sourceLabel(c)}</td>
                      {showCompetitorColumns ? (
                        <td className="max-w-[220px] py-2 pr-2 text-xs">
                          {meta ? (
                            <div className="space-y-1">
                              {meta.asin ? <div>ASIN: {meta.asin}</div> : null}
                              {meta.brand ? <div>品牌: {meta.brand}</div> : null}
                              {meta.matched_keywords?.length ? (
                                <div className="text-muted-foreground">
                                  命中: {meta.matched_keywords.slice(0, 4).join("、")}
                                </div>
                              ) : null}
                              {meta.match_reasons?.length ? (
                                <div className="text-muted-foreground">
                                  {meta.match_reasons.slice(0, 3).join("；")}
                                </div>
                              ) : null}
                              {meta.suspected_collab ? (
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
                              title="打开来源帖子"
                              onClick={() =>
                                window.open(c.source_post_url!, "_blank", "noopener,noreferrer")
                              }
                            >
                              帖
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
                          <Button size="sm" variant="ghost" className="h-7 px-2 text-xs" disabled title="后续支持">
                            重采
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
