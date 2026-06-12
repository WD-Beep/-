"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2, List, Mail, Pencil, Play, Plus, RefreshCw, Trash2, X } from "lucide-react";

import { AdminShell } from "@/components/layout/admin-shell";
import { useActiveProductId } from "@/components/providers/product-provider";
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
  COLLECTION_TASK_POLL_INTERVAL_MS,
  COLLECTION_TASK_SLOW_HINT_MS,
  createCollectionTask,
  deleteCollectionTask,
  fetchCollectionTasks,
  getCollectionTaskRunningElapsedMs,
  isCollectionTaskRunning,
  isCollectionTaskRunningStale,
  isCollectionTaskSettled,
  runCollectionTask,
  sendCollectionTaskEmail,
  updateCollectionTask,
  type CollectionTask,
  type CollectionTaskPayload,
  type CollectionTaskStatus,
} from "@/lib/api";
import {
  COLLECTION_MODE_LABELS,
  platformLabel,
  taskPlatforms,
  TASK_STATUS_LABELS,
  translateErrorMessage,
} from "@/lib/labels";

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

export function CollectionTasksPanel() {
  const productId = useActiveProductId();
  const [tasks, setTasks] = useState<CollectionTask[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogMode, setDialogMode] = useState<"create" | "edit">("create");
  const [editingTask, setEditingTask] = useState<CollectionTask | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [actionTaskId, setActionTaskId] = useState<number | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [candidatesTask, setCandidatesTask] = useState<CollectionTask | null>(null);
  const [candidatesOpen, setCandidatesOpen] = useState(false);
  const [toast, setToast] = useState<TaskToast | null>(null);
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
      const data = await fetchCollectionTasks(1, 100);
      applyTaskList(data.items, data.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载任务列表失败");
    } finally {
      if (!options?.silent) {
        setLoading(false);
      }
    }
  }, [applyTaskList]);

  useEffect(() => {
    if (productId === null) {
      setLoading(false);
      return;
    }
    queueMicrotask(() => {
      void loadTasks();
    });
  }, [loadTasks, productId]);

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

  function openCreateDialog() {
    setDialogMode("create");
    setEditingTask(null);
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

  async function handleDelete(task: CollectionTask) {
    if (isCollectionTaskRunning(task)) {
      setError("任务正在运行中，无法删除");
      return;
    }
    if (!confirm(`确定删除任务「${task.name}」吗？\n已采集到红人库的数据不会删除。`)) {
      return;
    }

    setActionTaskId(task.id);
    setMessage(null);
    setError(null);
    try {
      await deleteCollectionTask(task.id);
      setMessage("任务已删除");
      await loadTasks();
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除失败");
    } finally {
      setActionTaskId(null);
    }
  }

  return (
    <AdminShell title="Instagram 采集任务" description="创建任务后采集 Instagram 数据，并自动生成 Kimi 画像与合作评分">
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Button onClick={openCreateDialog}>
          <Plus className="h-4 w-4" />
          创建任务
        </Button>
        <Button variant="outline" onClick={() => void loadTasks()} disabled={loading}>
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          刷新
        </Button>
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
          <CardDescription>共 {total} 个采集任务，采集完成后会自动写入红人库与 AI 评分</CardDescription>
        </CardHeader>
        <CardContent className="pt-0">
          {loading ? (
            <LoadingState label="加载任务列表..." />
          ) : tasks.length === 0 ? (
            <EmptyState
              title="暂无采集任务"
              description="点击「创建任务」配置采集模式、关键词或链接后开始采集。"
            />
          ) : (
            <div className="overflow-x-auto rounded-md border">
              <table className="w-full table-fixed text-sm">
                <colgroup>
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
                    <th className="px-4 py-2.5 font-medium">任务</th>
                    <th className="px-4 py-2.5 font-medium">模式/平台</th>
                    <th className="px-4 py-2.5 font-medium">关键词</th>
                    <th className="px-4 py-2.5 font-medium">状态</th>
                    <th className="px-4 py-2.5 font-medium">采集结果</th>
                    <th className="whitespace-nowrap px-4 py-2.5 font-medium">最近运行</th>
                    <th className={COLLECTION_TASK_TABLE_LAYOUT.actionsHead}>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {tasks.map((task) => {
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

                    return (
                      <tr key={task.id} className="group border-b align-middle last:border-0 hover:bg-muted/20">
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
                              {COLLECTION_MODE_LABELS[mode] ?? mode}
                            </Badge>
                            {(taskPlatforms(task).length ? taskPlatforms(task) : [task.platform]).map((p) => (
                              <Badge key={p} variant="secondary" className="w-fit text-xs">
                                {platformLabel(p)}
                              </Badge>
                            ))}
                          </div>
                        </td>
                        <td className="max-w-[160px] px-4 py-3">
                          <p className="line-clamp-2" title={keywords.join(", ")}>
                            {keywords.length ? keywords.join(", ") : "-"}
                          </p>
                          {(task.country || task.category) && (
                            <p className="mt-1 truncate text-xs text-muted-foreground">
                              {[task.country, task.category].filter(Boolean).join(" · ")}
                            </p>
                          )}
                        </td>
                        <td className={COLLECTION_TASK_TABLE_LAYOUT.statusCell}>
                          <Badge variant={status.variant} className={COLLECTION_TASK_TABLE_LAYOUT.statusBadge}>
                            {status.label}
                          </Badge>
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
                            <Button
                              size="sm"
                              variant="ghost"
                              className={`${COLLECTION_TASK_TABLE_LAYOUT.actionButton} text-destructive hover:bg-destructive/10 hover:text-destructive`}
                              disabled={isBusy || isRunning}
                              onClick={() => handleDelete(task)}
                              title="删除任务"
                            >
                              <Trash2 className="h-4 w-4" />
                            </Button>
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
    </AdminShell>
  );
}
