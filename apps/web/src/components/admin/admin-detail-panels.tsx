"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Database,
  Download,
  FileText,
  Mail,
  Plus,
  RefreshCw,
  Send,
  ShieldCheck,
  ShoppingBag,
} from "lucide-react";

import {
  AdminActionButton,
  AdminCompactActions,
  AdminFilterBar,
  AdminFilterField,
  AdminInput,
  AdminKpiCard,
  AdminKpiGrid,
  AdminPageHeader,
  AdminSection,
  AdminSelect,
  AdminState,
  AdminStatusBadge,
  AdminTable,
} from "@/components/admin/admin-ui";
import { AdminFeedbackBanner } from "@/components/admin/admin-crud";
import {
  applyInfluencerQuickAction,
  deleteInfluencerSafely,
  EmailEditDrawer,
  InfluencerDeleteConfirmDialog,
  InfluencerEditDrawer,
  ReplyHandleDrawer,
} from "@/components/admin/admin-entity-management";
import { SalespersonFormDrawer, useAdminAvatarCache } from "@/components/admin/admin-products-management";
import { AdminFollowUpWorkbench, AdminSalesReminderBanner } from "@/components/admin/admin-follow-up-workbench";
import { ProductCreateDialog } from "@/components/layout/product-create-dialog";
import {
  filterAdminRows,
  buildSalesWorkbenchDetailView,
  formatAdminDate,
  formatAdminNumber,
  getCollectionTaskStatusMeta,
  getEmailStatusMeta,
  getEmailValidityLabel,
  getInfluencerStatusMeta,
  getPlatformLabel,
  getProductStatusMeta,
  getReplyIntentStatusMeta,
  getReplyProcessingStatusMeta,
  getReplyStateLabel,
  getRoleLabel,
  getAdminWorkStatusMeta,
  type AdminTone,
} from "@/components/admin/admin-ui-helpers";
import {
  type AdminCollectionTask,
  type AdminEmail,
  type AdminInfluencer,
  type AdminProduct,
  type AdminReply,
  type AdminUser,
  type TenantProduct,
  bulkDeleteAdminCollectionTasks,
  deleteAdminCollectionTask,
  fetchAdminCollectionTasks,
  fetchAdminEmails,
  fetchAdminInfluencers,
  fetchAdminProduct,
  fetchAdminProducts,
  fetchAdminReplies,
  fetchAdminUser,
  fetchAdminUsers,
  fetchAdminUserCollectionTasks,
  fetchAdminUserEmails,
  fetchAdminUserInfluencers,
  fetchAdminUserProducts,
  fetchAdminUserReplies,
  updateEmailReply,
} from "@/lib/api";
import { resolveAdminWorkStatus, upsertAdminWorkQueueEntry } from "@/lib/admin-work-queue";

function SectionWithTable({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <AdminSection title={title} description={description}>
      {children}
    </AdminSection>
  );
}

function countBy<T>(items: T[], getKey: (item: T) => string | null | undefined): Array<{ key: string; count: number }> {
  const counts = new Map<string, number>();
  for (const item of items) {
    const key = getKey(item)?.trim() || "暂无";
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }
  return Array.from(counts, ([key, count]) => ({ key, count })).sort((a, b) => b.count - a.count || a.key.localeCompare(b.key, "zh-Hans-CN"));
}

function ProductDistributionPanel({
  title,
  items,
  formatKey = (value) => value,
}: {
  title: string;
  items: Array<{ key: string; count: number }>;
  formatKey?: (value: string) => string;
}) {
  const total = items.reduce((sum, item) => sum + item.count, 0);
  return (
    <div className="rounded-lg border border-[#DDE6F0] bg-white p-4">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold text-[#102033]">{title}</h3>
        <span className="text-xs tabular-nums text-[#667085]">{formatAdminNumber(total)} 条</span>
      </div>
      <div className="mt-3 space-y-2">
        {items.length ? (
          items.slice(0, 5).map((item) => {
            const percent = total ? Math.round((item.count / total) * 100) : 0;
            return (
              <div key={item.key} className="space-y-1">
                <div className="flex items-center justify-between gap-3 text-xs">
                  <span className="truncate text-[#344054]">{formatKey(item.key)}</span>
                  <span className="shrink-0 tabular-nums text-[#667085]">{formatAdminNumber(item.count)} · {percent}%</span>
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-[#EEF2F7]">
                  <div className="h-full rounded-full bg-[#2563EB]" style={{ width: `${Math.max(percent, item.count ? 4 : 0)}%` }} />
                </div>
              </div>
            );
          })
        ) : (
          <p className="text-sm text-[#667085]">暂无数据</p>
        )}
      </div>
    </div>
  );
}

function ProductExceptionList({ tasks, replies }: { tasks: AdminCollectionTask[]; replies: AdminReply[] }) {
  const rows = [
    ...tasks
      .filter((item) => getCollectionTaskStatusMeta(item.status).tone === "danger" || getCollectionTaskStatusMeta(item.status).tone === "warning" || item.failed_count > 0)
      .map((item) => ({
        id: `task-${item.id}`,
        title: item.name,
        meta: `任务 #${item.id} · ${getPlatformLabel(item.platform)}`,
        status: getCollectionTaskStatusMeta(item.status),
      })),
    ...replies
      .filter((item) => getReplyProcessingStatusMeta(item.processing_status).tone === "warning")
      .map((item) => ({
        id: `reply-${item.id}`,
        title: item.subject || item.from_address || "待处理回复",
        meta: item.from_address || "回复记录",
        status: getReplyProcessingStatusMeta(item.processing_status),
      })),
  ].slice(0, 6);

  return (
    <div className="rounded-lg border border-[#DDE6F0] bg-white p-4">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold text-[#102033]">需要关注</h3>
        <span className="text-xs tabular-nums text-[#667085]">{formatAdminNumber(rows.length)} 条</span>
      </div>
      <div className="mt-3 space-y-2">
        {rows.length ? (
          rows.map((item) => (
            <div key={item.id} className="flex items-center justify-between gap-3 rounded-md bg-[#F8FAFD] px-3 py-2">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-[#102033]">{item.title}</p>
                <p className="mt-0.5 truncate text-xs text-[#667085]">{item.meta}</p>
              </div>
              <AdminStatusBadge meta={item.status} />
            </div>
          ))
        ) : (
          <p className="text-sm text-[#667085]">暂无异常或待处理事项</p>
        )}
      </div>
    </div>
  );
}

function TasksTable({
  items,
  onDeleteTask,
  deletingTaskId,
}: {
  items: AdminCollectionTask[];
  onDeleteTask?: (task: AdminCollectionTask) => void;
  deletingTaskId?: number | null;
}) {
  return (
    <AdminTable
      minWidth={1180}
      columns={["任务 ID", "任务名称", "品牌", "业务员", "平台", "状态", "入库数", "失败原因", "创建时间", "完成时间", "操作"]}
      rows={items.map((item) => [
        `#${item.id}`,
        <span key="name" className="font-medium text-[#102033]">{item.name}</span>,
        item.product_name ?? "暂无",
        item.username ?? "暂无",
        getPlatformLabel(item.platform),
        <AdminStatusBadge key="status" meta={getCollectionTaskStatusMeta(item.status)} />,
        formatAdminNumber(item.inserted_count || item.result_count),
        item.failed_count > 0 ? "存在失败记录，请查看日志" : "暂无",
        formatAdminDate(item.created_at),
        formatAdminDate(item.last_run_at ?? item.updated_at),
        <AdminCompactActions
          key="actions"
          primaryLabel="日志"
          items={[
            { label: "重新运行", disabled: true },
            { label: "导出结果", disabled: true },
            {
              label: deletingTaskId === item.id ? "删除中..." : "删除任务",
              disabled: !onDeleteTask || deletingTaskId === item.id || item.status === "running",
              danger: true,
              onClick: () => onDeleteTask?.(item),
            },
            { label: "标记异常", disabled: true, danger: true },
          ]}
        />,
      ])}
      emptyMessage="暂无采集任务。"
    />
  );
}

function InfluencersTable({
  items,
  detailHref = (id: number) => `/admin/influencers/${id}`,
  onEdit,
  onDelete,
  onQuickAction,
}: {
  items: AdminInfluencer[];
  detailHref?: (id: number) => string;
  onEdit?: (item: AdminInfluencer) => void;
  onDelete?: (item: AdminInfluencer) => void;
  onQuickAction?: (action: string, item: AdminInfluencer) => void;
}) {
  return (
    <AdminTable
      minWidth={1180}
      columns={["红人名称", "品牌", "平台", "粉丝数", "邮箱", "邮箱有效性", "联系状态", "回复状态", "创建时间", "操作"]}
      rows={items.map((item) => [
        <span key="name" className="font-medium text-[#102033]">{item.display_name || item.username}</span>,
        item.product_name ?? "暂无",
        getPlatformLabel(item.platform),
        formatAdminNumber(item.followers_count),
        item.email ?? "暂无",
        <AdminStatusBadge key="email" meta={getEmailValidityLabel(item.email)} />,
        <AdminStatusBadge key="contact" meta={getInfluencerStatusMeta(item.follow_status)} />,
        <AdminStatusBadge key="reply" meta={item.follow_status === "replied" ? getReplyStateLabel(true) : getReplyStateLabel(false)} />,
        formatAdminDate(item.created_at),
        <AdminCompactActions
          key="actions"
          primaryHref={detailHref(item.id)}
          primaryLabel="详情"
          secondaryLabel="编辑"
          secondaryOnClick={onEdit ? () => onEdit(item) : undefined}
          items={[
            { label: "删除", danger: true, onClick: onDelete ? () => onDelete(item) : undefined, disabled: !onDelete },
            { label: "标记已联系", onClick: onQuickAction ? () => onQuickAction("mark_contacted", item) : undefined, disabled: !onQuickAction },
            { label: "标记已回复", onClick: onQuickAction ? () => onQuickAction("mark_replied", item) : undefined, disabled: !onQuickAction },
            { label: "标记无效邮箱", danger: true, onClick: onQuickAction ? () => onQuickAction("mark_invalid", item) : undefined, disabled: !onQuickAction },
            { label: "加入待跟进", onClick: onQuickAction ? () => onQuickAction("add_follow_up", item) : undefined, disabled: !onQuickAction },
          ]}
        />,
      ])}
      emptyMessage="暂无红人数据。"
    />
  );
}

function EmailsTable({
  items,
  onRemind,
  onMarkHandled,
  onEdit,
}: {
  items: AdminEmail[];
  onRemind?: (item: AdminEmail) => void;
  onMarkHandled?: (item: AdminEmail) => void;
  onEdit?: (item: AdminEmail) => void;
}) {
  return (
    <AdminTable
      minWidth={980}
      columns={["邮件主题", "品牌", "业务员", "收件人", "发送状态", "回复", "发送时间", "操作"]}
      rows={items.map((item) => [
        <span key="subject" className="block max-w-[200px] truncate font-medium text-[#102033]" title={item.subject || "暂无主题"}>
          {item.subject || "暂无主题"}
        </span>,
        item.product_name ?? "暂无",
        item.username ?? "暂无",
        <span
          key="to"
          className="block max-w-[160px] truncate"
          title={(item.recipients ?? []).join("、") || item.influencer_username || "暂无"}
        >
          {(item.recipients ?? []).join("、") || item.influencer_username || "暂无"}
        </span>,
        <AdminStatusBadge key="status" meta={getEmailStatusMeta(item.status)} />,
        <AdminStatusBadge key="reply" meta={getReplyStateLabel(item.has_replied)} />,
        formatAdminDate(item.sent_at),
        <AdminCompactActions
          key="actions"
          primaryLabel="编辑"
          primaryOnClick={onEdit ? () => onEdit(item) : undefined}
          secondaryLabel="提醒"
          secondaryOnClick={onRemind ? () => onRemind(item) : undefined}
          items={[
            {
              label: "查看红人",
              href: item.product_influencer_id ? `/admin/influencers/${item.product_influencer_id}` : undefined,
              disabled: !item.product_influencer_id,
            },
            { label: "标记已处理", onClick: onMarkHandled ? () => onMarkHandled(item) : undefined, disabled: !onMarkHandled },
          ]}
        />,
      ])}
      emptyMessage="暂无邮件记录。"
    />
  );
}

function RepliesTable({
  items,
  onEdit,
  onRemind,
  onMarkHandled,
}: {
  items: AdminReply[];
  onEdit?: (item: AdminReply) => void;
  onRemind?: (item: AdminReply) => void;
  onMarkHandled?: (item: AdminReply) => void;
}) {
  return (
    <AdminTable
      minWidth={980}
      columns={["邮件主题", "品牌", "业务员", "发件人", "处理状态", "意向状态", "收到时间", "处理时间", "操作"]}
      rows={items.map((item) => {
        const workStatus = resolveAdminWorkStatus("reply", item.id, item.processing_status);
        return [
        <span key="subject" className="block max-w-[260px] truncate font-medium text-[#102033]">{item.subject || "暂无主题"}</span>,
        item.product_name ?? "暂无",
        item.username ?? "暂无",
        item.from_address ?? "暂无",
        <span key="processing" className="inline-flex flex-wrap gap-1">
          <AdminStatusBadge meta={getReplyProcessingStatusMeta(item.processing_status)} />
          {workStatus !== "pending" && workStatus !== "handled" ? (
            <AdminStatusBadge meta={getAdminWorkStatusMeta(workStatus)} />
          ) : null}
        </span>,
        <AdminStatusBadge key="intent" meta={getReplyIntentStatusMeta(item.intent_status)} />,
        formatAdminDate(item.received_at),
        formatAdminDate(item.handled_at),
        <AdminCompactActions
          key="actions"
          primaryLabel="编辑"
          primaryOnClick={onEdit ? () => onEdit(item) : undefined}
          secondaryLabel="提醒"
          secondaryOnClick={onRemind ? () => onRemind(item) : undefined}
          items={[
            { label: "标记已处理", onClick: onMarkHandled ? () => onMarkHandled(item) : undefined, disabled: !onMarkHandled },
            {
              label: "查看红人",
              href: item.product_influencer_id ? `/admin/influencers/${item.product_influencer_id}` : undefined,
              disabled: !item.product_influencer_id,
            },
          ]}
        />,
      ];
      })}
      emptyMessage="暂无回复记录。"
    />
  );
}

function BrandProgressTable({ items }: { items: ReturnType<typeof buildSalesWorkbenchDetailView>["brandProgress"] }) {
  return (
    <AdminTable
      minWidth={1180}
      columns={["品牌名", "SLUG", "风险", "采集任务数", "最近任务状态", "入库红人数", "邮件数", "回复数", "异常数", "最近更新时间"]}
      rows={items.map((item) => [
        <span key="name" className="font-medium text-[#102033]">{item.name}</span>,
        item.slug || "暂无",
        item.outreachInsufficient ? <AdminStatusBadge key="risk" meta={{ label: "外联不足", tone: "warning" }} /> : <AdminStatusBadge key="risk" meta={{ label: "正常", tone: "success" }} />,
        formatAdminNumber(item.taskCount),
        <AdminStatusBadge key="status" meta={getCollectionTaskStatusMeta(item.latestTaskStatus)} />,
        formatAdminNumber(item.influencerCount),
        formatAdminNumber(item.emailCount),
        formatAdminNumber(item.replyCount),
        item.exceptionCount > 0 ? <AdminStatusBadge key="exceptions" meta={{ label: formatAdminNumber(item.exceptionCount), tone: "danger" }} /> : "0",
        formatAdminDate(item.updatedAt),
      ])}
      emptyMessage="暂无负责品牌进度。"
    />
  );
}

function ExceptionsTable({
  tasks,
  emails,
  replies,
}: {
  tasks: AdminCollectionTask[];
  emails: AdminEmail[];
  replies: AdminReply[];
}) {
  const rows = [
    ...tasks
      .filter((item) => getCollectionTaskStatusMeta(item.status).tone === "danger" || (item.failed_count ?? 0) > 0)
      .map((item) => ({
        type: "采集任务",
        brand: item.product_name,
        title: item.name,
        status: getCollectionTaskStatusMeta(item.status),
        detail: (item.failed_count ?? 0) > 0 ? `失败 ${formatAdminNumber(item.failed_count)} 条` : "任务失败",
        time: item.updated_at ?? item.last_run_at ?? item.created_at,
      })),
    ...emails
      .filter((item) => getEmailStatusMeta(item.status).tone === "danger" || item.error_message)
      .map((item) => ({
        type: "邮件记录",
        brand: item.product_name,
        title: item.subject || item.influencer_username || "暂无主题",
        status: getEmailStatusMeta(item.status),
        detail: item.error_message || "发送失败",
        time: item.sent_at,
      })),
    ...replies
      .filter((item) => getReplyProcessingStatusMeta(item.processing_status).tone === "warning")
      .map((item) => ({
        type: "回复记录",
        brand: item.product_name,
        title: item.subject || item.from_address,
        status: getReplyProcessingStatusMeta(item.processing_status),
        detail: item.snippet || "待处理回复",
        time: item.received_at,
      })),
  ].sort((a, b) => new Date(b.time ?? 0).getTime() - new Date(a.time ?? 0).getTime());

  return (
    <AdminTable
      minWidth={980}
      columns={["类型", "品牌", "记录", "状态", "说明", "时间"]}
      rows={rows.map((item) => [
        item.type,
        item.brand ?? "暂无",
        <span key="title" className="block max-w-[280px] truncate font-medium text-[#102033]">{item.title}</span>,
        <AdminStatusBadge key="status" meta={item.status} />,
        <span key="detail" className="block max-w-[320px] truncate">{item.detail}</span>,
        formatAdminDate(item.time),
      ])}
      emptyMessage="暂无异常记录。"
    />
  );
}

function DetailTabs({
  tabs,
  activeTab,
  onChange,
}: {
  tabs: Array<{ key: string; label: string; count: number; tone?: AdminTone }>;
  activeTab: string;
  onChange: (key: string) => void;
}) {
  return (
    <div className="flex gap-1 overflow-x-auto border-b border-[#E5ECF4] bg-[#F7F9FC] px-3 pt-3">
      {tabs.map((tab) => (
        <button
          key={tab.key}
          type="button"
          onClick={() => onChange(tab.key)}
          className={[
            "inline-flex h-9 shrink-0 items-center gap-2 rounded-t-md border border-b-0 px-3 text-sm font-medium transition",
            activeTab === tab.key
              ? "border-[#DDE6F0] bg-white text-[#102033]"
              : "border-transparent text-[#667085] hover:bg-white/70 hover:text-[#102033]",
          ].join(" ")}
        >
          {tab.label}
          <span className="rounded-full bg-[#EEF2F7] px-1.5 py-0.5 text-xs tabular-nums text-[#667085]">{formatAdminNumber(tab.count)}</span>
        </button>
      ))}
    </div>
  );
}

export function AdminUserDetailPanel({ userId }: { userId: number }) {
  const [activeTab, setActiveTab] = useState("tasks");
  const [data, setData] = useState<{
    user: AdminUser;
    products: AdminProduct[];
    tasks: AdminCollectionTask[];
    influencers: AdminInfluencer[];
    emails: AdminEmail[];
    replies: AdminReply[];
  } | null>(null);
  const [allProducts, setAllProducts] = useState<AdminProduct[]>([]);
  const [allUsers, setAllUsers] = useState<AdminUser[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [editOpen, setEditOpen] = useState(false);
  const [draftAvatarUrl, setDraftAvatarUrl] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const avatarCache = useAdminAvatarCache();

  const reloadDetail = useCallback(async () => {
    const [user, products, tasks, influencers, emails, replies, catalog, users] = await Promise.all([
      fetchAdminUser(userId),
      fetchAdminUserProducts(userId),
      fetchAdminUserCollectionTasks(userId),
      fetchAdminUserInfluencers(userId),
      fetchAdminUserEmails(userId),
      fetchAdminUserReplies(userId),
      fetchAdminProducts(),
      fetchAdminUsers(),
    ]);
    setData({
      user,
      products: products ?? [],
      tasks: tasks ?? [],
      influencers: influencers ?? [],
      emails: emails ?? [],
      replies: replies ?? [],
    });
    setAllProducts(catalog);
    setAllUsers(users);
  }, [userId]);

  useEffect(() => {
    let active = true;
    queueMicrotask(() => {
      if (!active) return;
      void reloadDetail().catch((err) => {
        if (active) setError(err instanceof Error ? err.message : "业务员详情加载失败。");
      });
    });
    return () => {
      active = false;
    };
  }, [reloadDetail]);

  if (error) return <AdminState type="error" message={error} />;
  if (!data) return <AdminState type="loading" message="正在加载业务员详情..." />;

  const { user, products, tasks, influencers, emails, replies } = data;
  const detailView = buildSalesWorkbenchDetailView({ products, tasks, influencers, emails, replies });
  const exceptionCount =
    tasks.filter((item) => getCollectionTaskStatusMeta(item.status).tone === "danger" || (item.failed_count ?? 0) > 0).length +
    emails.filter((item) => getEmailStatusMeta(item.status).tone === "danger" || item.error_message).length +
    replies.filter((item) => getReplyProcessingStatusMeta(item.processing_status).tone === "warning").length;
  const tabs = [
    { key: "tasks", label: "采集任务", count: tasks.length },
    { key: "influencers", label: "红人数据", count: influencers.length },
    { key: "emails", label: "邮件记录", count: emails.length },
    { key: "replies", label: "回复记录", count: replies.length },
    { key: "exceptions", label: "异常记录", count: exceptionCount, tone: "danger" as AdminTone },
  ];

  return (
    <div className="space-y-3">
      <AdminPageHeader
        label="业务员作业明细"
        title={`${user.display_name?.trim() || user.username}（#${user.id}）`}
        description="查看这个业务员具体采集了哪些品牌的数据，以及每个品牌的任务、红人、邮件、回复和异常进度。"
        actions={
          <>
            <AdminActionButton
              onClick={() => {
                setDraftAvatarUrl(avatarCache.getUserAvatar(user.id) ?? null);
                setEditOpen(true);
              }}
            >
              编辑
            </AdminActionButton>
            <AdminActionButton href="/admin/products">返回品牌进度</AdminActionButton>
            <AdminActionButton href="/admin/sales-workbench">返回业务员作业</AdminActionButton>
          </>
        }
        backFallback="/admin/products"
      />
      {successMessage ? (
        <div className="rounded-md border border-[#BAE6D1] bg-[#ECFDF3] px-4 py-3 text-sm text-[#047857]">{successMessage}</div>
      ) : null}
      <AdminKpiGrid>
        <AdminKpiCard label="角色" value={getRoleLabel(user.role)} helper={user.is_active ? "账号启用" : "账号禁用"} icon={ShieldCheck} tone={user.is_active ? "success" : "muted"} />
        <AdminKpiCard label="负责品牌数" value={user.product_count ?? 0} helper="绑定品牌" icon={Database} tone="info" />
        <AdminKpiCard label="任务成功 / 失败" value={`${formatAdminNumber(user.collection_success_count)} / ${formatAdminNumber(user.collection_failed_count)}`} helper="采集表现" icon={RefreshCw} tone="info" />
        <AdminKpiCard label="回复 / 待处理" value={`${formatAdminNumber(user.reply_count)} / ${formatAdminNumber(user.pending_reply_count)}`} helper="跟进压力" icon={Mail} tone="warning" />
      </AdminKpiGrid>
      <SectionWithTable title="负责品牌进度" description="按品牌汇总采集任务、红人入库、邮件触达、回复和异常情况。">
        <BrandProgressTable items={detailView.brandProgress} />
      </SectionWithTable>
      <AdminSection title="作业明细" description="按采集、红人、邮件、回复和异常切换查看，表格均支持分页和横向滚动。">
        <DetailTabs tabs={tabs} activeTab={activeTab} onChange={setActiveTab} />
        {activeTab === "tasks" ? <TasksTable items={tasks} /> : null}
        {activeTab === "influencers" ? <InfluencersTable items={influencers} /> : null}
        {activeTab === "emails" ? <EmailsTable items={emails} /> : null}
        {activeTab === "replies" ? <RepliesTable items={replies} /> : null}
        {activeTab === "exceptions" ? <ExceptionsTable tasks={tasks} emails={emails} replies={replies} /> : null}
      </AdminSection>

      <SalespersonFormDrawer
        open={editOpen}
        mode="edit"
        user={user}
        products={allProducts}
        users={allUsers}
        avatarUrl={draftAvatarUrl}
        onAvatarChange={(url) => {
          setDraftAvatarUrl(url);
          if (url) avatarCache.setUserAvatar(user.id, url);
        }}
        onClose={() => setEditOpen(false)}
        onSaved={async () => {
          setSuccessMessage("业务员已更新。");
          await reloadDetail();
        }}
        onProductsChanged={reloadDetail}
      />
    </div>
  );
}

export function AdminProductDetailPanel({ productId }: { productId: number }) {
  const [product, setProduct] = useState<AdminProduct | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState("tasks");
  const [deletingTaskId, setDeletingTaskId] = useState<number | null>(null);

  useEffect(() => {
    let active = true;
    fetchAdminProduct(productId)
      .then((data) => {
        if (active) setProduct(data);
      })
      .catch((err) => {
        if (active) setError(err instanceof Error ? err.message : "品牌详情加载失败。");
      });
    return () => {
      active = false;
    };
  }, [productId]);

  if (error) return <AdminState type="error" message={error} />;
  if (!product) return <AdminState type="loading" message="正在加载品牌详情..." />;

  const tasks = product.collection_tasks ?? [];
  const influencers = product.influencers ?? [];
  const emails = product.emails ?? [];
  const replies = product.replies ?? [];
  const successTasks = tasks.filter((item) => getCollectionTaskStatusMeta(item.status).tone === "success").length;
  const warningTasks = tasks.filter((item) => getCollectionTaskStatusMeta(item.status).tone === "warning").length;
  const failedTasks = tasks.filter((item) => getCollectionTaskStatusMeta(item.status).tone === "danger" || item.failed_count > 0).length;
  const contactedInfluencers = influencers.filter((item) => item.follow_status === "contacted" || item.follow_status === "replied").length;
  const validEmails = influencers.filter((item) => item.email).length;
  const exceptionCount = failedTasks + replies.filter((item) => getReplyProcessingStatusMeta(item.processing_status).tone === "warning").length;
  const tabs = [
    { key: "tasks", label: "采集任务", count: tasks.length },
    { key: "influencers", label: "红人数据", count: influencers.length },
    { key: "emails", label: "邮件记录", count: emails.length },
    { key: "replies", label: "回复记录", count: replies.length },
    { key: "exceptions", label: "异常记录", count: exceptionCount, tone: "danger" as AdminTone },
  ];

  async function handleDeleteTask(task: AdminCollectionTask) {
    if (!window.confirm(`确定删除任务「${task.name}」吗？有追溯数据的任务会从后台列表归档隐藏，无追溯数据会直接删除。`)) return;
    setDeletingTaskId(task.id);
    setActionError(null);
    setNotice(null);
    try {
      const result = await deleteAdminCollectionTask(task.id);
      setProduct((prev) => {
        if (!prev) return prev;
        const nextTasks = (prev.collection_tasks ?? []).filter((item) => item.id !== task.id);
        return {
          ...prev,
          collection_task_count: Math.max(0, (prev.collection_task_count ?? nextTasks.length + 1) - 1),
          collection_tasks: nextTasks,
        };
      });
      setNotice(result.action === "archived" ? "任务已归档隐藏，红人库和来源追溯数据仍保留。" : "任务已删除。");
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "删除任务失败。");
    } finally {
      setDeletingTaskId(null);
    }
  }

  return (
    <div className="space-y-3">
      <AdminPageHeader
        label="品牌详情"
        title={`${product.name}（#${product.id}）`}
        description="展示品牌下的任务、红人、邮件和回复链路，便于判断品牌当前处在哪个运营阶段。"
        actions={<AdminActionButton href="/admin/products">返回品牌列表</AdminActionButton>}
        backFallback="/admin/products"
      />
      <AdminKpiGrid>
        <AdminKpiCard label="状态" value={getProductStatusMeta(product.status).label} helper={product.slug ?? "暂无"} icon={ShoppingBag} tone={getProductStatusMeta(product.status).tone} />
        <AdminKpiCard label="任务健康" value={`${formatAdminNumber(successTasks)} / ${formatAdminNumber(warningTasks + failedTasks)}`} helper="完成 / 需关注" icon={RefreshCw} tone={failedTasks ? "warning" : "success"} />
        <AdminKpiCard label="红人资料" value={influencers.length} helper={`${formatAdminNumber(validEmails)} 个有邮箱`} icon={Database} tone="info" />
        <AdminKpiCard label="外联进展" value={`${formatAdminNumber(emails.length)} / ${formatAdminNumber(replies.length)}`} helper={`${formatAdminNumber(contactedInfluencers)} 个已联系或回复`} icon={Mail} tone="success" />
      </AdminKpiGrid>
      {actionError ? <div className="rounded-lg border border-[#FECACA] bg-[#FEF2F2] px-4 py-3 text-sm text-[#B42318]">{actionError}</div> : null}
      {notice ? <div className="rounded-lg border border-[#BBF7D0] bg-[#F0FDF4] px-4 py-3 text-sm text-[#047857]">{notice}</div> : null}
      <div className="grid gap-3 xl:grid-cols-4">
        <ProductDistributionPanel title="任务状态分布" items={countBy(tasks, (item) => getCollectionTaskStatusMeta(item.status).label)} />
        <ProductDistributionPanel title="平台分布" items={countBy(tasks, (item) => item.platform)} formatKey={getPlatformLabel} />
        <ProductDistributionPanel title="业务员分布" items={countBy(tasks, (item) => item.username)} />
        <ProductExceptionList tasks={tasks} replies={replies} />
      </div>
      <SectionWithTable title="品牌成员" description="先看这个品牌由谁负责，后面再按任务、红人、邮件和回复分类查看。">
        <AdminTable columns={["用户 ID", "用户名", "角色", "加入时间"]} rows={(product.members ?? []).map((item) => [`#${item.user_id}`, item.username ?? "暂无", getRoleLabel(item.role), "暂无"])} />
      </SectionWithTable>
      <AdminSection title="品牌运营明细" description="按数据类型切换查看，避免任务、红人、邮件和回复全部堆在一个页面里。">
        <DetailTabs tabs={tabs} activeTab={activeTab} onChange={setActiveTab} />
        {activeTab === "tasks" ? <TasksTable items={tasks} onDeleteTask={handleDeleteTask} deletingTaskId={deletingTaskId} /> : null}
        {activeTab === "influencers" ? <InfluencersTable items={influencers} /> : null}
        {activeTab === "emails" ? <EmailsTable items={emails} /> : null}
        {activeTab === "replies" ? <RepliesTable items={replies} /> : null}
        {activeTab === "exceptions" ? <ExceptionsTable tasks={tasks} emails={emails} replies={replies} /> : null}
      </AdminSection>
    </div>
  );
}

export function AdminCollectionTasksPanel() {
  const [items, setItems] = useState<AdminCollectionTask[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTaskView, setActiveTaskView] = useState("all");
  const [deletingTaskId, setDeletingTaskId] = useState<number | null>(null);
  const [bulkDeleting, setBulkDeleting] = useState(false);
  const [filters, setFilters] = useState({ search: "", owner: "", brand: "", status: "", platform: "", startDate: "", endDate: "" });

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    queueMicrotask(() => {
      if (!active) return;
      fetchAdminCollectionTasks({ signal: controller.signal })
        .then((data) => {
          if (!active || controller.signal.aborted) return;
          setItems(data);
        })
        .catch((err) => {
          if (!active || controller.signal.aborted) return;
          if (err instanceof DOMException && err.name === "AbortError") return;
          setError(err instanceof Error ? err.message : "采集任务加载失败。");
        })
        .finally(() => {
          if (active && !controller.signal.aborted) setLoading(false);
        });
    });
    return () => {
      active = false;
      controller.abort();
    };
  }, []);

  const filteredRows = useMemo(
    () =>
      filterAdminRows(
        items.map((item) => ({
          ...item,
          name: item.name,
          brand: item.product_name,
          owner: item.username,
          platform: item.platform,
          status: item.status,
          createdAt: item.created_at,
        })),
        filters,
      ),
    [items, filters],
  );
  const rows = useMemo(
    () =>
      filteredRows.filter((item) => {
        const meta = getCollectionTaskStatusMeta(item.status);
        const inserted = item.inserted_count || item.result_count || 0;
        if (activeTaskView === "running") return meta.tone === "info" || item.status === "queued" || item.status === "pending";
        if (activeTaskView === "attention") return meta.tone === "warning" || meta.tone === "danger" || item.failed_count > 0;
        if (activeTaskView === "completed") return meta.tone === "success";
        if (activeTaskView === "empty") return inserted === 0 && item.status !== "running";
        return true;
      }),
    [activeTaskView, filteredRows],
  );
  const failed = items.filter((item) => getCollectionTaskStatusMeta(item.status).tone === "danger").length;
  const warning = items.filter((item) => getCollectionTaskStatusMeta(item.status).tone === "warning").length;
  const running = items.filter((item) => ["running", "processing", "collecting", "queued", "pending"].includes(item.status)).length;
  const noResult = items.filter((item) => (item.inserted_count || item.result_count || 0) === 0 && item.status !== "running").length;
  const cleanupCandidates = rows.filter((item) => !item.parent_task_id && (item.inserted_count || item.result_count || 0) === 0 && item.status !== "running");
  const taskViewTabs = [
    { key: "all", label: "全部", count: filteredRows.length },
    { key: "running", label: "运行/排队", count: filteredRows.filter((item) => ["running", "processing", "collecting", "queued", "pending"].includes(item.status)).length },
    { key: "attention", label: "需关注", count: filteredRows.filter((item) => {
      const meta = getCollectionTaskStatusMeta(item.status);
      return meta.tone === "warning" || meta.tone === "danger" || item.failed_count > 0;
    }).length, tone: "danger" as AdminTone },
    { key: "completed", label: "已完成", count: filteredRows.filter((item) => getCollectionTaskStatusMeta(item.status).tone === "success").length },
    { key: "empty", label: "无入库", count: filteredRows.filter((item) => (item.inserted_count || item.result_count || 0) === 0 && item.status !== "running").length },
  ];

  async function handleDeleteTask(task: AdminCollectionTask) {
    if (!window.confirm(`确定删除任务「${task.name}」吗？有追溯数据的任务会归档隐藏，无追溯数据会直接删除。`)) return;
    setDeletingTaskId(task.id);
    setActionError(null);
    setNotice(null);
    try {
      const result = await deleteAdminCollectionTask(task.id);
      setItems((prev) => prev.filter((item) => item.id !== task.id));
      setNotice(result.action === "archived" ? "任务已归档隐藏，红人库和来源追溯数据仍保留。" : "任务已删除。");
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "删除任务失败。");
    } finally {
      setDeletingTaskId(null);
    }
  }

  async function handleCleanupCurrentRows() {
    if (!cleanupCandidates.length) return;
    if (!window.confirm(`确定清理当前筛选下 ${cleanupCandidates.length} 个无入库、非运行任务吗？有追溯数据的会归档隐藏。`)) return;
    setBulkDeleting(true);
    setActionError(null);
    setNotice(null);
    try {
      const result = await bulkDeleteAdminCollectionTasks(cleanupCandidates.map((task) => task.id));
      const removedIds = [...result.deleted_ids, ...result.archived_ids];
      setItems((prev) => prev.filter((item) => !removedIds.includes(item.id)));
      setNotice(`已清理 ${removedIds.length} 个无入库任务${result.skipped_count ? `，跳过 ${result.skipped_count} 个运行中或不可删除任务` : ""}。`);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "批量清理失败。");
    } finally {
      setBulkDeleting(false);
    }
  }

  return (
    <div className="space-y-3">
      <AdminPageHeader
        label="采集任务"
        title="任务监控中心"
        description="按状态、平台、品牌和业务员归纳任务进度，管理员可以快速定位异常和清理无用任务。"
        backFallback="/admin/dashboard"
        actions={
          <AdminActionButton onClick={() => void handleCleanupCurrentRows()} disabled={bulkDeleting || cleanupCandidates.length === 0}>
            <RefreshCw className="h-3.5 w-3.5" />
            {bulkDeleting ? "清理中..." : `清理无入库任务 (${cleanupCandidates.length})`}
          </AdminActionButton>
        }
      />
      <AdminKpiGrid>
        <AdminKpiCard label="任务总数" value={items.length} helper="全部任务" icon={RefreshCw} tone="info" />
        <AdminKpiCard label="已完成" value={items.filter((item) => getCollectionTaskStatusMeta(item.status).tone === "success").length} helper="完成或有结果" icon={ShieldCheck} tone="success" />
        <AdminKpiCard label="需关注" value={failed + warning} helper={`${formatAdminNumber(running)} 个运行/排队`} icon={AlertTriangle} tone={failed ? "danger" : "warning"} />
        <AdminKpiCard label="入库 / 无入库" value={`${formatAdminNumber(items.reduce((sum, item) => sum + (item.inserted_count || item.result_count || 0), 0))} / ${formatAdminNumber(noResult)}`} helper="结果沉淀 / 可清理线索" icon={Database} tone="info" />
      </AdminKpiGrid>
      {actionError ? <div className="rounded-lg border border-[#FECACA] bg-[#FEF2F2] px-4 py-3 text-sm text-[#B42318]">{actionError}</div> : null}
      {notice ? <div className="rounded-lg border border-[#BBF7D0] bg-[#F0FDF4] px-4 py-3 text-sm text-[#047857]">{notice}</div> : null}
      <div className="grid gap-3 xl:grid-cols-4">
        <ProductDistributionPanel title="状态分布" items={countBy(items, (item) => getCollectionTaskStatusMeta(item.status).label)} />
        <ProductDistributionPanel title="平台分布" items={countBy(items, (item) => item.platform)} formatKey={getPlatformLabel} />
        <ProductDistributionPanel title="品牌分布" items={countBy(items, (item) => item.product_name)} />
        <ProductDistributionPanel title="业务员分布" items={countBy(items, (item) => item.username)} />
      </div>
      <AdminFilterBar>
        <AdminFilterField label="搜索任务" className="min-w-[220px] flex-1"><AdminInput value={filters.search} placeholder="任务名或品牌" onChange={(event) => setFilters((prev) => ({ ...prev, search: event.target.value }))} /></AdminFilterField>
        <AdminFilterField label="业务员"><AdminInput value={filters.owner} placeholder="业务员" onChange={(event) => setFilters((prev) => ({ ...prev, owner: event.target.value }))} /></AdminFilterField>
        <AdminFilterField label="品牌"><AdminInput value={filters.brand} placeholder="品牌" onChange={(event) => setFilters((prev) => ({ ...prev, brand: event.target.value }))} /></AdminFilterField>
        <AdminFilterField label="状态"><AdminSelect value={filters.status} onChange={(event) => setFilters((prev) => ({ ...prev, status: event.target.value }))}><option value="">全部状态</option><option value="queued">排队中</option><option value="running">采集中</option><option value="completed">已完成</option><option value="completed_with_results">有结果</option><option value="completed_without_results">无结果</option><option value="failed">失败</option><option value="cancelled">已取消</option></AdminSelect></AdminFilterField>
        <AdminFilterField label="平台"><AdminSelect value={filters.platform} onChange={(event) => setFilters((prev) => ({ ...prev, platform: event.target.value }))}><option value="">全部平台</option><option value="instagram">Instagram</option><option value="youtube">YouTube</option><option value="tiktok">TikTok</option><option value="facebook">Facebook</option></AdminSelect></AdminFilterField>
        <AdminFilterField label="开始时间"><AdminInput type="date" value={filters.startDate} onChange={(event) => setFilters((prev) => ({ ...prev, startDate: event.target.value }))} /></AdminFilterField>
        <AdminFilterField label="结束时间"><AdminInput type="date" value={filters.endDate} onChange={(event) => setFilters((prev) => ({ ...prev, endDate: event.target.value }))} /></AdminFilterField>
      </AdminFilterBar>
      <AdminSection title="任务列表" description="先按进度分类，再进入表格查看具体任务。删除后会立即从列表移除。">
        <DetailTabs tabs={taskViewTabs} activeTab={activeTaskView} onChange={setActiveTaskView} />
        {loading ? <AdminState type="loading" message="正在加载采集任务..." /> : error ? <AdminState type="error" message={error} /> : <TasksTable items={rows} onDeleteTask={handleDeleteTask} deletingTaskId={deletingTaskId} />}
      </AdminSection>
    </div>
  );
}

export function AdminInfluencersPanel() {
  const [items, setItems] = useState<AdminInfluencer[]>([]);
  const [products, setProducts] = useState<AdminProduct[]>([]);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [productCreateOpen, setProductCreateOpen] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [deletingItem, setDeletingItem] = useState<AdminInfluencer | null>(null);
  const [deleteLoading, setDeleteLoading] = useState(false);
  const [filters, setFilters] = useState({ search: "", owner: "", brand: "", platform: "", minFollowers: "", maxFollowers: "", hasEmail: "", contacted: "", replied: "" });

  const reload = useCallback(async () => {
    const [influencerRows, productRows, userRows] = await Promise.all([
      fetchAdminInfluencers(),
      fetchAdminProducts(),
      fetchAdminUsers(),
    ]);
    setItems(influencerRows);
    setProducts(productRows);
    setUsers(userRows);
  }, []);

  useEffect(() => {
    let active = true;
    queueMicrotask(() => {
      if (!active) return;
      void reload()
        .catch((err) => {
          if (active) setError(err instanceof Error ? err.message : "红人数据加载失败。");
        })
        .finally(() => {
          if (active) setLoading(false);
        });
    });
    return () => {
      active = false;
    };
  }, [reload]);

  const brandOptions = useMemo(() => {
    const names = new Set<string>();
    for (const product of products) {
      if (product.name) names.add(product.name);
    }
    for (const item of items) {
      if (item.product_name) names.add(item.product_name);
    }
    return Array.from(names).sort((a, b) => a.localeCompare(b, "zh-Hans-CN"));
  }, [items, products]);

  function handleProductCreated(product: TenantProduct) {
    setFilters((prev) => ({ ...prev, brand: product.name }));
    fetchAdminProducts()
      .then(setProducts)
      .catch(() => {
        setProducts((prev) => [
          {
            id: product.id,
            name: product.name,
            subject: null,
            slug: product.slug,
            created_at: product.created_at ?? null,
            updated_at: product.updated_at ?? null,
            members: [],
            owner_names: [],
            collection_task_count: 0,
            influencer_count: 0,
            email_count: 0,
            reply_count: 0,
            status: product.is_archived ? "archived" : product.is_hidden ? "hidden" : "active",
          },
          ...prev,
        ]);
      });
  }

  const rows = useMemo(() => {
    const base = filterAdminRows(
      items.map((item) => ({
        ...item,
        name: `${item.username} ${item.display_name ?? ""}`,
        brand: item.product_name,
        platform: item.platform,
        status: item.follow_status,
        createdAt: item.created_at,
        email: item.email,
      })),
      filters,
    );
    return base.filter((item) => {
      if (filters.minFollowers && (item.followers_count ?? 0) < Number(filters.minFollowers)) return false;
      if (filters.maxFollowers && (item.followers_count ?? 0) > Number(filters.maxFollowers)) return false;
      if (filters.hasEmail === "yes" && !item.email) return false;
      if (filters.hasEmail === "no" && item.email) return false;
      if (filters.contacted === "yes" && !item.follow_status) return false;
      if (filters.contacted === "no" && item.follow_status) return false;
      if (filters.replied === "yes" && item.follow_status !== "replied") return false;
      if (filters.replied === "no" && item.follow_status === "replied") return false;
      return true;
    });
  }, [items, filters]);

  return (
    <div className="space-y-3">
      <AdminPageHeader
        label="红人数据"
        title="红人资料库"
        description="按平台、品牌、邮箱质量、联系状态和回复状态筛选红人，支持编辑、删除和状态处理。"
        backFallback="/admin/dashboard"
      />
      <AdminFeedbackBanner message={successMessage} />
      <AdminFeedbackBanner message={error} tone="error" />
      <AdminKpiGrid>
        <AdminKpiCard label="红人总数" value={items.length} helper="资料库记录" icon={Database} tone="info" />
        <AdminKpiCard label="有邮箱" value={items.filter((item) => Boolean(item.email)).length} helper="可外联" icon={Mail} tone="success" />
        <AdminKpiCard label="已回复" value={items.filter((item) => item.follow_status === "replied").length} helper="跟进优先" icon={Send} tone="success" />
        <AdminKpiCard label="无邮箱" value={items.filter((item) => !item.email).length} helper="数据质量" icon={AlertTriangle} tone="warning" />
      </AdminKpiGrid>
      <AdminFilterBar>
        <AdminFilterField label="搜索红人" className="min-w-[220px] flex-1"><AdminInput value={filters.search} placeholder="名称、邮箱或品牌" onChange={(event) => setFilters((prev) => ({ ...prev, search: event.target.value }))} /></AdminFilterField>
        <AdminFilterField label="平台"><AdminSelect value={filters.platform} onChange={(event) => setFilters((prev) => ({ ...prev, platform: event.target.value }))}><option value="">全部平台</option><option value="instagram">Instagram</option><option value="youtube">YouTube</option><option value="tiktok">TikTok</option><option value="facebook">Facebook</option></AdminSelect></AdminFilterField>
        <AdminFilterField label="品牌" className="min-w-[280px]">
          <div className="flex gap-2">
            <AdminSelect
              className="min-w-0 flex-1"
              value={filters.brand}
              onChange={(event) => setFilters((prev) => ({ ...prev, brand: event.target.value }))}
            >
              <option value="">全部品牌</option>
              {brandOptions.map((brand) => (
                <option key={brand} value={brand}>
                  {brand}
                </option>
              ))}
            </AdminSelect>
            <AdminActionButton onClick={() => setProductCreateOpen(true)}>
              <Plus className="h-3.5 w-3.5" />
              新增品牌
            </AdminActionButton>
          </div>
        </AdminFilterField>
        <AdminFilterField label="业务员"><AdminInput value={filters.owner} placeholder="暂无字段" onChange={(event) => setFilters((prev) => ({ ...prev, owner: event.target.value }))} /></AdminFilterField>
        <AdminFilterField label="最低粉丝"><AdminInput type="number" value={filters.minFollowers} onChange={(event) => setFilters((prev) => ({ ...prev, minFollowers: event.target.value }))} /></AdminFilterField>
        <AdminFilterField label="最高粉丝"><AdminInput type="number" value={filters.maxFollowers} onChange={(event) => setFilters((prev) => ({ ...prev, maxFollowers: event.target.value }))} /></AdminFilterField>
        <AdminFilterField label="是否有邮箱"><AdminSelect value={filters.hasEmail} onChange={(event) => setFilters((prev) => ({ ...prev, hasEmail: event.target.value }))}><option value="">全部</option><option value="yes">有邮箱</option><option value="no">无邮箱</option></AdminSelect></AdminFilterField>
        <AdminFilterField label="是否已联系"><AdminSelect value={filters.contacted} onChange={(event) => setFilters((prev) => ({ ...prev, contacted: event.target.value }))}><option value="">全部</option><option value="yes">已联系</option><option value="no">未联系</option></AdminSelect></AdminFilterField>
        <AdminFilterField label="是否已回复"><AdminSelect value={filters.replied} onChange={(event) => setFilters((prev) => ({ ...prev, replied: event.target.value }))}><option value="">全部</option><option value="yes">已回复</option><option value="no">未回复</option></AdminSelect></AdminFilterField>
      </AdminFilterBar>
      <AdminSection title="红人列表" description="支持详情、编辑、删除，以及标记联系/回复/无效邮箱等快捷操作。">
        {loading ? (
          <AdminState type="loading" message="正在加载红人数据..." />
        ) : (
          <InfluencersTable
            items={rows}
            onEdit={(item) => setEditingId(item.id)}
            onDelete={(item) => setDeletingItem(item)}
            onQuickAction={async (action, item) => {
              try {
                await applyInfluencerQuickAction(item.id, action);
                await reload();
                setSuccessMessage("红人状态已更新。");
              } catch (err) {
                setError(err instanceof Error ? err.message : "操作失败。");
              }
            }}
          />
        )}
      </AdminSection>
      <InfluencerEditDrawer
        open={editingId != null}
        influencerId={editingId}
        products={products}
        users={users}
        onClose={() => setEditingId(null)}
        onSaved={async () => {
          await reload();
          setSuccessMessage("红人资料已保存。");
        }}
      />
      <InfluencerDeleteConfirmDialog
        open={Boolean(deletingItem)}
        influencer={deletingItem}
        loading={deleteLoading}
        onCancel={() => setDeletingItem(null)}
        onConfirm={async () => {
          if (!deletingItem) return;
          setDeleteLoading(true);
          try {
            const result = await deleteInfluencerSafely(deletingItem);
            if (result.mode === "archived") {
              await reload();
              setSuccessMessage("红人已归档（存在业务数据，未物理删除）。");
            } else {
              setItems((prev) => prev.filter((row) => row.id !== deletingItem.id));
              setSuccessMessage("红人已删除。");
            }
            setDeletingItem(null);
          } catch (err) {
            setError(err instanceof Error ? err.message : "删除红人失败。");
          } finally {
            setDeleteLoading(false);
          }
        }}
      />
      <ProductCreateDialog
        open={productCreateOpen}
        onClose={() => setProductCreateOpen(false)}
        onCreated={handleProductCreated}
      />
    </div>
  );
}

export function AdminEmailsPanel() {
  const [emails, setEmails] = useState<AdminEmail[]>([]);
  const [replies, setReplies] = useState<AdminReply[]>([]);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [editReply, setEditReply] = useState<AdminReply | null>(null);
  const [editEmail, setEditEmail] = useState<AdminEmail | null>(null);
  const [filters, setFilters] = useState({ search: "", owner: "", brand: "", status: "" });

  const reload = useCallback(async () => {
    const [emailRows, replyRows, userRows] = await Promise.all([
      fetchAdminEmails(),
      fetchAdminReplies(),
      fetchAdminUsers(),
    ]);
    setEmails(emailRows);
    setReplies(replyRows);
    setUsers(userRows);
  }, []);

  useEffect(() => {
    let active = true;
    queueMicrotask(() => {
      if (!active) return;
      void reload()
        .catch((err) => {
          if (active) setError(err instanceof Error ? err.message : "邮件与回复加载失败。");
        })
        .finally(() => {
          if (active) setLoading(false);
        });
    });
    return () => {
      active = false;
    };
  }, [reload]);

  async function remindEmail(item: AdminEmail) {
    upsertAdminWorkQueueEntry({ type: "email", id: item.id, assigneeUserId: item.user_id, status: "reminded" });
    setSuccessMessage("已提醒业务员跟进该邮件。");
    await reload();
  }

  async function markEmailHandled(item: AdminEmail) {
    upsertAdminWorkQueueEntry({ type: "email", id: item.id, status: "handled" });
    setSuccessMessage("邮件已标记为已处理。");
    await reload();
  }

  async function remindReply(item: AdminReply) {
    upsertAdminWorkQueueEntry({ type: "reply", id: item.id, assigneeUserId: item.user_id, status: "reminded" });
    await updateEmailReply(item.id, {
      manual_note: `[管理员提醒跟进] ${new Date().toLocaleString("zh-CN")}`,
    });
    setSuccessMessage("已提醒业务员处理该回复。");
    await reload();
  }

  async function markReplyHandled(item: AdminReply) {
    await updateEmailReply(item.id, { processing_status: "processed" });
    upsertAdminWorkQueueEntry({ type: "reply", id: item.id, status: "handled" });
    setSuccessMessage("回复已标记为已处理。");
    await reload();
  }

  const filteredEmails = useMemo(
    () =>
      filterAdminRows(
        emails.map((item) => ({
          ...item,
          name: item.subject,
          brand: item.product_name,
          owner: item.username,
          status: item.has_replied ? "replied" : item.status,
          subject: item.subject,
          recipient: (item.recipients ?? []).join(" "),
          createdAt: item.sent_at,
        })),
        filters,
      ),
    [emails, filters],
  );

  return (
    <div className="space-y-3">
      <AdminPageHeader
        label="邮件回复"
        title="待跟进中心"
        description="统一管理邮件待跟进与回复待处理，支持提醒、编辑和状态流转。"
        backFallback="/admin/dashboard"
      />
      <AdminFeedbackBanner message={successMessage} />
      <AdminFeedbackBanner message={error} tone="error" />
      <AdminSalesReminderBanner users={users} />
      <AdminKpiGrid>
        <AdminKpiCard label="邮件总数" value={emails.length} helper="外联记录" icon={Mail} tone="info" />
        <AdminKpiCard label="发送失败" value={emails.filter((item) => getEmailStatusMeta(item.status).tone === "danger").length} helper="需要重发" icon={AlertTriangle} tone="danger" />
        <AdminKpiCard label="已回复" value={emails.filter((item) => item.has_replied).length} helper="需要跟进" icon={Send} tone="success" />
        <AdminKpiCard label="待处理回复" value={replies.filter((item) => item.processing_status !== "handled" && item.processing_status !== "processed").length} helper="回复中心" icon={ShieldCheck} tone="warning" />
      </AdminKpiGrid>
      {loading ? (
        <AdminState type="loading" message="正在加载邮件与回复..." />
      ) : error ? (
        <AdminState type="error" message={error} />
      ) : (
        <>
          <AdminFollowUpWorkbench emails={emails} replies={replies} users={users} onReload={reload} />
          <AdminFilterBar>
            <AdminFilterField label="搜索邮件" className="min-w-[200px] flex-1">
              <AdminInput value={filters.search} placeholder="主题、收件人或品牌" onChange={(event) => setFilters((prev) => ({ ...prev, search: event.target.value }))} />
            </AdminFilterField>
            <AdminFilterField label="业务员">
              <AdminInput value={filters.owner} placeholder="业务员" onChange={(event) => setFilters((prev) => ({ ...prev, owner: event.target.value }))} />
            </AdminFilterField>
            <AdminFilterField label="品牌">
              <AdminInput value={filters.brand} placeholder="品牌" onChange={(event) => setFilters((prev) => ({ ...prev, brand: event.target.value }))} />
            </AdminFilterField>
            <AdminFilterField label="状态">
              <AdminSelect value={filters.status} onChange={(event) => setFilters((prev) => ({ ...prev, status: event.target.value }))}>
                <option value="">全部状态</option>
                <option value="sent">已发送</option>
                <option value="failed">发送失败</option>
                <option value="replied">已回复</option>
                <option value="pending">待跟进</option>
              </AdminSelect>
            </AdminFilterField>
          </AdminFilterBar>
          <AdminSection title="全部邮件记录" description="完整外联发送记录，可编辑跟进状态。">
            <EmailsTable
              items={filteredEmails}
              onEdit={setEditEmail}
              onRemind={(item) => void remindEmail(item)}
              onMarkHandled={(item) => void markEmailHandled(item)}
            />
          </AdminSection>
          <AdminSection title="全部回复记录" description="完整回复列表，可编辑处理与意向状态。">
            <RepliesTable
              items={replies}
              onEdit={setEditReply}
              onRemind={(item) => void remindReply(item)}
              onMarkHandled={(item) => void markReplyHandled(item)}
            />
          </AdminSection>
          <ReplyHandleDrawer
            open={Boolean(editReply)}
            reply={editReply}
            onClose={() => setEditReply(null)}
            onSaved={async () => {
              setSuccessMessage("回复处理状态已更新。");
              await reload();
            }}
          />
          <EmailEditDrawer
            open={Boolean(editEmail)}
            email={editEmail}
            onClose={() => setEditEmail(null)}
            onSaved={async () => {
              setSuccessMessage("邮件跟进状态已更新。");
              await reload();
            }}
          />
        </>
      )}
    </div>
  );
}

export function AdminSettingsPanel() {
  const modules = [
    ["异常中心", "集中展示失败任务、发送失败、无邮箱红人、低回复品牌。", "建议新增"],
    ["数据质量", "识别重复红人、无效邮箱、缺失字段和异常粉丝数。", "建议新增"],
    ["品牌详情页", "已提供品牌下任务、红人、邮件和回复链路。", "已接入"],
    ["业务员绩效页", "已通过业务员详情展示任务完成率、回复率和数据量。", "已接入"],
    ["批量操作中心", "批量分配、导出、重跑和发信可继续扩展为独立入口。", "建议新增"],
  ];

  return (
    <div className="space-y-3">
      <AdminPageHeader label="系统信息" title="后台模块与系统状态" description="查看管理员后台基础状态，并沉淀后续可扩展的运营管理模块。" backFallback="/admin/dashboard" />
      <AdminKpiGrid>
        <AdminKpiCard label="管理员模块" value="已启用" helper="仅管理员可访问" icon={ShieldCheck} tone="success" />
        <AdminKpiCard label="数据来源" value="现有真实表" helper="无新增接口依赖" icon={Database} tone="info" />
        <AdminKpiCard label="状态语言" value="中文展示" helper="隐藏技术字段" icon={FileText} tone="success" />
        <AdminKpiCard label="响应式" value="已适配" helper="窄屏横向滚动" icon={RefreshCw} tone="info" />
      </AdminKpiGrid>
      <AdminSection title="建议新增模块" description="在不影响现有接口的前提下，先形成清晰的信息架构入口。">
        <AdminTable minWidth={760} columns={["模块", "用途", "状态"]} rows={modules.map((item) => [item[0], item[1], <AdminStatusBadge key={item[0]} meta={{ label: item[2], tone: item[2] === "已接入" ? "success" : "warning" }} />])} />
      </AdminSection>
    </div>
  );
}
