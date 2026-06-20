import type { CollectionTask, LinkImportBatch } from "@/lib/api";

export type TaskEffectivenessCategory = "high_value" | "effective" | "low_value_result" | "no_result" | "failed";

export type TaskEffectivenessFilter =
  | "all"
  | "high_value"
  | "effective"
  | "low_value_result"
  | "no_result"
  | "ineffective"
  | "test_history"
  | "archived";

export type TaskManagementTag = {
  key: string;
  label: string;
  variant: "default" | "secondary" | "success" | "warning" | "destructive" | "outline";
};

const TEST_HISTORY_NAME_RE = /(test|测试|验收|seed-discovery-tiktok|ins采集|ltk-import|demo)/i;

export function taskEffectivenessCategory(task: CollectionTask): TaskEffectivenessCategory {
  if (task.effectiveness_category) {
    return task.effectiveness_category;
  }
  if (task.status === "running") return "no_result";
  const inserted = Math.max(
    task.inserted_count ?? 0,
    task.result_count ?? 0,
    task.success_count ?? 0,
  );
  const discovered = task.discovered_count ?? 0;
  const fetched = task.profile_fetched_count ?? 0;
  const email = task.email_count ?? 0;
  if (
    inserted >= 5 ||
    (task.result_count ?? 0) >= 5 ||
    (discovered >= 50 && inserted >= 1) ||
    (fetched >= 20 && inserted >= 1) ||
    (email >= 1 && inserted >= 1) ||
    ((task.status === "completed_with_results" || task.status === "partial_failed") &&
      inserted > 0 &&
      discovered >= inserted &&
      fetched >= inserted &&
      (discovered >= 10 || fetched >= 10))
  ) {
    return "high_value";
  }
  if (inserted <= 0 && task.status !== "completed_with_results") {
    if (task.status === "failed") return "failed";
    return "no_result";
  }
  if (inserted === 1 && discovered <= 3) return "low_value_result";
  return "effective";
}

export function taskEffectivenessCategoryLabel(category: TaskEffectivenessCategory): string {
  switch (category) {
    case "high_value":
      return "高价值";
    case "effective":
      return "有效";
    case "low_value_result":
      return "低价值结果";
    case "failed":
      return "失败";
    default:
      return "无结果";
  }
}

export function isLegacyBatchIneffective(batch: LinkImportBatch): boolean {
  if (batch.status === "running") return false;
  if (batch.status === "pending" && !batch.completed_at) return false;

  const inserted = (batch.new_count ?? 0) + (batch.updated_count ?? 0);
  if (inserted > 0) return false;

  return Boolean(batch.completed_at) || batch.status === "failed" || batch.status === "completed";
}

export function isTaskRowIneffective(task: CollectionTask): boolean {
  if (task.status === "running") return false;
  return !["high_value", "effective"].includes(taskEffectivenessCategory(task));
}

export function isTaskTestHistory(task: CollectionTask): boolean {
  if (task.management_tags?.includes("test_task") || task.management_tags?.includes("history_batch")) {
    return true;
  }
  if (TEST_HISTORY_NAME_RE.test(task.name ?? "")) return true;
  const checkpoint = task.run_checkpoint ?? {};
  return checkpoint.link_import_source === true || checkpoint.legacy_link_import_batch === true;
}

export function taskManagementTags(task: CollectionTask): TaskManagementTag[] {
  const raw = new Set(task.management_tags ?? []);
  if (isTaskTestHistory(task)) {
    if (TEST_HISTORY_NAME_RE.test(task.name ?? "")) raw.add("test_task");
    const checkpoint = task.run_checkpoint ?? {};
    if (checkpoint.link_import_source === true || checkpoint.legacy_link_import_batch === true) {
      raw.add("history_batch");
    }
  }
  if (task.is_possible_duplicate) raw.add("possible_duplicate");
  if (task.is_archived) raw.add("archived");
  const category = taskEffectivenessCategory(task);
  if (category === "high_value") raw.add("high_value");
  if (category === "no_result") raw.add("no_result");
  if (category === "failed") raw.add("failed");

  const labels: Record<string, TaskManagementTag> = {
    test_task: { key: "test_task", label: "测试任务", variant: "warning" },
    history_batch: { key: "history_batch", label: "历史批次", variant: "secondary" },
    no_result: { key: "no_result", label: "无结果", variant: "outline" },
    failed: { key: "failed", label: "失败", variant: "destructive" },
    high_value: { key: "high_value", label: "高价值", variant: "success" },
    archivable: { key: "archivable", label: "可归档", variant: "outline" },
    possible_duplicate: { key: "possible_duplicate", label: "可能重复", variant: "warning" },
    archived: { key: "archived", label: "已归档", variant: "secondary" },
  };
  return [...raw].map((key) => labels[key]).filter((tag): tag is TaskManagementTag => Boolean(tag));
}

export function taskHasRetentionData(task: CollectionTask): boolean {
  return Boolean(task.has_retention_traces);
}

export function matchesEffectivenessFilter(
  filter: TaskEffectivenessFilter,
  task: CollectionTask,
): boolean {
  if (filter === "archived") return task.is_archived === true;
  if (task.is_archived) return false;
  if (filter === "test_history") return isTaskTestHistory(task);
  if (filter === "all") return true;
  const category = taskEffectivenessCategory(task);
  if (filter === "ineffective") {
    return category === "low_value_result" || category === "no_result" || category === "failed";
  }
  return category === filter;
}

export function matchesLegacyBatchFilter(
  filter: TaskEffectivenessFilter,
  batch: LinkImportBatch,
): boolean {
  if (filter === "all") return true;
  if (filter === "effective") return false;
  const ineffective = isLegacyBatchIneffective(batch);
  return filter === "ineffective" || filter === "no_result" || filter === "low_value_result"
    ? ineffective
    : !ineffective;
}

export function nextTaskListPageForFilterChange(options: {
  currentPage: number;
  changed: boolean;
}): number {
  return options.changed ? 1 : options.currentPage;
}

export function buildTaskDeleteConfirmCopy(options: {
  count: number;
  hasRetentionData: boolean;
  taskName?: string;
}): { title: string; body: string; confirmLabel: string } {
  const { count, hasRetentionData, taskName } = options;
  const title = count > 1 ? `确定处理 ${count} 个可清理任务？` : `确定处理任务「${taskName ?? ""}」？`;
  const lines = [
    count > 1
      ? "将删除/归档所选无结果或无价值结果任务。不会删除红人库数据和来源作品关系。"
      : "将删除/归档该无结果或无价值结果任务。不会删除红人库数据和来源作品关系。",
  ];

  if (hasRetentionData) {
    lines.push(
      "所选任务存在历史入库或来源追溯数据，将归档隐藏（不物理删除），红人库与来源链接均保留。",
    );
  } else {
    lines.push("所选任务未产生可追溯数据，可安全物理删除。");
  }

  return {
    title,
    body: lines.join("\n"),
    confirmLabel: hasRetentionData
      ? count > 1
        ? "批量归档"
        : "归档任务"
      : count > 1
        ? "批量删除"
        : "删除任务",
  };
}

export function buildTaskDeleteResultMessage(result: {
  deleted_count?: number;
  archived_count?: number;
  skipped_count?: number;
}): string {
  const deleted = result.deleted_count ?? 0;
  const archived = result.archived_count ?? 0;
  const skipped = result.skipped_count ?? 0;
  const parts: string[] = [];

  if (deleted > 0) parts.push(`已删除 ${deleted} 个`);
  if (archived > 0) parts.push(`已归档 ${archived} 个`);
  if (skipped > 0) parts.push(`跳过 ${skipped} 个`);

  return parts.length > 0 ? parts.join("，") : "操作已完成";
}
