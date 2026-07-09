import type { AdminSummary } from "@/lib/api";

export type AdminTone = "success" | "warning" | "danger" | "info" | "muted" | "neutral";

export type StatusMeta = {
  label: string;
  tone: AdminTone;
};

export type AdminFilterState = {
  search?: string;
  owner?: string;
  brand?: string;
  status?: string;
  platform?: string;
  startDate?: string;
  endDate?: string;
};

export type AdminFilterableRow = {
  name?: string | null;
  brand?: string | null;
  owner?: string | null;
  status?: string | null;
  platform?: string | null;
  createdAt?: string | null;
  email?: string | null;
  subject?: string | null;
  recipient?: string | null;
};

const numberFormat = new Intl.NumberFormat("zh-CN");
const dateTimeFormat = new Intl.DateTimeFormat("zh-CN", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

const collectionTaskStatuses: Record<string, StatusMeta> = {
  queued: { label: "排队中", tone: "muted" },
  pending: { label: "排队中", tone: "muted" },
  processing: { label: "采集中", tone: "info" },
  running: { label: "采集中", tone: "info" },
  collecting: { label: "采集中", tone: "info" },
  completed: { label: "已完成", tone: "success" },
  completed_with_results: { label: "有结果", tone: "success" },
  completed_without_results: { label: "无结果", tone: "warning" },
  success: { label: "已完成", tone: "success" },
  failed: { label: "失败", tone: "danger" },
  error: { label: "失败", tone: "danger" },
  cancelled: { label: "已取消", tone: "muted" },
  canceled: { label: "已取消", tone: "muted" },
};

const productStatuses: Record<string, StatusMeta> = {
  active: { label: "启用", tone: "success" },
  collecting: { label: "采集中", tone: "info" },
  pending_outreach: { label: "待发信", tone: "warning" },
  replied: { label: "已有回复", tone: "success" },
  exception: { label: "异常", tone: "danger" },
  hidden: { label: "暂停", tone: "muted" },
  inactive: { label: "暂停", tone: "muted" },
  archived: { label: "已归档", tone: "muted" },
};

const emailStatuses: Record<string, StatusMeta> = {
  sent: { label: "已发送", tone: "success" },
  success: { label: "已发送", tone: "success" },
  failed: { label: "发送失败", tone: "danger" },
  error: { label: "发送失败", tone: "danger" },
  replied: { label: "已回复", tone: "success" },
  pending: { label: "待跟进", tone: "warning" },
  queued: { label: "待发送", tone: "muted" },
  handled: { label: "已处理", tone: "success" },
  processed: { label: "已处理", tone: "success" },
  no_action: { label: "无需处理", tone: "muted" },
  ignored: { label: "无需处理", tone: "muted" },
  new: { label: "待跟进", tone: "warning" },
  unread: { label: "待跟进", tone: "warning" },
  read: { label: "已查看", tone: "info" },
};

const influencerStatuses: Record<string, StatusMeta> = {
  contacted: { label: "已联系", tone: "info" },
  replied: { label: "已回复", tone: "success" },
  pending: { label: "待联系", tone: "warning" },
  invalid: { label: "无效", tone: "danger" },
  blacklisted: { label: "黑名单", tone: "danger" },
  new: { label: "未联系", tone: "muted" },
};

export function formatAdminNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "暂无";
  return numberFormat.format(value);
}

export function formatAdminDate(value: string | null | undefined): string {
  if (!value) return "暂无";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "暂无";
  return dateTimeFormat.format(date);
}

export function formatAdminPercent(numerator: number, denominator: number): string {
  if (!denominator) return "暂无";
  return `${Math.round((numerator / denominator) * 100)}%`;
}

export function getCollectionTaskStatusMeta(status: string | null | undefined): StatusMeta {
  return getStatusMeta(status, collectionTaskStatuses);
}

export function getProductStatusMeta(status: string | null | undefined): StatusMeta {
  return getStatusMeta(status, productStatuses);
}

export function getEmailStatusMeta(status: string | null | undefined): StatusMeta {
  return getStatusMeta(status, emailStatuses);
}

export function getInfluencerStatusMeta(status: string | null | undefined): StatusMeta {
  return getStatusMeta(status, influencerStatuses);
}

export function getRoleLabel(role: string | null | undefined): string {
  if (role === "admin") return "管理员";
  if (role === "sales") return "业务员";
  if (!role) return "暂无";
  return role;
}

export function getPlatformLabel(platform: string | null | undefined): string {
  if (!platform) return "暂无";
  const labels: Record<string, string> = {
    instagram: "Instagram",
    youtube: "YouTube",
    tiktok: "TikTok",
    facebook: "Facebook",
    amazon: "Amazon",
  };
  return labels[platform.toLowerCase()] ?? platform;
}

export function filterAdminRows<T extends AdminFilterableRow>(rows: T[], filters: AdminFilterState): T[] {
  return rows.filter((row) => {
    const haystack = [
      row.name,
      row.brand,
      row.owner,
      row.status,
      row.platform,
      row.email,
      row.subject,
      row.recipient,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    const search = filters.search?.trim().toLowerCase();
    if (search && !haystack.includes(search)) return false;
    if (filters.owner && !contains(row.owner, filters.owner)) return false;
    if (filters.brand && !contains(row.brand, filters.brand)) return false;
    if (filters.status && !equals(row.status, filters.status)) return false;
    if (filters.platform && !equals(row.platform, filters.platform)) return false;
    if (filters.startDate && !isAfterOrSameDay(row.createdAt, filters.startDate)) return false;
    if (filters.endDate && !isBeforeOrSameDay(row.createdAt, filters.endDate)) return false;
    return true;
  });
}

export function buildAdminDashboardView(summary: AdminSummary) {
  const successfulTasks = Math.max(summary.total_collection_tasks - summary.failed_collection_tasks, 0);
  const successRateLabel = formatAdminPercent(successfulTasks, summary.total_collection_tasks);
  const pendingExceptionCount = summary.failed_collection_tasks + summary.failed_email_logs + summary.pending_replies;

  return {
    successRateLabel,
    pendingExceptionCount,
    kpis: [
      { label: "总品牌数", value: summary.total_products, helper: "全部可见品牌" },
      { label: "总业务员数", value: summary.total_sales, helper: "正在参与运营" },
      { label: "今日采集任务", value: summary.today_collection_tasks, helper: "今日创建或执行" },
      { label: "采集成功率", value: successRateLabel, helper: "按失败任务推算" },
      { label: "红人总数", value: summary.total_influencers, helper: "已入库资料" },
      { label: "今日邮件发送数", value: summary.today_email_logs, helper: "外联触达" },
      { label: "邮件回复数", value: summary.total_replies, helper: "累计回复" },
      { label: "待处理异常数", value: pendingExceptionCount, helper: "任务、邮件和回复" },
    ],
    replyTrend: [
      { label: "累计回复", value: summary.total_replies },
      { label: "今日回复", value: summary.today_replies },
      { label: "待处理", value: summary.pending_replies },
    ],
  };
}

export function getEmailValidityLabel(email: string | null | undefined): StatusMeta {
  if (!email) return { label: "无邮箱", tone: "warning" };
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return { label: "疑似无效", tone: "danger" };
  return { label: "有效", tone: "success" };
}

export function getReplyStateLabel(hasReplied: boolean | null | undefined): StatusMeta {
  return hasReplied ? { label: "已回复", tone: "success" } : { label: "未回复", tone: "muted" };
}

function getStatusMeta(status: string | null | undefined, map: Record<string, StatusMeta>): StatusMeta {
  if (!status) return { label: "暂无", tone: "muted" };
  return map[status] ?? { label: status, tone: "neutral" };
}

function contains(value: string | null | undefined, filter: string): boolean {
  return (value ?? "").toLowerCase().includes(filter.toLowerCase());
}

function equals(value: string | null | undefined, filter: string): boolean {
  return (value ?? "").toLowerCase() === filter.toLowerCase();
}

function isAfterOrSameDay(value: string | null | undefined, day: string): boolean {
  if (!value) return false;
  return new Date(value).getTime() >= new Date(`${day}T00:00:00`).getTime();
}

function isBeforeOrSameDay(value: string | null | undefined, day: string): boolean {
  if (!value) return false;
  return new Date(value).getTime() <= new Date(`${day}T23:59:59`).getTime();
}
