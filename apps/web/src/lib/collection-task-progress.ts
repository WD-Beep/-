import type { CollectionTask } from "./api";

/** 与面板 COLLECTION_TASK_SLOW_HINT_MS 对齐：前端兜底慢接口提示默认 3 分钟。 */
export const COLLECTION_TASK_SLOW_FALLBACK_MS = 3 * 60 * 1000;

const STAGE_LABELS: Record<string, string> = {
  discovery: "发现候选",
  hydration: "主页补采",
  persist: "过滤入库",
  ai_processing: "AI 评分",
  ai_completed: "AI 完成",
  completed: "完成",
  failed: "失败",
  running: "采集中",
};

export const COLLECTION_TASK_TABLE_LAYOUT = {
  statusCell: "min-w-[88px] w-[88px] shrink-0 px-4 py-3 align-middle",
  statusBadge: "inline-flex whitespace-nowrap shrink-0 text-xs",
  actionsCell:
    "sticky right-0 z-10 w-[180px] min-w-[180px] shrink-0 whitespace-nowrap bg-background px-2 py-3 shadow-[-6px_0_8px_-6px_rgba(0,0,0,0.12)] group-hover:bg-muted/20",
  actionsHead:
    "sticky right-0 z-10 w-[180px] min-w-[180px] shrink-0 whitespace-nowrap bg-muted/40 px-2 py-2.5 font-medium shadow-[-6px_0_8px_-6px_rgba(0,0,0,0.12)]",
  actionsGroup: "flex flex-nowrap items-center justify-end gap-0.5",
  actionButton: "h-8 w-8 shrink-0 p-0",
} as const;

export type CollectionTaskProgressSummary = {
  stageLabel: string;
  processed: number;
  totalLabel: string;
  success: number;
  skipped: number;
  failed: number;
  hasStructuredProgress: boolean;
  primary: string;
  detail: string;
  insertedLabel: string;
  rateLimited: boolean;
  slowApi: boolean;
  runningHint: string | null;
};

export type CollectionResultLines = {
  primary: string;
  funnel: string;
  hint: string | null;
};

export function collectionTaskStageLabel(stage: string | null | undefined): string {
  if (!stage) return STAGE_LABELS.running;
  return STAGE_LABELS[stage] ?? stage;
}

export function collectionTaskTargetCount(task: Pick<CollectionTask, "discovery_limit">): number | null {
  if (task.discovery_limit == null || task.discovery_limit <= 0) return null;
  return task.discovery_limit;
}

export function formatTargetLabel(task: Pick<CollectionTask, "discovery_limit">): string {
  const target = collectionTaskTargetCount(task);
  return target == null ? "目标未设置" : `目标 ${target}`;
}

export function formatInsertedVsTarget(task: Pick<CollectionTask, "inserted_count" | "result_count" | "discovery_limit">): string {
  const inserted = task.inserted_count ?? task.result_count ?? 0;
  const target = collectionTaskTargetCount(task);
  if (target == null) return `已入库 ${inserted} / 目标未设置`;
  return `已入库 ${inserted} / 目标 ${target}`;
}

export function isCollectionTaskRateLimited(task: CollectionTask): boolean {
  const checkpoint = task.run_checkpoint ?? {};
  if (checkpoint.rate_limited === true) return true;
  const haystack = `${task.last_error ?? ""} ${task.status_summary ?? ""} ${task.error_message ?? ""}`;
  return /429|限流|rate.?limit/i.test(haystack);
}

export function isCollectionTaskSlowApiFromBackend(task: CollectionTask): boolean {
  const checkpoint = task.run_checkpoint ?? {};
  return checkpoint.slow_api === true;
}

export function isCollectionTaskSlowApi(
  task: CollectionTask,
  elapsedMs = 0,
  slowThresholdMs = COLLECTION_TASK_SLOW_FALLBACK_MS,
): boolean {
  if (task.status !== "running" || isCollectionTaskRateLimited(task)) return false;
  if (isCollectionTaskSlowApiFromBackend(task)) return true;
  if (elapsedMs < slowThresholdMs) return false;
  const discovered = task.discovered_count ?? 0;
  const inserted = task.inserted_count ?? task.result_count ?? 0;
  return discovered === 0 && inserted === 0;
}

/** 区分后端已判定慢接口 vs 前端等待较久的兜底提醒。 */
export function collectionTaskSlowApiHintLabel(
  task: CollectionTask,
  elapsedMs = 0,
  slowThresholdMs = COLLECTION_TASK_SLOW_FALLBACK_MS,
): string | null {
  if (task.status !== "running" || isCollectionTaskRateLimited(task)) return null;
  if (isCollectionTaskSlowApiFromBackend(task)) {
    return "接口响应较慢，继续处理";
  }
  if (elapsedMs >= slowThresholdMs) {
    const discovered = task.discovered_count ?? 0;
    const inserted = task.inserted_count ?? task.result_count ?? 0;
    if (discovered === 0 && inserted === 0) {
      return "等待较久，接口可能响应慢，请稍候";
    }
  }
  return null;
}

export function collectionTaskFunnelLine(task: CollectionTask): string {
  const discovered = task.discovered_count ?? 0;
  const deduped = task.deduped_count ?? 0;
  const fetched = task.profile_fetched_count ?? 0;
  const filtered = task.filtered_out_count ?? 0;
  const inserted = task.inserted_count ?? task.result_count ?? 0;
  const target = collectionTaskTargetCount(task);
  const targetPart = target == null ? "目标未设置" : `${inserted}/${target}`;
  return `发现 ${discovered} → 去重 ${deduped} → 主页 ${fetched} → 过滤 ${filtered} → 入库 ${targetPart}`;
}

function collectionTaskProviderLabel(task: CollectionTask, providerRaw: string | null): string {
  const platform = (task.platform || task.platforms?.[0] || "").toLowerCase();
  if (providerRaw === "api_direct") {
    if (platform === "facebook") return "API Direct Facebook";
    if (platform === "tiktok") return "API Direct TikTok";
    return "API Direct";
  }
  if (providerRaw === "apify") {
    if (platform === "facebook") return "Apify Facebook";
    if (platform === "tiktok") return "Apify TikTok";
    if (platform === "youtube") return "Apify YouTube";
    return "Apify";
  }
  if (platform === "facebook") return "Facebook";
  if (platform === "tiktok") return "TikTok";
  return "YouTube";
}

export function collectionTaskDiscoveryContext(task: CollectionTask): string | null {
  const checkpoint = task.run_checkpoint ?? {};
  const currentKeyword = typeof checkpoint.current_keyword === "string" ? checkpoint.current_keyword : null;
  const providerRaw = typeof checkpoint.discovery_provider === "string" ? checkpoint.discovery_provider : null;
  const provider = collectionTaskProviderLabel(task, providerRaw);
  const completed = typeof checkpoint.keywords_completed === "number" ? checkpoint.keywords_completed : null;
  const total = typeof checkpoint.keywords_total === "number" ? checkpoint.keywords_total : null;
  const discovered = task.discovered_count ?? 0;
  const hydratingTotal =
    typeof checkpoint.profiles_hydrating_total === "number" ? checkpoint.profiles_hydrating_total : null;
  const hydratingCompleted =
    typeof checkpoint.profiles_hydrating_completed === "number" ? checkpoint.profiles_hydrating_completed : null;

  const parts: string[] = [];
  if (currentKeyword) {
    if (total != null && completed != null) {
      parts.push(`${provider}：关键词「${currentKeyword}」（${completed}/${total}）`);
    } else {
      parts.push(`${provider}：关键词「${currentKeyword}」`);
    }
  } else if (total != null && completed != null && total > 0) {
    parts.push(`${provider}：关键词（${completed}/${total}）`);
  }

  if (discovered > 0) {
    parts.push(`已发现 ${discovered} 个候选`);
  }
  if (hydratingTotal != null && hydratingTotal > 0) {
    parts.push(`补采主页 ${hydratingCompleted ?? 0}/${hydratingTotal}`);
  }

  return parts.length > 0 ? parts.join("，") : null;
}

export function collectionTaskRunningHint(
  task: CollectionTask,
  options?: { elapsedMs?: number; slowThresholdMs?: number; stale?: boolean; recoverable?: boolean },
): string | null {
  const elapsedMs = options?.elapsedMs ?? 0;
  const slowThresholdMs = options?.slowThresholdMs ?? COLLECTION_TASK_SLOW_FALLBACK_MS;
  const stale = options?.stale ?? task.stale;
  const recoverable = options?.recoverable ?? task.recoverable;
  if (stale && recoverable) {
    return "任务可能中断，可点击重新运行继续";
  }
  const checkpoint = task.run_checkpoint ?? {};
  const partialSkipped =
    typeof checkpoint.partial_skip_note === "string" ||
    /跳过|继续处理/.test(task.status_summary ?? "");

  if (isCollectionTaskRateLimited(task)) {
    return "平台接口响应慢或限流，系统正在降速重试";
  }
  if (task.status === "running") {
    const stage = collectionTaskStageLabel(task.current_stage);
    const context = collectionTaskDiscoveryContext(task);
    const slowLabel = collectionTaskSlowApiHintLabel(task, elapsedMs, slowThresholdMs);
    const suffixParts = [
      context,
      slowLabel,
      partialSkipped ? "部分已跳过，继续处理" : null,
    ].filter(Boolean);
    if (suffixParts.length > 0) {
      return `正在采集：${stage}（${suffixParts.join("，")}）`;
    }
    if ((task.discovered_count ?? 0) === 0 && (task.inserted_count ?? 0) === 0 && task.status_summary) {
      return task.status_summary;
    }
    return `正在采集：${stage}`;
  }
  return null;
}

export function collectionTaskRunningDetail(task: CollectionTask): string {
  return collectionTaskFunnelLine(task);
}

export function formatCollectionResultLines(task: CollectionTask): CollectionResultLines {
  const insertedLabel = formatInsertedVsTarget(task);
  const funnel = collectionTaskFunnelLine(task);
  let hint: string | null = null;

  if (task.status_summary && task.status !== "running") {
    hint = task.status_summary;
  } else if (task.status === "running" && task.status_summary) {
    hint = task.status_summary;
  }

  return { primary: insertedLabel, funnel, hint };
}

export function collectionTaskProgressSummary(
  task: Pick<
    CollectionTask,
    | "status"
    | "current_stage"
    | "processed_count"
    | "total_estimate"
    | "success_count"
    | "failed_count"
    | "skipped_count"
    | "inserted_count"
    | "result_count"
    | "discovery_limit"
    | "discovered_count"
    | "deduped_count"
    | "profile_fetched_count"
    | "filtered_out_count"
    | "last_error"
    | "status_summary"
    | "error_message"
    | "run_checkpoint"
  >,
): CollectionTaskProgressSummary {
  const processed = Math.max(0, task.processed_count ?? 0);
  const total = Math.max(0, task.total_estimate ?? 0);
  const success = Math.max(0, task.success_count ?? task.inserted_count ?? task.result_count ?? 0);
  const skipped = Math.max(0, task.skipped_count ?? 0);
  const failed = Math.max(0, task.failed_count ?? 0);
  const stageLabel = collectionTaskStageLabel(task.current_stage ?? task.status);
  const target = collectionTaskTargetCount(task as CollectionTask);
  const totalLabel = total > 0 ? String(total) : target == null ? "?" : String(target);
  const rateLimited = isCollectionTaskRateLimited(task as CollectionTask);
  const slowApi = isCollectionTaskSlowApi(task as CollectionTask);
  const hasStructuredProgress = Boolean(
    task.current_stage || processed > 0 || total > 0 || success > 0 || skipped > 0 || failed > 0 ||
      (task.discovered_count ?? 0) > 0,
  );
  const insertedLabel = formatInsertedVsTarget(task);
  const runningHint = collectionTaskRunningHint(task as CollectionTask);

  let primary = `${stageLabel} ${processed}/${totalLabel}`;
  let detail = `成功 ${success} / 跳过 ${skipped} / 失败 ${failed}`;

  if (task.status === "running") {
    if (rateLimited) {
      primary = "接口限流/降速重试";
      detail = `${insertedLabel}；${collectionTaskFunnelLine(task as CollectionTask)}`;
    } else if (
      task.current_stage === "persist" &&
      (success > 0 || skipped > 0 || failed > 0 || processed > 0)
    ) {
      primary = `${stageLabel} ${processed}/${totalLabel}`;
      detail = `成功 ${success} / 跳过 ${skipped} / 失败 ${failed}`;
    } else {
      primary = runningHint ?? `正在采集：${stageLabel}`;
      detail = `${insertedLabel}；${collectionTaskFunnelLine(task as CollectionTask)}`;
    }
  } else if (task.current_stage === "persist") {
    detail = `${insertedLabel}，已处理 ${processed}/${total || "?"}`;
  }

  return {
    stageLabel,
    processed,
    totalLabel,
    success,
    skipped,
    failed,
    hasStructuredProgress,
    primary,
    detail,
    insertedLabel,
    rateLimited,
    slowApi,
    runningHint,
  };
}
