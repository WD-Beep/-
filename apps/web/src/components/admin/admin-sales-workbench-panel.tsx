"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, BriefcaseBusiness, Database, MessageSquareReply, Search, Send, UserCheck, Users } from "lucide-react";

import {
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
import {
  buildSalesWorkbenchView,
  filterAdminRows,
  formatAdminDate,
  formatAdminNumber,
  type SalesWorkbenchActivityStatus,
} from "@/components/admin/admin-ui-helpers";
import { type AdminUser, fetchAdminUsers } from "@/lib/api";

const activityStatusMeta: Record<SalesWorkbenchActivityStatus, { label: string; tone: "success" | "warning" | "muted" }> = {
  active_today: { label: "今日有动作", tone: "success" },
  inactive_today: { label: "今日未动作", tone: "warning" },
  disabled: { label: "账号禁用", tone: "muted" },
};

export function AdminSalesWorkbenchPanel() {
  const [items, setItems] = useState<AdminUser[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState({
    search: "",
    owner: "",
    brand: "",
    status: "",
    platform: "",
    startDate: "",
    endDate: "",
  });

  useEffect(() => {
    let active = true;
    fetchAdminUsers()
      .then((data) => {
        if (active) setItems(data);
      })
      .catch((err) => {
        if (active) setError(err instanceof Error ? err.message : "业务员作业数据加载失败。");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const view = useMemo(() => buildSalesWorkbenchView(items), [items]);

  const brandOptions = useMemo(() => {
    const names = new Set<string>();
    for (const row of view.rows) {
      for (const product of row.bound_products ?? []) {
        if (product.name) names.add(product.name);
      }
    }
    return Array.from(names).sort((a, b) => a.localeCompare(b, "zh-Hans-CN"));
  }, [view.rows]);

  const filteredRows = useMemo(
    () => {
      const statusFilter = filters.status === "outreach_insufficient" ? "" : filters.status;
      const rows = filterAdminRows(
        view.rows.map((item) => ({
          ...item,
          name: item.username,
          owner: item.username,
          brand: (item.bound_products ?? []).map((product) => product.name).join(" "),
          status: item.activityStatus,
          platform: (item.recent_activity?.collection_tasks ?? []).flatMap((task) => task.platforms?.length ? task.platforms : [task.platform]).filter(Boolean).join(" "),
          createdAt: item.last_active_at,
        })),
        { ...filters, status: statusFilter },
      );
      return filters.status === "outreach_insufficient" ? rows.filter((item) => item.outreachInsufficient) : rows;
    },
    [filters, view.rows],
  );

  return (
    <div className="space-y-5">
      <AdminPageHeader
        label="业务员作业"
        title="业务员作业看板"
        description="按业务员查看负责品牌、采集任务、红人入库、邮件触达、回复和异常情况，帮助管理员快速判断每个人当前在做什么。"
      />

      <AdminKpiGrid>
        <AdminKpiCard label="业务员总数" value={view.kpis.salesCount} helper="销售角色账号" icon={Users} tone="info" />
        <AdminKpiCard label="今日有动作业务员" value={view.kpis.activeTodayCount} helper="按最近活跃判断" icon={UserCheck} tone="success" />
        <AdminKpiCard label="负责品牌总数" value={view.kpis.productCount} helper="去重品牌" icon={BriefcaseBusiness} tone="info" />
        <AdminKpiCard label="今日采集任务" value={view.kpis.todayTaskCount} helper={view.hasPreciseTodayTaskData ? "按任务创建/更新时间" : "暂无精确今日字段"} icon={Search} tone="info" />
        <AdminKpiCard label="采集成功数" value={view.kpis.successCount} helper="累计成功任务" icon={Database} tone="success" />
        <AdminKpiCard label="采集失败 / 异常数" value={view.kpis.exceptionCount} helper="任务与邮件异常" icon={AlertTriangle} tone="danger" />
        <AdminKpiCard label="今日新增红人" value={view.kpis.todayInfluencerCount} helper={view.hasPreciseTodayInfluencerData ? "按红人创建/更新时间" : "暂无精确今日字段"} icon={UserCheck} tone="success" />
        <AdminKpiCard label="待处理回复" value={view.kpis.pendingReplyCount} helper="需要业务员跟进" icon={MessageSquareReply} tone="warning" />
        <AdminKpiCard label="外联不足品牌" value={view.kpis.outreachInsufficientCount} helper="有红人但邮件/回复不足" icon={Send} tone="warning" />
      </AdminKpiGrid>

      <AdminFilterBar>
        <AdminFilterField label="搜索业务员 / 品牌" className="min-w-[240px] flex-1">
          <AdminInput
            value={filters.search}
            placeholder="输入业务员、品牌或邮箱"
            onChange={(event) => setFilters((prev) => ({ ...prev, search: event.target.value }))}
          />
        </AdminFilterField>
        <AdminFilterField label="业务员筛选">
          <AdminInput value={filters.owner} placeholder="业务员名称" onChange={(event) => setFilters((prev) => ({ ...prev, owner: event.target.value }))} />
        </AdminFilterField>
        <AdminFilterField label="品牌筛选">
          <AdminSelect value={filters.brand} onChange={(event) => setFilters((prev) => ({ ...prev, brand: event.target.value }))}>
            <option value="">全部品牌</option>
            {brandOptions.map((brand) => (
              <option key={brand} value={brand}>{brand}</option>
            ))}
          </AdminSelect>
        </AdminFilterField>
        <AdminFilterField label="状态筛选">
          <AdminSelect value={filters.status} onChange={(event) => setFilters((prev) => ({ ...prev, status: event.target.value }))}>
            <option value="">全部状态</option>
            <option value="active_today">今日有动作</option>
            <option value="inactive_today">今日未动作</option>
            <option value="disabled">账号禁用</option>
            <option value="outreach_insufficient">外联不足</option>
          </AdminSelect>
        </AdminFilterField>
        <AdminFilterField label="平台筛选">
          <AdminSelect value={filters.platform} onChange={(event) => setFilters((prev) => ({ ...prev, platform: event.target.value }))}>
            <option value="">全部平台</option>
            <option value="instagram">Instagram</option>
            <option value="youtube">YouTube</option>
            <option value="tiktok">TikTok</option>
            <option value="facebook">Facebook</option>
            <option value="amazon">Amazon</option>
          </AdminSelect>
        </AdminFilterField>
        <AdminFilterField label="开始时间"><AdminInput type="date" value={filters.startDate} onChange={(event) => setFilters((prev) => ({ ...prev, startDate: event.target.value }))} /></AdminFilterField>
        <AdminFilterField label="结束时间"><AdminInput type="date" value={filters.endDate} onChange={(event) => setFilters((prev) => ({ ...prev, endDate: event.target.value }))} /></AdminFilterField>
      </AdminFilterBar>

      <AdminSection title="业务员作业追踪" description="按业务员聚合品牌、采集、红人、邮件、回复和异常数据。">
        {loading ? (
          <AdminState type="loading" message="正在加载业务员作业..." />
        ) : error ? (
          <AdminState type="error" message={error} />
        ) : (
          <AdminTable
            minWidth={1280}
            pageSize={10}
            columns={["业务员名称", "状态", "风险", "负责品牌数", "负责品牌名称", "今日任务数", "进行中任务数", "采集成功 / 失败", "红人数", "邮件发送 / 失败", "回复数 / 待处理", "最近活跃时间", "操作"]}
            rows={filteredRows.map((item) => [
              <span key="name" className="font-medium text-[#102033]">#{item.id} {item.username}</span>,
              <AdminStatusBadge key="status" meta={activityStatusMeta[item.activityStatus]} />,
              item.outreachInsufficient ? <AdminStatusBadge key="risk" meta={{ label: "外联不足", tone: "warning" }} /> : <AdminStatusBadge key="risk" meta={{ label: "正常", tone: "success" }} />,
              formatAdminNumber(item.product_count),
              <BrandTags key="brands" brands={(item.bound_products ?? []).map((product) => product.name)} />,
              formatAdminNumber(item.todayTaskCount),
              formatAdminNumber(item.activeTaskCount),
              `${formatAdminNumber(item.collection_success_count)} / ${formatAdminNumber(item.collection_failed_count)}`,
              formatAdminNumber(item.influencer_count),
              `${formatAdminNumber(item.email_count)} / ${formatAdminNumber(item.email_failed_count)}`,
              `${formatAdminNumber(item.reply_count)} / ${formatAdminNumber(item.pending_reply_count)}`,
              formatAdminDate(item.last_active_at),
              <AdminCompactActions
                key="actions"
                primaryHref={`/admin/users/${item.id}`}
                primaryLabel="查看作业明细"
                items={[
                  { label: "分配品牌", disabled: true },
                  { label: "查看采集任务", href: "/admin/collection-tasks" },
                  { label: "查看邮件回复", href: "/admin/emails" },
                ]}
              />,
            ])}
            emptyMessage="暂无匹配的业务员作业。"
          />
        )}
      </AdminSection>
    </div>
  );
}

function BrandTags({ brands }: { brands: string[] }) {
  const visible = brands.filter(Boolean).slice(0, 3);
  const rest = brands.filter(Boolean).length - visible.length;
  if (!visible.length) return <span className="text-[#98A2B3]">暂无</span>;
  return (
    <div className="flex max-w-[300px] flex-wrap gap-1.5">
      {visible.map((brand) => (
        <span key={brand} className="inline-flex max-w-[120px] items-center truncate rounded-full border border-[#DDE6F0] bg-[#F7F9FC] px-2 py-0.5 text-xs font-medium text-[#344054]">
          {brand}
        </span>
      ))}
      {rest > 0 ? <span className="inline-flex rounded-full bg-[#EEF2F7] px-2 py-0.5 text-xs font-medium text-[#667085]">+{rest}</span> : null}
    </div>
  );
}
