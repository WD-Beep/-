// 文件说明：前端管理员后台组件；当前文件：admin products panel
"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronRight, Plus, Search, Send, UserPlus, UserRound, Users } from "lucide-react";

import {
  AdminActionButton,
  AdminBrandLabel,
  AdminCompactActions,
  AdminDrawer,
  AdminFilterBar,
  AdminFilterField,
  AdminInput,
  AdminKpiCard,
  AdminKpiGrid,
  AdminPageHeader,
  AdminSalespersonLabel,
  AdminSection,
  AdminSelect,
  AdminState,
  AdminStatusBadge,
} from "@/components/admin/admin-ui";
import {
  AdminDeleteConfirmDialog,
  AssignBrandsDrawer,
  BrandFormDrawer,
  buildBrandDeleteDescription,
  deleteBrandSafely,
  deleteSalespersonSafely,
  disableBrand,
  disableSalesperson,
  ReassignOwnerDrawer,
  SalespersonDeleteDialog,
  SalespersonFormDrawer,
  useAdminAvatarCache,
} from "@/components/admin/admin-products-management";
import { ProductCreateDialog } from "@/components/layout/product-create-dialog";
import {
  buildSalespersonBrandProgressView,
  deriveBrandOperatorStatus,
  formatAdminDate,
  formatAdminNumber,
  formatAdminPercent,
  sortSalespersonBrands,
  UNASSIGNED_SALESPERSON_KEY,
  UNASSIGNED_SALESPERSON_LABEL,
  type EnrichedBrandProduct,
  type SalespersonProgressRow,
} from "@/components/admin/admin-ui-helpers";
import { fetchAdminProducts, fetchAdminUsers, type AdminProduct, type AdminUser } from "@/lib/api";
import { cn } from "@/lib/utils";

type BrandSortKey = "status" | "reply" | "updatedAt";

type PanelAction =
  | { type: "create-sales" }
  | { type: "edit-sales"; user: AdminUser }
  | { type: "assign-sales"; row: SalespersonProgressRow; user: AdminUser }
  | { type: "delete-sales"; user: AdminUser; row: SalespersonProgressRow }
  | { type: "edit-brand"; brand: EnrichedBrandProduct }
  | { type: "reassign-brand"; brand: EnrichedBrandProduct }
  | { type: "disable-brand"; brand: EnrichedBrandProduct }
  | { type: "delete-brand"; brand: EnrichedBrandProduct };

function matchesSalespersonFilters(
  row: SalespersonProgressRow,
  filters: { search: string; owner: string; status: string },
): boolean {
  const search = filters.search.trim().toLowerCase();
  if (search) {
    const haystack = [
      row.name,
      row.key,
      ...row.brands.map((brand) => brand.name),
      ...row.brands.map((brand) => brand.slug),
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    if (!haystack.includes(search)) return false;
  }

  if (filters.owner) {
    if (filters.owner === UNASSIGNED_SALESPERSON_KEY && row.key !== UNASSIGNED_SALESPERSON_KEY) return false;
    if (filters.owner !== UNASSIGNED_SALESPERSON_KEY && row.key !== filters.owner) return false;
  }

  if (filters.status) {
    if (filters.status === "无负责人") return row.key === UNASSIGNED_SALESPERSON_KEY;
    if (filters.status === "启用") return row.brands.some((brand) => brand.status === "active");
    if (filters.status === "已有回复") return row.replyCount > 0;
    if (filters.status === "待跟进") return row.pendingFollowUpCount > 0;
    if (row.progressStatus.label !== filters.status) return false;
  }

  return true;
}

function findUserByRow(row: SalespersonProgressRow, users: AdminUser[]): AdminUser | null {
  if (!row.userId) return null;
  return users.find((user) => user.id === row.userId) ?? null;
}

export function AdminProductsPanel() {
  const [items, setItems] = useState<AdminProduct[]>([]);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState({ search: "", owner: "", status: "" });
  const [expandedKeys, setExpandedKeys] = useState<Set<string>>(new Set());
  const [selectedRowKey, setSelectedRowKey] = useState<string | null>(null);
  const [panelAction, setPanelAction] = useState<PanelAction | null>(null);
  const [deleteLoading, setDeleteLoading] = useState(false);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [productCreateOpen, setProductCreateOpen] = useState(false);
  const [draftAvatarUrl, setDraftAvatarUrl] = useState<string | null>(null);
  const [draftLogoUrl, setDraftLogoUrl] = useState<string | null>(null);

  const avatarCache = useAdminAvatarCache();

  const reload = useCallback(async () => {
    const [products, userItems] = await Promise.all([fetchAdminProducts(), fetchAdminUsers()]);
    setItems(products);
    setUsers(userItems);
  }, []);

  useEffect(() => {
    let active = true;
    queueMicrotask(() => {
      if (!active) return;
      void reload()
        .catch((err) => {
          if (active) setError(err instanceof Error ? err.message : "业务员进度数据加载失败。");
        })
        .finally(() => {
          if (active) setLoading(false);
        });
    });
    return () => {
      active = false;
    };
  }, [reload]);

  const rows = useMemo(() => buildSalespersonBrandProgressView(items, users), [items, users]);

  const selectedRow = useMemo(() => {
    if (!selectedRowKey) return null;
    return rows.find((row) => row.key === selectedRowKey) ?? null;
  }, [rows, selectedRowKey]);

  const salesOptions = useMemo(
    () =>
      users
        .filter((user) => user.role === "sales")
        .map((user) => ({
          key: user.username,
          label: user.display_name?.trim() || user.username,
        }))
        .sort((left, right) => left.label.localeCompare(right.label, "zh-Hans-CN")),
    [users],
  );

  const filteredRows = useMemo(
    () => rows.filter((row) => matchesSalespersonFilters(row, filters)),
    [filters, rows],
  );

  const unassignedCount = rows.find((row) => row.key === UNASSIGNED_SALESPERSON_KEY)?.brandCount ?? 0;
  const totalPendingFollowUp = rows.reduce((sum, row) => sum + row.pendingFollowUpCount, 0);
  const activeSalesCount = rows.filter((row) => row.key !== UNASSIGNED_SALESPERSON_KEY && row.brandCount > 0).length;
  const totalReplies = rows.reduce((sum, row) => sum + row.replyCount, 0);

  async function handleSaved(message?: string) {
    setActionError(null);
    try {
      await reload();
      if (message) setSuccessMessage(message);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "刷新列表失败。");
    }
  }

  function toggleExpanded(key: string) {
    setExpandedKeys((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function openCreateSalesperson() {
    setDraftAvatarUrl(null);
    setPanelAction({ type: "create-sales" });
  }

  function openEditSalesperson(row: SalespersonProgressRow) {
    const user = findUserByRow(row, users);
    if (!user) return;
    setDraftAvatarUrl(avatarCache.getUserAvatar(user.id) ?? null);
    setPanelAction({ type: "edit-sales", user });
  }

  function openEditBrand(brand: EnrichedBrandProduct) {
    setDraftLogoUrl(avatarCache.getProductLogo(brand.id) ?? null);
    setPanelAction({ type: "edit-brand", brand });
  }

  async function confirmBrandDelete() {
    if (!panelAction || (panelAction.type !== "delete-brand" && panelAction.type !== "disable-brand")) return;
    setDeleteLoading(true);
    setActionError(null);
    setSuccessMessage(null);
    try {
      if (panelAction.type === "disable-brand") {
        await disableBrand(panelAction.brand.id);
        setPanelAction(null);
        await handleSaved("品牌已停用。");
        return;
      }
      await deleteBrandSafely(panelAction.brand);
      setPanelAction(null);
      await handleSaved("品牌已删除。");
    } catch (err) {
      setSuccessMessage(null);
      setActionError(err instanceof Error ? err.message : "操作失败。");
    } finally {
      setDeleteLoading(false);
    }
  }

  async function handleDeleteSalesperson() {
    if (panelAction?.type !== "delete-sales") return;
    setDeleteLoading(true);
    setActionError(null);
    try {
      const result = await deleteSalespersonSafely(panelAction.user.id);
      setPanelAction(null);
      setSuccessMessage(
        `删除成功，已释放 ${result.released_products} 个品牌和 ${result.released_tasks} 个任务，历史数据已保留。`,
      );
      await reload();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "删除业务员失败，请稍后重试。");
    } finally {
      setDeleteLoading(false);
    }
  }

  return (
    <div className="space-y-3">
      <AdminPageHeader
        label="品牌管理"
        title="业务员品牌进度"
        description="按业务员汇总负责品牌与跟进进度，支持在此页直接管理业务员和品牌。"
        backFallback="/admin/dashboard"
        actions={
          <>
            <AdminActionButton onClick={openCreateSalesperson}>
              <UserPlus className="h-3.5 w-3.5" />
              新增业务员
            </AdminActionButton>
            <AdminActionButton onClick={() => setProductCreateOpen(true)}>
              <Plus className="h-3.5 w-3.5" />
              新增品牌
            </AdminActionButton>
          </>
        }
      />

      <AdminKpiGrid>
        <AdminKpiCard label="业务员数" value={activeSalesCount} helper="已有负责品牌" icon={Users} tone="info" />
        <AdminKpiCard label="未分配品牌" value={unassignedCount} helper="需尽快分配负责人" icon={UserRound} tone={unassignedCount > 0 ? "warning" : "success"} />
        <AdminKpiCard label="待跟进品牌" value={totalPendingFollowUp} helper="已发信未回复" icon={Send} tone="warning" />
        <AdminKpiCard label="累计回复" value={totalReplies} helper="全部业务员汇总" icon={Search} tone="success" />
      </AdminKpiGrid>

      <AdminFilterBar>
        <AdminFilterField label="搜索业务员 / 品牌 / SLUG" className="min-w-[240px] flex-1">
          <AdminInput
            value={filters.search}
            placeholder="输入业务员姓名、品牌名或 slug"
            onChange={(event) => setFilters((prev) => ({ ...prev, search: event.target.value }))}
          />
        </AdminFilterField>
        <AdminFilterField label="业务员">
          <AdminSelect value={filters.owner} onChange={(event) => setFilters((prev) => ({ ...prev, owner: event.target.value }))}>
            <option value="">全部业务员</option>
            <option value={UNASSIGNED_SALESPERSON_KEY}>{UNASSIGNED_SALESPERSON_LABEL}</option>
            {salesOptions.map((option) => (
              <option key={option.key} value={option.key}>
                {option.label}
              </option>
            ))}
          </AdminSelect>
        </AdminFilterField>
        <AdminFilterField label="状态">
          <AdminSelect value={filters.status} onChange={(event) => setFilters((prev) => ({ ...prev, status: event.target.value }))}>
            <option value="">全部状态</option>
            <option value="启用">启用</option>
            <option value="已有回复">已有回复</option>
            <option value="待跟进">待跟进</option>
            <option value="需跟进">需跟进</option>
            <option value="进行中">进行中</option>
            <option value="未开始">未开始</option>
            <option value="完成较好">完成较好</option>
            <option value="无负责人">无负责人</option>
          </AdminSelect>
        </AdminFilterField>
      </AdminFilterBar>

      {actionError ? (
        <div className="rounded-md border border-[#FECDCA] bg-[#FEF3F2] px-4 py-3 text-sm text-[#B42318]">{actionError}</div>
      ) : null}
      {successMessage ? (
        <div className="rounded-md border border-[#BAE6D1] bg-[#ECFDF3] px-4 py-3 text-sm text-[#047857]">{successMessage}</div>
      ) : null}

      <AdminSection
        title="业务员跟进进度"
        description="业务员为一级信息（左侧蓝色标识），展开后的品牌列表为二级信息。"
      >
        {loading ? (
          <AdminState type="loading" message="正在加载业务员进度..." />
        ) : error ? (
          <AdminState type="error" message={error} />
        ) : filteredRows.length ? (
          <div className="overflow-auto">
            <table className="w-full min-w-[1280px] border-collapse text-left text-sm">
              <thead className="bg-[#F4F7FB] text-xs font-semibold text-[#667085]">
                <tr>
                  {[
                    "",
                    "业务员",
                    "负责品牌数",
                    "任务数",
                    "红人数",
                    "邮件发送数",
                    "回复数",
                    "回复率",
                    "待跟进数量",
                    "最近更新时间",
                    "当前进度状态",
                    "操作",
                  ].map((column) => (
                    <th key={column || "expand"} className="h-10 whitespace-nowrap border-b border-[#DDE6F0] px-3 py-0">
                      {column}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filteredRows.map((row) => (
                  <SalespersonProgressTableGroup
                    key={row.key}
                    row={row}
                    expanded={expandedKeys.has(row.key)}
                    avatarUrl={row.userId ? avatarCache.getUserAvatar(row.userId) : undefined}
                    getProductLogo={avatarCache.getProductLogo}
                    onToggle={() => toggleExpanded(row.key)}
                    onOpenDetail={() => setSelectedRowKey(row.key)}
                    onEditSalesperson={() => openEditSalesperson(row)}
                    onAssignBrands={() => {
                      const user = findUserByRow(row, users);
                      if (user) setPanelAction({ type: "assign-sales", row, user });
                    }}
                    onDisableSalesperson={async () => {
                      const user = findUserByRow(row, users);
                      if (!user) return;
                      try {
                        await disableSalesperson(user.id);
                        setSuccessMessage("业务员已停用。");
                        await reload();
                      } catch (err) {
                        setActionError(err instanceof Error ? err.message : "停用业务员失败。");
                      }
                    }}
                    onDeleteSalesperson={() => {
                      const user = findUserByRow(row, users);
                      if (!user) return;
                      setSuccessMessage(null);
                      setActionError(null);
                      setPanelAction({ type: "delete-sales", user, row });
                    }}
                    onEditBrand={openEditBrand}
                    onReassignBrand={(brand) => setPanelAction({ type: "reassign-brand", brand })}
                    onDisableBrand={(brand) => setPanelAction({ type: "disable-brand", brand })}
                    onDeleteBrand={(brand) => setPanelAction({ type: "delete-brand", brand })}
                    onQuickAssignBrand={(brand) => setPanelAction({ type: "reassign-brand", brand })}
                  />
                ))}
              </tbody>
            </table>
          </div>
        ) : users.filter((user) => user.role === "sales").length === 0 && !filters.search && !filters.owner && !filters.status ? (
          <AdminState
            message="暂无业务员账号，请创建业务员账号后分配品牌和任务。"
            action={
              <AdminActionButton onClick={openCreateSalesperson}>
                <UserPlus className="h-3.5 w-3.5" />
                新增业务员
              </AdminActionButton>
            }
          />
        ) : (
          <AdminState
            message="暂无匹配的业务员进度。"
            action={
              <AdminActionButton onClick={openCreateSalesperson}>
                <UserPlus className="h-3.5 w-3.5" />
                新增业务员
              </AdminActionButton>
            }
          />
        )}
      </AdminSection>

      <SalespersonBrandDrawer
        key={selectedRow?.key ?? "closed"}
        row={selectedRow}
        getProductLogo={avatarCache.getProductLogo}
        getUserAvatar={avatarCache.getUserAvatar}
        onClose={() => setSelectedRowKey(null)}
        onEditBrand={openEditBrand}
        onReassignBrand={(brand) => setPanelAction({ type: "reassign-brand", brand })}
        onDisableBrand={(brand) => setPanelAction({ type: "disable-brand", brand })}
        onDeleteBrand={(brand) => setPanelAction({ type: "delete-brand", brand })}
      />

      <SalespersonFormDrawer
        open={panelAction?.type === "create-sales" || panelAction?.type === "edit-sales"}
        mode={panelAction?.type === "edit-sales" ? "edit" : "create"}
        user={panelAction?.type === "edit-sales" ? panelAction.user : null}
        products={items}
        users={users}
        avatarUrl={draftAvatarUrl}
        onAvatarChange={(url) => {
          setDraftAvatarUrl(url);
          if (panelAction?.type === "edit-sales" && url) avatarCache.setUserAvatar(panelAction.user.id, url);
        }}
        onClose={() => setPanelAction(null)}
        onSaved={() => void handleSaved(panelAction?.type === "edit-sales" ? "业务员已更新。" : "业务员创建成功。")}
        onProductsChanged={reload}
      />

      <AssignBrandsDrawer
        open={panelAction?.type === "assign-sales"}
        rowKey={panelAction?.type === "assign-sales" ? panelAction.row.key : null}
        rowName={panelAction?.type === "assign-sales" ? panelAction.row.name : ""}
        user={panelAction?.type === "assign-sales" ? panelAction.user : null}
        products={items}
        onClose={() => setPanelAction(null)}
        onSaved={() => void handleSaved("品牌权限已更新。")}
      />

      <BrandFormDrawer
        open={panelAction?.type === "edit-brand"}
        brand={panelAction?.type === "edit-brand" ? panelAction.brand : null}
        users={users}
        logoUrl={draftLogoUrl}
        onLogoChange={(url) => {
          setDraftLogoUrl(url);
          if (panelAction?.type === "edit-brand" && url) avatarCache.setProductLogo(panelAction.brand.id, url);
        }}
        onClose={() => setPanelAction(null)}
        onSaved={() => void handleSaved("品牌已更新。")}
      />

      <ReassignOwnerDrawer
        open={panelAction?.type === "reassign-brand"}
        brand={panelAction?.type === "reassign-brand" ? panelAction.brand : null}
        users={users}
        onClose={() => setPanelAction(null)}
        onSaved={() => void handleSaved("品牌负责人已更新。")}
      />

      <SalespersonDeleteDialog
        open={panelAction?.type === "delete-sales"}
        userName={panelAction?.type === "delete-sales" ? panelAction.user.display_name?.trim() || panelAction.user.username : ""}
        username={panelAction?.type === "delete-sales" ? panelAction.user.username : ""}
        productCount={panelAction?.type === "delete-sales" ? panelAction.row.brandCount : 0}
        taskCount={panelAction?.type === "delete-sales" ? panelAction.row.taskCount : 0}
        influencerCount={panelAction?.type === "delete-sales" ? panelAction.row.influencerCount : 0}
        emailCount={panelAction?.type === "delete-sales" ? panelAction.row.emailCount : 0}
        replyCount={panelAction?.type === "delete-sales" ? panelAction.row.replyCount : 0}
        error={panelAction?.type === "delete-sales" ? actionError : null}
        loading={deleteLoading}
        onCancel={() => {
          setPanelAction(null);
          setActionError(null);
        }}
        onDelete={() => void handleDeleteSalesperson()}
      />

      <AdminDeleteConfirmDialog
        open={panelAction?.type === "delete-brand" || panelAction?.type === "disable-brand"}
        title={
          panelAction?.type === "disable-brand"
            ? "确认停用品牌？"
            : "确认删除品牌？"
        }
        description={
          panelAction?.type === "disable-brand"
            ? "停用后品牌将从前台可用列表中隐藏，历史任务与邮件数据会保留。"
            : panelAction?.type === "delete-brand"
              ? buildBrandDeleteDescription(panelAction.brand)
              : ""
        }
        confirmLabel={panelAction?.type === "disable-brand" ? "确认停用" : "确认删除"}
        loading={deleteLoading}
        onCancel={() => setPanelAction(null)}
        onConfirm={confirmBrandDelete}
      />

      <ProductCreateDialog
        open={productCreateOpen}
        onClose={() => setProductCreateOpen(false)}
        onCreated={() => {
          setProductCreateOpen(false);
          void handleSaved();
        }}
      />
    </div>
  );
}

function SalespersonBrandDrawer({
  row,
  getProductLogo,
  getUserAvatar,
  onClose,
  onEditBrand,
  onReassignBrand,
  onDisableBrand,
  onDeleteBrand,
}: {
  row: SalespersonProgressRow | null;
  getProductLogo: (productId: number | null | undefined) => string | undefined;
  getUserAvatar: (userId: number | null | undefined) => string | undefined;
  onClose: () => void;
  onEditBrand: (brand: EnrichedBrandProduct) => void;
  onReassignBrand: (brand: EnrichedBrandProduct) => void;
  onDisableBrand: (brand: EnrichedBrandProduct) => void;
  onDeleteBrand: (brand: EnrichedBrandProduct) => void;
}) {
  const [brandSort, setBrandSort] = useState<BrandSortKey>("updatedAt");
  const [brandSortDirection, setBrandSortDirection] = useState<"asc" | "desc">("desc");

  const sortedBrands = useMemo(() => {
    if (!row) return [];
    return sortSalespersonBrands(row.brands, brandSort, brandSortDirection);
  }, [brandSort, brandSortDirection, row]);

  const compactStats = row
    ? [
        { label: "品牌", value: formatAdminNumber(row.brandCount) },
        { label: "任务", value: formatAdminNumber(row.taskCount) },
        { label: "红人", value: formatAdminNumber(row.influencerCount) },
        { label: "邮件", value: formatAdminNumber(row.emailCount) },
        { label: "回复", value: formatAdminNumber(row.replyCount) },
        {
          label: "回复率",
          value: row.replyRate === null ? "暂无" : formatAdminPercent(row.replyCount, row.emailCount),
        },
        { label: "待跟进", value: formatAdminNumber(row.pendingFollowUpCount) },
        { label: "进度", value: row.progressStatus.label },
      ]
    : [];

  return (
    <AdminDrawer
      open={Boolean(row)}
      title={row ? `${row.name} · 品牌跟进详情` : ""}
      description={row ? `共负责 ${formatAdminNumber(row.brandCount)} 个品牌` : undefined}
      onClose={onClose}
    >
      {row ? (
        <div className="space-y-3 overflow-x-hidden">
          <div className="rounded-md border border-[#DDE6F0] bg-[#F8FAFD] px-3 py-2.5">
            <AdminSalespersonLabel
              name={row.name}
              subtitle={row.userId ? `#${row.userId} · ${row.key}` : "尚未分配负责人"}
              avatarUrl={row.userId ? getUserAvatar(row.userId) : null}
            />
          </div>

          <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-4">
            {compactStats.map((stat) => (
              <div key={stat.label} className="min-w-0 rounded-md border border-[#E5ECF4] bg-white px-2.5 py-1.5">
                <p className="text-[10px] font-medium text-[#98A2B3]">{stat.label}</p>
                <p className="mt-0.5 truncate text-sm font-semibold tabular-nums text-[#102033]">{stat.value}</p>
              </div>
            ))}
          </div>

          <AdminSection
            title="品牌明细"
            description="紧凑双行展示，适配抽屉宽度，无需横向滚动。"
            actions={
              <div className="flex flex-wrap items-center gap-1.5">
                <AdminSelect value={brandSort} onChange={(event) => setBrandSort(event.target.value as BrandSortKey)} className="h-7 text-xs">
                  <option value="updatedAt">按更新时间</option>
                  <option value="status">按跟进状态</option>
                  <option value="reply">按回复数</option>
                </AdminSelect>
                <AdminSelect
                  value={brandSortDirection}
                  onChange={(event) => setBrandSortDirection(event.target.value as "asc" | "desc")}
                  className="h-7 text-xs"
                >
                  <option value="desc">降序</option>
                  <option value="asc">升序</option>
                </AdminSelect>
              </div>
            }
          >
            {sortedBrands.length ? (
              <div className="divide-y divide-[#EEF2F7]">
                {sortedBrands.map((brand) => (
                  <BrandCompactRow
                    key={brand.id}
                    brand={brand}
                    logoUrl={getProductLogo(brand.id)}
                    isUnassigned={row.key === UNASSIGNED_SALESPERSON_KEY}
                    onEdit={() => onEditBrand(brand)}
                    onReassign={() => onReassignBrand(brand)}
                    onDisable={() => onDisableBrand(brand)}
                    onDelete={() => onDeleteBrand(brand)}
                  />
                ))}
              </div>
            ) : (
              <AdminState message="当前业务员暂无负责品牌。" />
            )}
          </AdminSection>
        </div>
      ) : null}
    </AdminDrawer>
  );
}

function BrandCompactRow({
  brand,
  logoUrl,
  isUnassigned,
  onEdit,
  onReassign,
  onDisable,
  onDelete,
}: {
  brand: EnrichedBrandProduct;
  logoUrl?: string;
  isUnassigned?: boolean;
  onEdit: () => void;
  onReassign: () => void;
  onDisable: () => void;
  onDelete: () => void;
}) {
  return (
    <div className="space-y-1.5 px-3 py-2.5 hover:bg-[#F8FAFC]">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <AdminBrandLabel
            name={brand.name}
            subtitle={`#${brand.id} · ${brand.slug || "暂无 slug"}`}
            logoUrl={logoUrl}
            compact
          />
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          <AdminStatusBadge meta={deriveBrandOperatorStatus(brand)} />
          <span className="text-[11px] text-[#98A2B3]">{formatAdminDate(brand.updated_at ?? brand.created_at)}</span>
        </div>
        <div className="shrink-0">
          <AdminCompactActions
            primaryHref={`/admin/products/${brand.id}`}
            primaryLabel="详情"
            secondaryLabel="编辑"
            secondaryOnClick={onEdit}
            items={[
              { label: isUnassigned ? "分配负责人" : "更换负责人", onClick: onReassign },
              { label: "停用品牌", onClick: onDisable },
              { label: "删除品牌", danger: true, onClick: onDelete },
            ]}
          />
        </div>
      </div>
      <div className="flex flex-wrap gap-x-3 gap-y-1 pl-9 text-[11px] text-[#667085]">
        <span>
          任务 <strong className="font-semibold tabular-nums text-[#344054]">{formatAdminNumber(brand.collection_task_count)}</strong>
        </span>
        <span>
          红人 <strong className="font-semibold tabular-nums text-[#344054]">{formatAdminNumber(brand.influencer_count)}</strong>
        </span>
        <span>
          邮件/回复{" "}
          <strong className="font-semibold tabular-nums text-[#344054]">
            {formatAdminNumber(brand.email_count)} / {formatAdminNumber(brand.reply_count)}
          </strong>
        </span>
        {brand.status !== "active" ? (
          <span className="rounded bg-[#F2F4F7] px-1.5 py-0.5 text-[#667085]">
            {brand.status === "hidden" ? "已停用" : "已归档"}
          </span>
        ) : null}
      </div>
    </div>
  );
}

function SalespersonProgressTableGroup({
  row,
  expanded,
  avatarUrl,
  getProductLogo,
  onToggle,
  onOpenDetail,
  onEditSalesperson,
  onAssignBrands,
  onDisableSalesperson,
  onDeleteSalesperson,
  onEditBrand,
  onReassignBrand,
  onDisableBrand,
  onDeleteBrand,
  onQuickAssignBrand,
}: {
  row: SalespersonProgressRow;
  expanded: boolean;
  avatarUrl?: string;
  getProductLogo: (productId: number | null | undefined) => string | undefined;
  onToggle: () => void;
  onOpenDetail: () => void;
  onEditSalesperson: () => void;
  onAssignBrands: () => void;
  onDisableSalesperson: () => void;
  onDeleteSalesperson: () => void;
  onEditBrand: (brand: EnrichedBrandProduct) => void;
  onReassignBrand: (brand: EnrichedBrandProduct) => void;
  onDisableBrand: (brand: EnrichedBrandProduct) => void;
  onDeleteBrand: (brand: EnrichedBrandProduct) => void;
  onQuickAssignBrand: (brand: EnrichedBrandProduct) => void;
}) {
  const previewBrands = sortSalespersonBrands(row.brands, "updatedAt", "desc").slice(0, 5);
  const isUnassigned = row.key === UNASSIGNED_SALESPERSON_KEY;
  const canManageSales = !isUnassigned && row.userId;

  return (
    <>
      <tr
        className={cn(
          "border-b border-[#E5ECF4] bg-white text-[#344054] transition hover:bg-[#F8FAFC]",
          isUnassigned && row.brandCount > 0 && "bg-[#FFFAEB]/30",
        )}
      >
        <td className="h-[44px] w-10 border-l-4 border-l-[#2563EB] px-3 py-1.5 align-middle">
          <button
            type="button"
            aria-label={expanded ? "收起品牌列表" : "展开品牌列表"}
            onClick={onToggle}
            disabled={row.brandCount === 0}
            className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-[#D8E2EE] bg-white text-[#667085] transition hover:bg-[#F3F6FA] disabled:cursor-not-allowed disabled:opacity-40"
          >
            {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
          </button>
        </td>
        <td className="h-[44px] px-3 py-1.5 align-middle">
          <AdminSalespersonLabel
            name={row.name}
            subtitle={isUnassigned ? "尚未分配负责人" : row.userId ? `#${row.userId} · ${row.key}` : row.key}
            avatarUrl={avatarUrl}
          />
        </td>
        <td className="h-[44px] px-3 py-1.5 align-middle tabular-nums font-medium text-[#102033]">{formatAdminNumber(row.brandCount)}</td>
        <td className="h-[44px] px-3 py-1.5 align-middle tabular-nums">{formatAdminNumber(row.taskCount)}</td>
        <td className="h-[44px] px-3 py-1.5 align-middle tabular-nums">{formatAdminNumber(row.influencerCount)}</td>
        <td className="h-[44px] px-3 py-1.5 align-middle tabular-nums">{formatAdminNumber(row.emailCount)}</td>
        <td className="h-[44px] px-3 py-1.5 align-middle tabular-nums">{formatAdminNumber(row.replyCount)}</td>
        <td className="h-[44px] px-3 py-1.5 align-middle tabular-nums">
          {row.replyRate === null ? "暂无" : formatAdminPercent(row.replyCount, row.emailCount)}
        </td>
        <td className="h-[44px] px-3 py-1.5 align-middle">
          <span className={cn("tabular-nums", row.pendingFollowUpCount > 0 && "font-medium text-[#B54708]")}>
            {formatAdminNumber(row.pendingFollowUpCount)}
          </span>
        </td>
        <td className="h-[44px] px-3 py-1.5 align-middle text-[#667085]">{formatAdminDate(row.updatedAt)}</td>
        <td className="h-[44px] px-3 py-1.5 align-middle">
          <AdminStatusBadge meta={row.progressStatus} />
        </td>
        <td className="h-[44px] min-w-[180px] px-3 py-1.5 align-middle">
          {canManageSales ? (
            <AdminCompactActions
              primaryOnClick={onOpenDetail}
              primaryLabel="查看详情"
              secondaryLabel="编辑"
              secondaryOnClick={onEditSalesperson}
              items={[
                { label: "删除", danger: true, onClick: onDeleteSalesperson },
                { label: "分配品牌", onClick: onAssignBrands },
                { label: "停用业务员", onClick: onDisableSalesperson },
                ...(row.userId ? [{ label: "账号详情", href: `/admin/users/${row.userId}` }] : []),
              ]}
            />
          ) : (
            <AdminActionButton onClick={onOpenDetail}>查看详情</AdminActionButton>
          )}
        </td>
      </tr>
      {expanded && row.brandCount > 0 ? (
        <tr className="bg-[#FAFBFC]">
          <td colSpan={12} className="px-3 py-2">
            <div className="ml-3 overflow-hidden rounded-md border border-[#E5ECF4] bg-white">
              <div className="divide-y divide-[#EEF2F7]">
                {previewBrands.map((brand) => (
                  <BrandCompactRow
                    key={brand.id}
                    brand={brand}
                    logoUrl={getProductLogo(brand.id)}
                    isUnassigned={isUnassigned}
                    onEdit={() => onEditBrand(brand)}
                    onReassign={() => onQuickAssignBrand(brand)}
                    onDisable={() => onDisableBrand(brand)}
                    onDelete={() => onDeleteBrand(brand)}
                  />
                ))}
              </div>
              {row.brandCount > previewBrands.length ? (
                <div className="border-t border-[#EEF2F7] px-3 py-2 text-xs text-[#98A2B3]">
                  还有 {formatAdminNumber(row.brandCount - previewBrands.length)} 个品牌，点击“查看详情”查看完整列表。
                </div>
              ) : null}
            </div>
          </td>
        </tr>
      ) : null}
    </>
  );
}
