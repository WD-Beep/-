import { ensureTenantProductId, tenantHeaders } from "./product-context.ts";
import { collectionTaskSeedDiscoveryDiagnosticHint } from "./shopping-seed-diagnostics.ts";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "/api-proxy";
const SERVER_API_URL =
  process.env.INTERNAL_API_URL?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";

const API_FETCH_TIMEOUT_MS = 30_000;

async function apiFetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  await ensureTenantProductId();
  const headers = new Headers(init.headers ?? {});
  for (const [key, value] of Object.entries(tenantHeaders())) {
    headers.set(key, value);
  }
  const timeoutSignal =
    typeof AbortSignal !== "undefined" && "timeout" in AbortSignal
      ? AbortSignal.timeout(API_FETCH_TIMEOUT_MS)
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
  created_at: string;
  updated_at: string;
};

export type CollectionTaskPayload = {
  name: string;
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
};

export type SmtpStatus = {
  configured: boolean;
  host: string | null;
  port: number | null;
  user_address: string | null;
  from_address: string | null;
  from_user_mismatch: boolean;
  warning: string | null;
  use_tls: boolean;
  message: string;
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

async function parseError(response: Response): Promise<string> {
  try {
    const text = await response.text();
    if (!text.trim()) {
      return `Request failed: ${response.status}`;
    }
    try {
      const data = JSON.parse(text) as { detail?: string | Array<{ msg?: string }> };
      if (typeof data.detail === "string") return data.detail;
      if (Array.isArray(data.detail)) {
        return data.detail.map((item: { msg?: string }) => item.msg ?? JSON.stringify(item)).join("；");
      }
    } catch {
      if (response.status >= 500 && /Internal Server Error/i.test(text)) {
        return "后端 API 当前不可用，请确认本地 8000 端口服务已启动。";
      }
      return text;
    }
    return `Request failed: ${response.status}`;
  } catch {
    return `Request failed: ${response.status}`;
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
    task_view?: TaskListView;
    search?: string;
    status?: CollectionTaskStatus;
    platform?: string;
  },
): Promise<PaginatedResponse<CollectionTask>> {
  const query = buildCollectionTasksQueryString(page, pageSize, options);
  const response = await apiFetch(`${API_URL}/api/collection-tasks?${query}`, {
    cache: "no-store",
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

export function buildCollectionTasksQueryString(
  page = 1,
  pageSize = 50,
  options?: {
    effectiveness?: "high_value" | "effective" | "ineffective" | "low_value_result" | "no_result" | "failed";
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

export async function fetchLinkImportBatches(
  page = 1,
  pageSize = 20,
): Promise<PaginatedResponse<LinkImportBatch>> {
  const response = await apiFetch(
    `${API_URL}/api/link-import/batches?page=${page}&page_size=${pageSize}`,
    { cache: "no-store" },
  );
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function createLinkImportBatch(
  payload: LinkImportBatchPayload,
): Promise<LinkImportBatch> {
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

export async function fetchKnowledgeBases(): Promise<KnowledgeBase[]> {
  const response = await apiFetch(`${API_URL}/api/knowledge-bases`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(await parseError(response));
  }
  return response.json();
}

export async function createKnowledgeBase(payload: {
  name: string;
  description?: string | null;
}): Promise<KnowledgeBase> {
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
