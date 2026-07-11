"use client";

import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  BriefcaseBusiness,
  CheckCircle2,
  Clock3,
  Database,
  MessageSquareReply,
  Search,
  Send,
  UserCheck,
  Users,
} from "lucide-react";

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
  type AdminTone,
  type SalesWorkbenchActivityStatus,
  type SalesWorkbenchAttentionLevel,
  type SalesWorkbenchRow,
} from "@/components/admin/admin-ui-helpers";
import { type AdminUser, fetchAdminUsers } from "@/lib/api";
import { cn } from "@/lib/utils";

const activityStatusMeta: Record<SalesWorkbenchActivityStatus, { label: string; tone: "success" | "warning" | "muted" }> = {
  active_today: { label: "今日有动作", tone: "success" },
  inactive_today: { label: "今日未动作", tone: "warning" },
  disabled: { label: "账号停用", tone: "muted" },
};

const attentionMeta: Record<SalesWorkbenchAttentionLevel, { label: string; tone: AdminTone; helper: string }> = {
  needs_attention: { label: "需要跟进", tone: "danger", helper: "异常、外联不足、待回复或今日未动作" },
  working: { label: "推进中", tone: "success", helper: "今天已有动作或任务仍在推进" },
  stable: { label: "暂无风险", tone: "info", helper: "暂无明显异常" },
  disabled: { label: "账号停用", tone: "muted", helper: "该账号当前停用" },
};

export function AdminSalesWorkbenchPanel() {
  const [items, setItems] = useState<AdminUser[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState({
    search: "",
    salesId: "",
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

  const selectedRow = useMemo(
    () => view.rows.find((row) => String(row.id) === filters.salesId) ?? null,
    [filters.salesId, view.rows],
  );

  const filteredRows = useMemo(() => {
    const matches = filterAdminRows(
      view.rows.map((item) => ({
        row: item,
        name: `${item.username} ${item.display_name ?? ""}`,
        owner: item.username,
        brand: (item.bound_products ?? []).map((product) => product.name).join(" "),
        status: item.activityStatus,
        platform: (item.recent_activity?.collection_tasks ?? [])
          .flatMap((task) => (task.platforms?.length ? task.platforms : [task.platform]))
          .filter(Boolean)
          .join(" "),
        createdAt: item.last_active_at,
      })),
      {
        search: filters.search,
        brand: filters.brand,
        platform: filters.platform,
        startDate: filters.startDate,
        endDate: filters.endDate,
      },
    );

    return matches.map((item) => item.row).filter((item) => {
      if (filters.salesId && String(item.id) !== filters.salesId) return false;
      if (filters.status === "outreach_insufficient") return item.outreachInsufficient;
      if (filters.status === "needs_attention" || filters.status === "working" || filters.status === "stable") {
        return item.attentionLevel === filters.status;
      }
      if (filters.status) return item.activityStatus === filters.status;
      return true;
    });
  }, [filters, view.rows]);

  const activeTaskHelper = view.hasPreciseTodayTaskData ? "按任务创建/更新时间" : "暂无精确今日字段";
  const activeInfluencerHelper = view.hasPreciseTodayInfluencerData ? "按红人创建/更新时间" : "暂无精确今日字段";

  return (
    <div className="space-y-5">
      <AdminPageHeader
        label="业务员作业"
        title="业务员作业看板"
        description="按天查看每个业务员的动作、风险、外联和回复状态，快速定位需要跟进的人。"
      />

      <AdminKpiGrid>
        <AdminKpiCard label="业务员总数" value={view.kpis.salesCount} helper="销售角色账号" icon={Users} tone="info" />
        <AdminKpiCard label="今日有动作业务员" value={view.kpis.activeTodayCount} helper="最近活跃在今天" icon={UserCheck} tone="success" />
        <AdminKpiCard label="今日未动作" value={view.kpis.inactiveTodayCount} helper="需要确认安排" icon={Clock3} tone="warning" />
        <AdminKpiCard label="今日采集任务" value={view.kpis.todayTaskCount} helper={activeTaskHelper} icon={Search} tone="info" />
        <AdminKpiCard label="今日新增红人" value={view.kpis.todayInfluencerCount} helper={activeInfluencerHelper} icon={UserCheck} tone="success" />
        <AdminKpiCard label="待处理回复" value={view.kpis.pendingReplyCount} helper="需要业务员跟进" icon={MessageSquareReply} tone="warning" />
        <AdminKpiCard label="采集失败/异常" value={view.kpis.exceptionCount} helper="任务与邮件异常" icon={AlertTriangle} tone="danger" />
        <AdminKpiCard label="外联不足品牌" value={view.kpis.outreachInsufficientCount} helper="有红人但触达不足" icon={Send} tone="warning" />
      </AdminKpiGrid>

      <div className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
        <AdminSection title="今日状态分布" description="按业务员当前状态归类。">
          <div className="grid gap-4 p-4 lg:grid-cols-2">
            <DistributionBlock title="动作分布" total={view.kpis.salesCount} items={view.activityDistribution} />
            <DistributionBlock title="风险分布" total={view.kpis.salesCount} items={view.riskDistribution} />
          </div>
        </AdminSection>

        <AdminSection title={selectedRow ? "当前业务员" : "业务员选择"} description={selectedRow ? attentionMeta[selectedRow.attentionLevel].helper : "选择后查看个人状态摘要。"}>
          <div className="space-y-3 p-4">
            <AdminSelect
              value={filters.salesId}
              onChange={(event) => setFilters((prev) => ({ ...prev, salesId: event.target.value }))}
              aria-label="选择业务员"
            >
              <option value="">全部业务员</option>
              {view.rows.map((row) => (
                <option key={row.id} value={row.id}>
                  #{row.id} {row.username}
                </option>
              ))}
            </AdminSelect>
            {selectedRow ? <SelectedSalesSummary row={selectedRow} /> : <SalesRoster rows={view.rows} onSelect={(id) => setFilters((prev) => ({ ...prev, salesId: String(id) }))} />}
          </div>
        </AdminSection>
      </div>

      <AdminFilterBar>
        <AdminFilterField label="搜索业务员 / 品牌" className="min-w-[240px] flex-1">
          <AdminInput
            value={filters.search}
            placeholder="输入业务员、品牌或邮箱"
            onChange={(event) => setFilters((prev) => ({ ...prev, search: event.target.value }))}
          />
        </AdminFilterField>
        <AdminFilterField label="品牌筛选">
          <AdminSelect value={filters.brand} onChange={(event) => setFilters((prev) => ({ ...prev, brand: event.target.value }))}>
            <option value="">全部品牌</option>
            {brandOptions.map((brand) => (
              <option key={brand} value={brand}>
                {brand}
              </option>
            ))}
          </AdminSelect>
        </AdminFilterField>
        <AdminFilterField label="状态筛选">
          <AdminSelect value={filters.status} onChange={(event) => setFilters((prev) => ({ ...prev, status: event.target.value }))}>
            <option value="">全部状态</option>
            <option value="needs_attention">需要跟进</option>
            <option value="working">推进中</option>
            <option value="stable">暂无风险</option>
            <option value="active_today">今日有动作</option>
            <option value="inactive_today">今日未动作</option>
            <option value="outreach_insufficient">外联不足</option>
            <option value="disabled">账号停用</option>
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
        <AdminFilterField label="开始时间">
          <AdminInput type="date" value={filters.startDate} onChange={(event) => setFilters((prev) => ({ ...prev, startDate: event.target.value }))} />
        </AdminFilterField>
        <AdminFilterField label="结束时间">
          <AdminInput type="date" value={filters.endDate} onChange={(event) => setFilters((prev) => ({ ...prev, endDate: event.target.value }))} />
        </AdminFilterField>
      </AdminFilterBar>

      <AdminSection title="业务员今日作业表" description="按人汇总品牌、采集、红人、邮件、回复和异常。">
        {loading ? (
          <AdminState type="loading" message="正在加载业务员作业..." />
        ) : error ? (
          <AdminState type="error" message={error} />
        ) : (
          <AdminTable
            minWidth={1180}
            pageSize={10}
            columns={["业务员", "今日状态", "关注等级", "负责品牌", "今日任务", "采集成功/失败", "红人", "邮件发送/失败", "回复/待处理", "最近活跃", "操作"]}
            rows={filteredRows.map((item) => [
              <SalesName key="name" row={item} />,
              <AdminStatusBadge key="status" meta={activityStatusMeta[item.activityStatus]} />,
              <AdminStatusBadge key="attention" meta={attentionMeta[item.attentionLevel]} />,
              <BrandTags key="brands" brands={(item.bound_products ?? []).map((product) => product.name)} />,
              <MetricStack key="tasks" main={item.todayTaskCount} sub={`${formatAdminNumber(item.activeTaskCount)} 进行中`} />,
              `${formatAdminNumber(item.collection_success_count)} / ${formatAdminNumber(item.collection_failed_count)}`,
              <MetricStack key="influencers" main={item.influencer_count ?? 0} sub={`今日 ${formatAdminNumber(item.todayInfluencerCount)}`} />,
              `${formatAdminNumber(item.email_count)} / ${formatAdminNumber(item.email_failed_count)}`,
              `${formatAdminNumber(item.reply_count)} / ${formatAdminNumber(item.pending_reply_count)}`,
              formatAdminDate(item.last_active_at),
              <AdminCompactActions
                key="actions"
                primaryHref={`/admin/users/${item.id}`}
                primaryLabel="查看作业明细"
                items={[
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

function DistributionBlock({
  title,
  total,
  items,
}: {
  title: string;
  total: number;
  items: Array<{ key: string; label: string; count: number; tone: AdminTone }>;
}) {
  return (
    <div className="min-w-0">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold text-[#102033]">{title}</h3>
        <span className="text-xs text-[#667085]">共 {formatAdminNumber(total)} 人</span>
      </div>
      <div className="space-y-3">
        {items.map((item) => {
          const percent = total ? Math.round((item.count / total) * 100) : 0;
          return (
            <div key={item.key} className="space-y-1.5">
              <div className="flex items-center justify-between gap-3 text-sm">
                <span className="font-medium text-[#344054]">{item.label}</span>
                <span className="tabular-nums text-[#667085]">
                  {formatAdminNumber(item.count)} 人，{percent}%
                </span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-[#EEF2F7]">
                <div className={cn("h-full rounded-full", distributionToneClasses[item.tone])} style={{ width: `${percent}%` }} />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function SalesRoster({ rows, onSelect }: { rows: SalesWorkbenchRow[]; onSelect: (id: number) => void }) {
  const visible = rows.slice(0, 12);
  if (!visible.length) return <p className="text-sm text-[#667085]">暂无业务员。</p>;
  return (
    <div className="grid max-h-[220px] gap-2 overflow-auto pr-1 sm:grid-cols-2">
      {visible.map((row) => (
        <button
          key={row.id}
          type="button"
          onClick={() => onSelect(row.id)}
          className="flex min-w-0 items-center justify-between gap-2 rounded-lg border border-[#DDE6F0] bg-[#FBFCFE] px-3 py-2 text-left transition hover:border-[#2563EB] hover:bg-[#F4F7FF]"
        >
          <span className="min-w-0">
            <span className="block truncate text-sm font-semibold text-[#102033]">{row.username}</span>
            <span className="block truncate text-xs text-[#667085]">{(row.bound_products ?? []).map((item) => item.name).filter(Boolean).slice(0, 2).join("、") || "暂无品牌"}</span>
          </span>
          <span className={cn("h-2.5 w-2.5 shrink-0 rounded-full", dotToneClasses[attentionMeta[row.attentionLevel].tone])} />
        </button>
      ))}
    </div>
  );
}

function SelectedSalesSummary({ row }: { row: SalesWorkbenchRow }) {
  return (
    <div className="rounded-lg border border-[#DDE6F0] bg-[#FBFCFE] p-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-lg font-semibold text-[#102033]">#{row.id} {row.username}</p>
          <p className="mt-1 text-xs text-[#667085]">{row.email || "暂无邮箱"}</p>
        </div>
        <AdminStatusBadge meta={attentionMeta[row.attentionLevel]} />
      </div>
      <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
        <SummaryMetric label="负责品牌" value={row.product_count ?? 0} icon={BriefcaseBusiness} />
        <SummaryMetric label="今日任务" value={row.todayTaskCount} icon={Search} />
        <SummaryMetric label="采集成功" value={row.collection_success_count ?? 0} icon={Database} />
        <SummaryMetric label="待处理回复" value={row.pending_reply_count ?? 0} icon={MessageSquareReply} />
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        <AdminStatusBadge meta={activityStatusMeta[row.activityStatus]} />
        {row.outreachInsufficient ? <AdminStatusBadge meta={{ label: "外联不足", tone: "warning" }} /> : <AdminStatusBadge meta={{ label: "外联正常", tone: "success" }} />}
        {row.exceptionCount > 0 ? <AdminStatusBadge meta={{ label: `${formatAdminNumber(row.exceptionCount)} 个异常`, tone: "danger" }} /> : <AdminStatusBadge meta={{ label: "暂无异常", tone: "success" }} />}
      </div>
    </div>
  );
}

function SummaryMetric({ label, value, icon: Icon }: { label: string; value: number; icon: typeof CheckCircle2 }) {
  return (
    <div className="flex items-center gap-2 rounded-md border border-[#E5ECF4] bg-white px-2.5 py-2">
      <Icon className="h-4 w-4 shrink-0 text-[#2563EB]" />
      <span className="min-w-0">
        <span className="block text-xs text-[#667085]">{label}</span>
        <span className="block text-base font-semibold tabular-nums text-[#102033]">{formatAdminNumber(value)}</span>
      </span>
    </div>
  );
}

function SalesName({ row }: { row: SalesWorkbenchRow }) {
  return (
    <span className="block min-w-[120px]">
      <span className="block font-semibold text-[#102033]">#{row.id} {row.username}</span>
      <span className="block text-xs text-[#667085]">{formatAdminNumber(row.product_count)} 个品牌</span>
    </span>
  );
}

function MetricStack({ main, sub }: { main: number; sub: string }) {
  return (
    <span className="block">
      <span className="block font-semibold tabular-nums text-[#102033]">{formatAdminNumber(main)}</span>
      <span className="block text-xs text-[#667085]">{sub}</span>
    </span>
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

const distributionToneClasses: Record<AdminTone, string> = {
  success: "bg-[#12B76A]",
  warning: "bg-[#F79009]",
  danger: "bg-[#D92D20]",
  info: "bg-[#2563EB]",
  muted: "bg-[#98A2B3]",
  neutral: "bg-[#667085]",
};

const dotToneClasses: Record<AdminTone, string> = {
  success: "bg-[#12B76A]",
  warning: "bg-[#F79009]",
  danger: "bg-[#D92D20]",
  info: "bg-[#2563EB]",
  muted: "bg-[#98A2B3]",
  neutral: "bg-[#667085]",
};
