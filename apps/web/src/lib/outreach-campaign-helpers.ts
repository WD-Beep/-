import type { ManualOutreachEmailPayload, ManualOutreachSendMode, MatchedKnowledgeItem, OutreachScheduleRequest } from "./api.ts";

export const TEMPLATE_VARIABLE_HINTS = [
  "{name}",
  "{username}",
  "{platform}",
  "{category}",
  "{brand}",
  "{product}",
  "{knowledge_point}",
  "{cta}",
] as const;

export type InfluencerFilterPayload = Record<string, string | number | boolean | undefined>;

export function buildOutreachCampaignPayload(input: {
  name: string;
  influencerIds?: number[];
  selectAllByFilters?: boolean;
  influencerFilters?: InfluencerFilterPayload;
  knowledgeBaseId?: number | null;
  messageTemplateId?: number | null;
  dailyLimit?: number;
  sendWindowStart?: string;
  sendWindowEnd?: string;
  skipSent?: boolean;
  skipReplied?: boolean;
  skipBlacklisted?: boolean;
  skipInvalid?: boolean;
  allowResend?: boolean;
  autoSendEnabled?: boolean;
  autoSendTime?: string | null;
  autoSendTimezone?: string;
}) {
  const payload: Record<string, unknown> = {
    name: input.name,
    knowledge_base_id: input.knowledgeBaseId ?? undefined,
    message_template_id: input.messageTemplateId ?? undefined,
    daily_limit: input.dailyLimit ?? 50,
    send_window_start: input.sendWindowStart ?? "10:00",
    send_window_end: input.sendWindowEnd ?? "18:00",
    timezone: "Asia/Shanghai",
    skip_sent: input.skipSent ?? true,
    skip_replied: input.skipReplied ?? true,
    skip_blacklisted: input.skipBlacklisted ?? true,
    skip_invalid: input.skipInvalid ?? true,
    allow_resend: input.allowResend ?? false,
    auto_send_enabled: input.autoSendEnabled ?? false,
    auto_send_timezone: input.autoSendTimezone ?? "Asia/Shanghai",
  };
  if (input.autoSendEnabled && input.autoSendTime) {
    payload.auto_send_time = input.autoSendTime;
  }
  if (input.selectAllByFilters && input.influencerFilters) {
    payload.select_all_by_filters = true;
    payload.influencer_filters = input.influencerFilters;
  } else if (input.influencerIds?.length) {
    payload.influencer_ids = input.influencerIds;
  }
  return payload;
}

export function buildScheduledOutreachQueuePayload(input: {
  campaignId: number;
  preview: {
    items: Array<{
      influencer_id: number;
      recipient: string | null;
      subject: string | null;
      body: string | null;
      can_queue: boolean;
      draft_status?: string;
      matched_knowledge?: MatchedKnowledgeItem[];
      reason?: string | null;
    }>;
  };
  startAt: Date;
  intervalMinutes: number;
  dailyLimit: number;
  hourlyLimit?: number;
  sendWindowStart?: string;
  sendWindowEnd?: string;
  allowResend?: boolean;
}): OutreachScheduleRequest {
  return {
    campaign_id: input.campaignId,
    items: input.preview.items
      .filter((item) => item.can_queue && item.recipient && item.subject && item.body)
      .map((item) => ({
        product_influencer_id: item.influencer_id,
        recipient: item.recipient as string,
        subject: item.subject as string,
        body: item.body as string,
        matched_knowledge: item.matched_knowledge ?? [],
        ai_reason: item.reason ?? undefined,
        allow_resend: input.allowResend ?? false,
        priority: 0,
        dedupe_key: `campaign:${input.campaignId}:influencer:${item.influencer_id}`,
        max_retries: 3,
      })),
    schedule_config: {
      start_at: input.startAt.toISOString(),
      timezone: "Asia/Shanghai",
      send_window_start: input.sendWindowStart ?? "09:00",
      send_window_end: input.sendWindowEnd ?? "18:00",
      interval_minutes: Math.max(1, Math.floor(input.intervalMinutes || 1)),
      daily_limit: Math.max(1, Math.floor(input.dailyLimit || 50)),
      hourly_limit: Math.max(1, Math.floor(input.hourlyLimit || 20)),
      weekdays_only: false,
    },
  };
}

const MANUAL_OUTREACH_EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function parseManualOutreachRecipients(text: string): {
  valid: string[];
  invalid: string[];
  overLimit: boolean;
} {
  const seen = new Set<string>();
  const valid: string[] = [];
  const invalid: string[] = [];
  const parts = text
    .split(/[\s,;，；]+/)
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean);

  for (const item of parts) {
    if (!MANUAL_OUTREACH_EMAIL_PATTERN.test(item)) {
      invalid.push(item);
      continue;
    }
    if (seen.has(item)) continue;
    seen.add(item);
    if (valid.length < 10) {
      valid.push(item);
    }
  }

  return {
    valid,
    invalid,
    overLimit: seen.size > 10,
  };
}

export function buildManualOutreachPayload(input: {
  recipientsText: string;
  subject: string;
  body: string;
  sendMode: ManualOutreachSendMode;
  scheduledAt?: Date | null;
}): ManualOutreachEmailPayload {
  const parsed = parseManualOutreachRecipients(input.recipientsText);
  const payload: ManualOutreachEmailPayload = {
    recipients: parsed.valid,
    subject: input.subject.trim(),
    body: input.body.trim(),
    send_mode: input.sendMode,
  };
  if (input.sendMode === "scheduled" && input.scheduledAt) {
    payload.scheduled_at = input.scheduledAt.toISOString();
  }
  return payload;
}

export function buildManualOutreachConfirmMessage(count: number, mode: ManualOutreachSendMode): string {
  if (mode === "scheduled") {
    return `本次将定时发送 ${count} 封自定义测试邮件。到时间后会自动发送，确认入队？`;
  }
  return `本次将立即发送 ${count} 封自定义测试邮件。确认发送？`;
}

export type CampaignSendMode = "now" | "scheduled" | "smart";
export type OneClickSendMode = "now" | "scheduled";
export type OneClickContentSource = "manual" | "template" | "ai";
export type OneClickQueueStatus = "not_queued" | "ready_to_send" | "waiting" | "sending" | "completed" | "failed";
export type OneClickPrimaryActionKind = "preview" | "send" | "queue" | "progress" | "retry";

export const OUTREACH_DRAFT_STATUS_LABELS: Record<string, string> = {
  pending_review: "已生成",
  modified: "已修改",
  approved: "已批准",
  skipped: "已跳过",
  queued: "已入队",
  sent: "已发送",
  failed: "发送失败",
};

export function getOutreachDraftStatusLabel(status: string | null | undefined): string {
  if (!status) return OUTREACH_DRAFT_STATUS_LABELS.pending_review;
  return OUTREACH_DRAFT_STATUS_LABELS[status] ?? status;
}

export function canApproveOutreachDraft(item: {
  can_queue: boolean;
  draft_status?: string | null;
  is_high_value?: boolean;
  opened_at?: string | null;
  subject?: string | null;
  body?: string | null;
}): boolean {
  if (!item.can_queue) return false;
  if (!item.subject?.trim() || !item.body?.trim()) return false;
  if (item.draft_status === "approved" || item.draft_status === "queued" || item.draft_status === "sent") return false;
  if (item.is_high_value && !item.opened_at) return false;
  return true;
}

export function countApprovedOutreachDrafts(
  items: Array<{ draft_status?: string | null; can_queue?: boolean }>,
): number {
  return items.filter((item) => item.draft_status === "approved" && item.can_queue !== false).length;
}

export function buildApprovedDraftSendConfirmMessage(count: number): string {
  return `本次将发送 ${count} 封 AI 生成邮件。确认后邮件会进入发送队列，并按发送间隔、每日上限和发送时间窗口执行。`;
}

export type OneClickQueueCampaignInput = {
  status: string;
  total_count: number;
  can_queue_count?: number;
  queued_count: number;
  sent_count: number;
  failed_count: number;
  skipped_count?: number;
  previewed_at: string | null;
};

export function deriveOneClickQueueStatusFromCampaign(
  campaign: OneClickQueueCampaignInput | null | undefined,
): OneClickQueueStatus {
  if (!campaign || !campaign.previewed_at) return "not_queued";
  if (campaign.status === "failed" || campaign.status === "cancelled") return "failed";

  const queued = campaign.queued_count ?? 0;
  const sent = campaign.sent_count ?? 0;
  const failed = campaign.failed_count ?? 0;
  const skipped = campaign.skipped_count ?? 0;
  const total = campaign.total_count ?? 0;
  const canQueue = campaign.can_queue_count ?? 0;

  if (queued > 0 && sent + failed >= queued) {
    return sent > 0 || failed === 0 ? "completed" : "failed";
  }
  if (queued > 0) {
    return campaign.status === "running" ? "sending" : "waiting";
  }
  if (total > 0 && canQueue === 0 && skipped >= total) return "completed";
  return "not_queued";
}

export function buildLocalDateTime(date: string, time: string): Date | null {
  const normalizedDate = date.trim();
  const normalizedTime = time.trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(normalizedDate) || !/^\d{2}:\d{2}$/.test(normalizedTime)) {
    return null;
  }
  const value = new Date(`${normalizedDate}T${normalizedTime}:00`);
  return Number.isNaN(value.getTime()) ? null : value;
}

export function formatDurationMinutes(totalMinutes: number): string {
  const minutes = Math.max(0, Math.round(totalMinutes));
  if (minutes < 60) return `${minutes} 分钟`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest > 0 ? `${hours} 小时 ${rest} 分钟` : `${hours} 小时`;
}

export function getOneClickQueueStatusLabel(status: OneClickQueueStatus): string {
  const labels: Record<OneClickQueueStatus, string> = {
    not_queued: "未发送",
    ready_to_send: "待确认发送",
    waiting: "已定时",
    sending: "正在发送",
    completed: "已完成",
    failed: "失败",
  };
  return labels[status];
}

export function getOneClickCurrentStatusLabel(input: {
  busyAction: "preview" | "send" | "queue" | "save" | null;
  copyMode: OneClickContentSource;
  hasPreview: boolean;
  queueStatus: OneClickQueueStatus;
  preview?: { total: number; can_queue_count: number; skip_count: number } | null;
}): string {
  if (input.busyAction === "preview") return "生成中";
  if (input.busyAction === "send") return "发送中";
  if (input.busyAction === "queue") return "创建定时中";
  if (
    input.preview &&
    input.preview.total > 0 &&
    input.preview.can_queue_count === 0 &&
    input.preview.skip_count >= input.preview.total
  ) {
    return "本批无可发送";
  }
  if (input.copyMode === "ai" && input.hasPreview && input.queueStatus === "ready_to_send") {
    return "待确认";
  }
  return getOneClickQueueStatusLabel(input.queueStatus);
}

export function getOneClickContentSourceLabel(source: OneClickContentSource): string {
  const labels: Record<OneClickContentSource, string> = {
    manual: "自己填写",
    template: "话术库",
    ai: "AI生成",
  };
  return labels[source];
}

export function getOneClickWorkbenchPrimaryAction(input: {
  hasPreview: boolean;
  sendMode: OneClickSendMode;
  queueStatus: OneClickQueueStatus;
}): { action: OneClickPrimaryActionKind; label: string } {
  if (input.queueStatus === "failed") {
    return { action: "retry", label: "查看失败原因 / 重试发送" };
  }
  if (input.queueStatus === "ready_to_send") {
    return input.sendMode === "now"
      ? { action: "send", label: "确认开始发送" }
      : { action: "queue", label: "确认定时发送" };
  }
  if (input.queueStatus === "waiting" || input.queueStatus === "sending" || input.queueStatus === "completed") {
    return { action: "progress", label: "查看发送进度" };
  }
  if (!input.hasPreview) {
    return { action: "preview", label: "生成话术并预览" };
  }
  if (input.sendMode === "now") {
    return { action: "send", label: "确认开始发送" };
  }
  return { action: "queue", label: "确认定时发送" };
}

export function formatOneClickDateTime(value: Date | string | null | undefined): string {
  if (!value) return "-";
  const date = typeof value === "string" ? new Date(value) : value;
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function buildScheduledQueueSuccessMessage(input: {
  createdCount: number;
  skippedCount: number;
  startAt: Date | string;
}): string {
  const skipped = input.skippedCount > 0 ? `，跳过 ${input.skippedCount} 人` : "";
  return `已设置定时发送：${formatOneClickDateTime(input.startAt)}，共 ${input.createdCount} 封${skipped}。到时间会自动发送，不需要再手动点。`;
}

export function buildScheduledSendCompletionMessage(input: {
  queuedCount: number;
  sentCount: number;
  failedCount: number;
  sendMode?: OneClickSendMode;
}): string | null {
  if (input.sentCount <= 0 && input.failedCount <= 0) return null;
  const prefix = input.sendMode === "now" ? "发送已完成" : "定时发送已完成";
  if (input.failedCount > 0) {
    return `${prefix}，发送成功 ${input.sentCount} 封，失败 ${input.failedCount} 封。请到发送队列查看失败原因。`;
  }
  return `${prefix}，发送成功：已发出 ${input.sentCount} 封邮件。`;
}

export function buildImmediateSendStartedMessage(): string {
  return "正在发送，请留在当前页面查看结果。";
}

export function buildImmediateSendResultMessage(input: {
  sent: number;
  failed: number;
  skipped: number;
  reason?: string | null;
}): string {
  if (input.failed > 0 && input.sent === 0) {
    return input.reason?.trim()
      ? input.reason.trim()
      : "发送失败：当前网络连不上 SMTP 服务器（如 Gmail）。请改用 QQ/企业邮 SMTP，或打通 Gmail 后再发。";
  }
  if (input.failed > 0) {
    return `成功 ${input.sent} 封，失败 ${input.failed} 封。点击查看失败原因。`;
  }
  const skipped = input.skipped > 0 ? `，跳过 ${input.skipped} 人` : "";
  return `已成功发送 ${input.sent} 封邮件${skipped}。`;
}

export function estimateCampaignEndTime(input: {
  recipientCount: number;
  startAt: Date;
  intervalMinutes: number;
}): Date {
  const count = Math.max(0, Math.floor(input.recipientCount));
  const interval = Math.max(1, Math.floor(input.intervalMinutes || 1));
  const elapsed = Math.max(0, count - 1) * interval;
  return new Date(input.startAt.getTime() + elapsed * 60 * 1000);
}

export function resolveOneClickSendLimit(input: {
  configuredValue: string;
  sourceCount: number;
  fallbackCount?: number;
}): number {
  const configured = Number(input.configuredValue);
  if (Number.isFinite(configured) && configured > 0) {
    return Math.floor(configured);
  }
  return Math.max(0, Math.floor(input.sourceCount || input.fallbackCount || 0));
}

export function getOneClickPrimaryDisabledReason(input: {
  recipientCount: number;
  sourceAvailable: boolean;
  smtpReady: boolean;
  smtpStatus?: string | null;
  aiReady: boolean;
  /** 工作台配置尚未拉回时不要报「未配置」，避免误导业务员 */
  configLoading?: boolean;
  generationMode: "ai" | "template" | "preview";
  action: "preview" | "send" | "queue" | "save";
  scheduledAt?: Date | null;
}): string | null {
  if (input.configLoading) return "正在检查配置，请稍候";
  if (!input.sourceAvailable || input.recipientCount <= 0) return "没有邮件发出。没有可发送对象，请回到红人库选择收件人。";
  if (input.generationMode === "ai" && !input.aiReady) return "AI 模型未配置，暂时无法自动优化话术。";
  if (input.action !== "preview" && !input.smtpReady) {
    if (input.smtpStatus === "error") {
      return "邮件没有发出。原因：SMTP 已配置，但当前网络连不上邮件服务器（如 Gmail）。请改用 QQ/企业邮 SMTP，或打通网络后再发。";
    }
    return "邮件没有发出。原因：SMTP 未配置，请先在设置中配置发件邮箱。";
  }
  if ((input.action === "queue" || input.action === "save") && !input.scheduledAt) return "请先选择发送日期和具体时间";
  return null;
}

export function buildSkipReasonBreakdown(items: Array<{ skip_reason?: string | null }>): {
  sent: number;
  blacklisted: number;
  invalid: number;
  replied: number;
  other: number;
} {
  const result = { sent: 0, blacklisted: 0, invalid: 0, replied: 0, other: 0 };
  for (const item of items) {
    const reason = item.skip_reason || "";
    if (/已发送|成功发信|sent/i.test(reason)) result.sent += 1;
    else if (/黑名单|black/i.test(reason)) result.blacklisted += 1;
    else if (/无效|invalid|格式|域名/i.test(reason)) result.invalid += 1;
    else if (/已回复|replied|interested/i.test(reason)) result.replied += 1;
    else if (reason.trim()) result.other += 1;
  }
  return result;
}

export function buildOneClickCampaignName(now: Date = new Date()): string {
  return `AI 一键发邮件 ${now.toLocaleDateString("zh-CN")}`;
}

export function humanizeOutreachFailureReason(message: string | null | undefined): string {
  const text = (message || "").trim();
  if (!text) return "-";
  if (/insufficient balance|exceeded_current_quota|quota|account suspended|额度|余额不足|充值/i.test(text)) {
    return "AI 账户余额不足或额度受限，请充值 DeepSeek/API 账户或更换可用密钥后重试。";
  }
  if (/AI 生成失败|GPT|标题.*正文.*空|OPENAI|生成.*失败/i.test(text)) {
    return "GPT 没有生成可用标题或正文";
  }
  if (/timed out|timeout|10060|无法连接邮件服务器|smtp\.gmail\.com/i.test(text)) {
    return "连不上邮件服务器（Gmail SMTP 超时）。请改用 QQ/企业邮 SMTP，或打通网络后再发";
  }
  if (/SMTP|535|authentication|auth|认证失败/i.test(text)) {
    return "邮箱授权码或 SMTP 配置不对，邮件没有发出去";
  }
  if (/缺少邮箱|没有可用邮箱/.test(text)) return "该红人没有可用邮箱";
  if (/已.*成功.*发信|已发送过|重复发送|成功发信记录/.test(text)) return "为避免重复骚扰，系统跳过";
  if (/已回复|跟进中|replied|interested/i.test(text)) return "该红人已回复，进入跟进，不重复发送";
  if (/邮箱格式无效|域名|测试邮箱|invalid email|format/i.test(text)) return "邮箱格式或域名不符合规则";
  if (/黑名单/.test(text)) return "该红人在黑名单中，系统跳过";
  if (/无效/.test(text)) return "该红人状态无效，系统跳过";
  if (/发件邮箱相同/.test(text)) return "收件邮箱和发件邮箱相同，系统跳过";
  return text;
}

export function countQueueablePreviewItems(items: { can_queue: boolean }[]): number {
  return items.filter((item) => item.can_queue).length;
}

export function buildPreviewResultMessage(input: {
  total: number;
  canQueueCount: number;
  skipCount: number;
}): string {
  if (input.total === 0) {
    return "生成完成：当前活动没有可生成邮件的红人";
  }
  if (input.skipCount > 0) {
    return `已生成草稿：${input.canQueueCount} 人可入队，${input.skipCount} 人已跳过（详见草稿列表和跳过原因）`;
  }
  return `已生成草稿：${input.canQueueCount} 人可加入发送队列`;
}

export function buildGenerateAndSendResultMessage(input: {
  preview: {
    total: number;
    can_queue_count: number;
    skip_count: number;
    items: Array<{ skip_reason?: string | null } & Record<string, unknown>>;
  } & Record<string, unknown>;
  queued: number;
  sent: number;
  failed: number;
  message: string;
}): string {
  const { preview } = input;
  if (preview.total > 0 && preview.can_queue_count === 0 && preview.skip_count >= preview.total) {
    const summary = buildSkipReasonSummary(preview.items);
    if (
      summary.length === 1 &&
      humanizeOutreachFailureReason(summary[0]?.reason) === "为避免重复骚扰，系统跳过"
    ) {
      return `没有发送新邮件：${preview.total} 人都已发送过，为避免重复骚扰，系统已跳过。`;
    }
    const reasonText = summary
      .slice(0, 3)
      .map((item) => `${humanizeOutreachFailureReason(item.reason)} ${item.count} 人`)
      .join("；");
    return reasonText
      ? `没有发送新邮件：${preview.total} 人被规则跳过。${reasonText}。`
      : `没有发送新邮件：${preview.total} 人都被规则跳过。`;
  }
  if (input.failed > 0) {
    return `已处理：成功发送 ${input.sent} 封，失败 ${input.failed} 封，跳过 ${preview.skip_count} 人。`;
  }
  return input.message;
}

export type CampaignPhaseInput = {
  status: string;
  previewed_at: string | null;
  total_count: number;
  can_queue_count?: number;
  queued_count: number;
  sent_count: number;
  skipped_count?: number;
  auto_send_enabled: boolean;
};

export function isCampaignFullySkipped(campaign: {
  previewed_at: string | null;
  total_count: number;
  can_queue_count?: number;
  queued_count: number;
  sent_count: number;
  skipped_count: number;
}): boolean {
  return Boolean(
    campaign.previewed_at &&
      campaign.total_count > 0 &&
      (campaign.can_queue_count ?? 0) === 0 &&
      campaign.queued_count === 0 &&
      campaign.sent_count === 0 &&
      campaign.skipped_count >= campaign.total_count,
  );
}

export function getCampaignPhaseLabel(campaign: CampaignPhaseInput): string {
  if (campaign.status === "cancelled") return "已取消";
  if (campaign.status === "completed") return "已完成";
  if (!campaign.previewed_at) return "待生成";
  if (isCampaignFullySkipped({ ...campaign, skipped_count: campaign.skipped_count ?? 0 })) {
    return "本批没有发送：全部被规则跳过";
  }
  if (campaign.queued_count === 0) {
    return "已生成草稿：草稿已保存，可查看";
  }
  if (campaign.auto_send_enabled && campaign.status === "running") {
    return `定时发送中：已入队 ${campaign.queued_count} 封`;
  }
  if (campaign.status === "paused") {
    return `已入队 ${campaign.queued_count} 封，活动已暂停`;
  }
  if (campaign.sent_count > 0 && campaign.queued_count > campaign.sent_count) {
    return `已入队 ${campaign.queued_count} 封，已发 ${campaign.sent_count} 封`;
  }
  return `已入队 ${campaign.queued_count} 封，等待发送`;
}

export const CAMPAIGN_STATUS_LABELS: Record<string, string> = {
  draft: "待生成",
  ready: "已准备",
  running: "定时发送中",
  paused: "已暂停",
  completed: "已完成",
  cancelled: "已取消",
};

export const CAMPAIGN_PAGE_DESCRIPTION =
  "从红人库选人后，一键 AI 自动生成每人不同邮件并逐封发送。";

export const CAMPAIGN_LIST_FLOW_HINT =
  "点击一键 AI 批量发送后，系统会自动筛选有邮箱且符合规则的红人，生成专属话术并逐封发送。";

export const CAMPAIGN_LIST_FLOW_STEPS = [
  "选择红人：可批量选择",
  "一键 AI 批量发送：自动生成专属邮件",
  "记录结果：成功、失败、跳过原因都可查看",
  "接收回复：红人回复后记录到活动、邮件日志和红人详情",
] as const;

export const CAMPAIGN_OPERATOR_GUIDE = [
  {
    title: "怎么批量发",
    description: "从红人库选人后，点击一键 AI 批量发送，系统会自动生成每人专属邮件并逐封发送。",
  },
  {
    title: "发出去的是什么",
    description: "不是同一封群发邮件，系统会按红人信息、产品、知识库和话术生成不同标题和正文。",
  },
  {
    title: "怎么看回复",
    description: "点击活动右侧的查看谁回复了，进入回复跟进表，看已回复、未回复、感兴趣和待跟进红人。",
  },
] as const;

export const CAMPAIGN_PREVIEW_BUTTON_LABEL = "生成/查看每人专属邮件";

export const CAMPAIGN_QUEUE_BUTTON_HINT = "生成草稿不会发送；确认入队后仍不会立即发送";

export const CAMPAIGN_PROCESS_BUTTON_HINT = "立即发送今日队列只处理今日符合规则的已入队邮件";

export const CAMPAIGN_AUTO_SEND_BUTTON_HINT = "开启定时自动发送后，系统按规则逐封发送";

export const CAMPAIGN_PROCESS_CONFIRM_MESSAGE =
  "确认一键 AI 批量发送本批次？系统会自动为每位可发送红人生成专属邮件并逐封发送。";

export const CAMPAIGN_QUEUE_CONFIRM_MESSAGE =
  "确认将已生成且通过校验的个性化草稿加入发送队列？加入后不会立即发送。";

export const CAMPAIGN_AUTO_SEND_CONFIRM_MESSAGE =
  "开启定时自动发送后，系统将在设定时间自动处理已入队邮件，按上限逐封发送，不会群发同一封邮件。";

export const CAMPAIGN_CREATE_SUCCESS_MESSAGE =
  "批次已创建，请点击「一键 AI 批量发送」自动生成每位红人的专属邮件并发送";

export type CampaignStatsInput = {
  total_count: number;
  draft_count?: number;
  can_queue_count?: number;
  queued_count: number;
  sent_count: number;
  failed_count: number;
  skipped_count: number;
  reply_count?: number;
  interested_count?: number;
  unreplied_count?: number;
};

export function buildCampaignStatsLine(campaign: CampaignStatsInput): string {
  return [
    `总 ${campaign.total_count}`,
    `草稿 ${campaign.draft_count ?? 0}`,
    `可入队 ${campaign.can_queue_count ?? 0}`,
    `队列 ${campaign.queued_count}`,
    `已发 ${campaign.sent_count}`,
    `失败 ${campaign.failed_count}`,
    `回复 ${campaign.reply_count ?? 0}`,
    `感兴趣 ${campaign.interested_count ?? 0}`,
    `未回复 ${campaign.unreplied_count ?? 0}`,
    `跳过 ${campaign.skipped_count}`,
  ].join(" | ");
}

export function buildCampaignBusinessSummary(campaign: CampaignStatsInput): string[] {
  const total = campaign.total_count;
  const canSend = campaign.can_queue_count ?? 0;
  const skipped = campaign.skipped_count;
  const sent = campaign.sent_count;
  const replied = campaign.reply_count ?? 0;
  const interested = campaign.interested_count ?? 0;
  const unreplied = campaign.unreplied_count ?? 0;
  return [
    `本批次 ${total} 位红人`,
    `${canSend} 封可发送 · ${skipped} 人跳过 · ${sent} 封已发送`,
    `${replied} 人已回复 · ${interested} 人感兴趣 · ${unreplied} 人待跟进`,
  ];
}

export type CampaignPrimaryActionInput = {
  status: string;
  previewed_at: string | null;
  total_count?: number;
  can_queue_count?: number;
  queued_count: number;
  sent_count: number;
  skipped_count?: number;
  reply_count?: number;
};

export type CampaignPrimaryAction = {
  kind: "preview" | "queue" | "send" | "replies";
  label: string;
  hint: string;
};

export function getCampaignPrimaryAction(campaign: CampaignPrimaryActionInput): CampaignPrimaryAction {
  if (
    isCampaignFullySkipped({
      previewed_at: campaign.previewed_at,
      total_count: campaign.total_count ?? 0,
      can_queue_count: campaign.can_queue_count ?? 0,
      queued_count: campaign.queued_count,
      sent_count: campaign.sent_count,
      skipped_count: campaign.skipped_count ?? 0,
    })
  ) {
    return {
      kind: "preview",
      label: "查看为什么没发送",
      hint: `本批没有可发送红人，${campaign.skipped_count ?? 0} 人都被规则跳过。点击查看每个人的跳过原因。`,
    };
  }
  if ((campaign.reply_count ?? 0) > 0) {
    return {
      kind: "replies",
      label: "查看谁回复了",
      hint: "查看谁已回复、谁感兴趣、谁需要继续跟进",
    };
  }
  if (!campaign.previewed_at) {
    return {
      kind: "send",
      label: "一键 AI 批量发送",
      hint: "系统会自动生成每人专属邮件，并逐封发送给可发送红人",
    };
  }
  if (campaign.queued_count === 0) {
    return {
      kind: "send",
      label: "一键 AI 批量发送",
      hint: "系统会自动生成每人专属邮件，并逐封发送给可发送红人",
    };
  }
  if (campaign.sent_count < campaign.queued_count) {
    return {
      kind: "send",
      label: "一键 AI 批量发送",
      hint: "系统会自动生成每人专属邮件，并逐封发送给可发送红人",
    };
  }
  return {
    kind: "replies",
    label: "查看谁回复了",
    hint: "查看已回复和未回复红人，安排下一步跟进",
  };
}

export function buildSkipReasonSummary(
  items: Array<{ skip_reason?: string | null }>,
): Array<{ reason: string; count: number }> {
  const counts = new Map<string, number>();
  for (const item of items) {
    const reason = item.skip_reason?.trim();
    if (!reason) continue;
    counts.set(reason, (counts.get(reason) ?? 0) + 1);
  }
  return [...counts.entries()].map(([reason, count]) => ({ reason, count }));
}

export function getReplyStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    unreplied: "未回复",
    replied: "已回复",
    interested: "感兴趣",
    not_interested: "暂无意向",
    needs_review: "需人工判断",
    skipped: "已跳过",
  };
  return labels[status] ?? status;
}

export function hasRealEmailReplyEvidence(reply: {
  reply_time?: string | null;
  reply_snippet?: string | null;
  reply_body?: string | null;
}): boolean {
  return Boolean(
    reply.reply_time ||
      reply.reply_snippet?.trim() ||
      reply.reply_body?.trim(),
  );
}

export function hasRealSendResultEvidence(result: {
  status?: string | null;
  sent_at?: string | null;
  subject?: string | null;
  reason?: string | null;
}): boolean {
  if (result.status === "sent" || result.status === "failed" || result.status === "pending") {
    return true;
  }
  return Boolean(result.sent_at || result.subject?.trim() || result.reason?.trim());
}
