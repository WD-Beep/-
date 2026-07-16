export type EmailLogView = "all" | "sent" | "failed" | "replied" | "unreplied";

const EMAIL_LOG_VIEWS = new Set<EmailLogView>(["all", "sent", "failed", "replied", "unreplied"]);

export function parseEmailLogView(value: string | null | undefined): EmailLogView {
  return EMAIL_LOG_VIEWS.has(value as EmailLogView) ? (value as EmailLogView) : "all";
}

export function buildOutreachRecordsUrl(view: EmailLogView): string {
  if (view === "all") return "/outreach-records";
  return `/outreach-records?view=${view}`;
}

export type EmailLogReplySummary = {
  id?: number | null;
  snippet?: string | null;
  body?: string | null;
  received_at?: string | null;
};

export type EmailLogListItem = {
  id: number;
  status: string;
  error_message?: string | null;
  has_replied?: boolean;
  reply?: EmailLogReplySummary | null;
};

export type EmailLogSummary = {
  queued: number;
  sent: number;
  failed: number;
  replied: number;
  unreplied: number;
};

export type OutreachSummaryMetric = {
  key: Exclude<EmailLogView, "all">;
  label: string;
  count: number;
  active: boolean;
};

export function buildEmailLogSummary(logs: EmailLogListItem[], queuedCount: number): EmailLogSummary {
  const sent = logs.filter((log) => log.status === "sent").length;
  const failed = logs.filter((log) => log.status === "failed").length;
  const replied = logs.filter((log) => Boolean(log.reply) || Boolean(log.has_replied)).length;
  return {
    queued: queuedCount,
    sent,
    failed,
    replied,
    unreplied: Math.max(sent - replied, 0),
  };
}

export function filterEmailLogsByView(logs: EmailLogListItem[], view: EmailLogView): EmailLogListItem[] {
  if (view === "sent") return logs.filter((log) => log.status === "sent");
  if (view === "failed") return logs.filter((log) => log.status === "failed");
  if (view === "replied") return logs.filter((log) => Boolean(log.reply) || Boolean(log.has_replied));
  if (view === "unreplied") {
    return logs.filter((log) => log.status === "sent" && !log.reply && !log.has_replied);
  }
  return logs;
}

export function getEmailLogReplyActions(log: EmailLogListItem): {
  canViewReply: boolean;
  canSendResponse: boolean;
} {
  const hasReplyRecord = Boolean(log.reply?.id);
  return {
    canViewReply: hasReplyRecord,
    canSendResponse: hasReplyRecord,
  };
}

export function getEmailLogViewTabs(summary: EmailLogSummary): Array<{
  key: EmailLogView;
  label: string;
  count: number;
}> {
  return [
    { key: "all", label: "全部记录", count: summary.sent + summary.failed },
    { key: "sent", label: "已发送", count: summary.sent },
    { key: "failed", label: "发送失败", count: summary.failed },
    { key: "replied", label: "已回复", count: summary.replied },
    { key: "unreplied", label: "未回复", count: summary.unreplied },
  ];
}

export function getOutreachSummaryMetrics(
  summary: EmailLogSummary,
  activeView: EmailLogView,
): OutreachSummaryMetric[] {
  return [
    { key: "sent", label: "已发送", count: summary.sent, active: activeView === "sent" },
    { key: "failed", label: "失败", count: summary.failed, active: activeView === "failed" },
    { key: "replied", label: "已回复", count: summary.replied, active: activeView === "replied" },
    { key: "unreplied", label: "未回复", count: summary.unreplied, active: activeView === "unreplied" },
  ];
}

export function translateEmailFailureReason(message: string | null | undefined): string {
  if (!message) return "-";
  if (message === "Recipient already replied; follow-up skipped") {
    return "红人已回复，已跳过跟进";
  }
  if (/smtp rejected/i.test(message)) {
    return "邮件服务器拒绝发送，邮件没有发出去。请检查收件邮箱、发件邮箱权限或发送频率限制。";
  }
  if (/收件人|recipient|email_recipients/i.test(message)) {
    return "收件人未配置，邮件没有发出去。请先为该任务或外联记录设置有效收件人。";
  }
  if (/not configured|未配置/i.test(message)) {
    return "发件邮箱未配置，邮件没有发出去。请先到系统设置完成 SMTP 配置。";
  }
  if (/auth|authentication|535|认证失败/i.test(message)) {
    return "SMTP 认证失败，邮件没有发出去。请检查企业邮箱客户端专用密码。";
  }
  return message;
}
