import type {
  AdminCollectionTask,
  AdminEmail,
  AdminInfluencer,
  AdminProduct,
  AdminReply,
  AdminSummary,
  AdminUser,
} from "@/lib/api";

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
  completed_no_results: { label: "无结果", tone: "warning" },
  partial_failed: { label: "部分失败", tone: "warning" },
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
  interested: { label: "有意向", tone: "success" },
  not_interested: { label: "无意向", tone: "muted" },
  need_follow_up: { label: "待跟进", tone: "warning" },
  unknown: { label: "待判断", tone: "muted" },
};

const replyProcessingStatuses: Record<string, StatusMeta> = {
  unprocessed: { label: "待处理", tone: "warning" },
  unread: { label: "待处理", tone: "warning" },
  new: { label: "待处理", tone: "warning" },
  pending: { label: "待处理", tone: "warning" },
  pending_reply: { label: "待处理", tone: "warning" },
  processed: { label: "已处理", tone: "success" },
  handled: { label: "已处理", tone: "success" },
  read: { label: "已查看", tone: "info" },
  no_action: { label: "无需处理", tone: "muted" },
  ignored: { label: "无需处理", tone: "muted" },
};

const replyIntentStatuses: Record<string, StatusMeta> = {
  positive: { label: "有意向", tone: "success" },
  interested: { label: "有意向", tone: "success" },
  follow_up: { label: "待跟进", tone: "warning" },
  need_follow_up: { label: "待跟进", tone: "warning" },
  pending_reply: { label: "待跟进", tone: "warning" },
  not_interested: { label: "无意向", tone: "muted" },
  unmatched: { label: "未匹配", tone: "muted" },
  unknown: { label: "待判断", tone: "muted" },
  unprocessed: { label: "待判断", tone: "muted" },
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

export function getReplyProcessingStatusMeta(status: string | null | undefined): StatusMeta {
  return getStatusMeta(status, replyProcessingStatuses);
}

export function getReplyIntentStatusMeta(status: string | null | undefined): StatusMeta {
  return getStatusMeta(status, replyIntentStatuses);
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

export type SalesWorkbenchActivityStatus = "active_today" | "inactive_today" | "disabled";

export type SalesWorkbenchRow = AdminUser & {
  activityStatus: SalesWorkbenchActivityStatus;
  todayTaskCount: number;
  activeTaskCount: number;
  todayInfluencerCount: number;
  exceptionCount: number;
  outreachInsufficient: boolean;
};

export type SalesWorkbenchView = {
  rows: SalesWorkbenchRow[];
  kpis: {
    salesCount: number;
    activeTodayCount: number;
    productCount: number;
    todayTaskCount: number;
    successCount: number;
    exceptionCount: number;
    todayInfluencerCount: number;
    pendingReplyCount: number;
    outreachInsufficientCount: number;
  };
  hasPreciseTodayTaskData: boolean;
  hasPreciseTodayInfluencerData: boolean;
};

export type SalesBrandProgress = {
  productId: number | null;
  name: string;
  slug: string;
  taskCount: number;
  latestTaskStatus: string | null;
  influencerCount: number;
  emailCount: number;
  replyCount: number;
  exceptionCount: number;
  updatedAt: string | null;
  outreachInsufficient: boolean;
};

export function buildSalesWorkbenchView(users: AdminUser[], now = new Date()): SalesWorkbenchView {
  const hasPreciseTodayTaskData =
    users.some((user) => typeof user.today_collection_task_count === "number") ||
    users.some((user) => (user.recent_activity?.collection_tasks ?? []).some(hasCreatedOrUpdatedAt));
  const hasPreciseTodayInfluencerData =
    users.some((user) => typeof user.today_influencer_count === "number") ||
    users.some((user) => (getRecentInfluencers(user.recent_activity) ?? []).some(hasCreatedOrUpdatedAt));
  const rows = users
    .filter((user) => user.role === "sales")
    .map((user) => {
      const activeToday = isSameLocalDay(user.last_active_at, now);
      const todayTaskCount =
        typeof user.today_collection_task_count === "number"
          ? user.today_collection_task_count
          : countRecentItemsForToday(user.recent_activity?.collection_tasks, now);
      const todayInfluencerCount =
        typeof user.today_influencer_count === "number"
          ? user.today_influencer_count
          : countRecentItemsForToday(getRecentInfluencers(user.recent_activity), now);
      return {
        ...user,
        activityStatus: !user.is_active ? "disabled" : activeToday ? "active_today" : "inactive_today",
        todayTaskCount,
        activeTaskCount: getRecentActivityCount(user.recent_activity?.collection_tasks, now),
        todayInfluencerCount,
        exceptionCount: (user.collection_failed_count ?? 0) + (user.email_failed_count ?? 0),
        outreachInsufficient: isOutreachInsufficient({
          influencerCount: user.influencer_count ?? 0,
          emailCount: user.email_count ?? 0,
          replyCount: user.reply_count ?? 0,
        }),
      } satisfies SalesWorkbenchRow;
    });

  const productIds = new Set<number>();
  for (const row of rows) {
    for (const product of row.bound_products ?? []) {
      productIds.add(product.id);
    }
  }

  return {
    rows,
    kpis: {
      salesCount: rows.length,
      activeTodayCount: rows.filter((row) => row.activityStatus === "active_today").length,
      productCount: productIds.size || rows.reduce((sum, row) => sum + (row.product_count ?? 0), 0),
      todayTaskCount: rows.reduce((sum, row) => sum + row.todayTaskCount, 0),
      successCount: rows.reduce((sum, row) => sum + (row.collection_success_count ?? 0), 0),
      exceptionCount: rows.reduce((sum, row) => sum + row.exceptionCount, 0),
      todayInfluencerCount: rows.reduce((sum, row) => sum + row.todayInfluencerCount, 0),
      pendingReplyCount: rows.reduce((sum, row) => sum + (row.pending_reply_count ?? 0), 0),
      outreachInsufficientCount: rows.filter((row) => row.outreachInsufficient).length,
    },
    hasPreciseTodayTaskData,
    hasPreciseTodayInfluencerData,
  };
}

export function buildSalesWorkbenchDetailView({
  products,
  tasks,
  influencers,
  emails,
  replies,
}: {
  products: AdminProduct[];
  tasks: AdminCollectionTask[];
  influencers: AdminInfluencer[];
  emails: AdminEmail[];
  replies: AdminReply[];
}): { brandProgress: SalesBrandProgress[] } {
  const productMap = new Map<number | null, SalesBrandProgress>();
  for (const product of products) {
    productMap.set(product.id, {
      productId: product.id,
      name: product.name || "暂无",
      slug: product.slug || "暂无",
      taskCount: 0,
      latestTaskStatus: null,
      influencerCount: 0,
      emailCount: 0,
      replyCount: 0,
      exceptionCount: 0,
      updatedAt: product.updated_at ?? product.created_at ?? null,
      outreachInsufficient: false,
    });
  }

  function ensureProgress(productId: number | null, name: string | null | undefined): SalesBrandProgress {
    const key = productId ?? null;
    const existing = productMap.get(key);
    if (existing) return existing;
    const progress: SalesBrandProgress = {
      productId: key,
      name: name || "暂无品牌",
      slug: "暂无",
      taskCount: 0,
      latestTaskStatus: null,
      influencerCount: 0,
      emailCount: 0,
      replyCount: 0,
      exceptionCount: 0,
      updatedAt: null,
      outreachInsufficient: false,
    };
    productMap.set(key, progress);
    return progress;
  }

  const latestTaskUpdatedAtByProduct = new Map<number | null, string | null>();
  for (const task of tasks) {
    const progress = ensureProgress(task.product_id, task.product_name);
    progress.taskCount += 1;
    if (isStatusExceptional(task.status) || (task.failed_count ?? 0) > 0) progress.exceptionCount += 1;
    const taskUpdatedAt = task.updated_at ?? task.last_run_at ?? task.created_at;
    if (isNewer(taskUpdatedAt, progress.updatedAt)) progress.updatedAt = taskUpdatedAt;
    if (!progress.latestTaskStatus || isNewer(taskUpdatedAt, latestTaskUpdatedAtByProduct.get(progress.productId) ?? null)) {
      progress.latestTaskStatus = task.status;
      latestTaskUpdatedAtByProduct.set(progress.productId, taskUpdatedAt ?? null);
    }
  }

  for (const influencer of influencers) {
    const progress = ensureProgress(influencer.product_id, influencer.product_name);
    progress.influencerCount += 1;
    if (isStatusExceptional(influencer.follow_status)) progress.exceptionCount += 1;
    if (isNewer(influencer.updated_at ?? influencer.created_at, progress.updatedAt)) {
      progress.updatedAt = influencer.updated_at ?? influencer.created_at;
    }
  }

  for (const email of emails) {
    const progress = ensureProgress(email.product_id, email.product_name);
    progress.emailCount += 1;
    if (isStatusExceptional(email.status) || email.error_message) progress.exceptionCount += 1;
    if (isNewer(email.replied_at ?? email.sent_at, progress.updatedAt)) progress.updatedAt = email.replied_at ?? email.sent_at;
  }

  for (const reply of replies) {
    const progress = ensureProgress(reply.product_id, reply.product_name);
    progress.replyCount += 1;
    if (getReplyProcessingStatusMeta(reply.processing_status).tone === "warning") progress.exceptionCount += 1;
    if (isNewer(reply.handled_at ?? reply.received_at, progress.updatedAt)) progress.updatedAt = reply.handled_at ?? reply.received_at;
  }

  const brandProgress = Array.from(productMap.values()).map((progress) => ({
    ...progress,
    outreachInsufficient: isOutreachInsufficient(progress),
  }));

  return {
    brandProgress: brandProgress.sort((a, b) => (dateValue(b.updatedAt) - dateValue(a.updatedAt)) || a.name.localeCompare(b.name, "zh-Hans-CN")),
  };
}

export function isOutreachInsufficient({
  influencerCount,
  emailCount,
  replyCount,
}: {
  influencerCount: number | null | undefined;
  emailCount: number | null | undefined;
  replyCount: number | null | undefined;
}): boolean {
  const influencers = influencerCount ?? 0;
  const emails = emailCount ?? 0;
  const replies = replyCount ?? 0;
  return (influencers > 0 && emails === 0) || (influencers >= 10 && emails / influencers < 0.5) || (emails > 0 && replies === 0);
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
  const normalized = status?.trim().toLowerCase();
  if (!normalized || normalized === "undefined" || normalized === "null") return { label: "暂无", tone: "muted" };
  return map[normalized] ?? { label: humanizeStatus(normalized), tone: "neutral" };
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

function getRecentActivityCount(items: AdminCollectionTask[] | undefined, now: Date): number {
  return (items ?? []).filter((item) => isActiveCollectionStatus(item.status) || isSameLocalDay(item.updated_at ?? item.last_run_at ?? item.created_at, now)).length;
}

function countRecentItemsForToday(items: Array<{ created_at?: string | null; updated_at?: string | null }> | undefined, now: Date): number {
  return (items ?? []).filter((item) => isSameLocalDay(item.created_at ?? item.updated_at, now) || isSameLocalDay(item.updated_at ?? item.created_at, now)).length;
}

function hasCreatedOrUpdatedAt(item: { created_at?: string | null; updated_at?: string | null }): boolean {
  return Boolean(item.created_at ?? item.updated_at);
}

function getRecentInfluencers(recentActivity: AdminUser["recent_activity"] | undefined): Array<{ created_at?: string | null; updated_at?: string | null }> {
  const maybeActivity = recentActivity as (AdminUser["recent_activity"] & { influencers?: Array<{ created_at?: string | null; updated_at?: string | null }> }) | undefined;
  return maybeActivity?.influencers ?? [];
}

function isActiveCollectionStatus(status: string | null | undefined): boolean {
  const meta = getCollectionTaskStatusMeta(status);
  return meta.tone === "info" || status === "queued" || status === "pending";
}

function isStatusExceptional(status: string | null | undefined): boolean {
  if (!status) return false;
  return getCollectionTaskStatusMeta(status).tone === "danger" || getEmailStatusMeta(status).tone === "danger";
}

function isSameLocalDay(value: string | null | undefined, now: Date): boolean {
  if (!value) return false;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return false;
  return date.getFullYear() === now.getFullYear() && date.getMonth() === now.getMonth() && date.getDate() === now.getDate();
}

function isNewer(candidate: string | null | undefined, current: string | null | undefined): boolean {
  return dateValue(candidate) > dateValue(current);
}

function dateValue(value: string | null | undefined): number {
  if (!value) return 0;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 0 : date.getTime();
}

function humanizeStatus(status: string): string {
  return status
    .split(/[_-]+/)
    .filter(Boolean)
    .map((part) => {
      const labels: Record<string, string> = {
        completed: "已完成",
        failed: "失败",
        pending: "待处理",
        processing: "处理中",
        running: "进行中",
        queued: "排队中",
        with: "有",
        without: "无",
        results: "结果",
        result: "结果",
        partial: "部分",
        sent: "已发送",
        replied: "已回复",
        handled: "已处理",
        unread: "未读",
        read: "已读",
        new: "新增",
        unprocessed: "待处理",
        processed: "已处理",
        positive: "有意向",
        interested: "有意向",
        follow: "跟进",
        up: "",
        not: "无",
        unmatched: "未匹配",
        unknown: "待判断",
      };
      return labels[part] ?? part;
    })
    .join("");
}
