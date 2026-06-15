import type { CollectionTask, LinkImportBatch } from "@/lib/api";

export type TaskEffectivenessCategory = "effective" | "low_value_result" | "no_result";

export type TaskEffectivenessFilter =
  | "all"
  | "effective"
  | "low_value_result"
  | "no_result"
  | "ineffective";

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
  if (inserted <= 0 && task.status !== "completed_with_results") {
    return "no_result";
  }
  return "low_value_result";
}

export function taskEffectivenessCategoryLabel(category: TaskEffectivenessCategory): string {
  switch (category) {
    case "effective":
      return "有效果";
    case "low_value_result":
      return "无价值结果";
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
  return taskEffectivenessCategory(task) !== "effective";
}

export function taskHasRetentionData(task: CollectionTask): boolean {
  return Boolean(task.has_retention_traces);
}

export function matchesEffectivenessFilter(
  filter: TaskEffectivenessFilter,
  task: CollectionTask,
): boolean {
  if (filter === "all") return true;
  const category = taskEffectivenessCategory(task);
  if (filter === "ineffective") {
    return category === "low_value_result" || category === "no_result";
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
