"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Loader2, List, Mail, Pencil, Play, Plus, RefreshCw, Trash2, X } from "lucide-react";

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
  collectionTaskRunningHint,
  formatCollectionResultLines,
  formatTargetLabel,
  isCollectionTaskRateLimited,
  isCollectionTaskSlowApi,
} from "@/lib/collection-task-progress";
import {
  buildCollectionTaskCompletionMessage,
  buildInfluencersPageUrl,
  bulkDeleteCollectionTasks,
  COLLECTION_TASK_POLL_INTERVAL_MS,
  COLLECTION_TASK_SLOW_HINT_MS,
  createCollectionTask,
  deleteLinkImportBatch,
  fetchCollectionTasks,
  fetchLinkImportBatches,
  getCollectionTaskRunningElapsedMs,
  isCollectionTaskRunning,
  isCollectionTaskRunningStale,
  isCollectionTaskSettled,
  runCollectionTask,
  runLinkImportBatch,
  sendCollectionTaskEmail,
  updateCollectionTask,
  type CollectionTask,
  type CollectionTaskPayload,
  type CollectionTaskStatus,
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
  matchesEffectivenessFilter,
  matchesLegacyBatchFilter,
  taskEffectivenessCategory,
  taskEffectivenessCategoryLabel,
  taskHasRetentionData,
  type TaskEffectivenessFilter,
} from "@/lib/task-effectiveness";

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

function formatCollectionResultCell(
  task: CollectionTask,
  options: { isStaleRunning?: boolean; elapsedMs?: number } = {},
) {
  const { isStaleRunning = false, elapsedMs = 0 } = options;
  const lines = formatCollectionResultLines(task);
  const runningHint = collectionTaskRunningHint(task, {
    elapsedMs,
    slowThresholdMs: COLLECTION_TASK_SLOW_HINT_MS,
    stale: isStaleRunning,
    recoverable: task.recoverable,
  });

  if (isStaleRunning) {
    return (
      <>
        <span className="inline-flex items-center gap-1.5 text-amber-700 dark:text-amber-400">
          <RefreshCw className="h-3.5 w-3.5 shrink-0" />
          任务可能中断，可重新运行继续
        </span>
        <span className="mt-0.5 block text-xs text-muted-foreground">{lines.primary}</span>
        <span className="mt-0.5 block text-xs text-muted-foreground">{lines.funnel}</span>
      </>
    );
  }

  if (isCollectionTaskRunning(task)) {
    const rateLimited = isCollectionTaskRateLimited(task);
    const slowApi = isCollectionTaskSlowApi(task, elapsedMs, COLLECTION_TASK_SLOW_HINT_MS);
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
  if (inserted > 0) {
    return (
      <>
        <Link
          href={buildInfluencersPageUrl({ taskId: task.id, taskName: task.name })}
          className="block rounded-sm text-primary transition-colors hover:bg-primary/5 hover:underline"
          title="查看该任务入库红人"
        >
          {lines.primary}
        </Link>
        <span className="mt-0.5 block text-xs text-muted-foreground">
          {inserted} 条 / 邮箱 {task.email_count ?? 0} / 缺联系 {task.missing_contact_count ?? 0}
        </span>
        <span className="mt-0.5 block text-xs text-muted-foreground">{lines.funnel}</span>
      </>
    );
  }

  return (
    <>
      <span className="text-muted-foreground">{lines.primary}</span>
      <span className="mt-0.5 block text-xs text-muted-foreground">{lines.funnel}</span>
      {lines.hint || task.status_summary ? (
        <span
          className="mt-0.5 block line-clamp-2 text-xs text-muted-foreground"
          title={lines.hint ?? task.status_summary ?? undefined}
        >
          {lines.hint ?? task.status_summary}
        </span>
      ) : null}
    </>
  );
}

type TaskToast = {
  tone: "success" | "warning" | "error" | "info";
  message: string;
};

type TaskListRow =
  | { kind: "task"; task: CollectionTask; sortAt: number }
  | { kind: "legacy_batch"; batch: LinkImportBatch; sortAt: number };

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
  } | null>(null);
  const [deleteSubmitting, setDeleteSubmitting] = useState(false);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const prevStatusRef = useRef<Map<number, CollectionTaskStatus>>(new Map());
  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const showToast = useCallback((next: TaskToast) => {
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    setToast(next);
    toastTimerRef.current = setTimeout(() => setToast(null), 8000);
  }, []);

  const applyTaskList = useCallback((items: CollectionTask[], totalCount: number) => {
    setTasks(items);
    setTotal(totalCount);
    setCandidatesTask((prev) => {
      if (!prev) return prev;
      return items.find((t) => t.id === prev.id) ?? prev;
    });
  }, []);

  const loadTasks = useCallback(async (options?: { silent?: boolean }) => {
    if (!options?.silent) {
      setLoading(true);
    }
    setError(null);
    try {
      const apiEffectiveness =
        effectivenessFilter === "all" ? undefined : effectivenessFilter;
      const [data, batchData] = await Promise.all([
        fetchCollectionTasks(1, 100, { effectiveness: apiEffectiveness }),
        fetchLinkImportBatches(1, 100).catch(() => ({ items: [] as LinkImportBatch[], total: 0 })),
      ]);
      const filteredTasks = data.items.filter((task) =>
        matchesEffectivenessFilter(effectivenessFilter, task),
      );
      const filteredLegacy = batchData.items.filter((batch) =>
        matchesLegacyBatchFilter(effectivenessFilter, batch),
      );
      applyTaskList(filteredTasks, filteredTasks.length + filteredLegacy.length);
      setLegacyBatches(filteredLegacy);
      setSelectedTaskIds((prev) => prev.filter((id) => filteredTasks.some((task) => task.id === id)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载任务列表失败");
    } finally {
      if (!options?.silent) {
        setLoading(false);
      }
    }
  }, [applyTaskList, effectivenessFilter]);

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
  }, [loadTasks, productId, effectivenessFilter]);

  useEffect(() => {
    if (searchParams.get("create") === "link_import") {
      queueMicrotask(() => {
        setDialogMode("create");
        setEditingTask(null);
        setDefaultSourceMethod("link_import");
        setDialogOpen(true);
      });
    }
  }, [searchParams]);

  useEffect(() => {
    return () => {
      if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    };
  }, []);

  const hasRunningTasks = tasks.some((t) => isCollectionTaskRunning(t));
  const activeRunningTask = tasks.find(
    (t) => isCollectionTaskRunning(t) && !isCollectionTaskRunningStale(t),
  );

  useEffect(() => {
    if (!hasRunningTasks) return;
    const tick = () => setNowMs(Date.now());
    tick();
    const clockId = window.setInterval(tick, 1000);
    const pollId = window.setInterval(() => {
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
      if (prev === "running" && isCollectionTaskSettled(task.status)) {
        const completion = buildCollectionTaskCompletionMessage(task);
        const completionMessage =
          completion.tone === "error" && task.error_message
            ? `采集失败：${translateErrorMessage(task.error_message)}`
            : completion.message;
        showToast({ tone: completion.tone, message: completionMessage });
        setMessage(completionMessage);
      }
      prevStatusRef.current.set(task.id, task.status);
    }
  }, [tasks, showToast]);

  function openCreateDialog(sourceMethod: TaskSourceMethod = "keyword_discovery") {
    setDialogMode("create");
    setEditingTask(null);
    setDefaultSourceMethod(sourceMethod);
    setDialogOpen(true);
  }

  function openEditDialog(task: CollectionTask) {
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
        await createCollectionTask(payload);
        setMessage("任务创建成功");
      } else if (editingTask) {
        await updateCollectionTask(editingTask.id, payload);
        setMessage("任务更新成功");
      }
      await loadTasks();
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败");
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
        showToast({ tone: "info", message: runningSummary });
        prevStatusRef.current.set(task.id, "running");
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
        setMessage(completion.message);
        showToast({ tone: completion.tone, message: completion.message });
        await loadTasks({ silent: true });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "运行采集失败");
      await loadTasks({ silent: true });
    } finally {
      setActionTaskId(null);
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

  const selectableTaskIds = ineffectiveTaskIds;

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

  async function executeDeleteDialog() {
    if (!deleteDialog) return;
    setDeleteSubmitting(true);
    setError(null);
    try {
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

  function toggleTaskSelection(taskId: number) {
    if (!selectableTaskIds.includes(taskId)) return;
    setSelectedTaskIds((prev) =>
      prev.includes(taskId) ? prev.filter((id) => id !== taskId) : [...prev, taskId],
    );
  }

  function handleBulkDeleteSelected() {
    const deletableIds = selectedTaskIds.filter((id) => selectableTaskIds.includes(id));
    if (deletableIds.length === 0) {
      setError("只能删除无效果任务");
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
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Button onClick={() => openCreateDialog("keyword_discovery")}>
          <Plus className="h-4 w-4" />
          创建任务
        </Button>
        <Button variant="outline" onClick={() => openCreateDialog("link_import")}>
          链接导入
        </Button>
        <Button variant="outline" onClick={() => void loadTasks()} disabled={loading}>
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          刷新
        </Button>
        <div className="flex flex-wrap items-center gap-1 rounded-md border p-1">
          {(
            [
              ["all", "全部任务"],
              ["effective", "有效果任务"],
              ["low_value_result", "无价值结果"],
              ["no_result", "无结果任务"],
            ] as const
          ).map(([value, label]) => (
            <Button
              key={value}
              size="sm"
              variant={effectivenessFilter === value ? "default" : "ghost"}
              onClick={() => {
                setEffectivenessFilter(value);
                setSelectedTaskIds([]);
              }}
            >
              {label}
            </Button>
          ))}
        </div>
        {effectivenessFilter !== "effective" && ineffectiveTaskIds.length > 0 ? (
          <Button
            variant="outline"
            size="sm"
            disabled={deleteSubmitting}
            onClick={handleDeleteAllIneffectiveOnPage}
          >
            删除本页无效果任务 ({ineffectiveTaskIds.length})
          </Button>
        ) : null}
      </div>

      {activeRunningTask ? (
        <div className="mb-4 rounded-lg border border-primary/30 bg-primary/5 px-4 py-3 text-sm">
          <span className="inline-flex items-center gap-2 font-medium">
            <Loader2 className="h-4 w-4 animate-spin" />
            「{activeRunningTask.name}」正在采集中
          </span>
          <p className="mt-1 text-muted-foreground">
            同一时间仅允许一个采集任务运行，其他任务的「运行」按钮已禁用。请等待状态变为有结果/无结果后再启动下一个。
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

      <Card>
        <CardHeader>
          <CardTitle>任务列表</CardTitle>
          <CardDescription>
            共 {total} 个任务（含历史链接导入批次）
            {effectivenessFilter === "low_value_result"
              ? " · 当前仅显示有入库但资料几乎为空的任务"
              : effectivenessFilter === "no_result"
                ? " · 当前仅显示完全无入库结果的任务"
                : effectivenessFilter === "effective"
                  ? " · 当前仅显示已产生可用资料的有效果任务"
                  : ""}
          </CardDescription>
        </CardHeader>
        <CardContent className="pt-0">
          {(effectivenessFilter === "low_value_result" ||
            effectivenessFilter === "no_result" ||
            effectivenessFilter === "ineffective") &&
          selectedTaskIds.length > 0 ? (
            <div className="mb-3 flex flex-wrap items-center gap-2 rounded-md border border-primary/20 bg-primary/5 px-3 py-2 text-sm">
              <span className="font-medium">已选择 {selectedTaskIds.length} 个任务</span>
              <Button
                variant="destructive"
                size="sm"
                disabled={deleteSubmitting}
                onClick={handleBulkDeleteSelected}
              >
                {deleteSubmitting ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : null}
                批量删除
              </Button>
              <Button variant="outline" size="sm" disabled={deleteSubmitting} onClick={clearTaskSelection}>
                取消选择
              </Button>
            </div>
          ) : null}
          {loading ? (
            <LoadingState label="加载任务列表..." />
          ) : listRows.length === 0 ? (
            <EmptyState
              title="暂无采集任务"
              description="点击「创建任务」配置关键词发现，或使用「链接导入」批量粘贴主页链接。"
            />
          ) : (
            <div className="overflow-x-auto rounded-md border">
              <table className="w-full table-fixed text-sm">
                <colgroup>
                  <col className="w-10" />
                  <col className="w-[24%]" />
                  <col className="w-[10%]" />
                  <col className="w-[12%]" />
                  <col className="w-[88px]" />
                  <col className="w-[22%]" />
                  <col className="w-[96px]" />
                  <col className="w-[180px]" />
                </colgroup>
                <thead className="bg-muted/40">
                  <tr className="border-b text-left text-muted-foreground">
                    <th className="w-10 px-2 py-2.5">
                      <input
                        type="checkbox"
                        aria-label="全选当前页无效果任务"
                        checked={
                          selectableTaskIds.length > 0 &&
                          selectableTaskIds.every((id) => selectedTaskIds.includes(id))
                        }
                        disabled={selectableTaskIds.length === 0}
                        onChange={(event) => {
                          setSelectedTaskIds(event.target.checked ? selectableTaskIds : []);
                        }}
                      />
                    </th>
                    <th className="px-4 py-2.5 font-medium">任务</th>
                    <th className="px-4 py-2.5 font-medium">来源/模式</th>
                    <th className="px-4 py-2.5 font-medium">关键词/链接</th>
                    <th className="px-4 py-2.5 font-medium">状态</th>
                    <th className="px-4 py-2.5 font-medium">采集结果</th>
                    <th className="whitespace-nowrap px-4 py-2.5 font-medium">最近运行</th>
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
                            <div className="truncate font-medium" title={batch.name}>
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
                    const isStaleRunning = isRunning && isCollectionTaskRunningStale(task);
                    const runningElapsedMs = isRunning ? getCollectionTaskRunningElapsedMs(task, nowMs) : 0;
                    const otherTaskRunning = tasks.some(
                      (t) =>
                        t.id !== task.id &&
                        isCollectionTaskRunning(t) &&
                        !isCollectionTaskRunningStale(t),
                    );
                    const runBlocked =
                      (isRunning && !isStaleRunning) || otherTaskRunning;
                    const taskResultSummary = isStaleRunning ? null : task.status_summary;
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

                    return (
                      <tr key={task.id} className="group border-b align-middle last:border-0 hover:bg-muted/20">
                        <td className="px-2 py-3">
                          <input
                            type="checkbox"
                            aria-label={`选择任务 ${task.name}`}
                            checked={selectedTaskIds.includes(task.id)}
                            disabled={!isTaskRowIneffective(task)}
                            onChange={() => toggleTaskSelection(task.id)}
                          />
                        </td>
                        <td className="min-w-0 px-4 py-3">
                          <div className="truncate font-medium" title={task.name}>
                            {task.name}
                          </div>
                          <div className="mt-1 truncate text-xs text-muted-foreground">
                            {formatTargetLabel(task)}
                            {" · 互动率 ≥"}
                            {formatPercent(task.min_engagement_rate)}
                            {followerRange ? ` · ${followerRange}` : ""}
                            {keywordFilters ? ` · ${keywordFilters}` : ""}
                          </div>
                          {task.error_message ? (
                            <p
                              className="mt-1 line-clamp-2 text-xs text-destructive"
                              title={translateErrorMessage(task.error_message)}
                            >
                              {translateErrorMessage(task.error_message)}
                            </p>
                          ) : null}
                          {taskResultSummary ? (
                            <p className="mt-1 line-clamp-3 text-xs text-muted-foreground" title={taskResultSummary}>
                              {taskResultSummary}
                            </p>
                          ) : null}
                        </td>
                        <td className="px-4 py-3 whitespace-nowrap">
                          <div className="flex flex-col gap-1.5">
                            <Badge variant="outline" className="w-fit text-xs">
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
                            {isTaskRowIneffective(task) ? (
                              <Badge variant="outline" className="w-fit text-[10px]">
                                {taskEffectivenessCategoryLabel(taskEffectivenessCategory(task))}
                              </Badge>
                            ) : null}
                          </div>
                        </td>
                        <td className="min-w-0 px-4 py-3 align-top">
                          {formatCollectionResultCell(task, {
                            isStaleRunning,
                            elapsedMs: runningElapsedMs,
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
                            <Button
                              size="sm"
                              variant="ghost"
                              className={COLLECTION_TASK_TABLE_LAYOUT.actionButton}
                              disabled={isBusy || runBlocked}
                              onClick={() => handleRun(task)}
                              title={
                                otherTaskRunning
                                  ? "另有任务正在采集，请等待完成"
                                  : isStaleRunning
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
                              effectivenessFilter === "no_result" ||
                              effectivenessFilter === "ineffective") ? (
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
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

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
