import type { InfluencerListFilters, OutreachCampaignCreatePayload } from "./api.ts";

export const INFLUENCER_ONE_CLICK_EMAIL_BUTTON_LABEL = "AI一键发邮件";

export type InfluencerSelectionMode = "none" | "page" | "filter_all";

export function resolveBulkOutreachSelection(input: {
  mode: InfluencerSelectionMode;
  selectedIds: number[];
  total: number;
  filters: Omit<InfluencerListFilters, "page" | "pageSize">;
}): {
  count: number;
  selectAll: boolean;
  ids?: number[];
  filters?: Omit<InfluencerListFilters, "page" | "pageSize">;
} {
  if (input.mode === "filter_all") {
    return {
      count: input.total,
      selectAll: true,
      filters: input.filters,
    };
  }
  return {
    count: input.selectedIds.length,
    selectAll: false,
    ids: input.selectedIds,
  };
}

export function resolveBulkDeleteSelection(
  selectedIds: number[],
  mode: InfluencerSelectionMode,
): number[] {
  if (mode === "filter_all") {
    return Array.from(new Set(selectedIds));
  }
  return Array.from(new Set(selectedIds));
}

export function encodeFiltersForCampaign(
  filters: Omit<InfluencerListFilters, "page" | "pageSize">,
): Record<string, string | number | boolean> {
  const out: Record<string, string | number | boolean> = {};
  if (filters.platform) out.platform = filters.platform;
  if (filters.category) out.category = filters.category;
  if (filters.niche) out.niche = filters.niche;
  if (filters.tag) out.tag = filters.tag;
  if (filters.sourceDiscoveryType) out.source_discovery_type = filters.sourceDiscoveryType;
  if (filters.hasEmail) out.has_email = true;
  if (filters.highValue) out.high_value = true;
  if (filters.valueTier) out.value_tier = filters.valueTier;
  if (filters.emailStatus) out.email_status = filters.emailStatus;
  if (filters.leadStatus) out.lead_status = filters.leadStatus;
  if (filters.search) out.search = filters.search;
  if (filters.collectionTaskId) out.collection_task_id = filters.collectionTaskId;
  if (filters.createdWithinHours) out.created_within_hours = filters.createdWithinHours;
  if (filters.collectedWithinDays) out.collected_within_days = filters.collectedWithinDays;
  if (filters.excludeTerminalStatuses) out.exclude_terminal_statuses = true;
  return out;
}

export function decodeFiltersFromSearchParams(
  params: URLSearchParams,
): Omit<InfluencerListFilters, "page" | "pageSize"> | null {
  if (params.get("select_all") !== "1") return null;
  const filters: Omit<InfluencerListFilters, "page" | "pageSize"> = {};
  const platform = params.get("platform");
  if (platform) filters.platform = platform;
  const category = params.get("category");
  if (category) filters.category = category;
  const niche = params.get("niche");
  if (niche) filters.niche = niche;
  const tag = params.get("tag");
  if (tag) filters.tag = tag;
  const source = params.get("source_discovery_type");
  if (source) filters.sourceDiscoveryType = source;
  if (params.get("has_email") === "true") filters.hasEmail = true;
  if (params.get("high_value") === "true") filters.highValue = true;
  const valueTier = params.get("value_tier");
  if (valueTier === "direct_contact" || valueTier === "manual_research" || valueTier === "skip") {
    filters.valueTier = valueTier;
  }
  const emailStatus = params.get("email_status");
  if (emailStatus === "sent" || emailStatus === "unsent") filters.emailStatus = emailStatus;
  const search = params.get("search");
  if (search) filters.search = search;
  if (params.get("exclude_terminal_statuses") === "true") filters.excludeTerminalStatuses = true;
  const taskId = params.get("collection_task_id");
  if (taskId) filters.collectionTaskId = Number(taskId);
  return filters;
}

export function buildOutreachCampaignsUrl(options: {
  ids?: number[];
  selectAll?: boolean;
  filters?: Omit<InfluencerListFilters, "page" | "pageSize">;
  total?: number;
}): string {
  const params = new URLSearchParams();
  if (options.selectAll && options.filters) {
    params.set("select_all", "1");
    if (options.total != null) params.set("total", String(options.total));
    const encoded = encodeFiltersForCampaign(options.filters);
    for (const [key, value] of Object.entries(encoded)) {
      params.set(key, String(value));
    }
  } else if (options.ids?.length) {
    params.set("ids", options.ids.join(","));
  }
  const qs = params.toString();
  return qs ? `/outreach-campaigns?${qs}` : "/outreach-campaigns";
}

export function buildOutreachCampaignResultUrl(options: {
  campaignId: number;
  message: string;
  ids?: number[];
  selectAll?: boolean;
  filters?: Omit<InfluencerListFilters, "page" | "pageSize">;
  total?: number;
}): string {
  const params = new URLSearchParams();
  params.set("highlight", String(options.campaignId));
  params.set("message", options.message);
  if (options.selectAll && options.filters) {
    params.set("select_all", "1");
    if (options.total != null) params.set("total", String(options.total));
    const encoded = encodeFiltersForCampaign(options.filters);
    for (const [key, value] of Object.entries(encoded)) {
      params.set(key, String(value));
    }
  } else if (options.ids?.length) {
    params.set("ids", options.ids.join(","));
  }
  return `/outreach-campaigns?${params.toString()}`;
}

export function buildOneClickCampaignName(now = new Date()): string {
  return `一键批量发送 ${now.toLocaleDateString("zh-CN")}`;
}

export function buildOneClickCampaignPayload(options: {
  name: string;
  ids?: number[];
  selectAll?: boolean;
  filters?: Omit<InfluencerListFilters, "page" | "pageSize">;
}): OutreachCampaignCreatePayload {
  const payload: OutreachCampaignCreatePayload = {
    name: options.name,
    daily_limit: 1000,
    send_window_start: "00:00",
    send_window_end: "23:59",
    timezone: "Asia/Shanghai",
    skip_sent: false,
    skip_replied: true,
    skip_blacklisted: true,
    skip_invalid: true,
    allow_resend: true,
    auto_send_enabled: false,
  };
  if (options.selectAll && options.filters) {
    payload.select_all_by_filters = true;
    payload.influencer_filters = encodeFiltersForCampaign(options.filters);
  } else if (options.ids?.length) {
    payload.influencer_ids = options.ids;
  }
  return payload;
}

export const CAMPAIGN_CANCEL_CONFIRM_MESSAGE =
  "确认取消该活动？未发送的队列项将被取消，已发送记录与邮件日志不会删除。";

export const CAMPAIGN_AUTO_SEND_HINT =
  "每天到点自动处理已入队邮件，仍受每日上限和发送时间窗口限制；逐封发送，不会话术库群发。";
