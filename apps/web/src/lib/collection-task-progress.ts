import type { CollectionTask } from "./api";
import { collectionTaskSeedDiscoveryDiagnosticHint } from "./shopping-seed-diagnostics.ts";

export { collectionTaskSeedDiscoveryDiagnosticHint } from "./shopping-seed-diagnostics.ts";

/** 与面板 COLLECTION_TASK_SLOW_HINT_MS / 后端 stale 默认 180s 对齐。 */
export const COLLECTION_TASK_SLOW_FALLBACK_MS = 180 * 1000;

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
  statusCell: "min-w-[88px] w-[88px] shrink-0 align-middle",
  statusBadge: "inline-flex whitespace-nowrap shrink-0 text-xs",
  actionsCell:
    "ops-sticky-actions w-[180px] min-w-[180px] shrink-0 whitespace-nowrap",
  actionsHead:
    "ops-sticky-actions w-[180px] min-w-[180px] shrink-0 whitespace-nowrap text-right",
  actionsGroup: "flex flex-nowrap items-center justify-end gap-0.5",
  actionButton: "ops-icon-button shrink-0",
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

export type TaskResultBreakdown = {
  primary: string[];
  funnel: string[];
  contacts: string[];
  reason: string | null;
  highValue: boolean;
  singleLinkImport: boolean;
};

const PLATFORM_LABELS: Record<string, string> = {
  instagram: "Instagram",
  tiktok: "TikTok",
  youtube: "YouTube",
  facebook: "Facebook",
  pinterest_apify: "Pinterest Apify",
  pinterest: "Pinterest",
};

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : null;
}

function providerReasonText(reason: string, label: string, message: string | null): string {
  if (reason === "apify_memory_limit_exceeded") {
    return `${label}：Apify 额度不足/并发 actor 过多，已跳过该通道`;
  }
  if (reason === "provider_not_configured") {
    return `${label}：provider 未配置，已提前跳过`;
  }
  if (reason === "timeout") {
    return `${label}：平台 provider 超时，已跳过`;
  }
  if (reason === "rate_limit") {
    return `${label}：平台接口限流，已暂停或跳过该平台`;
  }
  if (reason === "network_unreachable") {
    return `${label}：平台 provider 不可达，已跳过`;
  }
  return `${label}：${message || "provider 不可用，已跳过"}`;
}

export function collectionTaskProviderDiagnosticHint(task: CollectionTask): string | null {
  const checkpoint = task.run_checkpoint ?? {};
  const instagramFallback = asRecord(checkpoint.competitor_product_instagram_fallback);
  if (task.collection_mode === "competitor_product" && instagramFallback) {
    const probeCandidates = Array.isArray(instagramFallback.cross_platform_probe_candidates)
      ? instagramFallback.cross_platform_probe_candidates.length
      : 0;
    const matchedInstagram =
      typeof instagramFallback.matched_instagram_count === "number"
        ? instagramFallback.matched_instagram_count
        : 0;
    const inherited =
      typeof instagramFallback.inherited_evidence_count === "number"
        ? instagramFallback.inherited_evidence_count
        : 0;
    if (probeCandidates > 0 && matchedInstagram === 0) {
      return [
        "已找到 TikTok/YouTube Amazon 带货证据。",
        "Instagram 直接关键词未命中或未通过同款证据。",
        "已尝试按 TikTok/YouTube username/display_name 反查 Instagram。",
        "如果仍无结果，建议放宽互动率/粉丝阈值，或启用跨平台证据继承。",
      ].join("");
    }
    if (inherited > 0) {
      return [
        "已找到 TikTok/YouTube Amazon 带货证据。",
        "Instagram 由 TikTok/YouTube 同款证据反查得到，并已保留跨平台证据来源。",
      ].join("");
    }
  }
  const providerState = asRecord(checkpoint.provider_availability_state);
  const apiCounts = asRecord(checkpoint.platform_api_counts);
  const timedOutPlatforms = Array.isArray(checkpoint.timed_out_platforms)
    ? checkpoint.timed_out_platforms.map(String)
    : [];
  const parts: string[] = [];

  if (providerState) {
    for (const [platform, rawState] of Object.entries(providerState)) {
      const state = asRecord(rawState);
      if (!state) continue;
      const label = PLATFORM_LABELS[platform] ?? platform;
      const reason = typeof state.reason === "string" ? state.reason : "";
      const message = typeof state.message === "string" ? state.message : null;
      const apiCalls =
        typeof state.api_calls === "number"
          ? state.api_calls
          : typeof apiCounts?.[platform] === "number"
            ? (apiCounts[platform] as number)
            : null;
      const suffix = apiCalls != null ? `（API ${apiCalls} calls）` : "";
      parts.push(`${providerReasonText(reason, label, message)}${suffix}`);
    }
  }

  for (const platform of timedOutPlatforms) {
    const label = PLATFORM_LABELS[platform] ?? platform;
    if (!parts.some((part) => part.startsWith(`${label}：`))) {
      parts.push(`${label}：平台 provider 超时，已跳过`);
    }
  }

  if (parts.length > 0) return parts.join("；");

  const text = `${task.status_summary ?? ""} ${task.error_message ?? ""} ${task.last_error ?? ""}`;
  if (/post_author_missing/.test(text)) return "找到帖子但未解析到作者，已记录 raw 字段诊断";
  if (/no same-product results|同款过滤后|no_same_product_match/i.test(text)) {
    return "找到相关类目红人但无同款证据，未入库";
  }
  return null;
}

export function formatProgressUpdatedAt(updatedAt: string | null | undefined): string | null {
  if (!updatedAt) return null;
  const date = new Date(updatedAt);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function collectionTaskHydrationProgressLine(task: CollectionTask): string | null {
  if (task.current_stage !== "hydration") return null;
  const processed = task.processed_count ?? 0;
  const total = task.total_estimate ?? 0;
  const success = task.success_count ?? task.profile_fetched_count ?? 0;
  const skipped = task.skipped_count ?? 0;
  const failed = task.failed_count ?? task.profile_failed_count ?? 0;
  const totalLabel = total > 0 ? String(total) : "?";
  return `主页补采 ${processed}/${totalLabel}，成功 ${success}，跳过 ${skipped}，失败 ${failed}`;
}

export function isCollectionTaskTerminalSuccess(status: string | null | undefined): boolean {
  return status === "completed" || status === "completed_with_results" || status === "completed_no_results";
}

export function shouldShowCollectionTaskErrorMessage(
  task: Pick<CollectionTask, "status" | "error_message">,
): boolean {
  const message = task.error_message?.trim();
  if (!message) return false;
  return !isCollectionTaskTerminalSuccess(task.status);
}

export function collectionTaskInterruptedHint(task: CollectionTask): string {
  if (isCollectionTaskTerminalSuccess(task.status)) {
    return "";
  }
  const checkpoint = task.run_checkpoint ?? {};
  const stage =
    typeof checkpoint.interrupted_stage === "string"
      ? collectionTaskStageLabel(checkpoint.interrupted_stage)
      : collectionTaskStageLabel(task.current_stage);
  const updated = formatProgressUpdatedAt(task.updated_at);
  const err = task.last_error || task.error_message || task.status_summary;
  const parts = [`阶段：${stage}`];
  if (updated) parts.push(`最后更新 ${updated}`);
  if (err) parts.push(err);
  return parts.join("；");
}

export function isCollectionTaskProgressStalled(
  task: CollectionTask,
  elapsedMs = 0,
  staleThresholdMs = COLLECTION_TASK_SLOW_FALLBACK_MS,
): boolean {
  if (task.status !== "running") return false;
  if (elapsedMs < staleThresholdMs) return false;
  const updatedAt = task.updated_at ? new Date(task.updated_at).getTime() : 0;
  if (!updatedAt) return elapsedMs >= staleThresholdMs;
  return Date.now() - updatedAt >= staleThresholdMs;
}

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

export function isHighValueTaskResult(task: CollectionTask): boolean {
  const inserted = task.inserted_count ?? task.result_count ?? 0;
  const result = task.result_count ?? 0;
  const discovered = task.discovered_count ?? 0;
  const fetched = task.profile_fetched_count ?? 0;
  const email = task.email_count ?? 0;
  return (
    task.effectiveness_category === "high_value" ||
    inserted >= 5 ||
    result >= 5 ||
    (discovered >= 50 && inserted >= 1) ||
    (fetched >= 20 && inserted >= 1) ||
    (email >= 1 && inserted >= 1)
  );
}

export function buildTaskResultBreakdown(task: CollectionTask): TaskResultBreakdown {
  const discovered = task.discovered_count ?? 0;
  const deduped = task.deduped_count ?? 0;
  const posts = task.post_count ?? 0;
  const fetched = task.profile_fetched_count ?? 0;
  const filtered = task.filtered_out_count ?? 0;
  const inserted = task.inserted_count ?? task.result_count ?? 0;
  const email = task.email_count ?? 0;
  const missingContact = task.missing_contact_count ?? 0;
  const failed = task.failed_count ?? task.profile_failed_count ?? 0;
  const target = collectionTaskTargetCount(task);
  const singleLinkImport = task.collection_mode === "link_import" && inserted === 1 && discovered <= 3;
  const primary = [target == null ? `已入库 ${inserted} / 目标未设置` : `已入库 ${inserted} / 目标 ${target}`];
  if (singleLinkImport) primary.push("单条链接导入");
  const checkpoint = task.run_checkpoint ?? {};
  const seedDiag =
    checkpoint.shopping_seed_discovery && typeof checkpoint.shopping_seed_discovery === "object"
      ? (checkpoint.shopping_seed_discovery as Record<string, unknown>)
      : null;
  const completedSeedQueries = Array.isArray(checkpoint.completed_queries)
    ? checkpoint.completed_queries.length
    : null;
  const totalSeedQueries =
    typeof seedDiag?.query_count === "number"
      ? seedDiag.query_count
      : Array.isArray(seedDiag?.queries)
        ? seedDiag.queries.length
        : null;
  const seedDiscovered =
    typeof checkpoint.seed_discovered_count === "number" ? checkpoint.seed_discovered_count : discovered;
  const seedEnriched =
    typeof checkpoint.seed_enriched_count === "number" ? checkpoint.seed_enriched_count : fetched;
  const productEvidenceFiltered =
    typeof checkpoint.filtered_by_product_match_count === "number"
      ? checkpoint.filtered_by_product_match_count
      : typeof seedDiag?.product_evidence_filtered_count === "number"
        ? seedDiag.product_evidence_filtered_count
        : null;
  const platformFailed =
    typeof checkpoint.platform_failed_count === "number" ? checkpoint.platform_failed_count : null;
  const skippedPlatform =
    typeof checkpoint.skipped_platform_count === "number" ? checkpoint.skipped_platform_count : null;
  const failedSeedQueries = Array.isArray(checkpoint.failed_queries) ? checkpoint.failed_queries.length : 0;
  const funnel =
    task.collection_mode === "link_seed_discovery"
      ? [
          completedSeedQueries != null && totalSeedQueries != null && totalSeedQueries > 0
            ? `seed 查询 ${completedSeedQueries}/${totalSeedQueries}`
            : null,
          failedSeedQueries > 0 ? `失败查询 ${failedSeedQueries}` : null,
          `seed URL ${seedDiscovered}`,
          productEvidenceFiltered != null && productEvidenceFiltered > 0
            ? `商品证据过滤 ${productEvidenceFiltered}`
            : null,
          `主页补全 ${seedEnriched}`,
          platformFailed != null && platformFailed > 0 ? `通道失败 ${platformFailed}` : null,
          skippedPlatform != null && skippedPlatform > 0 ? `通道跳过 ${skippedPlatform}` : null,
        ].filter((item): item is string => Boolean(item))
      : [
          `发现 ${discovered}`,
          task.collection_mode === "link_import" ? `作品链接 ${posts > 0 ? posts : deduped || discovered}` : `去重 ${deduped}`,
          `主页 ${fetched}`,
          `过滤 ${filtered}`,
        ];
  const contacts = [`邮箱 ${email}`, `缺联系方式 ${missingContact}`];
  if (failed > 0) contacts.push(`失败 ${failed}`);
  const diagnostic = collectionTaskSeedDiscoveryDiagnosticHint(task);
  const providerDiagnostic = collectionTaskProviderDiagnosticHint(task);
  const reasonSource = diagnostic || providerDiagnostic || task.error_message || task.last_error || task.status_summary;
  return {
    primary,
    funnel,
    contacts,
    reason: reasonSource ? `主要原因：${reasonSource}` : null,
    highValue: isHighValueTaskResult(task),
    singleLinkImport,
  };
}

function zeroResultDiagnosticHint(task: CollectionTask): string | null {
  const inserted = task.inserted_count ?? task.result_count ?? 0;
  if (inserted > 0) return null;
  if (task.status !== "completed_no_results" && task.status !== "completed" && task.status !== "partial_failed") {
    return null;
  }
  const discovered = task.discovered_count ?? 0;
  const deduped = task.deduped_count ?? 0;
  const fetched = task.profile_fetched_count ?? 0;
  const filtered = task.filtered_out_count ?? 0;
  const below = task.filtered_below_min_followers_count ?? 0;
  const excluded = task.filtered_excluded_keyword_count ?? 0;
  const missingContact = task.missing_contact_count ?? 0;
  const checkpoint = task.run_checkpoint ?? {};
  if (/主页外链|涓婚〉澶栭摼|Amazon storefront|ShopMy|Linktree/i.test(task.status_summary ?? "")) {
    return null;
  }
  const contactFiltered =
    typeof checkpoint.filtered_by_contact_count === "number"
      ? checkpoint.filtered_by_contact_count
      : task.require_email || task.require_contact
        ? Math.max(missingContact, 0)
        : 0;
  const productFiltered =
    typeof checkpoint.filtered_by_product_match_count === "number"
      ? checkpoint.filtered_by_product_match_count
      : typeof checkpoint.product_evidence_filtered_count === "number"
        ? checkpoint.product_evidence_filtered_count
        : 0;

  if (discovered <= 0 && filtered <= 0 && fetched <= 0) return null;

  const reasons: string[] = [];
  if (task.require_email || task.require_contact || contactFiltered > 0) {
    reasons.push("任务要求必须有邮箱/联系方式");
  }
  if (below > 0 || excluded > 0) {
    reasons.push("部分候选未达到粉丝或互动条件");
  }
  if (productFiltered > 0) {
    reasons.push("同款商品证据不足");
  }
  if (filtered > 0 && reasons.length === 0) {
    reasons.push("过滤条件较严格");
  }

  const detailParts = [
    `发现 ${discovered} 个候选`,
    deduped > 0 ? `去重后 ${deduped} 个` : null,
    fetched > 0 ? `补全主页 ${fetched} 个` : null,
    filtered > 0 ? `过滤 ${filtered} 个` : null,
    contactFiltered > 0 ? `联系方式过滤 ${contactFiltered} 个` : null,
    productFiltered > 0 ? `同款商品证据过滤 ${productFiltered} 个` : null,
  ].filter(Boolean);
  const reasonText = reasons.length ? `主要原因：${reasons.join("，")}。` : "";
  const suggestion =
    task.require_email || task.require_contact
      ? "建议关闭必须邮箱/联系方式，先入库后筛选。"
      : "建议放宽粉丝/互动或同款证据条件，先入库后筛选。";
  return `${detailParts.join("，")}，但最终入库 0。${reasonText}${suggestion}`;
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
  const posts = task.post_count ?? 0;
  const fetched = task.profile_fetched_count ?? 0;
  const filtered = task.filtered_out_count ?? 0;
  const inserted = task.inserted_count ?? task.result_count ?? 0;
  const target = collectionTaskTargetCount(task);
  const targetPart = target == null ? `${inserted}/目标未设置` : `${inserted}/${target}`;
  if (task.collection_mode === "link_import") {
    const postPart = posts > 0 ? posts : deduped > 0 ? deduped : discovered;
    return `发现 ${discovered} → 作品链接 ${postPart} → 主页 ${fetched} → 入库 ${targetPart}`;
  }
  return `发现 ${discovered} → 去重 ${deduped} → 主页 ${fetched} → 过滤 ${filtered} → 入库 ${targetPart}`;
}

function collectionTaskProviderLabel(
  task: CollectionTask,
  providerRaw: string | null,
  platformOverride?: string,
): string {
  const platform = platformOverride || (task.platform || task.platforms?.[0] || "").toLowerCase();
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
  const platformRaw = typeof checkpoint.current_platform === "string" ? checkpoint.current_platform : null;
  const platformStatus =
    checkpoint.platform_discovery_status && typeof checkpoint.platform_discovery_status === "object"
      ? (checkpoint.platform_discovery_status as Record<string, string>)
      : null;
  const provider = collectionTaskProviderLabel(
    task,
    providerRaw,
    platformRaw || (task.platform || task.platforms?.[0] || "").toLowerCase(),
  );
  const completed = typeof checkpoint.keywords_completed === "number" ? checkpoint.keywords_completed : null;
  const total = typeof checkpoint.keywords_total === "number" ? checkpoint.keywords_total : null;
  const platformsCompleted =
    typeof checkpoint.platforms_completed === "number" ? checkpoint.platforms_completed : null;
  const platformsTotal = typeof checkpoint.platforms_total === "number" ? checkpoint.platforms_total : null;
  const discovered = task.discovered_count ?? 0;
  const hydratingTotal =
    typeof checkpoint.profiles_hydrating_total === "number" ? checkpoint.profiles_hydrating_total : null;
  const hydratingCompleted =
    typeof checkpoint.profiles_hydrating_completed === "number" ? checkpoint.profiles_hydrating_completed : null;
  const elapsedSeconds =
    typeof checkpoint.discovery_elapsed_seconds === "number" ? checkpoint.discovery_elapsed_seconds : null;
  const seedDiag =
    checkpoint.shopping_seed_discovery && typeof checkpoint.shopping_seed_discovery === "object"
      ? (checkpoint.shopping_seed_discovery as Record<string, unknown>)
      : null;
  const completedSeedQueries = Array.isArray(checkpoint.completed_queries)
    ? checkpoint.completed_queries.length
    : null;
  const failedSeedQueries = Array.isArray(checkpoint.failed_queries)
    ? checkpoint.failed_queries.length
    : null;
  const totalSeedQueries = Array.isArray(seedDiag?.queries)
    ? seedDiag?.queries.length
    : typeof seedDiag?.query_count === "number"
      ? seedDiag.query_count
      : null;
  const seedDiscovered =
    typeof checkpoint.seed_discovered_count === "number" ? checkpoint.seed_discovered_count : null;
  const seedEnriched =
    typeof checkpoint.seed_enriched_count === "number" ? checkpoint.seed_enriched_count : null;
  const providerState =
    checkpoint.provider_availability_state && typeof checkpoint.provider_availability_state === "object"
      ? (checkpoint.provider_availability_state as Record<string, Record<string, unknown>>)
      : null;
  const skippedCheckpoint =
    typeof checkpoint.skipped_due_checkpoint_count === "number" ? checkpoint.skipped_due_checkpoint_count : null;

  const parts: string[] = [];
  if (seedDiag || completedSeedQueries != null || seedDiscovered != null || seedEnriched != null) {
    if (completedSeedQueries != null && totalSeedQueries != null && totalSeedQueries > 0) {
      parts.push(`seed 查询 ${completedSeedQueries}/${totalSeedQueries}`);
    }
    if (failedSeedQueries != null && failedSeedQueries > 0) {
      parts.push(`失败 ${failedSeedQueries}`);
    }
    if (seedDiscovered != null) {
      parts.push(`seed ${seedDiscovered}`);
    }
    if (seedEnriched != null) {
      parts.push(`已补全 ${seedEnriched}`);
    }
    if (providerState?.pinterest_apify?.reason === "network_unreachable") {
      parts.push("Pinterest Apify 不可用");
    }
    if (skippedCheckpoint != null && skippedCheckpoint > 0) {
      parts.push(`checkpoint 跳过 ${skippedCheckpoint}`);
    }
  }
  if (platformStatus && Object.keys(platformStatus).length > 0) {
    const labelMap: Record<string, string> = {
      tiktok: "TikTok",
      youtube: "YouTube",
      facebook: "Facebook",
      instagram: "Instagram",
    };
    const stateMap: Record<string, string> = {
      queued: "排队",
      searching: "搜索中",
      done: "完成",
      partial: "部分成功",
      timeout_skipped: "超时跳过",
      failed: "失败",
    };
    const platformBits = Object.entries(platformStatus).map(
      ([name, status]) => `${labelMap[name] ?? name}${stateMap[status] ?? status}`,
    );
    parts.push(`平台：${platformBits.join("、")}`);
  } else if (platformsTotal != null && platformsCompleted != null && platformsTotal > 0) {
    parts.push(`多平台搜索（${platformsCompleted}/${platformsTotal}）`);
  }

  const providerHint = collectionTaskProviderDiagnosticHint(task);
  if (providerHint) {
    parts.push(providerHint);
  }

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
  if (elapsedSeconds != null && elapsedSeconds >= 30) {
    parts.push(`已运行 ${Math.round(elapsedSeconds)}s`);
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
    return `任务可能中断：${collectionTaskInterruptedHint(task)}；可点击继续运行`;
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
    const hydrationLine = collectionTaskHydrationProgressLine(task);
    const context = collectionTaskDiscoveryContext(task);
    const slowLabel = collectionTaskSlowApiHintLabel(task, elapsedMs, slowThresholdMs);
    const stalled = isCollectionTaskProgressStalled(task, elapsedMs, slowThresholdMs);
    const suffixParts = [
      hydrationLine,
      context,
      slowLabel,
      stalled ? "长时间无进度更新，可能卡住，可继续运行或查看最近错误" : null,
      task.last_error ? `最近错误：${task.last_error}` : null,
      partialSkipped ? "部分已跳过，继续处理" : null,
      formatProgressUpdatedAt(task.updated_at) ? `更新 ${formatProgressUpdatedAt(task.updated_at)}` : null,
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
  let hint: string | null = collectionTaskSeedDiscoveryDiagnosticHint(task);
  if (!hint) {
    hint = collectionTaskProviderDiagnosticHint(task);
  }

  if (!hint) {
    hint = zeroResultDiagnosticHint(task);
  }

  if (!hint) {
    if (task.status_summary && task.status !== "running") {
      hint = task.status_summary;
    } else if (task.status === "running" && task.status_summary) {
      hint = task.status_summary;
    }
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
