"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  BriefcaseBusiness,
  CheckCircle2,
  Clock3,
  Database,
  MessageSquareReply,
  Pencil,
  Plus,
  Search,
  Send,
  UserCheck,
  Users,
} from "lucide-react";

import {
  AdminActionButton,
  AdminBrandLabel,
  AdminCompactActions,
  AdminConfirmDialog,
  AdminFilterBar,
  AdminFilterField,
  AdminInput,
  AdminKpiCard,
  AdminKpiGrid,
  AdminMoreMenu,
  AdminPageHeader,
  AdminSection,
  AdminSelect,
  AdminState,
  AdminStatusBadge,
  AdminTable,
} from "@/components/admin/admin-ui";
import {
  AdminDeleteConfirmDialog,
  AssignBrandsDrawer,
  buildBrandDeleteDescription,
  deleteBrandSafely,
  disableSalesperson,
  WorkbenchBrandDrawer,
} from "@/components/admin/admin-products-management";
import { AdminUserAccountDialog } from "@/components/admin/admin-user-dialogs";
import {
  buildSalesWorkbenchView,
  deriveBrandOperatorStatus,
  filterAdminRows,
  formatAdminDate,
  formatAdminNumber,
  formatSalespersonDisplay,
  type AdminTone,
  type SalesWorkbenchActivityStatus,
  type SalesWorkbenchAttentionLevel,
  type SalesWorkbenchRow,
} from "@/components/admin/admin-ui-helpers";
import { fetchAdminProducts, fetchAdminUsers, type AdminProduct, type AdminUser } from "@/lib/api";
import { getStoredAuthSession } from "@/lib/auth";
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

type PanelAction =
  | { type: "create-sales" }
  | { type: "edit-sales-full"; user: AdminUser }
  | { type: "assign-sales"; user: AdminUser }
  | { type: "create-brand"; ownerUserId: number | null }
  | { type: "edit-brand"; brand: AdminProduct }
  | { type: "delete-brand"; brand: AdminProduct };

export function AdminSalesWorkbenchPanel() {
  const [items, setItems] = useState<AdminUser[]>([]);
  const [products, setProducts] = useState<AdminProduct[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [deleteLoading, setDeleteLoading] = useState(false);
  const [disableConfirmUser, setDisableConfirmUser] = useState<AdminUser | null>(null);
  const [panelAction, setPanelAction] = useState<PanelAction | null>(null);
  const [filters, setFilters] = useState({
    search: "",
    salesId: "",
    brand: "",
    status: "",
    platform: "",
    startDate: "",
    endDate: "",
  });

  const reload = useCallback(async () => {
    const [users, productItems] = await Promise.all([fetchAdminUsers(), fetchAdminProducts()]);
    setItems(users);
    setProducts(productItems);
  }, []);

  useEffect(() => {
    let active = true;
    queueMicrotask(() => {
      if (!active) return;
      void reload()
        .catch((err) => {
          if (active) setError(err instanceof Error ? err.message : "业务员作业数据加载失败。");
        })
        .finally(() => {
          if (active) setLoading(false);
        });
    });
    return () => {
      active = false;
    };
  }, [reload]);

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

  const selectedUser = useMemo(
    () => (selectedRow ? items.find((user) => user.id === selectedRow.id) ?? null : null),
    [items, selectedRow],
  );

  const selectedBrands = useMemo(() => {
    if (!selectedRow) return [];
    const ids = new Set((selectedRow.bound_products ?? []).map((product) => product.id));
    return products.filter((product) => ids.has(product.id));
  }, [products, selectedRow]);

  const filteredRows = useMemo(() => {
    const matches = filterAdminRows(
      view.rows.map((item) => ({
        row: item,
        name: `${formatSalespersonDisplay(item)} ${item.email ?? ""}`,
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

  async function handleSaved(message: string) {
    setSuccessMessage(message);
    await reload();
  }

  async function confirmDisableSalesperson() {
    if (!disableConfirmUser) return;
    try {
      await disableSalesperson(disableConfirmUser.id);
      setDisableConfirmUser(null);
      await handleSaved("业务员已停用。");
    } catch (err) {
      setError(err instanceof Error ? err.message : "停用业务员失败。");
      setDisableConfirmUser(null);
    }
  }

  async function confirmDeleteBrand() {
    if (panelAction?.type !== "delete-brand") return;
    setDeleteLoading(true);
    try {
      await deleteBrandSafely(panelAction.brand);
      setPanelAction(null);
      await handleSaved("品牌已删除。");
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除品牌失败。");
      setPanelAction(null);
    } finally {
      setDeleteLoading(false);
    }
  }

  const activeTaskHelper = view.hasPreciseTodayTaskData ? "按任务创建/更新时间" : "暂无精确今日字段";
  const activeInfluencerHelper = view.hasPreciseTodayInfluencerData ? "按红人创建/更新时间" : "暂无精确今日字段";

  return (
    <div className="space-y-3">
      <AdminPageHeader
        label="业务员作业"
        title="业务员作业看板"
        description="按天查看每个业务员的动作、风险、外联和回复状态，并可直接编辑业务员与品牌。"
        backFallback="/admin/dashboard"
        actions={
          <>
            <AdminActionButton onClick={() => setPanelAction({ type: "create-sales" })}>
              <Plus className="h-3.5 w-3.5" />
              新增业务员
            </AdminActionButton>
            <AdminActionButton
              onClick={() =>
                setPanelAction({
                  type: "create-brand",
                  ownerUserId: selectedRow?.id ?? null,
                })
              }
            >
              <Plus className="h-3.5 w-3.5" />
              新增品牌
            </AdminActionButton>
          </>
        }
      />

      {successMessage ? (
        <div className="rounded-md border border-[#BAE6D1] bg-[#ECFDF3] px-4 py-3 text-sm text-[#047857]">{successMessage}</div>
      ) : null}

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

        <AdminSection title={selectedRow ? "当前业务员" : "业务员选择"} description={selectedRow ? attentionMeta[selectedRow.attentionLevel].helper : "选择后查看个人状态摘要，也可直接编辑、分配品牌或停用。"}>
          <div className="space-y-3 p-4">
            <div className="flex flex-wrap items-center gap-2">
              <AdminSelect
                className="min-w-0 flex-1"
                value={filters.salesId}
                onChange={(event) => setFilters((prev) => ({ ...prev, salesId: event.target.value }))}
                aria-label="选择业务员"
              >
                <option value="">全部业务员</option>
                {view.rows.map((row) => (
                  <option key={row.id} value={row.id}>
                    {formatSalespersonDisplay(row)}
                  </option>
                ))}
              </AdminSelect>
              <AdminActionButton onClick={() => setPanelAction({ type: "create-sales" })}>
                <Plus className="h-3.5 w-3.5" />
                新增
              </AdminActionButton>
            </div>
            {selectedRow && selectedUser ? (
              <SelectedSalesSummary
                row={selectedRow}
                onEdit={() => setPanelAction({ type: "edit-sales-full", user: selectedUser })}
                onAssign={() => setPanelAction({ type: "assign-sales", user: selectedUser })}
                onDisable={() => setDisableConfirmUser(selectedUser)}
                onClear={() => setFilters((prev) => ({ ...prev, salesId: "" }))}
              />
            ) : (
              <SalesRoster
                rows={view.rows}
                users={items}
                onSelect={(id) => setFilters((prev) => ({ ...prev, salesId: String(id) }))}
                onEdit={(user) => setPanelAction({ type: "edit-sales-full", user })}
                onAssign={(user) => setPanelAction({ type: "assign-sales", user })}
                onDisable={(user) => setDisableConfirmUser(user)}
              />
            )}
          </div>
        </AdminSection>
      </div>

      {selectedRow ? (
        <AdminSection title="负责品牌明细" description={`${formatSalespersonDisplay(selectedRow)} 当前负责的 ${formatAdminNumber(selectedBrands.length)} 个品牌。`}>
          {selectedBrands.length ? (
            <AdminTable
              minWidth={980}
              columns={["品牌", "任务", "红人", "邮件 / 回复", "状态", "最近更新", "操作"]}
              rows={selectedBrands.map((brand) => [
                <AdminBrandLabel key="brand" name={brand.name} subtitle={`#${brand.id} · ${brand.slug}`} compact />,
                formatAdminNumber(brand.collection_task_count),
                formatAdminNumber(brand.influencer_count),
                `${formatAdminNumber(brand.email_count)} / ${formatAdminNumber(brand.reply_count)}`,
                <AdminStatusBadge key="status" meta={deriveBrandOperatorStatus(brand)} />,
                formatAdminDate(brand.updated_at ?? brand.created_at),
                <AdminCompactActions
                  key="actions"
                  primaryHref={`/admin/products/${brand.id}`}
                  primaryLabel="品牌详情"
                  secondaryLabel="编辑"
                  secondaryOnClick={() => setPanelAction({ type: "edit-brand", brand })}
                  items={[{ label: "删除", danger: true, onClick: () => setPanelAction({ type: "delete-brand", brand }) }]}
                />,
              ])}
              emptyMessage="暂无品牌。"
            />
          ) : (
            <AdminState message="当前业务员暂无负责品牌，可点击右上角“新增品牌”。" />
          )}
        </AdminSection>
      ) : null}

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
            rows={filteredRows.map((item) => {
              const user = items.find((entry) => entry.id === item.id);
              return [
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
                user ? (
                  <AdminCompactActions
                    key="actions"
                    primaryHref={`/admin/users/${item.id}`}
                    primaryLabel="作业明细"
                    secondaryLabel="编辑"
                    secondaryOnClick={() => setPanelAction({ type: "edit-sales-full", user })}
                    items={[
                      { label: "分配品牌", onClick: () => setPanelAction({ type: "assign-sales", user }) },
                      { label: "停用业务员", danger: true, onClick: () => setDisableConfirmUser(user) },
                    ]}
                  />
                ) : (
                  <AdminCompactActions key="actions" primaryHref={`/admin/users/${item.id}`} primaryLabel="作业明细" items={[]} />
                ),
              ];
            })}
            emptyMessage="暂无匹配的业务员作业。"
          />
        )}
      </AdminSection>

      <AdminUserAccountDialog
        key={`account-${panelAction?.type === "create-sales" ? "new" : panelAction?.type === "edit-sales-full" ? panelAction.user.id : "closed"}`}
        open={panelAction?.type === "create-sales" || panelAction?.type === "edit-sales-full"}
        user={panelAction?.type === "edit-sales-full" ? panelAction.user : null}
        products={products}
        users={items}
        currentUserId={getStoredAuthSession()?.userId ?? null}
        onClose={() => setPanelAction(null)}
        onProductsChanged={reload}
        onSaved={async () => {
          await handleSaved(panelAction?.type === "create-sales" ? "业务员已创建。" : "业务员账号与权限已更新。");
        }}
      />

      <AssignBrandsDrawer
        open={panelAction?.type === "assign-sales"}
        rowKey={panelAction?.type === "assign-sales" ? panelAction.user.username : null}
        rowName={panelAction?.type === "assign-sales" ? formatSalespersonDisplay(panelAction.user) : ""}
        user={panelAction?.type === "assign-sales" ? panelAction.user : null}
        products={products}
        onClose={() => setPanelAction(null)}
        onSaved={() => void handleSaved("品牌分配已更新。")}
      />

      <WorkbenchBrandDrawer
        open={panelAction?.type === "create-brand" || panelAction?.type === "edit-brand"}
        mode={panelAction?.type === "edit-brand" ? "edit" : "create"}
        brand={panelAction?.type === "edit-brand" ? panelAction.brand : null}
        users={items}
        defaultOwnerUserId={panelAction?.type === "create-brand" ? panelAction.ownerUserId : null}
        onClose={() => setPanelAction(null)}
        onSaved={() => void handleSaved(panelAction?.type === "edit-brand" ? "品牌已更新。" : "品牌已创建。")}
      />

      <AdminDeleteConfirmDialog
        open={panelAction?.type === "delete-brand"}
        title="确认删除品牌？"
        description={
          panelAction?.type === "delete-brand"
            ? buildBrandDeleteDescription(panelAction.brand)
            : ""
        }
        loading={deleteLoading}
        onCancel={() => setPanelAction(null)}
        onConfirm={() => void confirmDeleteBrand()}
      />

      <AdminConfirmDialog
        open={Boolean(disableConfirmUser)}
        title="确认停用业务员？"
        description={
          disableConfirmUser
            ? `停用后 ${formatSalespersonDisplay(disableConfirmUser)} 将无法登录后台，其负责品牌仍可重新分配给其他业务员。`
            : ""
        }
        confirmLabel="确认停用"
        danger
        onCancel={() => setDisableConfirmUser(null)}
        onConfirm={() => void confirmDisableSalesperson()}
      />
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

function SalesRoster({
  rows,
  users,
  onSelect,
  onEdit,
  onAssign,
  onDisable,
}: {
  rows: SalesWorkbenchRow[];
  users: AdminUser[];
  onSelect: (id: number) => void;
  onEdit: (user: AdminUser) => void;
  onAssign: (user: AdminUser) => void;
  onDisable: (user: AdminUser) => void;
}) {
  const visible = rows.slice(0, 12);
  if (!visible.length) return <p className="text-sm text-[#667085]">暂无业务员，可点击上方“新增”创建。</p>;
  return (
    <div className="grid max-h-[280px] gap-2 overflow-auto pr-1 sm:grid-cols-2">
      {visible.map((row) => {
        const user = users.find((entry) => entry.id === row.id);
        return (
          <div
            key={row.id}
            className="flex min-w-0 items-center gap-2 rounded-lg border border-[#DDE6F0] bg-[#FBFCFE] px-3 py-2 transition hover:border-[#2563EB] hover:bg-[#F4F7FF]"
          >
            <button type="button" onClick={() => onSelect(row.id)} className="min-w-0 flex-1 text-left">
              <span className="block truncate text-sm font-medium text-[#102033]">{formatSalespersonDisplay(row)}</span>
              <span className="block truncate text-xs text-[#667085]">
                {(row.bound_products ?? []).map((item) => item.name).filter(Boolean).slice(0, 2).join("、") || "暂无品牌"}
              </span>
            </button>
            <span className={cn("h-2.5 w-2.5 shrink-0 rounded-full", dotToneClasses[attentionMeta[row.attentionLevel].tone])} />
            {user ? (
              <div className="flex shrink-0 items-center gap-1">
                <button
                  type="button"
                  title="编辑业务员"
                  onClick={() => onEdit(user)}
                  className="inline-flex h-7 items-center gap-1 rounded-md border border-[#DDE6F0] bg-white px-2 text-xs font-medium text-[#344054] hover:border-[#2563EB] hover:text-[#2563EB]"
                >
                  <Pencil className="h-3 w-3" />
                  编辑
                </button>
                <AdminMoreMenu
                  items={[
                    { label: "查看摘要", onClick: () => onSelect(row.id) },
                    { label: "分配品牌", onClick: () => onAssign(user) },
                    { label: "停用业务员", danger: true, onClick: () => onDisable(user) },
                  ]}
                />
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

function SelectedSalesSummary({
  row,
  onEdit,
  onAssign,
  onDisable,
  onClear,
}: {
  row: SalesWorkbenchRow;
  onEdit: () => void;
  onAssign: () => void;
  onDisable: () => void;
  onClear: () => void;
}) {
  return (
    <div className="rounded-lg border border-[#DDE6F0] bg-[#FBFCFE] p-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-lg font-semibold text-[#102033]">{formatSalespersonDisplay(row)}</p>
          <p className="mt-1 text-xs text-[#667085]">{row.email || "暂无邮箱"} · #{row.id}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <AdminStatusBadge meta={attentionMeta[row.attentionLevel]} />
          <AdminActionButton onClick={onEdit}>
            <Pencil className="h-3.5 w-3.5" />
            编辑业务员
          </AdminActionButton>
          <AdminActionButton onClick={onAssign}>分配品牌</AdminActionButton>
          <button type="button" onClick={onDisable} className="text-xs font-medium text-[#B42318] hover:underline">
            停用
          </button>
          <button type="button" onClick={onClear} className="text-xs font-medium text-[#667085] hover:underline">
            返回列表
          </button>
        </div>
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
    <span className="block min-w-[140px]">
      <span className="block font-medium text-[#102033]">{formatSalespersonDisplay(row)}</span>
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
