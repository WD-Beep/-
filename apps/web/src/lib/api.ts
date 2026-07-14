import { ensureTenantProductId, tenantHeaders } from "./product-context.ts";
import { collectionTaskSeedDiscoveryDiagnosticHint } from "./shopping-seed-diagnostics.ts";

const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "/api-proxy").replace(/\/$/, "");
const SERVER_API_URL =
  process.env.INTERNAL_API_URL?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";
const LONG_RUNNING_API_URL =
  process.env.NEXT_PUBLIC_LONG_RUNNING_API_URL?.replace(/\/$/, "") ?? API_URL;

const API_FETCH_TIMEOUT_MS = 30_000;
const PREVIEW_FETCH_TIMEOUT_MS = 600_000;

async function apiFetch(
  input: RequestInfo | URL,
  init: RequestInit = {},
  options?: { timeoutMs?: number },
): Promise<Response> {
  await ensureTenantProductId();
  const headers = new Headers(init.headers ?? {});
  for (const [key, value] of Object.entries(tenantHeaders())) {
    headers.set(key, value);
  }
  const timeoutMs = options?.timeoutMs ?? API_FETCH_TIMEOUT_MS;
  const timeoutSignal =
    typeof AbortSignal !== "undefined" && "timeout" in AbortSignal
      ? AbortSignal.timeout(timeoutMs)
      : undefined;
  const signal = init.signal
    ? timeoutSignal
      ? AbortSignal.any([init.signal, timeoutSignal])
      : init.signal
    : timeoutSignal;
  try {
    return await fetch(input, { ...init, headers, signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === "TimeoutError") {
      throw new Error("请求超时，请确认后端服务已启动且可访问。");
    }
    throw error;
  }
}

function triggerBrowserDownload(blob: Blob, filename: string): void {
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(objectUrl);
}

export async function downloadWithTenantHeaders(url: string, filename = "export.xlsx"): Promise<void> {
  const response = await apiFetch(url);
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  const blob = await response.blob();
  const disposition = response.headers.get("content-disposition") ?? "";
  const match = disposition.match(/filename=\"?([^\";]+)\"?/i);
  triggerBrowserDownload(blob, match?.[1] ?? filename);
}

export type HealthResponse = {
  status: string;
  service: string;
  timestamp: string;
};

export type SocialLink = {
  label: string;
  url: string;
  type?: string;
};

export type InfluencerSourceRecord = {
  id: number;
  source_post_url: string | null;
  source_input_url: string | null;
  source_platform: string | null;
  task_id: number | null;
  task_name: string | null;
  import_batch_id: number | null;
  collected_at: string;
};

export type Influencer = {
  id: number;
  platform: string;
  username: string;
  display_name: string | null;
  profile_url: string;
  avatar_url: string | null;
  country: string | null;
  language: string | null;
  category: string | null;
  niche: string | null;
  bio: string | null;
  followers_count: number | null;
  avg_views: number | null;
  avg_likes: number | null;
  avg_comments: number | null;
  engagement_rate: number | null;
  email: string | null;
  final_email: string | null;
  public_email: string | null;
  business_email: string | null;
  email_source: string | null;
  contact_credibility: number | null;
  contact_score: number | null;
  contact_credibility_level: string | null;
  website: string | null;
  contact_page: string | null;
  linktree_url: string | null;
  whatsapp: string | null;
  telegram: string | null;
  other_social_links: SocialLink[];
  product_fit: number | null;
  data_completeness: number | null;
  has_brand_collaboration: boolean | null;
  estimated_collab_price: string | null;
  collaboration_formats: string[];
  content_topics: string[];
  audience_country: string | null;
  audience_language: string | null;
  travel_fit_score: number | null;
  purchasing_power_score: number | null;
  sales_potential_score: number | null;
  audience_match_score: number | null;
  roi_forecast: number | null;
  recent_post_titles: string[];
  recent_post_urls: string[];
  last_post_at: string | null;
  posting_frequency: string | null;
  tags: string[];
  engagement_score: number | null;
  content_match_score: number | null;
  contactability_score: number | null;
  commercial_signal_score: number | null;
  activity_score: number | null;
  risk_score: number | null;
  final_priority: string | null;
  score: number | null;
  risk_level: string | null;
  score_reason: string | null;
  ai_summary: string | null;
  ai_collaboration_suggestion: string | null;
  ai_outreach_message: string | null;
  follow_status: string | null;
  owner: string | null;
  note: string | null;
  next_follow_up_at: string | null;
  last_contacted_at: string | null;
  last_reply_at: string | null;
  invalid_reason: string | null;
  blacklist_reason: string | null;
  lead_status: string | null;
  lead_priority: string | null;
  owner_name: string | null;
  lead_note: string | null;
  last_collected_at: string | null;
  email_sent: boolean;
  last_email_sent_at: string | null;
  last_email_subject: string | null;
  source_discovery_type: string | null;
  source_post_url: string | null;
  source_comment_url: string | null;
  source_comment_text: string | null;
  source_records?: InfluencerSourceRecord[];
  contact_discovered_at: string | null;
  contact_sources: Array<Record<string, unknown>>;
  contact_fetch_status: string | null;
  contact_fetch_error: string | null;
  value_tier: "direct_contact" | "manual_research" | "skip";
  value_tier_label: string;
  value_tier_reason: string;
  contact_summary: string;
  created_at: string;
  updated_at: string;
};

export type InfluencerUpdatePayload = {
  platform?: string | null;
  username?: string | null;
  display_name?: string | null;
  profile_url?: string | null;
  country?: string | null;
  language?: string | null;
  category?: string | null;
  niche?: string | null;
  followers_count?: number | null;
  engagement_rate?: number | null;
  email?: string | null;
  follow_status?: string | null;
  owner?: string | null;
  note?: string | null;
  next_follow_up_at?: string | null;
  invalid_reason?: string | null;
  blacklist_reason?: string | null;
};

export type InfluencerLeadUpdatePayload = {
  lead_status?: string | null;
  lead_priority?: string | null;
  owner_name?: string | null;
  next_follow_up_at?: string | null;
  lead_note?: string | null;
  invalid_reason?: string | null;
  blacklist_reason?: string | null;
  operator_name?: string | null;
};

export type InfluencerBulkDeleteResult = {
  deleted_count: number;
  deleted_ids: number[];
  missing_ids: number[];
};

export type InfluencerFollowup = {
  id: number;
  influencer_id: number;
  action_type: string;
  old_status: string | null;
  new_status: string | null;
  content: string | null;
  operator_name: string | null;
  contact_channel: string | null;
  created_at: string;
};

export type FollowupCreatePayload = {
  action_type: string;
  content?: string | null;
  contact_channel?: string | null;
  operator_name?: string | null;
};

export type ContactRefreshResult = {
  influencer: Influencer;
  contact_fetch_status: string;
  contact_fetch_error: string | null;
  contact_discovered_at: string | null;
  contact_sources: Array<Record<string, unknown>>;
  final_email: string | null;
  email_source: string | null;
  contact_score: number | null;
  contact_credibility_level: string | null;
  contact_page: string | null;
  linktree_url: string | null;
  whatsapp: string | null;
  telegram: string | null;
};

export type AnalyzeInfluencerResponse = {
  influencer: Influencer;
  analysis: {
    ai_summary: string;
    ai_collaboration_suggestion: string;
    ai_outreach_message?: string;
    tags: string[];
    risk_level: string;
    score_reason: string;
    source: string;
    error_message?: string | null;
  };
};

export type CollectionTaskStatus =
  | "draft"
  | "pending"
  | "queued"
  | "running"
  | "completed"
  | "completed_with_results"
  | "completed_no_results"
  | "partial_failed"
  | "failed"
  | "paused";

export type CollectionMode =
  | "keyword"
  | "urls"
  | "mixed"
  | "discovery"
  | "category_discovery"
  | "clustering"
  | "comment_authors"
  | "competitor_product"
  | "link_import"
  | "link_seed_discovery";

/** 閲囬泦浠诲姟椤跺眰鏉ユ簮鏂瑰紡锛堣〃鍗曘€岄噰闆嗘柟寮忋€嶏級 */
export type TaskSourceMethod = "keyword_discovery" | "link_import" | "shopping_seed_auto";

export type PlatformCapability = {
  platform: string;
  label: string;
  status: "supported" | "not_configured" | "not_available" | "url_only";
  message: string;
  endpoints: string[];
  keyword_discovery: boolean;
  native_keyword_discovery?: boolean;
  external_seed_discovery?: boolean;
  reverse_link_expansion?: boolean;
  link_import: boolean;
  product_seed: boolean;
  link_import_hint?: string | null;
  discovery_category?: "search_discovery" | "external_seed_discovery" | "external_link_discovery" | "link_completion";
  external_link_discovery?: boolean;
};

export type PlatformCapabilitiesResponse = {
  items: PlatformCapability[];
  api_direct_configured: boolean;
  apify_configured: boolean;
  instagram_data_provider: string;
  youtube_data_provider: string;
  tiktok_data_provider?: string;
  facebook_data_provider?: string;
  collection_max_running_tasks?: number;
  collection_profile_enrich_concurrency?: number;
  collection_profile_request_timeout_seconds?: number;
  collection_running_stale_seconds?: number;
};

export type CollectionTask = {
  id: number;
  parent_task_id?: number | null;
  batch_group_id?: string | null;
  batch_round_index?: number | null;
  batch_round_count?: number | null;
  max_runtime_minutes?: number | null;
  name: string;
  collection_mode: CollectionMode;
  platform: string;
  platforms: string[];
  keywords: string[];
  input_urls: string[];
  country: string | null;
  category: string | null;
  discovery_limit: number | null;
  min_engagement_rate: number | null;
  min_followers_count: number | null;
  max_followers_count: number | null;
  filter_include_keywords: string[];
  filter_exclude_keywords: string[];
  require_email: boolean;
  require_contact: boolean;
  strict_quality_filter: boolean;
  insert_qualified_only: boolean;
  export_qualified_only: boolean;
  status: CollectionTaskStatus;
  schedule_enabled: boolean;
  schedule_cron: string | null;
  email_enabled: boolean;
  email_recipients: string[];
  outreach_enabled: boolean;
  outreach_provider: string;
  outreach_dry_run: boolean;
  outreach_templates: Record<string, string>;
  last_run_at: string | null;
  next_run_at: string | null;
  result_count: number;
  email_count: number;
  missing_contact_count: number;
  discovered_count: number;
  deduped_count: number;
  profile_fetched_count: number;
  profile_failed_count: number;
  filtered_out_count: number;
  inserted_count: number;
  hashtag_count: number;
  post_count: number;
  comment_author_count: number;
  filtered_below_min_followers_count: number;
  filtered_excluded_keyword_count: number;
  processed_count: number;
  success_count: number;
  failed_count: number;
  skipped_count: number;
  total_estimate: number;
  current_stage: string | null;
  last_error: string | null;
  run_checkpoint: Record<string, unknown>;
  stale: boolean;
  recoverable: boolean;
  stale_after_seconds: number;
  is_archived?: boolean;
  archived_at?: string | null;
  is_ineffective?: boolean;
  effectiveness_category?: "high_value" | "effective" | "low_value_result" | "no_result" | "failed";
  has_retention_traces?: boolean;
  management_tags?: string[];
  is_possible_duplicate?: boolean;
  status_summary: string | null;
  error_message: string | null;
  comment_discovery_enabled: boolean;
  child_tasks?: CollectionTaskChild[];
  created_at: string;
  updated_at: string;
};

export type CollectionTaskChild = {
  id: number;
  name: string;
  status: CollectionTaskStatus;
  batch_round_index: number | null;
  batch_round_count: number | null;
  keywords: string[];
  discovery_limit: number | null;
  inserted_count: number;
  result_count: number;
  deduped_count: number;
  failed_count: number;
  skipped_count?: number;
  last_run_at: string | null;
  status_summary: string | null;
  error_message: string | null;
};

export type CollectionTaskPayload = {
  name: string;
  max_runtime_minutes?: number | null;
  collection_mode: CollectionMode;
  platform: string;
  platforms: string[];
  keywords: string[];
  input_urls: string[];
  country?: string | null;
  category?: string | null;
  discovery_limit?: number | null;
  min_engagement_rate?: number | null;
  min_followers_count?: number | null;
  max_followers_count?: number | null;
  filter_include_keywords?: string[];
  filter_exclude_keywords?: string[];
  require_email?: boolean;
  require_contact?: boolean;
  strict_quality_filter?: boolean;
  insert_qualified_only?: boolean;
  export_qualified_only?: boolean;
  schedule_enabled: boolean;
  schedule_cron?: string | null;
  email_enabled: boolean;
  email_recipients: string[];
  outreach_enabled?: boolean;
  outreach_provider?: string;
  outreach_dry_run?: boolean;
  outreach_templates?: Record<string, string>;
  comment_discovery_enabled?: boolean;
  stable_collection_mode?: boolean;
  batch_round_enabled?: boolean;
  batch_total_limit?: number | null;
  batch_round_size?: number | null;
  batch_round_count?: number | null;
};

export type LinkImportBatchStatus = "pending" | "running" | "completed" | "failed";

export type ValidUrlItem = {
  url: string;
  platform: string;
};

export type LinkImportBatch = {
  id: number;
  name: string;
  raw_urls: string;
  valid_urls: ValidUrlItem[];
  invalid_urls: string[];
  status: LinkImportBatchStatus;
  total_count: number;
  success_count: number;
  failed_count: number;
  new_count: number;
  updated_count: number;
  error_message: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
};

export type LinkImportBatchPayload = {
  name: string;
  raw_urls: string;
};

export type LinkImportRunResult = {
  batch_id: number;
  status: LinkImportBatchStatus;
  total_count: number;
  success_count: number;
  failed_count: number;
  new_count: number;
  updated_count: number;
  invalid_urls: string[];
};

export type PaginatedResponse<T> = {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
  total_pages?: number;
};

export type CollectionRunResult = {
  task_id: number;
  new_count: number;
  updated_count: number;
  skipped_count: number;
  filtered_count: number;
  total_count: number;
  discovered_count: number;
  deduped_count: number;
  profile_fetched_count: number;
  profile_failed_count: number;
  filtered_out_count: number;
  inserted_count: number;
  hashtag_count: number;
  post_count: number;
  comment_author_count: number;
  email_count: number;
  missing_contact_count: number;
  status_summary: string | null;
  error_message?: string | null;
  status: CollectionTaskStatus;
};

export const COLLECTION_TASK_POLL_INTERVAL_MS = 3000;
export const COLLECTION_TASK_SLOW_HINT_MS = 180 * 1000;

const COLLECTION_TASK_TERMINAL_STATUSES: CollectionTaskStatus[] = [
  "completed",
  "completed_with_results",
  "completed_no_results",
  "partial_failed",
  "failed",
];

export function isCollectionTaskSettled(status: CollectionTaskStatus): boolean {
  return COLLECTION_TASK_TERMINAL_STATUSES.includes(status);
}

export function isCollectionTaskRunning(task: CollectionTask): boolean {
  return task.status === "running";
}

export function isCollectionTaskQueued(task: CollectionTask): boolean {
  return task.status === "queued";
}

export function isCollectionTaskPaused(task: CollectionTask): boolean {
  return task.status === "paused";
}

export function isCollectionTaskActive(task: CollectionTask): boolean {
  return isCollectionTaskRunning(task) || isCollectionTaskQueued(task);
}

export function getCollectionTaskRunningReferenceAt(task: CollectionTask): string | null {
  return task.last_run_at ?? task.updated_at ?? task.created_at;
}

export function getCollectionTaskRunningElapsedMs(task: CollectionTask, now = Date.now()): number {
  const ref = getCollectionTaskRunningReferenceAt(task);
  if (!ref) return 0;
  return Math.max(0, now - new Date(ref).getTime());
}

export function isCollectionTaskRunningStale(task: CollectionTask): boolean {
  if (!isCollectionTaskRunning(task)) return false;
  return task.recoverable === true || task.stale === true;
}

export function isCollectionTaskRateLimited(task: CollectionTask): boolean {
  const checkpoint = task.run_checkpoint ?? {};
  if (checkpoint.rate_limited === true) return true;
  const haystack = `${task.last_error ?? ""} ${task.status_summary ?? ""} ${task.error_message ?? ""}`;
  return /429|闄愭祦|rate.?limit/i.test(haystack);
}

export function getCollectionTaskTargetCount(task: CollectionTask): number {
  return Math.max(1, task.discovery_limit ?? 100);
}

export function buildCollectionTaskCompletionMessage(task: CollectionTask): {
  tone: "success" | "warning" | "error";
  message: string;
} {
  if (task.status === "failed") {
    const detail = task.error_message?.trim();
    return {
      tone: "error",
      message: detail ? `閲囬泦澶辫触锛?{detail}` : "閲囬泦澶辫触锛岃鏌ョ湅浠诲姟閿欒淇℃伅",
    };
  }
  const seedDiscoveryDiagnostic = collectionTaskSeedDiscoveryDiagnosticHint(task);
  if (seedDiscoveryDiagnostic) {
    return {
      tone: "warning",
      message: seedDiscoveryDiagnostic,
    };
  }
  const inserted = task.inserted_count ?? task.result_count ?? 0;
  if (
    task.status === "completed_with_results" ||
    (inserted > 0 && task.status !== "completed_no_results")
  ) {
    return {
      tone: "success",
      message: `采集完成，已入库 ${inserted} 条，邮箱 ${task.email_count ?? 0} 个，缺联系方式 ${task.missing_contact_count ?? 0} 个`,
    };
  }
  if (task.status === "partial_failed") {
    const summary = task.status_summary?.trim();
    return {
      tone: "warning",
      message:
        summary ??
        `采集部分完成，入库 ${inserted} 条，邮箱 ${task.email_count ?? 0} 个，缺联系方式 ${task.missing_contact_count ?? 0} 个`,
    };
  }
  if (task.status === "completed_no_results" || task.status === "completed") {
    return {
      tone: "warning",
      message: "采集完成，但未发现符合条件的红人",
    };
  }
  return {
    tone: "success",
    message: task.status_summary ?? "采集已完成",
  };
}

export type CollectionTaskCandidate = {
  id: number;
  task_id: number;
  username: string;
  profile_url: string;
  platform: string;
  source_type: string | null;
  source_keyword: string | null;
  source_hashtag: string | null;
  source_post_url: string | null;
  source_input_url: string | null;
  source_caption: string | null;
  source_comment_url: string | null;
  source_comment_text: string | null;
  source_discovery_type: string | null;
  source_meta: CompetitorCandidateSourceMeta | Record<string, unknown> | null;
  followers_count: number | null;
  engagement_rate: number | null;
  is_high_value: boolean | null;
  has_email: boolean | null;
  has_contact: boolean | null;
  contact_status: string | null;
  insert_blocked_reason: string | null;
  profile_fetched_at: string | null;
  influencer_id: number | null;
  status: string;
  failure_reason: string | null;
  failure_detail: string | null;
  run_at: string | null;
  created_at: string;
  updated_at: string | null;
};

export type CompetitorCandidateSourceMeta = {
  competitor_product_title?: string | null;
  asin?: string | null;
  brand?: string | null;
  amazon_asin?: string | null;
  amazon_brand?: string | null;
  amazon_product_title?: string | null;
  match_type?: string | null;
  matched_phrases?: string[];
  missing_required_phrases?: string[];
  product_match_confidence?: string | null;
  selected_reason?: string | null;
  matched_keywords?: string[];
  match_reasons?: string[];
  suspected_collab?: boolean;
  source_post_url?: string | null;
  source_caption?: string | null;
  collection_mode?: string;
  amazon_urls?: string[];
  search_hashtags?: string[];
};

export type CollectionTaskCandidateQuery = {
  status?: string;
  failure_reason?: string;
  source_type?: string;
  source_discovery_type?: string;
  platform?: string;
  high_value?: boolean;
  has_email?: boolean;
  has_contact?: boolean;
  min_followers_count?: number;
  max_followers_count?: number;
  min_engagement_rate?: number;
  max_engagement_rate?: number;
    insert_blocked_reason?: string;
    contact_status?: string;
    search?: string;
  page?: number;
  page_size?: number;
};

export type CollectionTaskCandidateRecrawlResult = {
  candidate_id: number;
  task_id: number;
  status: string;
  attempted: boolean;
  message: string | null;
  global_influencer_id: number | null;
  product_influencer_id: number | null;
};

export type CollectionTaskCandidateBatchRecrawlResult = {
  task_id: number;
  attempted: number;
  succeeded: number;
  failed: number;
  skipped: number;
  items: CollectionTaskCandidateRecrawlResult[];
};

export type CollectionTaskCandidateEmailEnrichmentResult = CollectionTaskCandidateRecrawlResult & {
  email: string | null;
};

export type CollectionTaskCandidateBatchEmailEnrichmentResult = {
  task_id: number;
  attempted: number;
  succeeded: number;
  failed: number;
  skipped: number;
  items: CollectionTaskCandidateEmailEnrichmentResult[];
};

export type EmailSendResult = {
  success: boolean;
  message: string;
  task_id: number;
  total_count: number;
  recipients: string[];
};

export type EmailLogStatus = "pending" | "sent" | "failed";

export type EmailLog = {
  id: number;
  task_id: number | null;
  product_influencer_id: number | null;
  sender_email: string | null;
  influencer_username: string | null;
  recipients: string[];
  subject: string;
  body: string | null;
  status: EmailLogStatus;
  attachment_path: string | null;
  error_message: string | null;
  generated_by_ai: boolean;
  ai_provider: string | null;
  ai_reason: string | null;
  matched_knowledge: MatchedKnowledgeItem[] | null;
  risk_notes: string[] | null;
  sent_at: string | null;
  message_id?: string | null;
  has_replied: boolean;
  replied_at: string | null;
  reply_email_log_id: number | null;
  reply_summary: string | null;
  last_outbound_at: string | null;
  follow_up_status: string | null;
  follow_up_count: number;
  max_followups: number;
  next_follow_up_at: string | null;
  stop_follow_up: boolean;
  stop_reason: string | null;
};

export type ScheduleOutreachRecordFollowUpPayload = {
  after_days?: number;
  max_followups?: number;
};

export type StopOutreachRecordFollowUpPayload = {
  reason?: string;
};

export type EmailLogBulkDeleteResult = {
  deleted_count: number;
  deleted_ids: number[];
  missing_ids: number[];
};

export type InboundEmailStatus = {
  configured: boolean;
  imap_configured: boolean;
  webhook_configured: boolean;
  inbound_address: string | null;
  imap_host: string | null;
  imap_port: number | null;
  imap_folder: string | null;
  imap_poll_enabled: boolean;
  message: string;
};

export type EmailReply = {
  id: number;
  product_id: number;
  email_log_id: number | null;
  product_influencer_id: number | null;
  campaign_id: number | null;
  message_id: string | null;
  in_reply_to: string | null;
  match_method: string | null;
  match_confidence?: string | null;
  processing_status: "unprocessed" | "processed" | string;
  intent_status: "unprocessed" | "interested" | "follow_up" | "not_interested" | "processed" | "unmatched" | string;
  source: string;
  from_address: string;
  to_address: string;
  subject: string;
  body: string | null;
  snippet: string | null;
  raw_headers?: Record<string, unknown> | null;
  received_at: string;
  viewed_at: string | null;
  handled_at: string | null;
  manual_note: string | null;
};

export type EmailReplySummary = {
  reply_count: number;
  latest_reply_at: string | null;
  latest_snippet: string | null;
};

export type EmailReplyWorkCount = {
  unprocessed_count: number;
  unmatched_count: number;
  unviewed_count: number;
};

export type EmailReplyBulkDeleteResult = {
  deleted_count: number;
  deleted_ids: number[];
  missing_ids: number[];
};

export type EmailReplySendResponsePayload = {
  body: string;
  subject?: string | null;
  use_ai_draft?: boolean;
  mark_processed?: boolean;
};

export type EmailReplySendResponseResult = {
  sent: boolean;
  message_id: string | null;
  reply_id: number;
  product_influencer_id: number | null;
  campaign_id: number | null;
  sent_at: string | null;
  delivery_provider: string | null;
  warning?: string | null;
  error?: string | null;
};

export type SmtpStatus = {
  configured: boolean;
  host: string | null;
  port: number | null;
  user_address: string | null;
  from_address: string | null;
  from_name?: string | null;
  from_user_mismatch: boolean;
  warning: string | null;
  use_tls: boolean;
  message: string;
  outreach_daily_send_limit?: number;
  test_recipient?: string | null;
  test_schedule_enabled?: boolean;
  test_interval_minutes?: number | null;
};

export type AiStatus = {
  provider: string;
  model: string | null;
  configured: boolean;
  mode: string;
};

export type CollectorStatus = {
  mode: string;
  message: string;
};

export type IntegrationStatus = {
  configured: boolean;
  message: string;
};

export type MailchimpStatus = {
  configured: boolean;
  server_prefix: string | null;
  list_id: string | null;
  message: string;
};

export type KlaviyoStatus = {
  configured: boolean;
  list_id: string | null;
  message: string;
};

export type CollectionConfigStatus = {
  collector_mode: string;
  instagram_data_provider: string;
  youtube_data_provider: string;
  tiktok_data_provider?: string;
  facebook_data_provider?: string;
  apify_configured: boolean;
  api_direct_configured: boolean;
  instagram_collector_configured: boolean;
  facebook_collector_configured?: boolean;
  instagram_message: string;
  facebook_message?: string;
};

export type SettingsStatus = {
  smtp: SmtpStatus;
  mailchimp: MailchimpStatus;
  klaviyo: KlaviyoStatus;
  inbound_email: InboundEmailStatus;
  ai: AiStatus;
  apify: IntegrationStatus;
  api_direct: IntegrationStatus;
  collection: CollectionConfigStatus;
  collector: CollectorStatus;
};

export type EmailTestResponse = {
  success: boolean;
  message: string;
  recipient: string | null;
};

export type ManualOutreachSendMode = "now" | "scheduled";

export type ManualOutreachEmailPayload = {
  recipients: string[];
  subject: string;
  body: string;
  send_mode: ManualOutreachSendMode;
  scheduled_at?: string;
};

export type ManualOutreachEmailItem = {
  id: number | null;
  recipient: string;
  status: string;
  email_log_id: number | null;
  error_message: string | null;
  scheduled_at: string | null;
  sent_at: string | null;
};

export type ManualOutreachEmailResponse = {
  status: string;
  total: number;
  sent_count: number;
  scheduled_count: number;
  failed_count: number;
  message: string;
  items: ManualOutreachEmailItem[];
};

export type DashboardSummary = {
  total_influencers: number;
  total_tasks: number;
  active_tasks: number;
  completed_tasks: number;
  failed_tasks: number;
  total_email_logs: number;
  sent_emails: number;
  failed_emails: number;
  instagram_influencers: number;
  email_coverage_rate: number;
  contactable_count: number;
  high_match_count: number;
  average_score: number | null;
  average_product_fit: number | null;
  average_roi_forecast: number | null;
  platforms: { platform: string; count: number }[];
  recent_tasks: CollectionTask[];
};

export type DashboardMonthlyReportMetricCard = {
  label: string;
  value: string;
  helper: string;
  href: string;
  tone: "primary" | "success" | "warning" | "danger" | "neutral" | string;
};

export type DashboardMonthlyReportFunnelStep = {
  label: string;
  value: number;
  href: string;
};

export type DashboardMonthlyReportSkipReason = {
  label: string;
  value: number;
  helper: string;
  href: string;
  tone: "primary" | "success" | "warning" | "danger" | "neutral" | string;
};

export type DashboardMonthlyReportTodo = {
  title: string;
  description: string;
  href: string;
  action_label: string;
  tone: "primary" | "success" | "warning" | "danger" | "neutral" | string;
};

export type DashboardMonthlyReportCardSection = {
  title: string;
  cards: DashboardMonthlyReportMetricCard[];
};

export type DashboardMonthlyReportFunnelSection = {
  title: string;
  funnel: DashboardMonthlyReportFunnelStep[];
};

export type DashboardMonthlyReportSkipReasonSection = {
  title: string;
  items: DashboardMonthlyReportSkipReason[];
};

export type DashboardMonthlyReport = {
  month: string;
  updated_at: string;
  review_notice: string;
  overview: DashboardMonthlyReportCardSection;
  outreach_recap: DashboardMonthlyReportFunnelSection;
  draft_quality: DashboardMonthlyReportCardSection;
  queue_performance: DashboardMonthlyReportCardSection;
  skip_reasons: DashboardMonthlyReportSkipReasonSection;
  reply_progress: DashboardMonthlyReportCardSection;
  todos: DashboardMonthlyReportTodo[];
};

export function cleanBackendErrorMessage(message: string): string {
  const cleaned = message
    .replace(/^body:\s*/i, "")
    .replace(/^Value error,\s*/i, "")
    .trim();
  if (cleaned.includes("链接导入至少需要一个链接")) {
    return "请先粘贴至少一个链接，或切回关键词发现模式。";
  }
  if (
    /valid email|email address|@-sign/i.test(cleaned) ||
    /邮箱.*(?:无效|格式|地址)/.test(cleaned)
  ) {
    return "邮箱格式不正确，请输入有效的邮箱地址。";
  }
  if (/Method Not Allowed/i.test(cleaned)) {
    return "请求方法不被允许，请检查接口是否支持该操作。";
  }
  if (/[\u4e00-\u9fff]/.test(cleaned)) {
    return cleaned;
  }
  return "请求失败，请稍后重试。";
}

async function parseError(response: Response): Promise<string> {
  try {
    const text = await response.text();
    if (!text.trim()) {
      if (response.status === 405) {
        return "请求方法不被允许，请检查接口是否支持该操作。";
      }
      return "请求失败，请稍后重试。";
    }
    try {
      const data = JSON.parse(text) as { detail?: string | Array<{ msg?: string; loc?: Array<string | number> }> };
      if (typeof data.detail === "string") return cleanBackendErrorMessage(data.detail);
      if (Array.isArray(data.detail)) {
        return data.detail
          .map((item) => cleanBackendErrorMessage(item.msg ?? JSON.stringify(item)))
          .join("；");
      }
    } catch {
      if (response.status === 405 || /Method Not Allowed/i.test(text)) {
        return "请求方法不被允许，请检查接口是否支持该操作。";
      }
      if (response.status >= 500 && /Internal Server Error/i.test(text)) {
        return "后端处理失败，请稍后重试，或查看后端日志里的具体接口错误。";
      }
      return "请求失败，请稍后重试。";
    }
    return "请求失败，请稍后重试。";
  } catch {
    return "请求失败，请稍后重试。";
  }
}

async function parseJsonResponse<T>(response: Response): Promise<T> {
  const text = await response.text();
  if (!text.trim()) {
    return {} as T;
  }
  return JSON.parse(text) as T;
}

export async function fetchHealth(): Promise<HealthResponse> {
  const response = await apiFetch(`${API_URL}/health`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Health check failed: ${response.status}`);
  }
  return response.json();
}

export async function fetchDashboardSummary(): Promise<DashboardSummary> {
  const response = await apiFetch(`${API_URL}/api/dashboard/summary`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function fetchDashboardMonthlyReport(month: string): Promise<DashboardMonthlyReport> {
  const response = await apiFetch(`${API_URL}/api/dashboard/monthly-report?month=${encodeURIComponent(month)}`, {
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export type InfluencerListFilters = {
  page?: number;
  pageSize?: number;
  hasEmail?: boolean;
  contactable?: boolean;
  highValue?: boolean;
  valueTier?: "direct_contact" | "manual_research" | "skip";
  highMatch?: boolean;
  highPriority?: boolean;
  todayRecommended?: boolean;
  pendingFollowUp?: boolean;
  unassigned?: boolean;
  leadStatus?: string;
  leadPriority?: string;
  ownerName?: string;
  missingContact?: boolean;
  highCredibilityContact?: boolean;
  emailStatus?: "sent" | "unsent";
  collectionTaskId?: number;
  createdWithinHours?: number;
  collectedWithinDays?: number;
  search?: string;
  platform?: string;
  category?: string;
  niche?: string;
  tag?: string;
  sourceDiscoveryType?: string;
  excludeTerminalStatuses?: boolean;
};

export function buildInfluencersPageUrl(options: {
  taskId?: number;
  taskName?: string;
} = {}): string {
  const params = new URLSearchParams();
  if (options.taskId) params.set("task_id", String(options.taskId));
  if (options.taskName) params.set("task_name", options.taskName);
  const qs = params.toString();
  return qs ? `/influencers?${qs}` : "/influencers";
}

function buildQueryString(params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === "") continue;
    search.set(key, String(value));
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

export function buildInfluencerExportUrl(filters: InfluencerListFilters = {}): string {
  return `${API_URL}/api/influencers/export/excel${buildQueryString({
    has_email: filters.hasEmail,
    contactable: filters.contactable,
    high_value: filters.highValue,
    value_tier: filters.valueTier,
    high_match: filters.highMatch,
    today_recommended: filters.todayRecommended,
    email_status: filters.emailStatus,
    platform: filters.platform,
    keyword: filters.search,
    lead_status: filters.leadStatus,
    collection_task_id: filters.collectionTaskId,
    created_within_hours: filters.createdWithinHours,
    collected_within_days: filters.collectedWithinDays,
    missing_contact: filters.missingContact,
  })}`;
}

export function influencerFilterQueryParams(
  filters: Omit<InfluencerListFilters, "page" | "pageSize"> = {},
): Record<string, string | number | boolean | undefined> {
  return {
    has_email: filters.hasEmail,
    contactable: filters.contactable,
    high_value: filters.highValue,
    value_tier: filters.valueTier,
    high_match: filters.highMatch,
    high_priority: filters.highPriority,
    today_recommended: filters.todayRecommended,
    pending_follow_up: filters.pendingFollowUp,
    unassigned: filters.unassigned,
    lead_status: filters.leadStatus,
    lead_priority: filters.leadPriority,
    owner_name: filters.ownerName,
    missing_contact: filters.missingContact,
    high_credibility_contact: filters.highCredibilityContact,
    email_status: filters.emailStatus,
    collection_task_id: filters.collectionTaskId,
    created_within_hours: filters.createdWithinHours,
    collected_within_days: filters.collectedWithinDays,
    platform: filters.platform,
    category: filters.category,
    niche: filters.niche,
    tag: filters.tag,
    source_discovery_type: filters.sourceDiscoveryType,
    exclude_terminal_statuses: filters.excludeTerminalStatuses,
    search: filters.search,
  };
}

function influencerFilterParams(filters: Omit<InfluencerListFilters, "page" | "pageSize">) {
  return influencerFilterQueryParams(filters);
}

export async function fetchInfluencers(
  page = 1,
  pageSize = 20,
  filters: Omit<InfluencerListFilters, "page" | "pageSize"> = {},
): Promise<PaginatedResponse<Influencer>> {
  const qs = buildQueryString({
    page,
    page_size: pageSize,
    ...influencerFilterParams(filters),
  });
  const response = await apiFetch(`${API_URL}/api/influencers${qs}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export type InfluencerPlatformStatItem = {
  platform: string;
  total: number;
  has_email: number;
  direct_contact: number;
  missing_contact: number;
  high_value: number;
  sent_email_count?: number;
  unsent_email_count?: number;
};

export type InfluencerPlatformStatsResponse = {
  items: InfluencerPlatformStatItem[];
};

export async function fetchInfluencerPlatformStats(
  filters: Omit<InfluencerListFilters, "page" | "pageSize" | "platform"> = {},
): Promise<InfluencerPlatformStatsResponse> {
  const qs = buildQueryString(influencerFilterParams(filters));
  const response = await apiFetch(`${API_URL}/api/influencers/platform-stats${qs}`, {
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function fetchInfluencer(id: number): Promise<Influencer> {
  const response = await apiFetch(`${API_URL}/api/influencers/${id}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function fetchInfluencerServer(id: number): Promise<Influencer> {
  const response = await apiFetch(`${SERVER_API_URL}/api/influencers/${id}`, { cache: "no-store" });
  if (!response.ok) {
    const detail = await parseError(response);
    const error = new Error(detail) as Error & { status?: number };
    error.status = response.status;
    throw error;
  }
  return response.json();
}

export async function updateInfluencer(
  id: number,
  payload: InfluencerUpdatePayload,
): Promise<Influencer> {
  const response = await apiFetch(`${API_URL}/api/influencers/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function updateInfluencerLead(
  id: number,
  payload: InfluencerLeadUpdatePayload,
): Promise<Influencer> {
  const response = await apiFetch(`${API_URL}/api/influencers/${id}/lead`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function deleteInfluencers(ids: number[]): Promise<InfluencerBulkDeleteResult> {
  const response = await apiFetch(`${API_URL}/api/influencers/bulk-delete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids }),
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function fetchInfluencerFollowups(id: number): Promise<InfluencerFollowup[]> {
  const response = await apiFetch(`${API_URL}/api/influencers/${id}/followups`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function addInfluencerFollowup(
  id: number,
  payload: FollowupCreatePayload,
): Promise<InfluencerFollowup> {
  const response = await apiFetch(`${API_URL}/api/influencers/${id}/followups`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function refreshInfluencerContact(id: number): Promise<ContactRefreshResult> {
  const response = await apiFetch(`${API_URL}/api/influencers/${id}/refresh-contact`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function analyzeInfluencer(id: number): Promise<AnalyzeInfluencerResponse> {
  const response = await apiFetch(`${API_URL}/api/ai/analyze-influencer/${id}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function fetchPlatformCapabilities(): Promise<PlatformCapabilitiesResponse> {
  const response = await apiFetch(`${API_URL}/api/collection-tasks/platform-capabilities`, {
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function fetchCollectionTasks(
  page = 1,
  pageSize = 50,
  options?: {
    effectiveness?: "high_value" | "effective" | "ineffective" | "low_value_result" | "no_result" | "failed";
    owner_scope?: CollectionTaskOwnerScope;
    task_view?: TaskListView;
    search?: string;
    status?: CollectionTaskStatus;
    platform?: string;
    signal?: AbortSignal;
  },
): Promise<PaginatedResponse<CollectionTask>> {
  const { signal, ...queryOptions } = options ?? {};
  const query = buildCollectionTasksQueryString(page, pageSize, queryOptions);
  const response = await apiFetch(`${API_URL}/api/collection-tasks?${query}`, {
    cache: "no-store",
    signal,
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export type TaskListView =
  | "all"
  | "high_value"
  | "effective"
  | "ineffective"
  | "low_value_result"
  | "no_result"
  | "test_history"
  | "archived";

export type CollectionTaskOwnerScope = "mine" | "all";

export function buildCollectionTasksQueryString(
  page = 1,
  pageSize = 50,
  options?: {
    effectiveness?: "high_value" | "effective" | "ineffective" | "low_value_result" | "no_result" | "failed";
    owner_scope?: CollectionTaskOwnerScope;
    task_view?: TaskListView;
    search?: string;
    status?: CollectionTaskStatus;
    platform?: string;
  },
): string {
  const params = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
  });
  params.set("owner_scope", options?.owner_scope ?? "mine");
  if (options?.effectiveness) {
    params.set("effectiveness", options.effectiveness);
  }
  if (options?.task_view && options.task_view !== "all") {
    params.set("task_view", options.task_view);
  }
  if (options?.search?.trim()) {
    params.set("search", options.search.trim());
  }
  if (options?.status) {
    params.set("status", options.status);
  }
  if (options?.platform) {
    params.set("platform", options.platform);
  }
  return params.toString();
}

export async function fetchCollectionTask(id: number): Promise<CollectionTask> {
  const response = await apiFetch(`${API_URL}/api/collection-tasks/${id}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function createCollectionTask(
  payload: CollectionTaskPayload,
): Promise<CollectionTask> {
  if ((await ensureTenantProductId()) === 0) {
    throw new Error("创建采集任务需要先选择具体产品/品牌");
  }
  const response = await apiFetch(`${API_URL}/api/collection-tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function updateCollectionTask(
  id: number,
  payload: Partial<CollectionTaskPayload>,
): Promise<CollectionTask> {
  const response = await apiFetch(`${API_URL}/api/collection-tasks/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function runCollectionTask(id: number): Promise<CollectionRunResult> {
  const response = await apiFetch(`${API_URL}/api/collection-tasks/${id}/run`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function pauseCollectionTask(id: number): Promise<CollectionTask> {
  const response = await apiFetch(`${API_URL}/api/collection-tasks/${id}/pause`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function stopCollectionTask(id: number): Promise<CollectionTask> {
  const response = await apiFetch(`${API_URL}/api/collection-tasks/${id}/stop`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function resumeCollectionTask(id: number): Promise<CollectionRunResult> {
  const response = await apiFetch(`${API_URL}/api/collection-tasks/${id}/resume`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function enrichLinkSeedProfiles(taskId: number): Promise<CollectionRunResult> {
  const response = await apiFetch(`${API_URL}/api/collection-tasks/${taskId}/enrich-link-seeds`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

function collectionTaskCandidateQueryParams(
  query: Omit<CollectionTaskCandidateQuery, "page" | "page_size"> = {},
) {
  return {
    status: query.status,
    failure_reason: query.failure_reason,
    source_type: query.source_type,
    source_discovery_type: query.source_discovery_type,
    platform: query.platform,
    high_value: query.high_value,
    has_email: query.has_email,
    has_contact: query.has_contact,
    min_followers_count: query.min_followers_count,
    max_followers_count: query.max_followers_count,
    min_engagement_rate: query.min_engagement_rate,
    max_engagement_rate: query.max_engagement_rate,
    insert_blocked_reason: query.insert_blocked_reason,
    contact_status: query.contact_status,
    search: query.search,
  };
}

export function buildCollectionTaskCandidatesExportUrl(
  taskId: number,
  query: Omit<CollectionTaskCandidateQuery, "page" | "page_size"> = {},
): string {
  return `${API_URL}/api/collection-tasks/${taskId}/candidates/export${buildQueryString(
    collectionTaskCandidateQueryParams(query),
  )}`;
}

export async function downloadInfluencerExport(
  filters: InfluencerListFilters = {},
): Promise<void> {
  await downloadWithTenantHeaders(buildInfluencerExportUrl(filters));
}

export async function downloadCollectionTaskCandidatesExport(
  taskId: number,
  query: Omit<CollectionTaskCandidateQuery, "page" | "page_size"> = {},
): Promise<void> {
  await downloadWithTenantHeaders(buildCollectionTaskCandidatesExportUrl(taskId, query));
}

export async function fetchCollectionTaskCandidates(
  taskId: number,
  query: CollectionTaskCandidateQuery = {},
): Promise<PaginatedResponse<CollectionTaskCandidate>> {
  const params = new URLSearchParams();
  const filterParams = collectionTaskCandidateQueryParams(query);
  for (const [key, value] of Object.entries(filterParams)) {
    if (value === undefined || value === null || value === "") continue;
    params.set(key, String(value));
  }
  params.set("page", String(query.page ?? 1));
  params.set("page_size", String(query.page_size ?? 20));
  const qs = params.toString();
  const response = await apiFetch(`${API_URL}/api/collection-tasks/${taskId}/candidates?${qs}`);
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function recrawlCollectionTaskCandidate(
  taskId: number,
  candidateId: number,
): Promise<CollectionTaskCandidateRecrawlResult> {
  const response = await apiFetch(
    `${API_URL}/api/collection-tasks/${taskId}/candidates/${candidateId}/recrawl`,
    { method: "POST" },
    { timeoutMs: PREVIEW_FETCH_TIMEOUT_MS },
  );
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function recrawlCollectionTaskFailedCandidates(
  taskId: number,
  payload: { concurrency?: number; limit?: number } = {},
): Promise<CollectionTaskCandidateBatchRecrawlResult> {
  const response = await apiFetch(
    `${API_URL}/api/collection-tasks/${taskId}/candidates/recrawl-failed`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    { timeoutMs: PREVIEW_FETCH_TIMEOUT_MS },
  );
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function enrichYoutubeCandidateEmail(
  taskId: number,
  candidateId: number,
): Promise<CollectionTaskCandidateEmailEnrichmentResult> {
  const response = await apiFetch(
    `${API_URL}/api/collection-tasks/${taskId}/candidates/${candidateId}/enrich-youtube-email`,
    { method: "POST" },
    { timeoutMs: PREVIEW_FETCH_TIMEOUT_MS },
  );
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function enrichYoutubeCandidateEmails(
  taskId: number,
  payload: { limit?: number } = {},
): Promise<CollectionTaskCandidateBatchEmailEnrichmentResult> {
  const response = await apiFetch(
    `${API_URL}/api/collection-tasks/${taskId}/candidates/enrich-youtube-emails`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    { timeoutMs: PREVIEW_FETCH_TIMEOUT_MS },
  );
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export type CollectionTaskDeleteResult = {
  action: "deleted" | "archived";
  task_id: number;
};

export type CollectionTaskBulkDeleteResult = {
  deleted_count: number;
  archived_count: number;
  skipped_count: number;
  deleted_ids: number[];
  archived_ids: number[];
  skipped_ids: number[];
};

export type CollectionTaskBulkManageAction =
  | "archive_test_history"
  | "delete_no_result"
  | "restore_archived"
  | "archive_duplicates";

export type CollectionTaskBulkManageResult = {
  matched_count: number;
  archived_count: number;
  deleted_count: number;
  skipped_count: number;
  restored_count: number;
  archived_ids: number[];
  deleted_ids: number[];
  restored_ids: number[];
  skipped_ids: number[];
  skipped_reasons: Record<string, string>;
};

export async function bulkManageCollectionTasks(
  action: CollectionTaskBulkManageAction,
  taskIds: number[] = [],
): Promise<CollectionTaskBulkManageResult> {
  const response = await apiFetch(`${API_URL}/api/collection-tasks/bulk-manage`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, task_ids: taskIds }),
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  const result = await parseJsonResponse<Partial<CollectionTaskBulkManageResult>>(response);
  return {
    matched_count: result.matched_count ?? 0,
    archived_count: result.archived_count ?? 0,
    deleted_count: result.deleted_count ?? 0,
    skipped_count: result.skipped_count ?? 0,
    restored_count: result.restored_count ?? 0,
    archived_ids: result.archived_ids ?? [],
    deleted_ids: result.deleted_ids ?? [],
    restored_ids: result.restored_ids ?? [],
    skipped_ids: result.skipped_ids ?? [],
    skipped_reasons: result.skipped_reasons ?? {},
  };
}

export type CollectionTaskBulkRunResult = {
  started_ids: number[];
  queued_ids: number[];
  skipped_ids: number[];
  skipped_reasons: Record<string, string>;
  capacity: number;
  active_count: number;
  message: string;
};

export async function bulkRunCollectionTasks(taskIds: number[]): Promise<CollectionTaskBulkRunResult> {
  const response = await apiFetch(`${API_URL}/api/collection-tasks/bulk-run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task_ids: taskIds }),
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return parseJsonResponse<CollectionTaskBulkRunResult>(response);
}

export async function deleteCollectionTask(id: number): Promise<CollectionTaskDeleteResult> {
  const response = await apiFetch(`${API_URL}/api/collection-tasks/${id}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  if (response.status === 204) {
    return { action: "deleted", task_id: id };
  }
  const result = await parseJsonResponse<Partial<CollectionTaskDeleteResult>>(response);
  return {
    action: result.action ?? "deleted",
    task_id: result.task_id ?? id,
  };
}

export async function bulkDeleteCollectionTasks(
  taskIds: number[],
): Promise<CollectionTaskBulkDeleteResult> {
  const response = await apiFetch(`${API_URL}/api/collection-tasks/bulk-delete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task_ids: taskIds }),
  });
  if (response.status === 405) {
    return bulkDeleteCollectionTasksFallback(taskIds);
  }
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  const result = await parseJsonResponse<Partial<CollectionTaskBulkDeleteResult>>(response);
  return {
    deleted_count: result.deleted_count ?? 0,
    archived_count: result.archived_count ?? 0,
    skipped_count: result.skipped_count ?? 0,
    deleted_ids: result.deleted_ids ?? [],
    archived_ids: result.archived_ids ?? [],
    skipped_ids: result.skipped_ids ?? [],
  };
}

async function bulkDeleteCollectionTasksFallback(
  taskIds: number[],
): Promise<CollectionTaskBulkDeleteResult> {
  const result: CollectionTaskBulkDeleteResult = {
    deleted_count: 0,
    archived_count: 0,
    skipped_count: 0,
    deleted_ids: [],
    archived_ids: [],
    skipped_ids: [],
  };
  for (const taskId of taskIds) {
    try {
      const single = await deleteCollectionTask(taskId);
      if (single.action === "archived") {
        result.archived_count += 1;
        result.archived_ids.push(taskId);
      } else {
        result.deleted_count += 1;
        result.deleted_ids.push(taskId);
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      if (
        message.includes("409") ||
        message.includes("无效果") ||
        message.includes("Conflict") ||
        message.includes("正在运行")
      ) {
        result.skipped_count += 1;
        result.skipped_ids.push(taskId);
        continue;
      }
      throw error;
    }
  }
  return result;
}

export async function sendCollectionTaskEmail(id: number): Promise<EmailSendResult> {
  const response = await apiFetch(`${API_URL}/api/collection-tasks/${id}/send-email`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function fetchEmailLogs(
  page = 1,
  pageSize = 50,
): Promise<PaginatedResponse<EmailLog>> {
  const response = await apiFetch(
    `${API_URL}/api/email-logs?page=${page}&page_size=${pageSize}`,
    { cache: "no-store" },
  );
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function deleteEmailLogs(ids: number[]): Promise<EmailLogBulkDeleteResult> {
  const response = await apiFetch(`${API_URL}/api/email-logs/bulk-delete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids }),
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function deleteEmailLogsByStatus(status: EmailLogStatus): Promise<EmailLogBulkDeleteResult> {
  const response = await apiFetch(`${API_URL}/api/email-logs/bulk-delete-by-status`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function scheduleOutreachRecordFollowUp(
  recordId: number,
  payload: ScheduleOutreachRecordFollowUpPayload = {},
): Promise<EmailLog> {
  const response = await apiFetch(`${API_URL}/api/outreach-records/${recordId}/schedule-follow-up`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function stopOutreachRecordFollowUp(
  recordId: number,
  payload: StopOutreachRecordFollowUpPayload = {},
): Promise<EmailLog> {
  const response = await apiFetch(`${API_URL}/api/outreach-records/${recordId}/stop-follow-up`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function markOutreachRecordReplied(recordId: number): Promise<EmailLog> {
  const response = await apiFetch(`${API_URL}/api/outreach-records/${recordId}/mark-replied`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function markOutreachRecordUnreplied(recordId: number): Promise<EmailLog> {
  const response = await apiFetch(`${API_URL}/api/outreach-records/${recordId}/mark-unreplied`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function fetchDueFollowUpOutreachRecords(limit = 50): Promise<EmailLog[]> {
  const response = await apiFetch(`${API_URL}/api/outreach-records/follow-up-due?limit=${limit}`, {
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function fetchEmailReplies(params?: {
  productInfluencerId?: number;
  emailLogId?: number;
  campaignId?: number;
  processingStatus?: string;
  intentStatus?: string;
  unmatched?: boolean;
  page?: number;
  pageSize?: number;
}): Promise<PaginatedResponse<EmailReply>> {
  const search = new URLSearchParams();
  if (params?.productInfluencerId) search.set("product_influencer_id", String(params.productInfluencerId));
  if (params?.emailLogId) search.set("email_log_id", String(params.emailLogId));
  if (params?.campaignId) search.set("campaign_id", String(params.campaignId));
  if (params?.processingStatus) search.set("processing_status", params.processingStatus);
  if (params?.intentStatus) search.set("intent_status", params.intentStatus);
  if (typeof params?.unmatched === "boolean") search.set("unmatched", params.unmatched ? "true" : "false");
  search.set("page", String(params?.page ?? 1));
  search.set("page_size", String(params?.pageSize ?? 50));
  const response = await apiFetch(`${API_URL}/api/email-inbound/replies?${search.toString()}`, {
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function fetchEmailReplyWorkCount(): Promise<EmailReplyWorkCount> {
  const response = await apiFetch(`${API_URL}/api/email-inbound/replies/work-count`, {
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function updateEmailReply(
  replyId: number,
  payload: {
    product_influencer_id?: number | null;
    campaign_id?: number | null;
    intent_status?: string | null;
    processing_status?: string | null;
    manual_note?: string | null;
    mark_viewed?: boolean | null;
  },
): Promise<EmailReply> {
  const response = await apiFetch(`${API_URL}/api/email-inbound/replies/${replyId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function sendEmailReplyResponse(
  replyId: number,
  payload: EmailReplySendResponsePayload,
): Promise<EmailReplySendResponseResult> {
  const response = await apiFetch(`${API_URL}/api/email-replies/${replyId}/send-response`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function deleteEmailReplies(ids: number[]): Promise<EmailReplyBulkDeleteResult> {
  const response = await apiFetch(`${API_URL}/api/email-inbound/replies/bulk-delete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids }),
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function fetchInfluencerEmailReplies(influencerId: number): Promise<EmailReply[]> {
  const response = await apiFetch(`${API_URL}/api/influencers/${influencerId}/email-replies`, {
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function fetchInfluencerEmailReplySummary(
  influencerId: number,
): Promise<EmailReplySummary> {
  const response = await apiFetch(`${API_URL}/api/influencers/${influencerId}/email-reply-summary`, {
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function fetchCampaignReplySummary(campaignId: number): Promise<EmailReplySummary> {
  const response = await apiFetch(
    `${API_URL}/api/email-inbound/campaigns/${campaignId}/reply-summary`,
    { cache: "no-store" },
  );
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function pollImapInbox(markSeen = false): Promise<{
  processed: number;
  ingested: number;
  skipped: number;
  failed: number;
}> {
  const response = await apiFetch(
    `${API_URL}/api/email-inbound/poll-imap?mark_seen=${markSeen ? "true" : "false"}`,
    { method: "POST" },
  );
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function fetchSettingsStatus(): Promise<SettingsStatus> {
  const response = await apiFetch(`${API_URL}/api/settings/status`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function sendTestEmail(recipient: string): Promise<EmailTestResponse> {
  const response = await apiFetch(`${API_URL}/api/email/test`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ recipient }),
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function sendManualOutreachEmail(
  payload: ManualOutreachEmailPayload,
): Promise<ManualOutreachEmailResponse> {
  const response = await apiFetch(`${API_URL}/api/manual-outreach-email/send`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function fetchLinkImportBatches(
  page = 1,
  pageSize = 20,
  options?: { signal?: AbortSignal },
): Promise<PaginatedResponse<LinkImportBatch>> {
  const response = await apiFetch(
    `${API_URL}/api/link-import/batches?page=${page}&page_size=${pageSize}`,
    { cache: "no-store", signal: options?.signal },
  );
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function createLinkImportBatch(
  payload: LinkImportBatchPayload,
): Promise<LinkImportBatch> {
  if ((await ensureTenantProductId()) === 0) {
    throw new Error("创建链接导入任务需要先选择具体产品/品牌");
  }
  const response = await apiFetch(`${API_URL}/api/link-import/batches`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function fetchLinkImportBatch(batchId: number): Promise<LinkImportBatch> {
  const response = await apiFetch(`${API_URL}/api/link-import/batches/${batchId}`, {
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function runLinkImportBatch(batchId: number): Promise<LinkImportRunResult> {
  const response = await apiFetch(`${API_URL}/api/link-import/batches/${batchId}/run`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function deleteLinkImportBatch(batchId: number): Promise<void> {
  const response = await apiFetch(`${API_URL}/api/link-import/batches/${batchId}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
}

export type TenantProduct = {
  id: number;
  workspace_id: number;
  name: string;
  slug: string;
  brand?: string | null;
  description?: string | null;
  is_default?: boolean;
  is_archived?: boolean;
  is_hidden?: boolean;
  is_test?: boolean;
  created_source?: string | null;
  display_order?: number | null;
  created_at?: string;
  updated_at?: string;
};

export type TenantProductPayload = {
  name: string;
  slug?: string;
  brand?: string | null;
  description?: string | null;
  is_default?: boolean;
};

export type TenantProductUpdatePayload = {
  name?: string;
  slug?: string;
  brand?: string | null;
  description?: string | null;
  is_default?: boolean;
  is_hidden?: boolean;
  is_archived?: boolean;
};

export async function fetchTenantProducts(options?: {
  includeTest?: boolean;
}): Promise<TenantProduct[]> {
  const params = options?.includeTest ? "?include_test=true" : "";
  const response = await apiFetch(`${API_URL}/api/tenant/products${params}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function createTenantProduct(payload: TenantProductPayload): Promise<TenantProduct> {
  const response = await apiFetch(`${API_URL}/api/tenant/products`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function updateTenantProduct(productId: number, payload: TenantProductUpdatePayload): Promise<TenantProduct> {
  const response = await apiFetch(`${API_URL}/api/tenant/products/${productId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function runCollectionTaskBatch(
  id: number,
  options: { failedOnly?: boolean } = {},
): Promise<CollectionTaskBulkRunResult> {
  const params = new URLSearchParams();
  if (options.failedOnly) params.set("failed_only", "true");
  const qs = params.toString();
  const response = await apiFetch(`${API_URL}/api/collection-tasks/${id}/run-batch${qs ? `?${qs}` : ""}`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function deleteTenantProduct(productId: number): Promise<void> {
  const response = await apiFetch(`${API_URL}/api/tenant/products/${productId}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
}

export async function deleteAdminProduct(productId: number): Promise<void> {
  const response = await apiFetch(`${API_URL}/api/admin/products/${productId}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
}

export type AdminSummary = {
  total_users: number;
  total_sales: number;
  total_products: number;
  total_collection_tasks: number;
  total_influencers: number;
  total_email_logs: number;
  total_replies: number;
  today_collection_tasks: number;
  today_influencers: number;
  today_email_logs: number;
  today_replies: number;
  failed_collection_tasks: number;
  failed_email_logs: number;
  pending_replies: number;
  sales_rank: Array<{ id: number; username: string; product_count: number }>;
  product_rank: Array<{ id: number; name: string; influencer_count: number }>;
};

export type AdminUser = {
  id: number;
  username: string;
  display_name: string | null;
  email: string | null;
  role: "admin" | "sales";
  is_admin: boolean;
  is_active: boolean;
  product_count: number;
  bound_products: Array<{
    id: number;
    name: string;
    slug: string;
    role: string;
    status: string;
    created_at: string | null;
  }>;
  collection_task_count: number;
  today_collection_task_count?: number;
  collection_success_count: number;
  collection_failed_count: number;
  influencer_count: number;
  today_influencer_count?: number;
  email_count: number;
  email_failed_count: number;
  reply_count: number;
  pending_reply_count: number;
  last_active_at: string | null;
  created_at: string | null;
  updated_at: string | null;
  status: "active" | "disabled";
  recent_activity?: {
    collection_tasks: AdminCollectionTask[];
    emails: AdminEmail[];
    replies: AdminReply[];
  };
};

export type AdminUserCreatePayload = {
  username: string;
  password: string;
  display_name?: string | null;
  email?: string | null;
  role: "admin" | "sales";
  is_active: boolean;
  product_ids: number[];
};

export type AdminUserUpdatePayload = {
  username?: string;
  display_name?: string | null;
  email?: string | null;
  role?: "admin" | "sales";
  is_active?: boolean;
};

export type AdminProductMember = {
  user_id: number;
  username: string;
  role: string;
};

export type AdminProduct = {
  id: number;
  name: string;
  subject: string | null;
  brand?: string | null;
  description?: string | null;
  slug: string;
  created_at: string | null;
  updated_at?: string | null;
  members: AdminProductMember[];
  owner_names: string[];
  collection_task_count: number;
  influencer_count: number;
  email_count: number;
  reply_count: number;
  status: "active" | "hidden" | "archived";
  collection_tasks?: AdminCollectionTask[];
  influencers?: AdminInfluencer[];
  emails?: AdminEmail[];
  replies?: AdminReply[];
};

export type AdminCollectionTask = {
  id: number;
  parent_task_id?: number | null;
  name: string;
  status: string;
  platform: string;
  platforms: string[];
  keywords: string[];
  product_id: number | null;
  product_name: string | null;
  user_id: number | null;
  username: string | null;
  success_count: number;
  failed_count: number;
  inserted_count: number;
  result_count: number;
  last_run_at: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export type AdminInfluencer = {
  id: number;
  product_id: number;
  product_name: string | null;
  platform: string;
  username: string;
  display_name: string | null;
  profile_url: string;
  followers_count: number | null;
  email: string | null;
  follow_status: string | null;
  score: number | null;
  created_at: string | null;
  updated_at: string | null;
};

export type AdminEmail = {
  id: number;
  user_id: number | null;
  username: string | null;
  product_id: number | null;
  product_name: string | null;
  task_id: number | null;
  product_influencer_id: number | null;
  sender_email: string | null;
  influencer_username: string | null;
  recipients: string[];
  subject: string;
  status: string;
  error_message: string | null;
  sent_at: string | null;
  has_replied: boolean;
  replied_at: string | null;
};

export type AdminReply = {
  id: number;
  user_id: number | null;
  username: string | null;
  product_id: number;
  product_name: string | null;
  email_log_id: number | null;
  product_influencer_id: number | null;
  from_address: string;
  to_address: string;
  subject: string;
  snippet: string | null;
  processing_status: string;
  intent_status: string;
  received_at: string | null;
  handled_at: string | null;
};

export async function fetchAdminSummary(): Promise<AdminSummary> {
  const response = await apiFetch(`${API_URL}/api/admin/summary`, { cache: "no-store" });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function fetchAdminUsers(): Promise<AdminUser[]> {
  const response = await apiFetch(`${API_URL}/api/admin/users`, { cache: "no-store" });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function createAdminUser(payload: AdminUserCreatePayload): Promise<AdminUser> {
  const response = await apiFetch(`${API_URL}/api/admin/users`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function updateAdminUser(userId: number, payload: AdminUserUpdatePayload): Promise<AdminUser> {
  const response = await apiFetch(`${API_URL}/api/admin/users/${userId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function deleteAdminUser(userId: number): Promise<void> {
  const response = await apiFetch(`${API_URL}/api/admin/users/${userId}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
}

export async function setAdminUserProducts(userId: number, productIds: number[]): Promise<AdminUser> {
  const response = await apiFetch(`${API_URL}/api/admin/users/${userId}/products`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ product_ids: productIds }),
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function resetAdminUserPassword(userId: number, password: string): Promise<void> {
  const response = await apiFetch(`${API_URL}/api/admin/users/${userId}/reset-password`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
  });
  if (!response.ok) throw new Error(await parseError(response));
}

export async function fetchAdminUser(userId: number): Promise<AdminUser> {
  const response = await apiFetch(`${API_URL}/api/admin/users/${userId}`, { cache: "no-store" });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function fetchAdminUserProducts(userId: number): Promise<AdminProduct[]> {
  const response = await apiFetch(`${API_URL}/api/admin/users/${userId}/products`, { cache: "no-store" });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function fetchAdminUserCollectionTasks(userId: number): Promise<AdminCollectionTask[]> {
  const response = await apiFetch(`${API_URL}/api/admin/users/${userId}/collection-tasks`, { cache: "no-store" });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function fetchAdminUserInfluencers(userId: number): Promise<AdminInfluencer[]> {
  const response = await apiFetch(`${API_URL}/api/admin/users/${userId}/influencers`, { cache: "no-store" });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function fetchAdminUserEmails(userId: number): Promise<AdminEmail[]> {
  const response = await apiFetch(`${API_URL}/api/admin/users/${userId}/emails`, { cache: "no-store" });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function fetchAdminUserReplies(userId: number): Promise<AdminReply[]> {
  const response = await apiFetch(`${API_URL}/api/admin/users/${userId}/replies`, { cache: "no-store" });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function fetchAdminProducts(): Promise<AdminProduct[]> {
  const response = await apiFetch(`${API_URL}/api/admin/products`, { cache: "no-store" });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function fetchAdminProduct(productId: number): Promise<AdminProduct> {
  const response = await apiFetch(`${API_URL}/api/admin/products/${productId}`, { cache: "no-store" });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function deleteAdminCollectionTask(taskId: number): Promise<CollectionTaskDeleteResult> {
  const response = await apiFetch(`${API_URL}/api/admin/collection-tasks/${taskId}`, {
    method: "DELETE",
  });
  if (!response.ok) throw new Error(await parseError(response));
  const result = await parseJsonResponse<Partial<CollectionTaskDeleteResult>>(response);
  return {
    action: result.action ?? "deleted",
    task_id: result.task_id ?? taskId,
  };
}

export async function bulkDeleteAdminCollectionTasks(taskIds: number[]): Promise<CollectionTaskBulkDeleteResult> {
  const response = await apiFetch(`${API_URL}/api/admin/collection-tasks/bulk-delete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ task_ids: taskIds }),
  });
  if (!response.ok) throw new Error(await parseError(response));
  const result = await parseJsonResponse<Partial<CollectionTaskBulkDeleteResult>>(response);
  return {
    deleted_count: result.deleted_count ?? 0,
    archived_count: result.archived_count ?? 0,
    skipped_count: result.skipped_count ?? 0,
    deleted_ids: result.deleted_ids ?? [],
    archived_ids: result.archived_ids ?? [],
    skipped_ids: result.skipped_ids ?? [],
  };
}

export async function fetchAdminCollectionTasks(options?: {
  signal?: AbortSignal;
}): Promise<AdminCollectionTask[]> {
  const response = await apiFetch(`${API_URL}/api/admin/collection-tasks`, {
    cache: "no-store",
    signal: options?.signal,
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function fetchAdminInfluencers(): Promise<AdminInfluencer[]> {
  const response = await apiFetch(`${API_URL}/api/admin/influencers`, { cache: "no-store" });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function fetchAdminEmails(): Promise<AdminEmail[]> {
  const response = await apiFetch(`${API_URL}/api/admin/emails`, { cache: "no-store" });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function fetchAdminReplies(): Promise<AdminReply[]> {
  const response = await apiFetch(`${API_URL}/api/admin/replies`, { cache: "no-store" });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export type MessageTemplate = {
  id: number;
  user_id: number;
  workspace_id: number;
  product_id: number;
  title: string;
  scenario: string;
  platform: string | null;
  language: string | null;
  tags: string[];
  content: string;
  note: string | null;
  usage_count: number;
  last_used_at: string | null;
  created_at: string;
  updated_at: string;
  is_system_default?: boolean;
};

export type MessageTemplatePayload = {
  title: string;
  scenario: string;
  platform?: string | null;
  language?: string | null;
  tags?: string[];
  content: string;
  note?: string | null;
};

export type MessageTemplateListParams = {
  page?: number;
  pageSize?: number;
  search?: string;
  scenario?: string;
  platform?: string;
  language?: string;
  tag?: string;
};

export async function fetchMessageTemplates(
  params: MessageTemplateListParams = {},
): Promise<PaginatedResponse<MessageTemplate>> {
  const query = new URLSearchParams();
  query.set("page", String(params.page ?? 1));
  query.set("page_size", String(params.pageSize ?? 20));
  if (params.search?.trim()) query.set("search", params.search.trim());
  if (params.scenario) query.set("scenario", params.scenario);
  if (params.platform) query.set("platform", params.platform);
  if (params.language) query.set("language", params.language);
  if (params.tag?.trim()) query.set("tag", params.tag.trim());
  const response = await apiFetch(`${API_URL}/api/message-templates?${query.toString()}`, {
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function createMessageTemplate(payload: MessageTemplatePayload): Promise<MessageTemplate> {
  if ((await ensureTenantProductId()) === 0) {
    throw new Error("创建话术模板需要先选择具体产品/品牌");
  }
  const response = await apiFetch(`${API_URL}/api/message-templates`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function updateMessageTemplate(
  id: number,
  payload: Partial<MessageTemplatePayload>,
): Promise<MessageTemplate> {
  const response = await apiFetch(`${API_URL}/api/message-templates/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function deleteMessageTemplate(id: number): Promise<void> {
  const response = await apiFetch(`${API_URL}/api/message-templates/${id}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
}

export async function recordMessageTemplateUse(id: number): Promise<MessageTemplate> {
  const response = await apiFetch(`${API_URL}/api/message-templates/${id}/use`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function duplicateMessageTemplate(id: number): Promise<MessageTemplate> {
  const response = await apiFetch(`${API_URL}/api/message-templates/${id}/duplicate`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export type KnowledgeBase = {
  id: number;
  workspace_id: number;
  product_id: number;
  name: string;
  description: string | null;
  document_count: number;
  chunk_count: number;
  created_at: string;
  updated_at: string;
};

export type LinkKnowledgeChunk = {
  id: number;
  link_knowledge_base_id: number;
  workspace_id: number;
  chunk_index: number;
  chunk_type: string;
  title: string | null;
  content: string;
  metadata: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
};

export type LinkKnowledgeBase = {
  id: number;
  workspace_id: number;
  user_id: number | null;
  product_id: number | null;
  name: string;
  url: string;
  domain: string | null;
  source_type: string;
  status: string;
  fetch_status: string | null;
  parse_status: string | null;
  summary: string | null;
  extracted_knowledge: Record<string, unknown> | null;
  tags: string[] | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  last_fetched_at: string | null;
  error_message: string | null;
  chunks: LinkKnowledgeChunk[];
};

export type CreateLinkKnowledgeBasePayload = {
  name?: string | null;
  url: string;
  product_id?: number | null;
  tags?: string[] | null;
  parse_immediately?: boolean;
};

export type UpdateLinkKnowledgeBasePayload = {
  name?: string | null;
  url?: string | null;
  summary?: string | null;
  extracted_knowledge?: Record<string, unknown> | null;
  tags?: string[] | null;
  is_active?: boolean;
  reparse?: boolean;
};

export type GenerateLinkScriptsPayload = {
  name?: string | null;
  influencer_ids: number[];
  language?: string;
  tone?: string;
  collaboration_type?: string;
  script_types?: string[];
  extra_instruction?: string | null;
};

export type LinkScriptJob = {
  id: number;
  workspace_id: number;
  link_knowledge_base_id: number;
  product_id: number | null;
  name: string;
  status: string;
  total_count: number;
  success_count: number;
  failed_count: number;
  language: string;
  tone: string;
  collaboration_type: string;
  script_types: string[] | null;
  ai_model: string | null;
  extra_instruction: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  error_message: string | null;
};

export type LinkScriptResult = {
  id: number;
  workspace_id: number;
  job_id: number;
  link_knowledge_base_id: number;
  influencer_id: number;
  platform: string | null;
  profile_url: string | null;
  influencer_name: string | null;
  influencer_handle: string | null;
  status: string;
  input_snapshot: Record<string, unknown> | null;
  generated_content: Record<string, unknown> | null;
  edited_content: Record<string, unknown> | null;
  used_content: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
  error_message: string | null;
};

export type UpdateLinkScriptResultPayload = {
  edited_content?: Record<string, unknown> | null;
  used_content?: Record<string, unknown> | null;
};

export type RegenerateLinkScriptPayload = {
  tone?: string | null;
  language?: string | null;
  collaboration_type?: string | null;
  extra_instruction?: string | null;
};

export type KnowledgeDocument = {
  id: number;
  knowledge_base_id: number;
  workspace_id: number;
  product_id: number;
  file_name: string;
  file_type: string;
  source_path: string | null;
  uploaded_file_path: string | null;
  status: "pending" | "processing" | "ready" | "failed" | string;
  error_message: string | null;
  chunk_count: number;
  created_at: string;
  updated_at: string;
};

export type KnowledgeChunk = {
  id: number;
  document_id: number;
  knowledge_base_id: number;
  product_id: number;
  chunk_index: number;
  title: string | null;
  content: string;
  metadata: Record<string, unknown>;
  created_at: string;
};

export type KnowledgeSearchResult = {
  chunk_id: number;
  document_id: number;
  document_name: string;
  title: string | null;
  section: string | null;
  content: string;
  score: number;
  metadata: Record<string, unknown>;
};

export type ScriptRecommendPayload = {
  influencer_id: number;
  user_intent?: string;
  selected_script_ids?: number[];
  contact_status?: string | null;
  followup_status?: string | null;
};

export type MatchedKnowledgeItem = {
  document: string;
  section?: string | null;
  summary: string;
};

export type ScriptRecommendResponse = {
  recommended_script_id: string | null;
  recommended_script_title: string;
  final_message: string;
  reason: string;
  matched_knowledge: MatchedKnowledgeItem[];
  tone: string;
  risk_notes: string[];
  provider: string;
  configured: boolean;
  error_message?: string | null;
};

export type OutreachPreviewItem = {
  influencer_id: number;
  username: string;
  display_name: string | null;
  recipient: string | null;
  subject: string;
  body: string;
  reason: string;
  matched_knowledge: MatchedKnowledgeItem[];
  risk_notes: string[];
  tone: string;
  can_send: boolean;
  generated_by_ai: boolean;
  provider: string;
  error_message: string | null;
};

export type OutreachBatchPreviewResponse = {
  items: OutreachPreviewItem[];
  summary: {
    total: number;
    generated: number;
    missing_email: number;
    failed: number;
  };
};

export type OutreachBatchSendResponse = {
  items: Array<{
    influencer_id: number;
    username: string;
    recipient: string | null;
    subject: string;
    body: string;
    status: string;
    email_log_id: number | null;
    error_message: string | null;
    generated_by_ai: boolean;
  }>;
  summary: {
    total: number;
    generated: number;
    sent: number;
    pending: number;
    failed: number;
    skipped_missing_email: number;
  };
  dry_run: boolean;
};

export async function previewOutreachBatch(payload: {
  influencer_ids: number[];
  user_intent?: string;
  limit?: number;
}): Promise<OutreachBatchPreviewResponse> {
  const response = await apiFetch(`${API_URL}/api/email/outreach/preview-batch`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function sendOutreachBatch(payload: {
  influencer_ids: number[];
  user_intent?: string;
  dry_run?: boolean;
}): Promise<OutreachBatchSendResponse> {
  if ((await ensureTenantProductId()) === 0) {
    throw new Error("发送外联邮件需要先选择具体产品/品牌");
  }
  const response = await apiFetch(`${API_URL}/api/email/outreach/send-batch`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export type SaveEmailLogAsTemplatePayload = {
  title?: string;
  scenario?: string;
  platform?: string | null;
  language?: string | null;
  tags?: string[];
  content?: string;
  note?: string | null;
  save_as_copy?: boolean;
};

export type SaveEmailLogAsTemplateResponse = {
  created: boolean;
  duplicate: boolean;
  message: string;
  template: MessageTemplate | null;
};

export async function saveEmailLogAsMessageTemplate(
  logId: number,
  payload: SaveEmailLogAsTemplatePayload,
): Promise<SaveEmailLogAsTemplateResponse> {
  const response = await apiFetch(`${API_URL}/api/email-logs/${logId}/save-as-message-template`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export type SingleOutreachEmailPreview = {
  subject: string;
  body: string;
  recipient: string;
  sender_email: string;
  sender_display?: string;
  template_title: string;
  reason: string;
  matched_knowledge: MatchedKnowledgeItem[];
};

export type SingleOutreachEmailSendResponse = {
  success: boolean;
  message: string;
  email_log: EmailLog | null;
};

export async function previewInfluencerOutreachEmail(
  influencerId: number,
): Promise<SingleOutreachEmailPreview> {
  const response = await apiFetch(
    `${API_URL}/api/influencers/${influencerId}/outreach-email/preview`,
    { method: "POST" },
  );
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function sendInfluencerOutreachEmail(
  influencerId: number,
  payload: { subject: string; body: string },
): Promise<SingleOutreachEmailSendResponse> {
  const response = await apiFetch(
    `${API_URL}/api/influencers/${influencerId}/outreach-email/send`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export type OutreachSendQueueItem = {
  id: number;
  product_id: number;
  user_id: number;
  product_influencer_id: number;
  recipient: string;
  sender_email: string | null;
  subject: string;
  body: string;
  status: string;
  scheduled_at: string | null;
  sent_at: string | null;
  failed_at: string | null;
  next_retry_at: string | null;
  retry_count: number;
  max_retries: number;
  priority: number;
  error_message: string | null;
  dedupe_key: string | null;
  locked_at: string | null;
  generated_by_ai: boolean;
  ai_reason: string | null;
  campaign_id: number | null;
  email_log_id: number | null;
  smtp_account_id: number | null;
  queue_type: string;
  follow_up_step: number | null;
  parent_queue_id: number | null;
  outreach_record_id: number | null;
  should_skip_if_replied: boolean;
  created_at: string;
  updated_at: string;
};

export type OutreachScheduleConfig = {
  start_at: string;
  timezone?: string;
  send_window_start?: string;
  send_window_end?: string;
  interval_minutes?: number;
  daily_limit?: number;
  hourly_limit?: number;
  weekdays_only?: boolean;
};

export type OutreachScheduleItem = {
  product_influencer_id: number;
  recipient: string;
  subject: string;
  body: string;
  matched_knowledge?: MatchedKnowledgeItem[];
  ai_reason?: string;
  allow_resend?: boolean;
  priority?: number;
  dedupe_key?: string;
  max_retries?: number;
};

export type OutreachScheduleRequest = {
  campaign_id?: number | null;
  items: OutreachScheduleItem[];
  schedule_config: OutreachScheduleConfig;
};

export type OutreachScheduleResult = {
  created_count: number;
  skipped_count: number;
  first_scheduled_at: string | null;
  last_scheduled_at: string | null;
};

export type OutreachSendQueueProcessResult = {
  processed: number;
  sent: number;
  failed: number;
  skipped: number;
  daily_limit: number;
  sent_today: number;
  message: string;
};

export type OutreachSendQueueClearFailedResult = {
  deleted_count: number;
  message: string;
};

export async function enqueueInfluencerOutreachEmail(
  influencerId: number,
  payload: {
    subject: string;
    body: string;
    matched_knowledge?: MatchedKnowledgeItem[];
    ai_reason?: string;
    template_title?: string;
    allow_resend?: boolean;
  },
): Promise<OutreachSendQueueItem> {
  const response = await apiFetch(
    `${API_URL}/api/influencers/${influencerId}/outreach-email/enqueue`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function fetchOutreachSendQueue(params: {
  page?: number;
  pageSize?: number;
  status?: string;
  campaignId?: number;
  recipientEmail?: string;
  scheduledFrom?: string;
  scheduledTo?: string;
} = {}): Promise<PaginatedResponse<OutreachSendQueueItem>> {
  const query = new URLSearchParams();
  query.set("page", String(params.page ?? 1));
  query.set("page_size", String(params.pageSize ?? 50));
  if (params.status) query.set("status", params.status);
  if (params.campaignId) query.set("campaign_id", String(params.campaignId));
  if (params.recipientEmail) query.set("recipient_email", params.recipientEmail);
  if (params.scheduledFrom) query.set("scheduled_from", params.scheduledFrom);
  if (params.scheduledTo) query.set("scheduled_to", params.scheduledTo);
  const response = await apiFetch(`${API_URL}/api/outreach-send-queue?${query.toString()}`, {
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function scheduleOutreachSendQueue(
  payload: OutreachScheduleRequest,
): Promise<OutreachScheduleResult> {
  const response = await apiFetch(`${API_URL}/api/outreach-send-queue/schedule`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function fetchOutreachSendQueueItem(itemId: number): Promise<OutreachSendQueueItem> {
  const response = await apiFetch(`${API_URL}/api/outreach-send-queue/${itemId}`, {
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function processTodayOutreachQueue(): Promise<OutreachSendQueueProcessResult> {
  const response = await apiFetch(`${API_URL}/api/outreach-send-queue/process-today`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function cancelOutreachQueueItem(itemId: number): Promise<OutreachSendQueueItem> {
  const response = await apiFetch(`${API_URL}/api/outreach-send-queue/${itemId}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function pauseOutreachQueueItem(itemId: number): Promise<OutreachSendQueueItem> {
  const response = await apiFetch(`${API_URL}/api/outreach-send-queue/${itemId}/pause`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function resumeOutreachQueueItem(itemId: number): Promise<OutreachSendQueueItem> {
  const response = await apiFetch(`${API_URL}/api/outreach-send-queue/${itemId}/resume`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function cancelScheduledOutreachQueueItem(itemId: number): Promise<OutreachSendQueueItem> {
  const response = await apiFetch(`${API_URL}/api/outreach-send-queue/${itemId}/cancel`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function sendOutreachQueueItemNow(itemId: number): Promise<OutreachSendQueueItem> {
  const response = await apiFetch(`${API_URL}/api/outreach-send-queue/${itemId}/send-now`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function rescheduleOutreachQueueItem(
  itemId: number,
  scheduledAt: string,
): Promise<OutreachSendQueueItem> {
  const response = await apiFetch(`${API_URL}/api/outreach-send-queue/${itemId}/reschedule`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scheduled_at: scheduledAt }),
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function bulkPauseOutreachQueue(ids: number[]): Promise<{ updated_count: number }> {
  const response = await apiFetch(`${API_URL}/api/outreach-send-queue/bulk-pause`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids }),
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function bulkCancelOutreachQueue(ids: number[]): Promise<{ updated_count: number }> {
  const response = await apiFetch(`${API_URL}/api/outreach-send-queue/bulk-cancel`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids }),
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function clearFailedOutreachQueue(): Promise<OutreachSendQueueClearFailedResult> {
  const response = await apiFetch(`${API_URL}/api/outreach-send-queue/failed`, {
    method: "DELETE",
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export type OutreachCampaign = {
  id: number;
  product_id: number;
  user_id: number;
  name: string;
  status: string;
  knowledge_base_id: number | null;
  message_template_id: number | null;
  daily_limit: number;
  send_window_start: string | null;
  send_window_end: string | null;
  timezone: string;
  skip_sent: boolean;
  skip_replied: boolean;
  skip_blacklisted: boolean;
  skip_invalid: boolean;
  allow_resend: boolean;
  auto_send_enabled: boolean;
  auto_send_time: string | null;
  auto_send_timezone: string;
  total_count: number;
  draft_count: number;
  can_queue_count: number;
  queued_count: number;
  sent_count: number;
  failed_count: number;
  skipped_count: number;
  reply_count: number;
  interested_count: number;
  unreplied_count: number;
  latest_reply_at: string | null;
  previewed_at: string | null;
  last_processed_at: string | null;
  last_auto_processed_at: string | null;
  next_auto_process_at: string | null;
  influencer_filters_snapshot: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
};

export type OutreachCampaignCreatePayload = {
  name: string;
  influencer_ids?: number[];
  select_all_by_filters?: boolean;
  influencer_filters?: Record<string, string | number | boolean>;
  knowledge_base_id?: number | null;
  message_template_id?: number | null;
  daily_limit?: number;
  send_window_start?: string | null;
  send_window_end?: string | null;
  timezone?: string;
  skip_sent?: boolean;
  skip_replied?: boolean;
  skip_blacklisted?: boolean;
  skip_invalid?: boolean;
  allow_resend?: boolean;
  auto_send_enabled?: boolean;
  auto_send_time?: string | null;
  auto_send_timezone?: string;
};

export type OutreachCampaignUpdatePayload = {
  name?: string;
  daily_limit?: number;
  send_window_start?: string | null;
  send_window_end?: string | null;
  skip_sent?: boolean;
  skip_replied?: boolean;
  skip_blacklisted?: boolean;
  skip_invalid?: boolean;
  allow_resend?: boolean;
  auto_send_enabled?: boolean;
  auto_send_time?: string | null;
  auto_send_timezone?: string;
};

export type OutreachCampaignPreviewItem = {
  influencer_id: number;
  username: string;
  display_name: string | null;
  recipient: string | null;
  subject: string;
  body: string;
  reason: string;
  matched_knowledge: MatchedKnowledgeItem[];
  template_title: string;
  can_queue: boolean;
  skip_reason: string | null;
  draft_status: string;
  is_high_value: boolean;
  opened_at: string | null;
  approved_at: string | null;
  queued_at: string | null;
  approval_block_reason: string | null;
};

export type OutreachCampaignPreviewResponse = {
  campaign_id: number;
  items: OutreachCampaignPreviewItem[];
  total: number;
  can_queue_count: number;
  skip_count: number;
};

export type OutreachCampaignPreviewPayload = {
  content_source?: "ai" | "manual" | "template";
  subject?: string;
  body?: string;
};

export type OutreachCampaignRecipientListResponse = OutreachCampaignPreviewResponse;

export type OutreachCampaignBulkApproveResponse = {
  approved: number;
  skipped: number;
  message: string;
};

export type OutreachCampaignGenerateAndSendResponse = {
  campaign_id: number;
  preview: OutreachCampaignPreviewResponse;
  queued: number;
  queue_skipped: number;
  processed: number;
  sent: number;
  failed: number;
  skipped: number;
  daily_limit: number;
  sent_today: number;
  message: string;
};

export type OutreachCampaignReplyBoardItem = {
  influencer_id: number;
  username: string;
  display_name: string | null;
  platform: string | null;
  recipient: string | null;
  subject: string | null;
  send_status: string;
  reply_status: string;
  reply_time: string | null;
  reply_snippet: string | null;
  reply_body?: string | null;
  match_method: string | null;
  skip_reason: string | null;
};

export type OutreachCampaignReplyBoard = {
  campaign_id: number;
  total: number;
  reply_count: number;
  interested_count: number;
  unreplied_count: number;
  latest_reply_at: string | null;
  items: OutreachCampaignReplyBoardItem[];
};

export type OutreachWorkbenchStatusItem = {
  status: "normal" | "not_configured" | "error" | string;
  message: string;
};

export type OutreachWorkbenchResultItem = {
  influencer_id: number;
  username: string;
  display_name: string | null;
  recipient: string | null;
  status: "sent" | "pending" | "skipped" | "failed" | string;
  subject: string | null;
  body: string | null;
  reason: string | null;
  sent_at: string | null;
};

export type OutreachWorkbenchResultSection = {
  campaign_id: number | null;
  total: number;
  sent: number;
  skipped: number;
  failed: number;
  pending: number;
  items: OutreachWorkbenchResultItem[];
};

export type OutreachOneClickWorkbench = {
  ai_generation: OutreachWorkbenchStatusItem;
  smtp: OutreachWorkbenchStatusItem;
  available_recipient_count: number;
  latest_campaign: OutreachCampaign | null;
  latest_results: OutreachWorkbenchResultSection;
  reply_followup: OutreachCampaignReplyBoard;
};

export async function fetchOutreachCampaigns(): Promise<OutreachCampaign[]> {
  const response = await apiFetch(`${API_URL}/api/outreach-campaigns`, { cache: "no-store" });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function fetchOutreachWorkbench(): Promise<OutreachOneClickWorkbench> {
  try {
    const response = await apiFetch(`${API_URL}/api/outreach-campaigns/workbench`, {
      cache: "no-store",
    });
    if (!response.ok) {
      if (response.status === 404 || response.status === 405) {
        return fetchOutreachWorkbenchFallback();
      }
      throw new Error(await parseError(response));
    }
    return response.json();
  } catch (error) {
    try {
      return await fetchOutreachWorkbenchFallback();
    } catch {
      throw error;
    }
  }
}

async function fetchOutreachWorkbenchFallback(): Promise<OutreachOneClickWorkbench> {
  const settings = await fetchSettingsStatus();
  const campaigns = await fetchOutreachCampaigns().catch(() => []);
  const latest = campaigns[0] ?? null;
  const recipients = latest
    ? await fetchOutreachCampaignRecipients(latest.id).catch(() => null)
    : null;
  const replies = latest
    ? await fetchOutreachCampaignReplyBoard(latest.id).catch(() => null)
    : null;
  const replyBoard =
    replies ??
    ({
      campaign_id: latest?.id ?? 0,
      total: 0,
      reply_count: 0,
      interested_count: 0,
      unreplied_count: 0,
      latest_reply_at: null,
      items: [],
    } satisfies OutreachCampaignReplyBoard);
  const replyByInfluencer = new Map(
    replyBoard.items.map((item) => [item.influencer_id, item]),
  );
  const items: OutreachWorkbenchResultItem[] = (recipients?.items ?? []).map((item) => {
    const reply = replyByInfluencer.get(item.influencer_id);
    const sendStatus = reply?.send_status;
    const status =
      sendStatus === "sent"
        ? "sent"
        : sendStatus === "failed"
          ? "failed"
          : item.skip_reason || sendStatus === "skipped"
            ? "skipped"
            : "pending";
    return {
      influencer_id: item.influencer_id,
      username: item.username,
      display_name: item.display_name,
      recipient: item.recipient,
      status,
      subject: item.subject || reply?.subject || null,
      body: item.body || null,
      reason: item.skip_reason || reply?.skip_reason || null,
      sent_at: null,
    };
  });

  return {
    ai_generation: {
      status: settings.ai.configured ? "normal" : "not_configured",
      message: settings.ai.configured
        ? `${settings.ai.provider} 已配置，可生成个性化邮件`
        : "未配置 GPT，无法生成个性化邮件",
    },
    smtp: {
      status: settings.smtp.configured && !settings.smtp.from_user_mismatch ? "normal" : "not_configured",
      message: settings.smtp.message,
    },
    available_recipient_count: latest?.can_queue_count ?? 0,
    latest_campaign: latest,
    latest_results: {
      campaign_id: latest?.id ?? null,
      total: items.length,
      sent: items.filter((item) => item.status === "sent").length,
      skipped: items.filter((item) => item.status === "skipped").length,
      failed: items.filter((item) => item.status === "failed").length,
      pending: items.filter((item) => item.status === "pending").length,
      items,
    },
    reply_followup: replyBoard,
  };
}

export async function createOutreachCampaign(
  payload: OutreachCampaignCreatePayload,
): Promise<OutreachCampaign> {
  if ((await ensureTenantProductId()) === 0) {
    throw new Error("创建外联任务需要先选择具体产品/品牌");
  }
  const response = await apiFetch(`${API_URL}/api/outreach-campaigns`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function previewOutreachCampaign(
  campaignId: number,
  payload?: OutreachCampaignPreviewPayload,
): Promise<OutreachCampaignPreviewResponse> {
  const response = await apiFetch(
    `${LONG_RUNNING_API_URL}/api/outreach-campaigns/${campaignId}/preview`,
    {
      method: "POST",
      headers: payload ? { "Content-Type": "application/json" } : undefined,
      body: payload ? JSON.stringify(payload) : undefined,
    },
    { timeoutMs: PREVIEW_FETCH_TIMEOUT_MS },
  );
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function fetchOutreachCampaignRecipients(
  campaignId: number,
): Promise<OutreachCampaignRecipientListResponse> {
  const response = await apiFetch(`${API_URL}/api/outreach-campaigns/${campaignId}/recipients`, {
    cache: "no-store",
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function openOutreachCampaignDraft(
  campaignId: number,
  influencerId: number,
): Promise<OutreachCampaignPreviewItem> {
  const response = await apiFetch(
    `${API_URL}/api/outreach-campaigns/${campaignId}/recipients/${influencerId}/open`,
    { method: "POST" },
  );
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function updateOutreachCampaignDraft(
  campaignId: number,
  influencerId: number,
  payload: { subject?: string; body?: string },
): Promise<OutreachCampaignPreviewItem> {
  const response = await apiFetch(
    `${API_URL}/api/outreach-campaigns/${campaignId}/recipients/${influencerId}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function regenerateOutreachCampaignDraft(
  campaignId: number,
  influencerId: number,
): Promise<OutreachCampaignPreviewItem> {
  const response = await apiFetch(
    `${LONG_RUNNING_API_URL}/api/outreach-campaigns/${campaignId}/recipients/${influencerId}/regenerate`,
    { method: "POST" },
    { timeoutMs: PREVIEW_FETCH_TIMEOUT_MS },
  );
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function approveOutreachCampaignDraft(
  campaignId: number,
  influencerId: number,
): Promise<OutreachCampaignPreviewItem> {
  const response = await apiFetch(
    `${API_URL}/api/outreach-campaigns/${campaignId}/recipients/${influencerId}/approve`,
    { method: "POST" },
  );
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function skipOutreachCampaignDraft(
  campaignId: number,
  influencerId: number,
): Promise<OutreachCampaignPreviewItem> {
  const response = await apiFetch(
    `${API_URL}/api/outreach-campaigns/${campaignId}/recipients/${influencerId}/skip`,
    { method: "POST" },
  );
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function bulkApproveOutreachCampaignDrafts(
  campaignId: number,
  payload: { confirm: boolean; influencer_ids?: number[] },
): Promise<OutreachCampaignBulkApproveResponse> {
  const response = await apiFetch(
    `${API_URL}/api/outreach-campaigns/${campaignId}/recipients/bulk-approve`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function queueOutreachCampaign(
  campaignId: number,
  payload: { confirm: boolean; influencer_ids?: number[] },
): Promise<{ queued: number; skipped: number; message: string }> {
  const response = await apiFetch(`${API_URL}/api/outreach-campaigns/${campaignId}/queue`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function fetchOutreachCampaignReplyBoard(
  campaignId: number,
): Promise<OutreachCampaignReplyBoard> {
  const response = await apiFetch(`${API_URL}/api/outreach-campaigns/${campaignId}/replies`, {
    cache: "no-store",
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function processOutreachCampaign(
  campaignId: number,
): Promise<OutreachSendQueueProcessResult> {
  const response = await apiFetch(`${API_URL}/api/outreach-campaigns/${campaignId}/process`, {
    method: "POST",
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function sendOutreachCampaignNow(
  campaignId: number,
  payload: { confirm: boolean; influencer_ids?: number[] },
): Promise<OutreachSendQueueProcessResult> {
  const response = await apiFetch(
    `${LONG_RUNNING_API_URL}/api/outreach-campaigns/${campaignId}/send-now`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    { timeoutMs: PREVIEW_FETCH_TIMEOUT_MS },
  );
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function generateAndSendOutreachCampaign(
  campaignId: number,
): Promise<OutreachCampaignGenerateAndSendResponse> {
  const response = await apiFetch(
    `${LONG_RUNNING_API_URL}/api/outreach-campaigns/${campaignId}/generate-and-send`,
    { method: "POST" },
    { timeoutMs: PREVIEW_FETCH_TIMEOUT_MS },
  );
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function pauseOutreachCampaign(campaignId: number): Promise<OutreachCampaign> {
  const response = await apiFetch(`${API_URL}/api/outreach-campaigns/${campaignId}/pause`, {
    method: "POST",
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function resumeOutreachCampaign(campaignId: number): Promise<OutreachCampaign> {
  const response = await apiFetch(`${API_URL}/api/outreach-campaigns/${campaignId}/resume`, {
    method: "POST",
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function cancelOutreachCampaign(campaignId: number): Promise<OutreachCampaign> {
  const response = await apiFetch(`${API_URL}/api/outreach-campaigns/${campaignId}/cancel`, {
    method: "POST",
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function updateOutreachCampaign(
  campaignId: number,
  payload: OutreachCampaignUpdatePayload,
): Promise<OutreachCampaign> {
  const response = await apiFetch(`${API_URL}/api/outreach-campaigns/${campaignId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error(await parseError(response));
  return response.json();
}

export async function fetchKnowledgeBases(): Promise<KnowledgeBase[]> {
  const response = await apiFetch(`${API_URL}/api/knowledge-bases`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function fetchLinkKnowledgeBases(params: {
  page?: number;
  pageSize?: number;
  status?: string;
  domain?: string;
  keyword?: string;
  tag?: string;
} = {}): Promise<PaginatedResponse<LinkKnowledgeBase>> {
  const query = new URLSearchParams();
  query.set("page", String(params.page ?? 1));
  query.set("page_size", String(params.pageSize ?? 20));
  if (params.status) query.set("status", params.status);
  if (params.domain) query.set("domain", params.domain);
  if (params.keyword) query.set("keyword", params.keyword);
  if (params.tag) query.set("tag", params.tag);
  const response = await apiFetch(`${API_URL}/api/link-knowledge-bases?${query.toString()}`, {
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function createLinkKnowledgeBase(
  payload: CreateLinkKnowledgeBasePayload,
): Promise<LinkKnowledgeBase> {
  if ((await ensureTenantProductId()) === 0) {
    throw new Error("创建链接库需要先选择具体产品/品牌");
  }
  const response = await apiFetch(
    `${API_URL}/api/link-knowledge-bases`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    { timeoutMs: PREVIEW_FETCH_TIMEOUT_MS },
  );
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function fetchLinkKnowledgeBase(id: number): Promise<LinkKnowledgeBase> {
  const response = await apiFetch(`${API_URL}/api/link-knowledge-bases/${id}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function updateLinkKnowledgeBase(
  id: number,
  payload: UpdateLinkKnowledgeBasePayload,
): Promise<LinkKnowledgeBase> {
  const response = await apiFetch(`${API_URL}/api/link-knowledge-bases/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function refreshLinkKnowledgeBase(id: number): Promise<LinkKnowledgeBase> {
  const response = await apiFetch(
    `${API_URL}/api/link-knowledge-bases/${id}/refresh`,
    { method: "POST" },
    { timeoutMs: PREVIEW_FETCH_TIMEOUT_MS },
  );
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function archiveLinkKnowledgeBase(id: number): Promise<LinkKnowledgeBase> {
  const response = await apiFetch(`${API_URL}/api/link-knowledge-bases/${id}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export const deleteLinkKnowledgeBase = archiveLinkKnowledgeBase;

export async function generateLinkScripts(
  id: number,
  payload: GenerateLinkScriptsPayload,
): Promise<LinkScriptJob> {
  const response = await apiFetch(
    `${API_URL}/api/link-knowledge-bases/${id}/generate-scripts`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    { timeoutMs: PREVIEW_FETCH_TIMEOUT_MS },
  );
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function fetchLinkScriptJobs(params: {
  page?: number;
  pageSize?: number;
  linkKnowledgeBaseId?: number;
  status?: string;
} = {}): Promise<PaginatedResponse<LinkScriptJob>> {
  const query = new URLSearchParams();
  query.set("page", String(params.page ?? 1));
  query.set("page_size", String(params.pageSize ?? 20));
  if (params.linkKnowledgeBaseId) {
    query.set("link_knowledge_base_id", String(params.linkKnowledgeBaseId));
  }
  if (params.status) query.set("status", params.status);
  const response = await apiFetch(`${API_URL}/api/link-script-jobs?${query.toString()}`, {
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function fetchLinkScriptJob(id: number): Promise<LinkScriptJob> {
  const response = await apiFetch(`${API_URL}/api/link-script-jobs/${id}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function fetchLinkScriptResults(
  jobId: number,
  params: {
    page?: number;
    pageSize?: number;
    status?: string;
    platform?: string;
    keyword?: string;
  } = {},
): Promise<PaginatedResponse<LinkScriptResult>> {
  const query = new URLSearchParams();
  query.set("page", String(params.page ?? 1));
  query.set("page_size", String(params.pageSize ?? 100));
  if (params.status) query.set("status", params.status);
  if (params.platform) query.set("platform", params.platform);
  if (params.keyword) query.set("keyword", params.keyword);
  const response = await apiFetch(`${API_URL}/api/link-script-jobs/${jobId}/results?${query.toString()}`, {
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function fetchLinkScriptResult(id: number): Promise<LinkScriptResult> {
  const response = await apiFetch(`${API_URL}/api/link-script-results/${id}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function updateLinkScriptResult(
  id: number,
  payload: UpdateLinkScriptResultPayload,
): Promise<LinkScriptResult> {
  const response = await apiFetch(`${API_URL}/api/link-script-results/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function regenerateLinkScript(
  id: number,
  payload: RegenerateLinkScriptPayload = {},
): Promise<LinkScriptResult> {
  const response = await apiFetch(
    `${API_URL}/api/link-script-results/${id}/regenerate`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    { timeoutMs: PREVIEW_FETCH_TIMEOUT_MS },
  );
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function exportLinkScriptJob(id: number): Promise<void> {
  await downloadWithTenantHeaders(`${API_URL}/api/link-script-jobs/${id}/export`, `link-script-job-${id}.xlsx`);
}

export async function createKnowledgeBase(payload: {
  name: string;
  description?: string | null;
}): Promise<KnowledgeBase> {
  if ((await ensureTenantProductId()) === 0) {
    throw new Error("创建知识库需要先选择具体产品/品牌");
  }
  const response = await apiFetch(`${API_URL}/api/knowledge-bases`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function fetchKnowledgeDocuments(params: {
  page?: number;
  pageSize?: number;
  knowledgeBaseId?: number;
} = {}): Promise<PaginatedResponse<KnowledgeDocument>> {
  const query = new URLSearchParams();
  query.set("page", String(params.page ?? 1));
  query.set("page_size", String(params.pageSize ?? 20));
  if (params.knowledgeBaseId) {
    query.set("knowledge_base_id", String(params.knowledgeBaseId));
  }
  const response = await apiFetch(`${API_URL}/api/knowledge-documents?${query.toString()}`, {
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function fetchKnowledgeDocumentChunks(
  documentId: number,
  params: { page?: number; pageSize?: number } = {},
): Promise<PaginatedResponse<KnowledgeChunk>> {
  const query = new URLSearchParams();
  query.set("page", String(params.page ?? 1));
  query.set("page_size", String(params.pageSize ?? 50));
  const response = await apiFetch(
    `${API_URL}/api/knowledge-documents/${documentId}/chunks?${query.toString()}`,
    { cache: "no-store" },
  );
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function uploadKnowledgeDocument(
  file: File,
  knowledgeBaseId?: number,
): Promise<KnowledgeDocument> {
  const form = new FormData();
  form.append("file", file);
  if (knowledgeBaseId) {
    form.append("knowledge_base_id", String(knowledgeBaseId));
  }
  const response = await apiFetch(`${API_URL}/api/knowledge-documents/upload`, {
    method: "POST",
    body: form,
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export type KnowledgeImportPreset = {
  id: string;
  label: string;
  file_path: string;
  available: boolean;
};

export async function fetchKnowledgeImportPresets(): Promise<KnowledgeImportPreset[]> {
  const response = await apiFetch(`${API_URL}/api/knowledge-documents/import-presets`, {
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function importKnowledgeDocument(payload: {
  file_path: string;
  knowledge_base_id?: number;
}): Promise<KnowledgeDocument> {
  const response = await apiFetch(`${API_URL}/api/knowledge-documents/import`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function reprocessKnowledgeDocument(documentId: number): Promise<KnowledgeDocument> {
  const response = await apiFetch(`${API_URL}/api/knowledge-documents/${documentId}/reprocess`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function deleteKnowledgeDocument(documentId: number): Promise<void> {
  const response = await apiFetch(`${API_URL}/api/knowledge-documents/${documentId}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
}

export async function searchKnowledge(
  query: string,
  params: { knowledgeBaseId?: number; limit?: number } = {},
): Promise<KnowledgeSearchResult[]> {
  const search = new URLSearchParams();
  search.set("q", query);
  if (params.knowledgeBaseId) {
    search.set("knowledge_base_id", String(params.knowledgeBaseId));
  }
  if (params.limit) {
    search.set("limit", String(params.limit));
  }
  const response = await apiFetch(`${API_URL}/api/knowledge-search?${search.toString()}`, {
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function recommendScript(payload: ScriptRecommendPayload): Promise<ScriptRecommendResponse> {
  const response = await apiFetch(`${API_URL}/api/scripts/recommend`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export { API_URL };
