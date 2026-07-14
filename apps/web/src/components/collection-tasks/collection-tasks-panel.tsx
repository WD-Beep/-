"use client";

import Link from "next/link";
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ChevronDown, Loader2, List, Mail, Pause, Pencil, Play, Plus, RefreshCw, Square, Trash2, X } from "lucide-react";

import { AdminShell } from "@/components/layout/admin-shell";
import { useActiveProductId } from "@/components/providers/product-provider";
import { TaskDeleteConfirmDialog } from "@/components/collection-tasks/task-delete-confirm-dialog";
import { TaskFormDialog } from "@/components/collection-tasks/task-form-dialog";
import { TaskCandidatesDialog } from "@/components/collection-tasks/task-candidates-dialog";
import { EmptyState, ErrorAlert, LoadingState, SuccessAlert } from "@/components/shared/page-states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  COLLECTION_TASK_TABLE_LAYOUT,
  buildTaskResultBreakdown,
  collectionTaskInterruptedHint,
  collectionTaskRunningHint,
  formatCollectionResultLines,
  formatTargetLabel,
  isCollectionTaskRateLimited,
  isCollectionTaskSlowApi,
  shouldShowCollectionTaskErrorMessage,
} from "@/lib/collection-task-progress";
import {
  buildCollectionTaskCompletionMessage,
  buildInfluencersPageUrl,
  bulkDeleteCollectionTasks,
  bulkManageCollectionTasks,
  bulkRunCollectionTasks,
  COLLECTION_TASK_POLL_INTERVAL_MS,
  COLLECTION_TASK_SLOW_HINT_MS,
  createCollectionTask,
  deleteLinkImportBatch,
  fetchCollectionTasks,
  fetchLinkImportBatches,
  fetchPlatformCapabilities,
  getCollectionTaskRunningElapsedMs,
  isCollectionTaskActive,
  isCollectionTaskPaused,
  isCollectionTaskQueued,
  isCollectionTaskRunning,
  isCollectionTaskRunningStale,
  isCollectionTaskSettled,
  pauseCollectionTask,
  stopCollectionTask,
  resumeCollectionTask,
  runCollectionTask,
  runCollectionTaskBatch,
  runLinkImportBatch,
  sendCollectionTaskEmail,
  updateCollectionTask,
  type CollectionTask,
  type CollectionTaskPayload,
  type CollectionTaskStatus,
  type CollectionTaskBulkManageAction,
  type CollectionTaskBulkManageResult,
  type LinkImportBatch,
  type TaskSourceMethod,
} from "@/lib/api";
import {
  extractAmazonProductSeeds,
  formatAmazonProductClueLine,
  formatTaskKeywordsOrLinks,
  platformLabel,
  taskDisplayPlatforms,
  taskModeBadgeLabel,
  taskPlatformGroupLabel,
  taskProductClueGroupLabel,
  TASK_STATUS_LABELS,
  taskSourceLabelForMode,
  translateErrorMessage,
} from "@/lib/labels";
import {
  buildTaskDeleteConfirmCopy,
  buildTaskDeleteResultMessage,
  isLegacyBatchIneffective,
  isTaskRowIneffective,
  matchesLegacyBatchFilter,
  taskEffectivenessCategory,
  taskEffectivenessCategoryLabel,
  taskHasRetentionData,
  taskManagementTags,
  type TaskEffectivenessFilter,
} from "@/lib/task-effectiveness";
import {
  canCreateCollectionTaskForProduct,
  collectionTaskCreateDisabledReason,
  getCreatedCollectionTaskMessage,
} from "@/lib/task-form-payload";

function formatDate(value: string | null): string {
  if (!value) return "-";
  return new Date(value).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function statusMeta(status: keyof typeof TASK_STATUS_LABELS) {
  return TASK_STATUS_LABELS[status] ?? TASK_STATUS_LABELS.draft;
}

function formatPercent(value: number | null): string {
  if (value === null) return "-";
  return `${value}%`;
}

function formatFollowerRange(task: CollectionTask): string | null {
  const min = task.min_followers_count;
  const max = task.max_followers_count;
  if (min == null && max == null) return null;
  if (min != null && max != null) {
    return `粉丝 ${min.toLocaleString("zh-CN")}-${max.toLocaleString("zh-CN")}`;
  }
  if (min != null) return `粉丝 ≥${min.toLocaleString("zh-CN")}`;
  return `粉丝 ≤${max!.toLocaleString("zh-CN")}`;
}

function formatKeywordFilters(task: CollectionTask): string | null {
  const include = task.filter_include_keywords ?? [];
  const exclude = task.filter_exclude_keywords ?? [];
  const parts: string[] = [];
  if (include.length) parts.push(`含词 ${include.length}`);
  if (exclude.length) parts.push(`排除 ${exclude.length}`);
  return parts.length ? parts.join(" · ") : null;
}

function batchProgressLines(task: CollectionTask): { headline: string; counts: string } | null {
  if (task.parent_task_id || (task.batch_round_count ?? 0) <= 1) return null;
  const children = task.child_tasks ?? [];
  const roundCount = task.batch_round_count ?? children.length;
  const activeChild = children.find((child) => child.status === "running" || child.status === "queued");
  const terminalChildren = children.filter((child) =>
    ["completed", "completed_with_results", "completed_no_results", "failed", "partial_failed"].includes(child.status),
  );
  const currentRound = activeChild?.batch_round_index ?? Math.min(roundCount, terminalChildren.length + 1);
  const successRounds = children.filter((child) =>
    ["completed", "completed_with_results", "completed_no_results"].includes(child.status),
  ).length;
  const failedRounds = children.filter((child) => child.status === "failed" || child.status === "partial_failed").length;
  const skippedRounds = children.reduce((sum, child) => sum + (child.skipped_count ?? 0), task.skipped_count ?? 0);
  const inserted = task.inserted_count ?? task.result_count ?? 0;
  const total = task.discovery_limit ?? 0;
  return {
    headline: `多轮采集 · 第 ${currentRound}/${roundCount} 轮 · 已入库 ${inserted} / ${total}`,
    counts: `成功 ${successRounds} 轮 / 失败 ${failedRounds} 轮 / 跳过 ${skippedRounds}`,
  };
}

function formatCollectionResultCell(
  task: CollectionTask,
  options: { isStaleRunning?: boolean; elapsedMs?: number; slowThresholdMs?: number } = {},
) {
  const { isStaleRunning = false, elapsedMs = 0, slowThresholdMs = COLLECTION_TASK_SLOW_HINT_MS } = options;
  const lines = formatCollectionResultLines(task);
  const batchLines = batchProgressLines(task);
  const runningHint = collectionTaskRunningHint(task, {
    elapsedMs,
    slowThresholdMs,
    stale: isStaleRunning,
    recoverable: task.recoverable,
  });

  if (isStaleRunning) {
    return (
      <>
        <span className="inline-flex items-center gap-1.5 text-amber-700 dark:text-amber-400">
          <RefreshCw className="h-3.5 w-3.5 shrink-0" />
          任务可能中断，可继续运行
        </span>
        <span className="mt-0.5 block text-xs text-muted-foreground">{collectionTaskInterruptedHint(task)}</span>
        <span className="mt-0.5 block text-xs text-muted-foreground">{lines.primary}</span>
        <span className="mt-0.5 block text-xs text-muted-foreground">{lines.funnel}</span>
      </>
    );
  }

  if (isCollectionTaskQueued(task)) {
    const reasonLabels = Array.isArray(task.run_checkpoint?.queue_reason_labels)
      ? task.run_checkpoint.queue_reason_labels.filter((item): item is string => typeof item === "string")
      : [];
    const queuedText = task.status_summary ?? "任务已排队，等待空位";
    const reasonText = reasonLabels.length > 0 ? reasonLabels.join("；") : null;
    return (
      <>
        <span className="inline-flex items-center gap-1.5 text-amber-700 dark:text-amber-400">
          <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" />
          {queuedText}
        </span>
        {reasonText ? (
          <span className="mt-0.5 block text-xs text-muted-foreground">排队原因：{reasonText}</span>
        ) : null}
        <span className="mt-0.5 block text-xs text-muted-foreground">{lines.primary}</span>
      </>
    );
  }

  if (isCollectionTaskRunning(task)) {
    const rateLimited = isCollectionTaskRateLimited(task);
    const slowApi = isCollectionTaskSlowApi(task, elapsedMs, slowThresholdMs);
    return (
      <>
        <span
          className={`inline-flex items-center gap-1.5 ${
            rateLimited || slowApi ? "text-amber-700 dark:text-amber-400" : ""
          }`}
        >
          <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-primary" />
          {runningHint ?? lines.primary}
        </span>
        <span className="mt-0.5 block text-xs text-muted-foreground">{lines.primary}</span>
        <span className="mt-0.5 block text-xs text-muted-foreground">{lines.funnel}</span>
        {lines.hint ? (
          <span className="mt-0.5 block line-clamp-2 text-xs text-muted-foreground" title={lines.hint}>
            {lines.hint}
          </span>
        ) : null}
      </>
    );
  }

  const inserted = task.inserted_count ?? task.result_count ?? 0;
  const breakdown = buildTaskResultBreakdown(task);
  if (batchLines) {
    return (
      <div className="space-y-1 text-xs">
        <span className="block text-sm font-medium">{batchLines.headline}</span>
        <span className="block text-muted-foreground">{batchLines.counts}</span>
        {task.status_summary ? (
          <span className="block line-clamp-2 text-muted-foreground" title={task.status_summary}>
            {task.status_summary}
          </span>
        ) : null}
      </div>
    );
  }
  if (inserted > 0) {
    return (
      <div className="space-y-1 text-xs">
        <Link
          href={buildInfluencersPageUrl({ taskId: task.id, taskName: task.name })}
          className="inline-flex flex-wrap items-center gap-1 rounded-sm text-sm font-medium text-primary transition-colors hover:bg-primary/5 hover:underline"
          title="查看该任务入库红人"
        >
          <span>{breakdown.primary[0]}</span>
          {breakdown.highValue ? (
            <Badge variant="success" className="text-[10px]">
              高价值
            </Badge>
          ) : null}
          {breakdown.singleLinkImport ? (
            <Badge variant="outline" className="text-[10px]">
              单条链接导入
            </Badge>
          ) : null}
        </Link>
        <div className="flex flex-wrap gap-x-2 gap-y-0.5 text-muted-foreground">
          {breakdown.funnel.map((item) => (
            <span key={item}>{item}</span>
          ))}
        </div>
        <div className="flex flex-wrap gap-x-2 gap-y-0.5 text-muted-foreground">
          {breakdown.contacts.map((item) => (
            <span key={item}>{item}</span>
          ))}
        </div>
        {breakdown.reason ? (
          <div className="line-clamp-2 text-muted-foreground" title={breakdown.reason}>
            {breakdown.reason}
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <div className="space-y-1 text-xs text-muted-foreground">
      <span className="block text-sm">{breakdown.primary[0]}</span>
      <div className="flex flex-wrap gap-x-2 gap-y-0.5">
        {breakdown.funnel.map((item) => (
          <span key={item}>{item}</span>
        ))}
      </div>
      <div className="flex flex-wrap gap-x-2 gap-y-0.5">
        {breakdown.contacts.map((item) => (
          <span key={item}>{item}</span>
        ))}
      </div>
      {breakdown.reason || lines.hint || task.status_summary ? (
        <span
          className="block line-clamp-2"
          title={breakdown.reason ?? lines.hint ?? task.status_summary ?? undefined}
        >
          {breakdown.reason ?? lines.hint ?? task.status_summary}
        </span>
      ) : null}
    </div>
  );
}

type TaskToast = {
  tone: "success" | "warning" | "error" | "info";
  message: string;
};

type TaskListRow =
  | { kind: "task"; task: CollectionTask; sortAt: number }
  | { kind: "legacy_batch"; batch: LinkImportBatch; sortAt: number };

const TASK_PAGE_SIZE_OPTIONS = [10, 20, 50] as const;
const PAGE_ALERT_CLEAR_MS = 8000;

const PRIMARY_TASK_TABS: { value: TaskEffectivenessFilter; label: string }[] = [
  { value: "all", label: "全部" },
  { value: "effective", label: "有结果" },
  { value: "no_result", label: "无结果" },
  { value: "archived", label: "已归档" },
];

const SECONDARY_TASK_FILTERS: { value: TaskEffectivenessFilter; label: string }[] = [
  { value: "high_value", label: "高价值" },
  { value: "low_value_result", label: "低价值结果" },
  { value: "test_history", label: "测试/历史" },
];

function buildBulkManageResultMessage(result: CollectionTaskBulkManageResult): string {
  const parts: string[] = [];
  if (result.archived_count > 0) parts.push(`已归档 ${result.archived_count} 个`);
  if (result.deleted_count > 0) parts.push(`已删除 ${result.deleted_count} 个`);
  if (result.restored_count > 0) parts.push(`已恢复 ${result.restored_count} 个`);
  if (result.skipped_count > 0) parts.push(`跳过 ${result.skipped_count} 个`);
  return parts.length > 0 ? parts.join("，") : `匹配 ${result.matched_count} 个，暂无可处理任务`;
}

function legacyBatchStatus(status: string): CollectionTaskStatus {
  switch (status) {
    case "running":
      return "running";
    case "completed":
      return "completed_with_results";
    case "failed":
      return "failed";
    default:
      return "draft";
  }
}

function legacyBatchSortTime(batch: LinkImportBatch): number {
  const value = batch.completed_at ?? batch.created_at;
  return value ? new Date(value).getTime() : 0;
}

export function CollectionTasksPanel() {
  const productId = useActiveProductId();
  const searchParams = useSearchParams();
  const [tasks, setTasks] = useState<CollectionTask[]>([]);
  const [legacyBatches, setLegacyBatches] = useState<LinkImportBatch[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState<(typeof TASK_PAGE_SIZE_OPTIONS)[number]>(20);
  const [totalPages, setTotalPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogMode, setDialogMode] = useState<"create" | "edit">("create");
  const [defaultSourceMethod, setDefaultSourceMethod] = useState<TaskSourceMethod>("keyword_discovery");
  const [editingTask, setEditingTask] = useState<CollectionTask | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [actionTaskId, setActionTaskId] = useState<number | null>(null);
  const [actionLegacyBatchId, setActionLegacyBatchId] = useState<number | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [candidatesTask, setCandidatesTask] = useState<CollectionTask | null>(null);
  const [candidatesOpen, setCandidatesOpen] = useState(false);
  const [toast, setToast] = useState<TaskToast | null>(null);
  const [effectivenessFilter, setEffectivenessFilter] = useState<TaskEffectivenessFilter>("all");
  const [selectedTaskIds, setSelectedTaskIds] = useState<number[]>([]);
  const [deleteDialog, setDeleteDialog] = useState<{
    open: boolean;
    title: string;
    body: string;
    confirmLabel: string;
    taskIds: number[];
    legacyBatchIds: number[];
    bulkAction?: CollectionTaskBulkManageAction;
  } | null>(null);
  const [deleteSubmitting, setDeleteSubmitting] = useState(false);
  const [maxRunningTasks, setMaxRunningTasks] = useState(2);
  const [staleAfterSeconds, setStaleAfterSeconds] = useState(180);
  const [bulkRunSubmitting, setBulkRunSubmitting] = useState(false);
  const [expandedBatchIds, setExpandedBatchIds] = useState<number[]>([]);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const prevStatusRef = useRef<Map<number, CollectionTaskStatus>>(new Map());
  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pageAlertTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const loadRequestIdRef = useRef(0);
  const loadAbortRef = useRef<AbortController | null>(null);
  const loadInflightRef = useRef(false);

  const showToast = useCallback((next: TaskToast) => {
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    setToast(next);
    toastTimerRef.current = setTimeout(() => setToast(null), 8000);
  }, []);

  useEffect(() => {
    let active = true;
    void fetchPlatformCapabilities()
      .then((caps) => {
        if (!active) return;
        setMaxRunningTasks(Math.max(1, caps.collection_max_running_tasks ?? 2));
        setStaleAfterSeconds(Math.max(30, caps.collection_running_stale_seconds ?? 180));
      })
      .catch(() => {
        if (!active) return;
        setMaxRunningTasks(2);
        setStaleAfterSeconds(180);
      });
    return () => {
      active = false;
    };
  }, []);

  const applyTaskList = useCallback((items: CollectionTask[], totalCount: number, pages = 1) => {
    setTasks(items);
    setTotal(totalCount);
    setTotalPages(Math.max(1, pages));
    setCandidatesTask((prev) => {
      if (!prev) return prev;
      return items.find((t) => t.id === prev.id) ?? prev;
    });
  }, []);

  const loadTasks = useCallback(async (options?: { silent?: boolean }) => {
    loadAbortRef.current?.abort();
    const controller = new AbortController();
    loadAbortRef.current = controller;
    const requestId = ++loadRequestIdRef.current;
    loadInflightRef.current = true;

    if (!options?.silent) {
      setLoading(true);
      setError(null);
    }
    try {
      const showLegacyBatches = effectivenessFilter === "test_history";
      const [data, batchData] = await Promise.all([
        fetchCollectionTasks(page, pageSize, {
          task_view: effectivenessFilter,
          signal: controller.signal,
        }),
        showLegacyBatches
          ? fetchLinkImportBatches(1, 20, { signal: controller.signal }).catch((err) => {
              if (controller.signal.aborted) throw err;
              return { items: [] as LinkImportBatch[], total: 0 };
            })
          : Promise.resolve({ items: [] as LinkImportBatch[], total: 0 }),
      ]);
      if (controller.signal.aborted || requestId !== loadRequestIdRef.current) return;

      const filteredLegacy = batchData.items.filter((batch) =>
        matchesLegacyBatchFilter(effectivenessFilter, batch),
      );
      const pages = data.total_pages ?? data.pages ?? Math.ceil((data.total ?? 0) / pageSize);
      applyTaskList(data.items, data.total, pages);
      setLegacyBatches(filteredLegacy);
      setSelectedTaskIds((prev) => prev.filter((id) => data.items.some((task) => task.id === id)));
      if (data.items.length === 0 && page > 1 && data.total > 0) {
        setPage((current) => Math.max(1, current - 1));
      }
    } catch (err) {
      if (controller.signal.aborted || requestId !== loadRequestIdRef.current) return;
      if (err instanceof DOMException && err.name === "AbortError") return;
      if (!options?.silent) {
        setError(err instanceof Error ? err.message : "加载任务列表失败");
      }
    } finally {
      if (requestId === loadRequestIdRef.current) {
        loadInflightRef.current = false;
        if (!options?.silent) {
          setLoading(false);
        }
      }
    }
  }, [applyTaskList, effectivenessFilter, page, pageSize]);

  const listRows = useMemo<TaskListRow[]>(() => {
    const rows: TaskListRow[] = [
      ...tasks.map((task) => ({
        kind: "task" as const,
        task,
        sortAt: new Date(task.updated_at ?? task.created_at).getTime(),
      })),
      ...legacyBatches.map((batch) => ({
        kind: "legacy_batch" as const,
        batch,
        sortAt: legacyBatchSortTime(batch),
      })),
    ];
    return rows.sort((a, b) => b.sortAt - a.sortAt);
  }, [legacyBatches, tasks]);

  useEffect(() => {
    if (productId === null) {
      queueMicrotask(() => setLoading(false));
      return;
    }
    queueMicrotask(() => {
      void loadTasks();
    });
    return () => {
      loadAbortRef.current?.abort();
    };
  }, [loadTasks, productId]);

  useEffect(() => {
    if (searchParams.get("create") === "link_import") {
      queueMicrotask(() => {
        setMessage(null);
        setError(null);
        setDialogMode("create");
        setEditingTask(null);
        setDefaultSourceMethod("link_import");
        setDialogOpen(true);
      });
    }
  }, [searchParams]);

  useEffect(() => {
    return () => {
      loadAbortRef.current?.abort();
      if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
      if (pageAlertTimerRef.current) clearTimeout(pageAlertTimerRef.current);
    };
  }, []);

  useEffect(() => {
    if (!message && !error) return;
    if (pageAlertTimerRef.current) clearTimeout(pageAlertTimerRef.current);
    pageAlertTimerRef.current = setTimeout(() => {
      setMessage(null);
      setError(null);
    }, PAGE_ALERT_CLEAR_MS);
    return () => {
      if (pageAlertTimerRef.current) clearTimeout(pageAlertTimerRef.current);
    };
  }, [message, error]);

  const hasRunningTasks = tasks.some((t) => isCollectionTaskActive(t));
  const activeRunningTasks = tasks.filter(
    (t) => isCollectionTaskRunning(t) && !isCollectionTaskRunningStale(t),
  );
  const activeRunningTask = activeRunningTasks[0];
  const createDisabledReason = collectionTaskCreateDisabledReason(productId);

  useEffect(() => {
    if (!hasRunningTasks) return;
    const clockId = window.setInterval(() => {
      setNowMs(Date.now());
    }, 1000);
    const pollId = window.setInterval(() => {
      if (loadInflightRef.current) return;
      void loadTasks({ silent: true });
    }, COLLECTION_TASK_POLL_INTERVAL_MS);
    return () => {
      window.clearInterval(clockId);
      window.clearInterval(pollId);
    };
  }, [hasRunningTasks, loadTasks]);

  useEffect(() => {
    for (const task of tasks) {
      const prev = prevStatusRef.current.get(task.id);
      if ((prev === "running" || prev === "queued") && isCollectionTaskSettled(task.status)) {
        const completion = buildCollectionTaskCompletionMessage(task);
        const completionMessage =
          completion.tone === "error" && task.error_message
            ? `采集失败：${translateErrorMessage(task.error_message)}`
            : completion.message;
        showToast({ tone: completion.tone, message: completionMessage });
        queueMicrotask(() => {
          if (completion.tone === "error") {
            setError(completionMessage);
            setMessage(null);
          } else {
            setMessage(completionMessage);
            setError(null);
          }
        });
      }
      prevStatusRef.current.set(task.id, task.status);
    }
  }, [tasks, showToast]);

  function openCreateDialog(sourceMethod: TaskSourceMethod = "keyword_discovery") {
    if (!canCreateCollectionTaskForProduct(productId)) {
      setMessage(null);
      setError(createDisabledReason ?? "请先选择具体产品/品牌");
      return;
    }
    setMessage(null);
    setError(null);
    setDialogMode("create");
    setEditingTask(null);
    setDefaultSourceMethod(sourceMethod);
    setDialogOpen(true);
  }

  function openEditDialog(task: CollectionTask) {
    setMessage(null);
    setError(null);
    setDialogMode("edit");
    setEditingTask(task);
    setDialogOpen(true);
  }

  async function handleSubmit(payload: CollectionTaskPayload) {
    setSubmitting(true);
    setMessage(null);
    setError(null);
    try {
      if (dialogMode === "create") {
        if (!canCreateCollectionTaskForProduct(productId)) {
          throw new Error(createDisabledReason ?? "请先选择具体产品/品牌");
        }
        const created = await createCollectionTask(payload);
        setMessage("任务创建成功");
        setMessage(getCreatedCollectionTaskMessage(created));
      } else if (editingTask) {
        await updateCollectionTask(editingTask.id, payload);
        setMessage("任务更新成功");
      }
      await loadTasks();
    } catch (err) {
      throw err;
    } finally {
      setSubmitting(false);
    }
  }

  async function handleRun(task: CollectionTask) {
    setActionTaskId(task.id);
    setMessage(null);
    setError(null);

    try {
      const kickoff = await runCollectionTask(task.id);
      const runningSummary =
        kickoff.status_summary ?? "采集中… 任务已在后台运行，正在从 Instagram 拉取数据";
      setTasks((prev) =>
        prev.map((t) =>
          t.id === task.id
            ? {
                ...t,
                status: kickoff.status,
                status_summary: runningSummary,
                error_message: kickoff.error_message ?? null,
              }
            : t,
        ),
      );
      setCandidatesTask((prev) =>
        prev?.id === task.id
          ? { ...prev, status: kickoff.status, status_summary: runningSummary }
          : prev,
      );
      if (kickoff.status === "running") {
        setMessage(runningSummary);
        showToast({ tone: "info", message: `任务已开始：${runningSummary}` });
        prevStatusRef.current.set(task.id, "running");
        await loadTasks({ silent: true });
      } else if (kickoff.status === "queued") {
        setMessage(runningSummary);
        showToast({ tone: "warning", message: runningSummary });
        prevStatusRef.current.set(task.id, "queued");
        await loadTasks({ silent: true });
      } else {
        const pseudoTask: CollectionTask = {
          ...task,
          status: kickoff.status,
          inserted_count: kickoff.inserted_count,
          result_count: kickoff.total_count,
          email_count: kickoff.email_count,
          missing_contact_count: kickoff.missing_contact_count,
          status_summary: kickoff.status_summary,
          error_message: kickoff.error_message ?? null,
        };
        const completion = buildCollectionTaskCompletionMessage(pseudoTask);
        showToast({ tone: completion.tone, message: completion.message });
        if (completion.tone === "error") {
          setError(completion.message);
          setMessage(null);
        } else {
          setMessage(completion.message);
          setError(null);
        }
        await loadTasks({ silent: true });
      }
    } catch (err) {
      const errMsg =
        err instanceof Error ? err.message : "运行采集失败";
      // Also show as toast so user definitely sees it
      showToast({ tone: "error", message: errMsg });
      setError(errMsg);
      await loadTasks({ silent: true });
    } finally {
      setActionTaskId(null);
    }
  }

  async function handlePause(task: CollectionTask) {
    const confirmed = window.confirm(
      "确定暂停该采集任务吗？当前已采集的数据会保存入库。",
    );
    if (!confirmed) return;
    setActionTaskId(task.id);
    setMessage(null);
    setError(null);
    try {
      const paused = await pauseCollectionTask(task.id);
      setTasks((prev) => prev.map((t) => (t.id === task.id ? { ...t, ...paused } : t)));
      setCandidatesTask((prev) => (prev?.id === task.id ? { ...prev, ...paused } : prev));
      setMessage("任务已暂停，已采集的数据和进度已保留。");
      showToast({ tone: "info", message: "任务已暂停，点击继续可从上次进度恢复。" });
      await loadTasks({ silent: true });
    } catch (err) {
      const errMsg = err instanceof Error ? err.message : "暂停采集失败";
      showToast({ tone: "error", message: errMsg });
      setError(errMsg);
      await loadTasks({ silent: true });
    } finally {
      setActionTaskId(null);
    }
  }

  async function handleStop(task: CollectionTask) {
    const confirmed = window.confirm(
      "确定停止这个采集任务吗？\n\n已经采集成功的数据会保留并入库，正在执行的轮次和后续轮次会结束，停止后不会自动重试。",
    );
    if (!confirmed) return;
    setActionTaskId(task.id);
    setMessage(null);
    setError(null);
    try {
      const stopped = await stopCollectionTask(task.id);
      setTasks((prev) => prev.map((item) => (item.id === task.id ? { ...item, ...stopped } : item)));
      setCandidatesTask((prev) => (prev?.id === task.id ? { ...prev, ...stopped } : prev));
      const stoppedMessage = stopped.status_summary ?? "任务已停止，已采集的数据已经保留入库。";
      setMessage(stoppedMessage);
      showToast({ tone: "success", message: stoppedMessage });
      await loadTasks({ silent: true });
    } catch (err) {
      const errMsg = err instanceof Error ? err.message : "停止采集失败";
      showToast({ tone: "error", message: errMsg });
      setError(errMsg);
      await loadTasks({ silent: true });
    } finally {
      setActionTaskId(null);
    }
  }

  async function handleResume(task: CollectionTask) {
    setActionTaskId(task.id);
    setMessage(null);
    setError(null);
    try {
      const kickoff = await resumeCollectionTask(task.id);
      const runningSummary = kickoff.status_summary ?? "任务已继续，将从上次保存进度恢复采集。";
      setTasks((prev) =>
        prev.map((t) =>
          t.id === task.id
            ? {
                ...t,
                status: kickoff.status,
                status_summary: runningSummary,
                error_message: kickoff.error_message ?? null,
              }
            : t,
        ),
      );
      setCandidatesTask((prev) =>
        prev?.id === task.id
          ? { ...prev, status: kickoff.status, status_summary: runningSummary }
          : prev,
      );
      setMessage(runningSummary);
      showToast({ tone: kickoff.status === "queued" ? "warning" : "info", message: runningSummary });
      await loadTasks({ silent: true });
    } catch (err) {
      const errMsg = err instanceof Error ? err.message : "继续采集失败";
      showToast({ tone: "error", message: errMsg });
      setError(errMsg);
      await loadTasks({ silent: true });
    } finally {
      setActionTaskId(null);
    }
  }

  async function handleRunBatch(task: CollectionTask, failedOnly = false) {
    setActionTaskId(task.id);
    setMessage(null);
    setError(null);
    try {
      const result = await runCollectionTaskBatch(task.id, { failedOnly });
      setMessage(result.message);
      showToast({
        tone: result.started_ids.length > 0 ? "info" : "warning",
        message: result.message,
      });
      await loadTasks({ silent: true });
    } catch (err) {
      const errMsg = err instanceof Error ? err.message : "批次运行失败";
      showToast({ tone: "error", message: errMsg });
      setError(errMsg);
    } finally {
      setActionTaskId(null);
    }
  }

  async function handleBulkRunPageIncomplete() {
    const runnableIds = tasks
      .filter((t) => {
        if (t.is_archived) return false;
        if (isCollectionTaskRunning(t) && !isCollectionTaskRunningStale(t)) return false;
        if (isCollectionTaskSettled(t.status) && (t.inserted_count ?? t.result_count ?? 0) > 0) {
          return false;
        }
        return true;
      })
      .map((t) => t.id);
    if (runnableIds.length === 0) {
      showToast({ tone: "warning", message: "当前页没有可运行的未完成任务" });
      return;
    }
    setBulkRunSubmitting(true);
    setMessage(null);
    setError(null);
    try {
      const result = await bulkRunCollectionTasks(runnableIds);
      setMessage(result.message);
      showToast({
        tone: result.started_ids.length > 0 ? "info" : "warning",
        message: result.message,
      });
      await loadTasks({ silent: true });
    } catch (err) {
      const errMsg = err instanceof Error ? err.message : "批量运行失败";
      showToast({ tone: "error", message: errMsg });
      setError(errMsg);
    } finally {
      setBulkRunSubmitting(false);
    }
  }

  async function handleSendEmail(task: CollectionTask) {
    setActionTaskId(task.id);
    setMessage(null);
    setError(null);
    try {
      const result = await sendCollectionTaskEmail(task.id);
      if (result.success) {
        setMessage(result.message || "邮件发送成功");
      } else {
        setError(result.message || "邮件发送失败");
      }
      await loadTasks();
    } catch (err) {
      setError(err instanceof Error ? err.message : "发送邮件失败");
    } finally {
      setActionTaskId(null);
    }
  }

  const ineffectiveTaskIds = useMemo(
    () => tasks.filter((task) => isTaskRowIneffective(task)).map((task) => task.id),
    [tasks],
  );

  const selectableTaskIds = useMemo(
    () =>
      tasks
        .filter(
          (task) =>
            !task.parent_task_id &&
            !["high_value", "effective"].includes(taskEffectivenessCategory(task)),
        )
        .map((task) => task.id),
    [tasks],
  );

  function changeTaskView(value: TaskEffectivenessFilter) {
    setEffectivenessFilter(value);
    setPage(1);
    setSelectedTaskIds([]);
  }

  function changePageSize(value: number) {
    if (!TASK_PAGE_SIZE_OPTIONS.includes(value as (typeof TASK_PAGE_SIZE_OPTIONS)[number])) return;
    setPageSize(value as (typeof TASK_PAGE_SIZE_OPTIONS)[number]);
    setPage(1);
    setSelectedTaskIds([]);
  }

  function openDeleteDialog(options: {
    taskIds: number[];
    legacyBatchIds?: number[];
    taskName?: string;
    hasRetentionData?: boolean;
  }) {
    const selectedTasks = tasks.filter((task) => options.taskIds.includes(task.id));
    const hasRetentionData =
      options.hasRetentionData ??
      selectedTasks.some((task) => taskHasRetentionData(task));
    const copy = buildTaskDeleteConfirmCopy({
      count: options.taskIds.length + (options.legacyBatchIds?.length ?? 0),
      hasRetentionData,
      taskName: options.taskName,
    });
    setDeleteDialog({
      open: true,
      title: copy.title,
      body: copy.body,
      confirmLabel: copy.confirmLabel,
      taskIds: options.taskIds,
      legacyBatchIds: options.legacyBatchIds ?? [],
    });
  }

  function openBulkManageDialog(options: {
    action: CollectionTaskBulkManageAction;
    title: string;
    body: string;
    confirmLabel: string;
    taskIds?: number[];
  }) {
    setDeleteDialog({
      open: true,
      title: options.title,
      body: options.body,
      confirmLabel: options.confirmLabel,
      taskIds: options.taskIds ?? [],
      legacyBatchIds: [],
      bulkAction: options.action,
    });
  }

  async function executeDeleteDialog() {
    if (!deleteDialog) return;
    setDeleteSubmitting(true);
    setError(null);
    try {
      if (deleteDialog.bulkAction) {
        const result = await bulkManageCollectionTasks(deleteDialog.bulkAction, deleteDialog.taskIds);
        setMessage(buildBulkManageResultMessage(result));
        setDeleteDialog(null);
        setSelectedTaskIds([]);
        await loadTasks();
        return;
      }
      if (deleteDialog.taskIds.length > 0) {
        const result = await bulkDeleteCollectionTasks(deleteDialog.taskIds);
        setMessage(buildTaskDeleteResultMessage(result));
      }
      for (const batchId of deleteDialog.legacyBatchIds) {
        await deleteLinkImportBatch(batchId);
      }
      if (deleteDialog.taskIds.length === 0) {
        setMessage(
          deleteDialog.legacyBatchIds.length > 1
            ? "历史导入批次已批量删除"
            : "历史导入批次已删除",
        );
      }
      setDeleteDialog(null);
      setSelectedTaskIds([]);
      await loadTasks();
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除失败");
    } finally {
      setDeleteSubmitting(false);
      setActionTaskId(null);
      setActionLegacyBatchId(null);
    }
  }

  async function handleDelete(task: CollectionTask) {
    if (!isTaskRowIneffective(task)) {
      setError("只能删除无效果任务");
      return;
    }
    if (isCollectionTaskRunning(task)) {
      setError("任务正在运行中，无法删除");
      return;
    }
    setActionTaskId(task.id);
    openDeleteDialog({
      taskIds: [task.id],
      taskName: task.name,
      hasRetentionData: taskHasRetentionData(task),
    });
  }

  function getTaskSelectionBlockedReason(task: CollectionTask) {
    if (task.parent_task_id) return "子轮次会随父任务一起清理";
    if (["high_value", "effective"].includes(taskEffectivenessCategory(task))) {
      return "该任务已有有效结果，不能批量删除";
    }
    return "";
  }

  function toggleTaskSelection(taskId: number) {
    if (!selectableTaskIds.includes(taskId)) return;
    setSelectedTaskIds((prev) =>
      prev.includes(taskId) ? prev.filter((id) => id !== taskId) : [...prev, taskId],
    );
  }

  function handleBulkDeleteSelected() {
    const deletableIds = selectedTaskIds.filter((id) => selectableTaskIds.includes(id));
    if (deletableIds.length === 0) {
      setError("请选择可删除任务");
      return;
    }
    const selectedTasks = tasks.filter((task) => deletableIds.includes(task.id));
    openDeleteDialog({
      taskIds: deletableIds,
      hasRetentionData: selectedTasks.some((task) => taskHasRetentionData(task)),
    });
  }

  function clearTaskSelection() {
    setSelectedTaskIds([]);
  }

  function handleDeleteAllIneffectiveOnPage() {
    openDeleteDialog({ taskIds: ineffectiveTaskIds });
  }

  function handleArchiveTestHistory() {
    openBulkManageDialog({
      action: "archive_test_history",
      title: "批量归档测试/历史任务？",
      body: "系统只会归档当前产品范围内命中测试/历史规则的任务，不会删除红人库数据。归档后默认列表不再显示，可在“已归档任务”中恢复。",
      confirmLabel: "批量归档",
    });
  }

  function handleDeleteNoResult() {
    openBulkManageDialog({
      action: "delete_no_result",
      title: "批量删除无结果任务？",
      body: "系统只会处理当前产品范围内无结果、且没有保留价值的任务；有入库或追溯数据的任务会被跳过或归档保护。此操作不会删除真实业务红人数据。",
      confirmLabel: "确认删除无结果任务",
    });
  }

  function handleRestoreArchived() {
    openBulkManageDialog({
      action: "restore_archived",
      title: "批量恢复归档任务？",
      body: "系统只会恢复当前产品范围内的已归档任务，恢复后会重新出现在默认列表中。",
      confirmLabel: "批量恢复",
    });
  }

  function handleArchiveDuplicates() {
    openBulkManageDialog({
      action: "archive_duplicates",
      title: "只保留最新一条，其余归档？",
      body: "系统会按同名、同关键词、同模式、同平台、同产品识别可能重复任务，并仅归档较旧记录；不会自动删除任何重复任务。",
      confirmLabel: "归档重复任务",
    });
  }

  async function handleRunLegacyBatch(batch: LinkImportBatch) {
    if (batch.status === "running") return;
    setActionLegacyBatchId(batch.id);
    setMessage(null);
    setError(null);
    try {
      await runLinkImportBatch(batch.id);
      setMessage("历史链接导入批次已完成");
      await loadTasks();
    } catch (err) {
      setError(err instanceof Error ? err.message : "运行导入失败");
    } finally {
      setActionLegacyBatchId(null);
    }
  }

  async function handleDeleteLegacyBatch(batch: LinkImportBatch) {
    if (batch.status === "running") {
      setError("批次正在运行中，无法删除");
      return;
    }
    setActionLegacyBatchId(batch.id);
    openDeleteDialog({
      taskIds: [],
      legacyBatchIds: [batch.id],
      taskName: batch.name,
      hasRetentionData: (batch.new_count ?? 0) + (batch.updated_count ?? 0) > 0,
    });
  }

  return (
    <AdminShell title="采集任务" description="在同一处创建关键词发现或链接导入任务，运行后写入红人库">
      <div className="ops-page">
      <div className="ops-toolbar shrink-0">
        <div className="flex items-center gap-2">
          <Button
            onClick={() => openCreateDialog("keyword_discovery")}
            disabled={!canCreateCollectionTaskForProduct(productId)}
            title={createDisabledReason ?? undefined}
          >
            <Plus className="h-4 w-4" />
            创建任务
          </Button>
          <Button
            variant="outline"
            onClick={() => openCreateDialog("link_import")}
            disabled={!canCreateCollectionTaskForProduct(productId)}
            title={createDisabledReason ?? undefined}
          >
            链接导入
          </Button>
          <Button variant="outline" onClick={() => void loadTasks()} disabled={loading}>
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            刷新
          </Button>
        </div>
        <div className="flex flex-1 flex-wrap items-center gap-2">
          <div className="flex flex-wrap items-center gap-1 rounded-md border border-slate-200 bg-slate-50 p-1">
          {PRIMARY_TASK_TABS.map(({ value, label }) => (
            <Button
              key={value}
              size="sm"
              variant={effectivenessFilter === value ? "default" : "ghost"}
              onClick={() => changeTaskView(value)}
            >
              {label}
            </Button>
          ))}
          </div>
          <select
            className="h-8 rounded-md border border-slate-200 bg-white px-2 text-xs font-medium text-slate-800 outline-none transition-colors hover:border-slate-300 focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
            value={SECONDARY_TASK_FILTERS.some((item) => item.value === effectivenessFilter) ? effectivenessFilter : ""}
            onChange={(event) => {
              const value = event.target.value as TaskEffectivenessFilter;
              if (value) changeTaskView(value);
            }}
            aria-label="高级任务筛选"
          >
            <option value="">高级筛选</option>
            {SECONDARY_TASK_FILTERS.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
        {effectivenessFilter !== "high_value" ? (
          <Button variant="outline" size="sm" disabled={deleteSubmitting} onClick={handleArchiveTestHistory}>
            批量归档测试/历史任务
          </Button>
        ) : null}
        {effectivenessFilter !== "archived" ? (
          <Button
            variant="outline"
            size="sm"
            disabled={bulkRunSubmitting || loading}
            onClick={() => void handleBulkRunPageIncomplete()}
          >
            {bulkRunSubmitting ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : null}
            运行本页未完成任务
          </Button>
        ) : null}
        {effectivenessFilter !== "high_value" ? (
          <Button variant="outline" size="sm" disabled={deleteSubmitting} onClick={handleArchiveDuplicates}>
            只保留最新一条
          </Button>
        ) : null}
        {effectivenessFilter === "archived" ? (
          <Button variant="outline" size="sm" disabled={deleteSubmitting} onClick={handleRestoreArchived}>
            批量恢复归档任务
          </Button>
        ) : null}
        {effectivenessFilter !== "high_value" && (effectivenessFilter === "no_result" || effectivenessFilter === "low_value_result") ? (
          <Button variant="outline" size="sm" disabled={deleteSubmitting} onClick={handleDeleteNoResult}>
            批量删除无结果任务
          </Button>
        ) : null}
        {effectivenessFilter !== "high_value" && ["low_value_result", "no_result", "test_history"].includes(effectivenessFilter) && ineffectiveTaskIds.length > 0 ? (
          <Button
            variant="outline"
            size="sm"
            disabled={deleteSubmitting}
            onClick={handleDeleteAllIneffectiveOnPage}
          >
            删除本页可清理任务 ({ineffectiveTaskIds.length})
          </Button>
        ) : null}
      </div>
      </div>

      {activeRunningTasks.length > 0 ? (
        <div className="mb-4 rounded-lg border border-primary/30 bg-primary/5 px-4 py-3 text-sm">
          <span className="inline-flex items-center gap-2 font-medium">
            <Loader2 className="h-4 w-4 animate-spin" />
            {activeRunningTasks.length === 1
              ? `「${activeRunningTask?.name ?? "采集中"}」正在采集中`
              : `${activeRunningTasks.length} 个任务正在采集中（上限 ${maxRunningTasks}）`}
          </span>
          <p className="mt-1 text-muted-foreground">
            {maxRunningTasks <= 1
              ? "当前配置为单任务串行运行，其他任务的「运行」按钮已禁用。请等待状态变为有结果/无结果后再启动下一个。"
              : `当前最多同时运行 ${maxRunningTasks} 个任务；已达上限时其余任务需等待空位。`}
          </p>
        </div>
      ) : null}

      {message ? <SuccessAlert message={message} className="mb-4" /> : null}
      {error ? <ErrorAlert message={error} className="mb-4" /> : null}

      {toast ? (
        <div
          role="status"
          className={`fixed bottom-4 right-4 z-50 flex max-w-md items-start gap-2 rounded-lg border px-4 py-3 text-sm shadow-lg ${
            toast.tone === "error"
              ? "border-destructive/40 bg-destructive/10 text-destructive"
              : toast.tone === "warning"
                ? "border-amber-500/40 bg-amber-500/10 text-amber-950 dark:text-amber-100"
                : toast.tone === "info"
                  ? "border-primary/30 bg-primary/5"
                  : "border-emerald-500/40 bg-emerald-500/10 text-emerald-950 dark:text-emerald-100"
          }`}
        >
          <span className="flex-1">{toast.message}</span>
          <button
            type="button"
            className="shrink-0 rounded p-0.5 opacity-70 hover:opacity-100"
            aria-label="关闭提示"
            onClick={() => setToast(null)}
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      ) : null}

      <Card className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <CardHeader className="shrink-0 border-b px-4 py-3">
          <CardTitle>任务列表</CardTitle>
          <CardDescription>
            共 {total} 个任务，当前第 {page} / {totalPages} 页
            {effectivenessFilter === "high_value"
              ? " · 当前仅显示发现、主页或入库规模明显较高的任务"
              : effectivenessFilter === "low_value_result"
              ? " · 当前仅显示有入库但资料几乎为空的任务"
              : effectivenessFilter === "no_result"
                ? " · 当前仅显示完全无入库结果的任务"
                : effectivenessFilter === "effective"
                  ? " · 当前仅显示有价值但未达到高价值阈值的任务"
                  : effectivenessFilter === "test_history"
                    ? " · 当前显示测试任务、验收任务和历史批次"
                    : effectivenessFilter === "archived"
                      ? " · 当前显示已归档任务"
                  : ""}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex min-h-0 flex-1 flex-col p-0">
          <div className="mb-3 flex flex-wrap items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm">
            <span className="font-medium">
              {selectedTaskIds.length > 0
                ? `已选择 ${selectedTaskIds.length} 个任务`
                : `当前页可删除 ${selectableTaskIds.length} 个任务`}
            </span>
            <Button
              variant="destructive"
              size="sm"
              disabled={deleteSubmitting || selectedTaskIds.length === 0}
              onClick={handleBulkDeleteSelected}
              title={selectedTaskIds.length === 0 ? "请先勾选可删除任务" : "删除已选任务"}
            >
              {deleteSubmitting ? (
                <Loader2 className="mr-1 h-4 w-4 animate-spin" />
              ) : (
                <Trash2 className="mr-1 h-4 w-4" />
              )}
              删除已选
            </Button>
            {selectedTaskIds.length > 0 ? (
              <Button variant="outline" size="sm" disabled={deleteSubmitting} onClick={clearTaskSelection}>
                取消选择
              </Button>
            ) : null}
            {selectableTaskIds.length === 0 ? (
              <span className="text-xs text-muted-foreground">只有无有效结果的父任务可批量删除</span>
            ) : null}
          </div>
          {loading ? (
            <LoadingState label="加载任务列表..." />
          ) : listRows.length === 0 ? (
            <EmptyState
              title="暂无采集任务"
              description="点击「创建任务」配置关键词发现，或使用「链接导入」批量粘贴主页链接。"
            />
          ) : (
            <div className="ops-table-wrap">
              <table className="ops-table min-w-[1180px] table-fixed">
            <colgroup>
              <col className="w-10" />
              <col className="w-[22%]" />
              <col className="w-[13%]" />
              <col className="min-w-[140px] max-w-[180px]" />
              <col className="w-[88px]" />
              <col className="w-[22%]" />
              <col className="w-[96px]" />
              <col className="w-[176px]" />
                </colgroup>
                <thead>
                  <tr>
                    <th className="w-10">
                      <input
                        type="checkbox"
                        aria-label="全选当前页可删除任务"
                        checked={
                          selectableTaskIds.length > 0 &&
                          selectableTaskIds.every((id) => selectedTaskIds.includes(id))
                        }
                        disabled={selectableTaskIds.length === 0}
                        title={
                          selectableTaskIds.length === 0
                            ? "当前页没有可批量删除的任务"
                            : "全选当前页可删除任务"
                        }
                        onChange={(event) => {
                          setSelectedTaskIds(event.target.checked ? selectableTaskIds : []);
                        }}
                      />
                    </th>
                    <th>任务</th>
                    <th>来源/模式</th>
                    <th>关键词/链接</th>
                    <th>状态</th>
                    <th>采集结果</th>
                    <th>最近运行</th>
                    <th className={COLLECTION_TASK_TABLE_LAYOUT.actionsHead}>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {listRows.map((row) => {
                    if (row.kind === "legacy_batch") {
                      const batch = row.batch;
                      const status = statusMeta(legacyBatchStatus(batch.status));
                      const isBusy = actionLegacyBatchId === batch.id;
                      const isRunning = batch.status === "running";
                      return (
                        <tr key={`legacy-${batch.id}`} className="group border-b align-middle last:border-0 hover:bg-muted/20">
                          <td className="px-2 py-3" />
                          <td className="min-w-0 px-4 py-3">
                            <div className="line-clamp-2 font-medium" title={batch.name}>
                              {batch.name}
                            </div>
                            <div className="mt-1 truncate text-xs text-muted-foreground">历史链接导入批次</div>
                            {batch.error_message ? (
                              <p className="mt-1 line-clamp-2 text-xs text-destructive" title={batch.error_message}>
                                {batch.error_message}
                              </p>
                            ) : null}
                          </td>
                          <td className="px-4 py-3 whitespace-nowrap">
                            <div className="flex flex-col gap-1.5">
                              <Badge variant="outline" className="w-fit text-xs">
                                链接导入
                              </Badge>
                              <Badge variant="secondary" className="w-fit text-xs">
                                历史批次
                              </Badge>
                            </div>
                          </td>
                          <td className="max-w-[160px] px-4 py-3">
                            <p className="line-clamp-2">{batch.total_count} 条链接</p>
                          </td>
                          <td className={COLLECTION_TASK_TABLE_LAYOUT.statusCell}>
                            <div className="flex flex-col gap-1">
                              <Badge variant={status.variant} className={COLLECTION_TASK_TABLE_LAYOUT.statusBadge}>
                                {status.label}
                              </Badge>
                              {isLegacyBatchIneffective(batch) ? (
                                <Badge variant="outline" className="w-fit text-[10px]">
                                  无效果
                                </Badge>
                              ) : null}
                            </div>
                          </td>
                          <td className="min-w-0 px-4 py-3 align-top text-sm text-muted-foreground">
                            成功 {batch.success_count ?? 0}/{batch.total_count} · 新增 {batch.new_count ?? 0} · 更新{" "}
                            {batch.updated_count ?? 0}
                          </td>
                          <td className="whitespace-nowrap px-4 py-3 text-muted-foreground">
                            {formatDate(batch.completed_at ?? batch.created_at)}
                          </td>
                          <td className={COLLECTION_TASK_TABLE_LAYOUT.actionsCell}>
                            <div className={COLLECTION_TASK_TABLE_LAYOUT.actionsGroup}>
                              <Button
                                size="sm"
                                variant="ghost"
                                className={COLLECTION_TASK_TABLE_LAYOUT.actionButton}
                                disabled={isBusy || isRunning}
                                onClick={() => void handleRunLegacyBatch(batch)}
                                title="运行历史导入批次"
                              >
                                {isBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                              </Button>
                              <Button
                                size="sm"
                                variant="ghost"
                                className={`${COLLECTION_TASK_TABLE_LAYOUT.actionButton} text-destructive hover:bg-destructive/10 hover:text-destructive`}
                                disabled={isBusy || isRunning}
                                onClick={() => void handleDeleteLegacyBatch(batch)}
                                title="删除历史批次"
                              >
                                <Trash2 className="h-4 w-4" />
                              </Button>
                            </div>
                          </td>
                        </tr>
                      );
                    }

                    const task = row.task;
                    const status = statusMeta(task.status);
                    const isBusy = actionTaskId === task.id;
                    const isRunning = isCollectionTaskRunning(task);
                    const isPaused = isCollectionTaskPaused(task);
                    const isQueued = isCollectionTaskQueued(task);
                    const isStaleRunning = isRunning && isCollectionTaskRunningStale(task);
                    const runningElapsedMs = isRunning ? getCollectionTaskRunningElapsedMs(task, nowMs) : 0;
                    const runBlocked = isRunning && !isStaleRunning;
                    const mode = task.collection_mode ?? "keyword";
                    const keywords = task.keywords ?? [];
                    const followerRange = formatFollowerRange(task);
                    const keywordFilters = formatKeywordFilters(task);
                    const platformGroupLabel = taskPlatformGroupLabel(mode);
                    const productClueGroupLabel = taskProductClueGroupLabel(mode);
                    const displayPlatforms = taskDisplayPlatforms(task);
                    const amazonSeeds = extractAmazonProductSeeds(task.run_checkpoint);
                    const keywordsOrLinksText = formatTaskKeywordsOrLinks(task);
                    const keywordsOrLinksTitle =
                      mode === "competitor_product" || mode === "link_import"
                        ? keywordsOrLinksText
                        : keywords.join(", ") || (task.input_urls ?? []).join(", ");
                    const showModeBadge =
                      taskModeBadgeLabel(mode) !== taskSourceLabelForMode(mode);
                    const managementTags = taskManagementTags(task);
                    const batchChildren = task.child_tasks ?? [];
                    const isBatchParent = !task.parent_task_id && (task.batch_round_count ?? 0) > 1;
                    const batchExpanded = expandedBatchIds.includes(task.id);
                    const failedBatchChildren = batchChildren.filter((child) =>
                      child.status === "failed" || child.status === "partial_failed"
                    );
                    const selectionBlockedReason = getTaskSelectionBlockedReason(task);

                    return (
                      <Fragment key={task.id}>
                      <tr className="group border-b align-middle last:border-0 hover:bg-muted/20">
                        <td className="px-2 py-3">
                          <input
                            type="checkbox"
                            aria-label={`选择任务 ${task.name}`}
                            checked={selectedTaskIds.includes(task.id)}
                            disabled={!selectableTaskIds.includes(task.id)}
                            title={selectionBlockedReason || "选择该任务用于批量删除"}
                            onChange={() => toggleTaskSelection(task.id)}
                          />
                        </td>
                        <td className="min-w-0 px-4 py-3">
                          <div className="line-clamp-2 font-medium leading-snug" title={task.name}>
                            {task.name}
                          </div>
                          {isBatchParent ? (
                            <button
                              type="button"
                              className="mt-1 inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
                              onClick={() =>
                                setExpandedBatchIds((prev) =>
                                  prev.includes(task.id)
                                    ? prev.filter((id) => id !== task.id)
                                    : [...prev, task.id],
                                )
                              }
                            >
                              <ChevronDown className={`h-3.5 w-3.5 transition-transform ${batchExpanded ? "rotate-180" : ""}`} />
                              {batchExpanded ? "收起轮次" : `展开 ${batchChildren.length || task.batch_round_count} 个轮次`}
                            </button>
                          ) : null}
                          <div className="mt-1 truncate text-xs text-muted-foreground">
                            {formatTargetLabel(task)}
                            {" · 互动率 ≥"}
                            {formatPercent(task.min_engagement_rate)}
                            {followerRange ? ` · ${followerRange}` : ""}
                            {keywordFilters ? ` · ${keywordFilters}` : ""}
                            {task.max_runtime_minutes ? ` · 最长 ${task.max_runtime_minutes} 分钟` : ""}
                          </div>
                          {shouldShowCollectionTaskErrorMessage(task) ? (
                            <p
                              className="mt-1 line-clamp-2 text-xs text-destructive"
                              title={translateErrorMessage(task.error_message!)}
                            >
                              {translateErrorMessage(task.error_message!)}
                            </p>
                          ) : null}
                        </td>
                        <td className="px-4 py-3 align-top">
                          <div className="flex flex-col gap-1.5 max-w-full overflow-hidden">
                            <Badge variant="outline" className="w-fit text-xs break-words">
                              {taskSourceLabelForMode(mode)}
                            </Badge>
                            {showModeBadge ? (
                              <Badge variant="outline" className="w-fit text-xs">
                                {taskModeBadgeLabel(mode)}
                              </Badge>
                            ) : null}
                            {displayPlatforms.length && platformGroupLabel ? (
                              <div className="flex flex-col gap-1">
                                <span className="text-[10px] leading-none text-muted-foreground">
                                  {platformGroupLabel}
                                </span>
                                <div className="flex flex-wrap gap-1">
                                  {displayPlatforms.map((p) => (
                                    <Badge key={p} variant="secondary" className="w-fit text-xs">
                                      {platformLabel(p)}
                                    </Badge>
                                  ))}
                                </div>
                              </div>
                            ) : null}
                            {productClueGroupLabel && amazonSeeds.length > 0 ? (
                              <div className="flex flex-col gap-1">
                                <span className="text-[10px] leading-none text-muted-foreground">
                                  {productClueGroupLabel}
                                </span>
                                <div className="space-y-1 text-[11px] leading-snug text-muted-foreground">
                                  {amazonSeeds.map((seed, index) => (
                                    <p
                                      key={`${seed.asin ?? seed.normalized_url ?? index}`}
                                      className="line-clamp-2"
                                      title={formatAmazonProductClueLine(seed)}
                                    >
                                      {formatAmazonProductClueLine(seed)}
                                    </p>
                                  ))}
                                </div>
                              </div>
                            ) : null}
                          </div>
                        </td>
                        <td className="max-w-[160px] px-4 py-3">
                          <p className="line-clamp-2" title={keywordsOrLinksTitle}>
                            {keywordsOrLinksText}
                          </p>
                          {(task.country || task.category) && (
                            <p className="mt-1 truncate text-xs text-muted-foreground">
                              {[task.country, task.category].filter(Boolean).join(" · ")}
                            </p>
                          )}
                        </td>
                        <td className={COLLECTION_TASK_TABLE_LAYOUT.statusCell}>
                          <div className="flex flex-col gap-1">
                            <Badge variant={status.variant} className={COLLECTION_TASK_TABLE_LAYOUT.statusBadge}>
                              {status.label}
                            </Badge>
                            {taskEffectivenessCategory(task) === "high_value" ? (
                              <Badge variant="success" className="w-fit text-[10px]">高价值</Badge>
                            ) : isTaskRowIneffective(task) ? (
                              <Badge variant="outline" className="w-fit text-[10px]">
                                {taskEffectivenessCategoryLabel(taskEffectivenessCategory(task))}
                              </Badge>
                            ) : null}
                            {managementTags
                              .filter((tag) => tag.key !== "high_value")
                              .map((tag) => (
                                <Badge key={tag.key} variant={tag.variant} className="w-fit text-[10px]">
                                  {tag.label}
                                </Badge>
                              ))}
                          </div>
                        </td>
                        <td className="min-w-0 px-4 py-3 align-top">
                          {formatCollectionResultCell(task, {
                            isStaleRunning,
                            elapsedMs: runningElapsedMs,
                            slowThresholdMs: staleAfterSeconds * 1000,
                          })}
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-muted-foreground">
                          {formatDate(task.last_run_at)}
                        </td>
                        <td className={COLLECTION_TASK_TABLE_LAYOUT.actionsCell}>
                          <div className={COLLECTION_TASK_TABLE_LAYOUT.actionsGroup}>
                            <Button
                              size="sm"
                              variant="ghost"
                              className={COLLECTION_TASK_TABLE_LAYOUT.actionButton}
                              disabled={isBusy}
                              onClick={() => {
                                setCandidatesTask(task);
                                setCandidatesOpen(true);
                              }}
                              title="查看候选池"
                            >
                              <List className="h-4 w-4" />
                            </Button>
                            {isBatchParent ? (
                              <>
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  className={COLLECTION_TASK_TABLE_LAYOUT.actionButton}
                                  disabled={isBusy || batchChildren.length === 0}
                                  onClick={() => handleRun(task)}
                                  title="启动多轮采集"
                                >
                                  {isBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                                </Button>
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  className={COLLECTION_TASK_TABLE_LAYOUT.actionButton}
                                  disabled={isBusy || failedBatchChildren.length === 0}
                                  onClick={() => void handleRunBatch(task, true)}
                                  title="只运行失败轮次"
                                >
                                  <RefreshCw className="h-4 w-4" />
                                </Button>
                              </>
                            ) : null}
                            {(isRunning || isQueued || isPaused) ? (
                              <Button
                                size="sm"
                                variant="ghost"
                                className={`${COLLECTION_TASK_TABLE_LAYOUT.actionButton} text-destructive hover:bg-destructive/10 hover:text-destructive`}
                                disabled={isBusy}
                                onClick={() => void handleStop(task)}
                                title="停止采集并保留已入库数据"
                              >
                                {isBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Square className="h-4 w-4 fill-current" />}
                              </Button>
                            ) : null}
                            <Button
                              size="sm"
                              variant="ghost"
                              className={COLLECTION_TASK_TABLE_LAYOUT.actionButton}
                              disabled={isBusy || runBlocked || isPaused || isBatchParent}
                              onClick={() => handleRun(task)}
                              title={
                                isStaleRunning
                                    ? "上次运行可能中断，继续采集"
                                    : isRunning
                                      ? "任务采集中"
                                      : "运行采集"
                              }
                            >
                              {isBusy ? (
                                <Loader2 className="h-4 w-4 animate-spin" />
                              ) : (
                                <Play className="h-4 w-4" />
                              )}
                            </Button>
                            {(isRunning || isQueued) && !isBatchParent ? (
                              <Button
                                size="sm"
                                variant="ghost"
                                className={COLLECTION_TASK_TABLE_LAYOUT.actionButton}
                                disabled={isBusy}
                                onClick={() => void handlePause(task)}
                                title="暂停采集，保留已采集数据和进度"
                              >
                                {isBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Pause className="h-4 w-4" />}
                              </Button>
                            ) : isPaused && !isBatchParent ? (
                              <Button
                                size="sm"
                                variant="ghost"
                                className={COLLECTION_TASK_TABLE_LAYOUT.actionButton}
                                disabled={isBusy}
                                onClick={() => void handleResume(task)}
                                title="继续采集，从上次进度恢复"
                              >
                                {isBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                              </Button>
                            ) : null}
                            <Button
                              size="sm"
                              variant="ghost"
                              className={COLLECTION_TASK_TABLE_LAYOUT.actionButton}
                              disabled={isBusy}
                              onClick={() => openEditDialog(task)}
                              title="编辑"
                            >
                              <Pencil className="h-4 w-4" />
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              className={COLLECTION_TASK_TABLE_LAYOUT.actionButton}
                              disabled={isBusy}
                              onClick={() => handleSendEmail(task)}
                              title="发送邮件"
                            >
                              <Mail className="h-4 w-4" />
                            </Button>
                            {isTaskRowIneffective(task) &&
                            (effectivenessFilter === "low_value_result" ||
                              effectivenessFilter === "no_result") ? (
                              <Button
                                size="sm"
                                variant="ghost"
                                className={`${COLLECTION_TASK_TABLE_LAYOUT.actionButton} text-destructive hover:bg-destructive/10 hover:text-destructive`}
                                disabled={isBusy || isRunning}
                                onClick={() => handleDelete(task)}
                                title="删除或归档无效果任务"
                              >
                                <Trash2 className="h-4 w-4" />
                              </Button>
                            ) : null}
                          </div>
                        </td>
                      </tr>
                      {isBatchParent && batchExpanded
                        ? batchChildren.map((child) => {
                            const childStatus = statusMeta(child.status);
                            const childPaused = child.status === "paused";
                            return (
                              <tr key={`child-${child.id}`} className="border-b bg-muted/10 text-sm">
                                <td className="px-2 py-2" />
                                <td className="px-4 py-2 pl-8">
                                  <div className="font-medium">{child.name}</div>
                                  <div className="mt-1 text-xs text-muted-foreground">
                                    第 {child.batch_round_index ?? "-"} / {child.batch_round_count ?? task.batch_round_count} 轮
                                  </div>
                                </td>
                                <td className="px-4 py-2">
                                  <Badge variant="outline" className="w-fit text-xs">子任务</Badge>
                                </td>
                                <td className="max-w-[160px] px-4 py-2">
                                  <p className="line-clamp-2" title={(child.keywords ?? []).join(", ")}>
                                    {(child.keywords ?? []).join(", ") || "-"}
                                  </p>
                                </td>
                                <td className={COLLECTION_TASK_TABLE_LAYOUT.statusCell}>
                                  <Badge variant={childStatus.variant} className={COLLECTION_TASK_TABLE_LAYOUT.statusBadge}>
                                    {childStatus.label}
                                  </Badge>
                                </td>
                                <td className="px-4 py-2 text-muted-foreground">
                                  已入库 {child.inserted_count ?? 0} / 目标 {child.discovery_limit ?? "-"}
                                  {child.deduped_count ? ` · 去重 ${child.deduped_count}` : ""}
                                </td>
                                <td className="whitespace-nowrap px-4 py-2 text-muted-foreground">
                                  {formatDate(child.last_run_at)}
                                </td>
                                <td className={COLLECTION_TASK_TABLE_LAYOUT.actionsCell}>
                                  <div className={COLLECTION_TASK_TABLE_LAYOUT.actionsGroup}>
                                    <Button
                                      size="sm"
                                      variant="ghost"
                                      className={COLLECTION_TASK_TABLE_LAYOUT.actionButton}
                                      disabled={actionTaskId === child.id || child.status === "running"}
                                      onClick={() => {
                                        const childTask = { ...task, ...child, parent_task_id: task.id } as CollectionTask;
                                        void (childPaused ? handleResume(childTask) : handleRun(childTask));
                                      }}
                                      title="运行本轮"
                                    >
                                      {actionTaskId === child.id ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                                    </Button>
                                  </div>
                                </td>
                              </tr>
                            );
                          })
                        : null}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
              <div className="flex flex-wrap items-center justify-between gap-3 border-t bg-muted/20 px-4 py-3 text-sm">
                <div className="text-muted-foreground">
                  每页
                  <select
                    className="mx-2 rounded-md border bg-background px-2 py-1"
                    value={pageSize}
                    onChange={(event) => changePageSize(Number(event.target.value))}
                    aria-label="每页任务数量"
                  >
                    {TASK_PAGE_SIZE_OPTIONS.map((size) => (
                      <option key={size} value={size}>
                        {size}
                      </option>
                    ))}
                  </select>
                  条，共 {total} 个任务
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={page <= 1 || loading}
                    onClick={() => setPage((current) => Math.max(1, current - 1))}
                  >
                    上一页
                  </Button>
                  <span className="min-w-[96px] text-center text-muted-foreground">
                    {page} / {totalPages}
                  </span>
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={page >= totalPages || loading}
                    onClick={() => setPage((current) => Math.min(totalPages, current + 1))}
                  >
                    下一页
                  </Button>
                </div>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
      </div>

      <TaskFormDialog
        open={dialogOpen}
        mode={dialogMode}
        initialTask={editingTask}
        defaultSourceMethod={defaultSourceMethod}
        submitting={submitting}
        onClose={() => setDialogOpen(false)}
        onSubmit={handleSubmit}
      />

      <TaskCandidatesDialog
        task={candidatesTask}
        open={candidatesOpen}
        onClose={() => {
          setCandidatesOpen(false);
          setCandidatesTask(null);
        }}
      />

      <TaskDeleteConfirmDialog
        open={Boolean(deleteDialog?.open)}
        title={deleteDialog?.title ?? ""}
        body={deleteDialog?.body ?? ""}
        confirmLabel={deleteDialog?.confirmLabel}
        loading={deleteSubmitting}
        onConfirm={() => void executeDeleteDialog()}
        onCancel={() => {
          if (!deleteSubmitting) setDeleteDialog(null);
        }}
      />
    </AdminShell>
  );
}
