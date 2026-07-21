// 文件说明：前端管理员后台组件；当前文件：admin users panel
"use client";

import { useEffect, useMemo, useState } from "react";
import { KeyRound, Search, UserCheck, Users } from "lucide-react";

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
import {
  filterAdminRows,
  formatAdminDate,
  formatAdminNumber,
  formatSalespersonDisplay,
  getRoleLabel,
  type StatusMeta,
} from "@/components/admin/admin-ui-helpers";
import { AdminPasswordResetDialog, AdminUserAccountDialog } from "@/components/admin/admin-user-dialogs";
import { SalespersonDeleteDialog } from "@/components/admin/admin-products-management";
import { deleteAdminUser, fetchAdminProducts, fetchAdminUsers, updateAdminUser, type AdminProduct, type AdminUser } from "@/lib/api";
import { getStoredAuthSession } from "@/lib/auth";

const activeMeta: Record<string, StatusMeta> = {
  active: { label: "启用", tone: "success" },
  disabled: { label: "禁用", tone: "muted" },
};

export function AdminUsersPanel() {
  const [items, setItems] = useState<AdminUser[]>([]);
  const [products, setProducts] = useState<AdminProduct[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [productsLoading, setProductsLoading] = useState(false);
  const [filters, setFilters] = useState({ search: "", owner: "", status: "" });
  const [accountDialogOpen, setAccountDialogOpen] = useState(false);
  const [editingUser, setEditingUser] = useState<AdminUser | null>(null);
  const [passwordUser, setPasswordUser] = useState<AdminUser | null>(null);
  const [deleteUser, setDeleteUser] = useState<AdminUser | null>(null);
  const [deleteLoading, setDeleteLoading] = useState(false);

  useEffect(() => {
    let active = true;
    fetchAdminUsers()
      .then((users) => {
        if (active) setItems(users);
      })
      .catch((err) => {
        if (active) setError(err instanceof Error ? err.message : "业务员列表加载失败。");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  async function reloadAll() {
    const users = await fetchAdminUsers();
    setItems(users);
  }

  async function ensureProductsLoaded() {
    if (products.length > 0 || productsLoading) return;
    setProductsLoading(true);
    setActionError(null);
    try {
      const productItems = await fetchAdminProducts();
      setProducts(productItems);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "品牌权限加载失败，请稍后重试。");
    } finally {
      setProductsLoading(false);
    }
  }

  async function reloadProducts() {
    const productItems = await fetchAdminProducts();
    setProducts(productItems);
  }

  function replaceUser(saved: AdminUser) {
    setItems((current) => {
      const exists = current.some((item) => item.id === saved.id);
      return exists ? current.map((item) => item.id === saved.id ? saved : item) : [...current, saved];
    });
  }

  async function toggleUser(user: AdminUser) {
    setActionError(null);
    try {
      replaceUser(await updateAdminUser(user.id, { is_active: !user.is_active }));
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "账号状态更新失败。");
    }
  }

  async function confirmDeleteUser() {
    if (!deleteUser) return;
    setDeleteLoading(true);
    setActionError(null);
    try {
      const username = deleteUser.username;
      const result = await deleteAdminUser(deleteUser.id);
      setDeleteUser(null);
      await reloadAll();
      setSuccessMessage(
        `已删除 ${username}，释放 ${result.released_products} 个品牌和 ${result.released_tasks} 个任务，历史数据已保留。`,
      );
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "删除业务员失败，请稍后重试。");
    } finally {
      setDeleteLoading(false);
    }
  }

  const filteredItems = useMemo(
    () =>
      filterAdminRows(
        items.map((item) => ({
          ...item,
          name: item.username,
          owner: item.role,
          brand: (item.bound_products ?? []).map((product) => product.name).join(" "),
          status: item.status,
          createdAt: item.created_at,
        })),
        filters,
      ),
    [items, filters],
  );

  const totalTasks = items.reduce((sum, item) => sum + (item.collection_task_count ?? 0), 0);
  const totalFailures = items.reduce((sum, item) => sum + (item.collection_failed_count ?? 0) + (item.email_failed_count ?? 0), 0);
  const pendingReplies = items.reduce((sum, item) => sum + (item.pending_reply_count ?? 0), 0);

  return (
    <div className="space-y-3">
      <AdminPageHeader
        label="业务员管理"
        title="业务员业绩与账号状态"
        description="按业务员查看品牌负责范围、采集表现、邮件触达和回复处理压力，方便分配品牌和追踪业绩。"
        backFallback="/admin/dashboard"
        actions={
          <>
            <AdminActionButton
              onClick={() => {
                setEditingUser(null);
                setAccountDialogOpen(true);
                void ensureProductsLoaded();
              }}
            >
              <UserCheck className="h-3.5 w-3.5" />
              创建业务员
            </AdminActionButton>
            <AdminActionButton href="/admin/products">
              <KeyRound className="h-3.5 w-3.5" />
              管理品牌权限
            </AdminActionButton>
          </>
        }
      />

      <AdminKpiGrid>
        <AdminKpiCard label="账号总数" value={items.length} helper="管理员与业务员" icon={Users} tone="info" />
        <AdminKpiCard label="启用账号" value={items.filter((item) => item.is_active).length} helper="可登录后台" icon={UserCheck} tone="success" />
        <AdminKpiCard label="任务总数" value={totalTasks} helper="负责采集任务" icon={Search} tone="info" />
        <AdminKpiCard label="异常待处理" value={totalFailures + pendingReplies} helper="失败任务、邮件和回复" icon={KeyRound} tone="warning" />
      </AdminKpiGrid>

      <AdminFilterBar>
        <AdminFilterField label="搜索账号 / 品牌" className="min-w-[240px] flex-1">
          <AdminInput
            value={filters.search}
            placeholder="输入账号、品牌或邮箱"
            onChange={(event) => setFilters((prev) => ({ ...prev, search: event.target.value }))}
          />
        </AdminFilterField>
        <AdminFilterField label="角色">
          <AdminSelect value={filters.owner} onChange={(event) => setFilters((prev) => ({ ...prev, owner: event.target.value }))}>
            <option value="">全部角色</option>
            <option value="sales">业务员</option>
            <option value="admin">管理员</option>
          </AdminSelect>
        </AdminFilterField>
        <AdminFilterField label="状态">
          <AdminSelect value={filters.status} onChange={(event) => setFilters((prev) => ({ ...prev, status: event.target.value }))}>
            <option value="">全部状态</option>
            <option value="active">启用</option>
            <option value="disabled">禁用</option>
          </AdminSelect>
        </AdminFilterField>
      </AdminFilterBar>

      {actionError ? <div className="rounded-md border border-[#FECDCA] bg-[#FEF3F2] px-4 py-3 text-sm text-[#B42318]">{actionError}</div> : null}
      {successMessage ? <div className="rounded-md border border-[#BAE6D1] bg-[#ECFDF3] px-4 py-3 text-sm text-[#047857]">{successMessage}</div> : null}

      <AdminSection title="业务员列表" description="展示负责品牌、任务产出、邮件触达、回复处理和最近活跃时间。">
        {loading ? (
          <AdminState type="loading" message="正在加载业务员..." />
        ) : error ? (
          <AdminState type="error" message={error} />
        ) : filteredItems.length === 0 && items.length === 0 ? (
          <AdminState
            message="暂无业务员账号，请创建业务员账号后分配品牌和任务。"
            action={
              <AdminActionButton
                onClick={() => {
                  setEditingUser(null);
                  setAccountDialogOpen(true);
                  void ensureProductsLoaded();
                }}
              >
                <UserCheck className="h-3.5 w-3.5" />
                创建业务员账号
              </AdminActionButton>
            }
          />
        ) : (
          <AdminTable
            minWidth={1180}
            columns={["账号", "角色", "状态", "负责品牌数", "绑定品牌", "任务数", "采集成功 / 失败", "红人数", "邮件发送 / 失败", "回复 / 待处理", "最近活跃时间", "操作"]}
            rows={filteredItems.map((item) => [
              <span key="name" className="block min-w-[140px]">
                <span className="block font-medium text-[#102033]">{formatSalespersonDisplay(item)}</span>
                <span className="block text-xs text-[#667085]">#{item.id}</span>
              </span>,
              getRoleLabel(item.role),
              <AdminStatusBadge key="status" meta={activeMeta[item.status] ?? activeMeta.disabled} />,
              formatAdminNumber(item.product_count),
              <span key="brands" className="block max-w-[260px] truncate">{(item.bound_products ?? []).map((product) => product.name).join("、") || "暂无"}</span>,
              formatAdminNumber(item.collection_task_count),
              `${formatAdminNumber(item.collection_success_count)} / ${formatAdminNumber(item.collection_failed_count)}`,
              formatAdminNumber(item.influencer_count),
              `${formatAdminNumber(item.email_count)} / ${formatAdminNumber(item.email_failed_count)}`,
              `${formatAdminNumber(item.reply_count)} / ${formatAdminNumber(item.pending_reply_count)}`,
              formatAdminDate(item.last_active_at),
              <AdminCompactActions
                key="actions"
                primaryOnClick={() => {
                  setEditingUser(item);
                  setAccountDialogOpen(true);
                  void ensureProductsLoaded();
                }}
                primaryLabel="编辑"
                items={[
                  { label: "查看详情", href: `/admin/users/${item.id}` },
                  { label: item.is_active ? "禁用账号" : "启用账号", onClick: () => void toggleUser(item), danger: item.is_active },
                  { label: "重置密码", onClick: () => setPasswordUser(item) },
                  ...(item.role === "sales"
                    ? [{ label: "删除", onClick: () => setDeleteUser(item), danger: true }]
                    : []),
                ]}
              />,
            ])}
            emptyMessage="暂无匹配的业务员。"
          />
        )}
      </AdminSection>
      <AdminUserAccountDialog
        key={`${accountDialogOpen ? "open" : "closed"}-${editingUser?.id ?? "new"}`}
        open={accountDialogOpen}
        user={editingUser}
        products={products}
        users={items}
        currentUserId={getStoredAuthSession()?.userId ?? null}
        onClose={() => setAccountDialogOpen(false)}
        onProductsChanged={reloadProducts}
        onSaved={async (saved) => {
          replaceUser(saved);
          await reloadAll();
          setSuccessMessage("账号与品牌权限已保存。");
        }}
      />
      <AdminPasswordResetDialog user={passwordUser} onClose={() => setPasswordUser(null)} />
      <SalespersonDeleteDialog
        open={Boolean(deleteUser)}
        userName={deleteUser?.display_name?.trim() || deleteUser?.username || ""}
        username={deleteUser?.username || ""}
        productCount={deleteUser?.product_count ?? 0}
        taskCount={deleteUser?.collection_task_count ?? 0}
        influencerCount={deleteUser?.influencer_count ?? 0}
        emailCount={deleteUser?.email_count ?? 0}
        replyCount={deleteUser?.reply_count ?? 0}
        error={deleteUser ? actionError : null}
        loading={deleteLoading}
        onCancel={() => {
          setDeleteUser(null);
          setActionError(null);
        }}
        onDelete={() => void confirmDeleteUser()}
      />
    </div>
  );
}
