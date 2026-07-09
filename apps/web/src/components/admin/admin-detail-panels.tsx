"use client";

import { useEffect, useMemo, useState } from "react";
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
import { ProductCreateDialog } from "@/components/layout/product-create-dialog";
import {
  filterAdminRows,
  formatAdminDate,
  formatAdminNumber,
  getCollectionTaskStatusMeta,
  getEmailStatusMeta,
  getEmailValidityLabel,
  getInfluencerStatusMeta,
  getPlatformLabel,
  getProductStatusMeta,
  getReplyStateLabel,
  getRoleLabel,
} from "@/components/admin/admin-ui-helpers";
import {
  type AdminCollectionTask,
  type AdminEmail,
  type AdminInfluencer,
  type AdminProduct,
  type AdminReply,
  type AdminUser,
  type TenantProduct,
  fetchAdminCollectionTasks,
  fetchAdminEmails,
  fetchAdminInfluencers,
  fetchAdminProduct,
  fetchAdminProducts,
  fetchAdminReplies,
  fetchAdminUser,
  fetchAdminUserCollectionTasks,
  fetchAdminUserEmails,
  fetchAdminUserInfluencers,
  fetchAdminUserProducts,
  fetchAdminUserReplies,
} from "@/lib/api";

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

function TasksTable({ items }: { items: AdminCollectionTask[] }) {
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
            { label: "标记异常", disabled: true, danger: true },
          ]}
        />,
      ])}
      emptyMessage="暂无采集任务。"
    />
  );
}

function InfluencersTable({ items }: { items: AdminInfluencer[] }) {
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
          primaryHref={`/influencers/${item.id}`}
          primaryLabel="详情"
          items={[
            { label: "发送邮件", disabled: true },
            { label: "标记无效", disabled: true, danger: true },
            { label: "加入黑名单", disabled: true, danger: true },
            { label: "导出", disabled: true },
          ]}
        />,
      ])}
      emptyMessage="暂无红人数据。"
    />
  );
}

function EmailsTable({ items }: { items: AdminEmail[] }) {
  return (
    <AdminTable
      minWidth={1180}
      columns={["邮件主题", "品牌", "业务员", "收件人", "发送状态", "是否回复", "跟进状态", "发送时间", "最近回复时间", "操作"]}
      rows={items.map((item) => [
        <span key="subject" className="block max-w-[260px] truncate font-medium text-[#102033]">{item.subject || "暂无主题"}</span>,
        item.product_name ?? "暂无",
        item.username ?? "暂无",
        item.recipients.join("、") || item.influencer_username || "暂无",
        <AdminStatusBadge key="status" meta={getEmailStatusMeta(item.status)} />,
        <AdminStatusBadge key="reply" meta={getReplyStateLabel(item.has_replied)} />,
        <AdminStatusBadge key="follow" meta={item.has_replied ? getEmailStatusMeta("pending") : getEmailStatusMeta(item.status)} />,
        formatAdminDate(item.sent_at),
        formatAdminDate(item.replied_at),
        <AdminCompactActions
          key="actions"
          primaryLabel="邮件"
          items={[
            { label: "查看红人", href: item.product_influencer_id ? `/influencers/${item.product_influencer_id}` : undefined, disabled: !item.product_influencer_id },
            { label: "分配跟进人", disabled: true },
            { label: "标记已处理", disabled: true },
            { label: "再次发送", disabled: true },
          ]}
        />,
      ])}
      emptyMessage="暂无邮件记录。"
    />
  );
}

function RepliesTable({ items }: { items: AdminReply[] }) {
  return (
    <AdminTable
      minWidth={980}
      columns={["邮件主题", "品牌", "业务员", "发件人", "处理状态", "意向状态", "收到时间", "处理时间", "操作"]}
      rows={items.map((item) => [
        <span key="subject" className="block max-w-[260px] truncate font-medium text-[#102033]">{item.subject || "暂无主题"}</span>,
        item.product_name ?? "暂无",
        item.username ?? "暂无",
        item.from_address,
        <AdminStatusBadge key="processing" meta={getEmailStatusMeta(item.processing_status)} />,
        <AdminStatusBadge key="intent" meta={getEmailStatusMeta(item.intent_status)} />,
        formatAdminDate(item.received_at),
        formatAdminDate(item.handled_at),
        <AdminCompactActions
          key="actions"
          primaryLabel="邮件"
          items={[
            { label: "标记已处理", disabled: true },
          ]}
        />,
      ])}
      emptyMessage="暂无回复记录。"
    />
  );
}

export function AdminUserDetailPanel({ userId }: { userId: number }) {
  const [data, setData] = useState<{
    user: AdminUser;
    products: AdminProduct[];
    tasks: AdminCollectionTask[];
    influencers: AdminInfluencer[];
    emails: AdminEmail[];
    replies: AdminReply[];
  } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    Promise.all([
      fetchAdminUser(userId),
      fetchAdminUserProducts(userId),
      fetchAdminUserCollectionTasks(userId),
      fetchAdminUserInfluencers(userId),
      fetchAdminUserEmails(userId),
      fetchAdminUserReplies(userId),
    ])
      .then(([user, products, tasks, influencers, emails, replies]) => {
        if (active) setData({ user, products, tasks, influencers, emails, replies });
      })
      .catch((err) => {
        if (active) setError(err instanceof Error ? err.message : "业务员详情加载失败。");
      });
    return () => {
      active = false;
    };
  }, [userId]);

  if (error) return <AdminState type="error" message={error} />;
  if (!data) return <AdminState type="loading" message="正在加载业务员详情..." />;

  const { user, products, tasks, influencers, emails, replies } = data;

  return (
    <div className="space-y-5">
      <AdminPageHeader
        label="业务员详情"
        title={`${user.username}（#${user.id}）`}
        description="查看该账号从品牌负责、任务执行、红人沉淀到邮件回复的完整链路。"
        actions={<AdminActionButton href="/admin/users">返回业务员列表</AdminActionButton>}
      />
      <AdminKpiGrid>
        <AdminKpiCard label="角色" value={getRoleLabel(user.role)} helper={user.is_active ? "账号启用" : "账号禁用"} icon={ShieldCheck} tone={user.is_active ? "success" : "muted"} />
        <AdminKpiCard label="负责品牌数" value={user.product_count} helper="绑定品牌" icon={Database} tone="info" />
        <AdminKpiCard label="任务成功 / 失败" value={`${formatAdminNumber(user.collection_success_count)} / ${formatAdminNumber(user.collection_failed_count)}`} helper="采集表现" icon={RefreshCw} tone="info" />
        <AdminKpiCard label="回复 / 待处理" value={`${formatAdminNumber(user.reply_count)} / ${formatAdminNumber(user.pending_reply_count)}`} helper="跟进压力" icon={Mail} tone="warning" />
      </AdminKpiGrid>
      <SectionWithTable title="负责品牌"><AdminTable columns={["品牌", "SLUG", "状态", "成员"]} rows={products.map((item) => [item.name, item.slug, <AdminStatusBadge key="status" meta={getProductStatusMeta(item.status)} />, item.members.map((member) => member.username).join("、") || "暂无"])} /></SectionWithTable>
      <SectionWithTable title="采集任务"><TasksTable items={tasks} /></SectionWithTable>
      <SectionWithTable title="红人数据"><InfluencersTable items={influencers} /></SectionWithTable>
      <SectionWithTable title="邮件记录"><EmailsTable items={emails} /></SectionWithTable>
      <SectionWithTable title="回复记录"><RepliesTable items={replies} /></SectionWithTable>
    </div>
  );
}

export function AdminProductDetailPanel({ productId }: { productId: number }) {
  const [product, setProduct] = useState<AdminProduct | null>(null);
  const [error, setError] = useState<string | null>(null);

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

  return (
    <div className="space-y-5">
      <AdminPageHeader
        label="品牌详情"
        title={`${product.name}（#${product.id}）`}
        description="展示品牌下的任务、红人、邮件和回复链路，便于判断品牌当前处在哪个运营阶段。"
        actions={<AdminActionButton href="/admin/products">返回品牌列表</AdminActionButton>}
      />
      <AdminKpiGrid>
        <AdminKpiCard label="状态" value={getProductStatusMeta(product.status).label} helper={product.slug} icon={ShoppingBag} tone={getProductStatusMeta(product.status).tone} />
        <AdminKpiCard label="任务数" value={product.collection_task_count} helper="采集任务" icon={RefreshCw} tone="info" />
        <AdminKpiCard label="红人数" value={product.influencer_count} helper="资料库" icon={Database} tone="info" />
        <AdminKpiCard label="邮件 / 回复" value={`${formatAdminNumber(product.email_count)} / ${formatAdminNumber(product.reply_count)}`} helper="外联进度" icon={Mail} tone="success" />
      </AdminKpiGrid>
      <SectionWithTable title="品牌成员">
        <AdminTable columns={["用户 ID", "用户名", "角色", "加入时间"]} rows={product.members.map((item) => [`#${item.user_id}`, item.username, getRoleLabel(item.role), "暂无"])} />
      </SectionWithTable>
      <SectionWithTable title="采集任务"><TasksTable items={product.collection_tasks ?? []} /></SectionWithTable>
      <SectionWithTable title="红人数据"><InfluencersTable items={product.influencers ?? []} /></SectionWithTable>
      <SectionWithTable title="邮件记录"><EmailsTable items={product.emails ?? []} /></SectionWithTable>
      <SectionWithTable title="回复记录"><RepliesTable items={product.replies ?? []} /></SectionWithTable>
    </div>
  );
}

export function AdminCollectionTasksPanel() {
  const [items, setItems] = useState<AdminCollectionTask[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState({ search: "", owner: "", brand: "", status: "", platform: "", startDate: "", endDate: "" });

  useEffect(() => {
    fetchAdminCollectionTasks()
      .then(setItems)
      .catch((err) => setError(err instanceof Error ? err.message : "采集任务加载失败。"))
      .finally(() => setLoading(false));
  }, []);

  const rows = useMemo(
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
  const failed = items.filter((item) => getCollectionTaskStatusMeta(item.status).tone === "danger").length;

  return (
    <div className="space-y-5">
      <AdminPageHeader
        label="采集任务"
        title="任务监控中心"
        description="集中查看任务队列、采集状态、入库结果和失败原因，支持管理员快速重跑、导出和标记异常。"
        actions={<AdminActionButton><RefreshCw className="h-3.5 w-3.5" />批量重试</AdminActionButton>}
      />
      <AdminKpiGrid>
        <AdminKpiCard label="任务总数" value={items.length} helper="全部任务" icon={RefreshCw} tone="info" />
        <AdminKpiCard label="已完成" value={items.filter((item) => getCollectionTaskStatusMeta(item.status).tone === "success").length} helper="完成或有结果" icon={ShieldCheck} tone="success" />
        <AdminKpiCard label="失败任务" value={failed} helper="需要查看日志" icon={AlertTriangle} tone="danger" />
        <AdminKpiCard label="入库总数" value={items.reduce((sum, item) => sum + (item.inserted_count || item.result_count || 0), 0)} helper="任务结果" icon={Database} tone="info" />
      </AdminKpiGrid>
      <AdminFilterBar>
        <AdminFilterField label="搜索任务" className="min-w-[220px] flex-1"><AdminInput value={filters.search} placeholder="任务名或品牌" onChange={(event) => setFilters((prev) => ({ ...prev, search: event.target.value }))} /></AdminFilterField>
        <AdminFilterField label="业务员"><AdminInput value={filters.owner} placeholder="业务员" onChange={(event) => setFilters((prev) => ({ ...prev, owner: event.target.value }))} /></AdminFilterField>
        <AdminFilterField label="品牌"><AdminInput value={filters.brand} placeholder="品牌" onChange={(event) => setFilters((prev) => ({ ...prev, brand: event.target.value }))} /></AdminFilterField>
        <AdminFilterField label="状态"><AdminSelect value={filters.status} onChange={(event) => setFilters((prev) => ({ ...prev, status: event.target.value }))}><option value="">全部状态</option><option value="queued">排队中</option><option value="running">采集中</option><option value="completed">已完成</option><option value="completed_with_results">有结果</option><option value="completed_without_results">无结果</option><option value="failed">失败</option><option value="cancelled">已取消</option></AdminSelect></AdminFilterField>
        <AdminFilterField label="平台"><AdminSelect value={filters.platform} onChange={(event) => setFilters((prev) => ({ ...prev, platform: event.target.value }))}><option value="">全部平台</option><option value="instagram">Instagram</option><option value="youtube">YouTube</option><option value="tiktok">TikTok</option><option value="facebook">Facebook</option></AdminSelect></AdminFilterField>
        <AdminFilterField label="开始时间"><AdminInput type="date" value={filters.startDate} onChange={(event) => setFilters((prev) => ({ ...prev, startDate: event.target.value }))} /></AdminFilterField>
        <AdminFilterField label="结束时间"><AdminInput type="date" value={filters.endDate} onChange={(event) => setFilters((prev) => ({ ...prev, endDate: event.target.value }))} /></AdminFilterField>
      </AdminFilterBar>
      <AdminSection title="任务列表" description="状态已中文化，失败原因没有后端字段时兼容显示“暂无”。">
        {loading ? <AdminState type="loading" message="正在加载采集任务..." /> : error ? <AdminState type="error" message={error} /> : <TasksTable items={rows} />}
      </AdminSection>
    </div>
  );
}

export function AdminInfluencersPanel() {
  const [items, setItems] = useState<AdminInfluencer[]>([]);
  const [products, setProducts] = useState<AdminProduct[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [productCreateOpen, setProductCreateOpen] = useState(false);
  const [filters, setFilters] = useState({ search: "", owner: "", brand: "", platform: "", minFollowers: "", maxFollowers: "", hasEmail: "", contacted: "", replied: "" });

  useEffect(() => {
    Promise.all([fetchAdminInfluencers(), fetchAdminProducts()])
      .then(([influencerRows, productRows]) => {
        setItems(influencerRows);
        setProducts(productRows);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "红人数据加载失败。"))
      .finally(() => setLoading(false));
  }, []);

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
    <div className="space-y-5">
      <AdminPageHeader label="红人数据" title="红人资料库" description="按平台、品牌、邮箱质量、联系状态和回复状态筛选红人，支持外联和数据质量处理。" actions={<AdminActionButton><Download className="h-3.5 w-3.5" />导出</AdminActionButton>} />
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
      <AdminSection title="红人列表" description="邮箱和联系状态以管理员可处理的中文标签展示。">
        {loading ? <AdminState type="loading" message="正在加载红人数据..." /> : error ? <AdminState type="error" message={error} /> : <InfluencersTable items={rows} />}
      </AdminSection>
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
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState({ search: "", owner: "", brand: "", status: "" });

  useEffect(() => {
    Promise.all([fetchAdminEmails(), fetchAdminReplies()])
      .then(([emailRows, replyRows]) => {
        setEmails(emailRows);
        setReplies(replyRows);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "邮件与回复加载失败。"))
      .finally(() => setLoading(false));
  }, []);

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
          recipient: item.recipients.join(" "),
          createdAt: item.sent_at,
        })),
        filters,
      ),
    [emails, filters],
  );

  return (
    <div className="space-y-5">
      <AdminPageHeader label="邮件回复" title="邮件跟进工作台" description="集中查看发送状态、回复状态和待跟进邮件，帮助管理员分配跟进人并完成处理闭环。" actions={<AdminActionButton>批量标记已处理</AdminActionButton>} />
      <AdminKpiGrid>
        <AdminKpiCard label="邮件总数" value={emails.length} helper="外联记录" icon={Mail} tone="info" />
        <AdminKpiCard label="发送失败" value={emails.filter((item) => getEmailStatusMeta(item.status).tone === "danger").length} helper="需要重发" icon={AlertTriangle} tone="danger" />
        <AdminKpiCard label="已回复" value={emails.filter((item) => item.has_replied).length} helper="需要跟进" icon={Send} tone="success" />
        <AdminKpiCard label="待处理回复" value={replies.filter((item) => item.processing_status !== "handled" && item.processing_status !== "processed").length} helper="回复中心" icon={ShieldCheck} tone="warning" />
      </AdminKpiGrid>
      <AdminFilterBar>
        <AdminFilterField label="搜索邮件" className="min-w-[240px] flex-1"><AdminInput value={filters.search} placeholder="主题、收件人或品牌" onChange={(event) => setFilters((prev) => ({ ...prev, search: event.target.value }))} /></AdminFilterField>
        <AdminFilterField label="业务员"><AdminInput value={filters.owner} placeholder="业务员" onChange={(event) => setFilters((prev) => ({ ...prev, owner: event.target.value }))} /></AdminFilterField>
        <AdminFilterField label="品牌"><AdminInput value={filters.brand} placeholder="品牌" onChange={(event) => setFilters((prev) => ({ ...prev, brand: event.target.value }))} /></AdminFilterField>
        <AdminFilterField label="状态"><AdminSelect value={filters.status} onChange={(event) => setFilters((prev) => ({ ...prev, status: event.target.value }))}><option value="">全部状态</option><option value="sent">已发送</option><option value="failed">发送失败</option><option value="replied">已回复</option><option value="pending">待跟进</option><option value="handled">已处理</option><option value="no_action">无需处理</option></AdminSelect></AdminFilterField>
      </AdminFilterBar>
      {loading ? (
        <AdminState type="loading" message="正在加载邮件与回复..." />
      ) : error ? (
        <AdminState type="error" message={error} />
      ) : (
        <>
          <AdminSection title="邮件记录" description="发送状态、回复状态和跟进状态统一中文展示。"><EmailsTable items={filteredEmails} /></AdminSection>
          <AdminSection title="回复记录" description="用于快速处理新回复和待跟进客户。"><RepliesTable items={replies} /></AdminSection>
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
    <div className="space-y-5">
      <AdminPageHeader label="系统信息" title="后台模块与系统状态" description="查看管理员后台基础状态，并沉淀后续可扩展的运营管理模块。" />
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
