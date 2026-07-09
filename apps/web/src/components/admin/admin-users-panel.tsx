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
  getRoleLabel,
  type StatusMeta,
} from "@/components/admin/admin-ui-helpers";
import { type AdminUser, fetchAdminUsers } from "@/lib/api";

const activeMeta: Record<string, StatusMeta> = {
  active: { label: "启用", tone: "success" },
  disabled: { label: "禁用", tone: "muted" },
};

export function AdminUsersPanel() {
  const [items, setItems] = useState<AdminUser[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState({ search: "", owner: "", status: "" });

  useEffect(() => {
    let active = true;
    fetchAdminUsers()
      .then((data) => {
        if (active) setItems(data);
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

  const filteredItems = useMemo(
    () =>
      filterAdminRows(
        items.map((item) => ({
          ...item,
          name: item.username,
          owner: item.role,
          brand: item.bound_products.map((product) => product.name).join(" "),
          status: item.status,
          createdAt: item.created_at,
        })),
        filters,
      ),
    [items, filters],
  );

  const totalTasks = items.reduce((sum, item) => sum + item.collection_task_count, 0);
  const totalFailures = items.reduce((sum, item) => sum + item.collection_failed_count + item.email_failed_count, 0);
  const pendingReplies = items.reduce((sum, item) => sum + item.pending_reply_count, 0);

  return (
    <div className="space-y-5">
      <AdminPageHeader
        label="业务员管理"
        title="业务员业绩与账号状态"
        description="按业务员查看品牌负责范围、采集表现、邮件触达和回复处理压力，方便分配品牌和追踪业绩。"
        actions={
          <>
            <AdminActionButton>
              <UserCheck className="h-3.5 w-3.5" />
              新增业务员
            </AdminActionButton>
            <AdminActionButton>
              <KeyRound className="h-3.5 w-3.5" />
              批量重置
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

      <AdminSection title="业务员列表" description="展示负责品牌、任务产出、邮件触达、回复处理和最近活跃时间。">
        {loading ? (
          <AdminState type="loading" message="正在加载业务员..." />
        ) : error ? (
          <AdminState type="error" message={error} />
        ) : (
          <AdminTable
            minWidth={1180}
            columns={["账号", "角色", "状态", "负责品牌数", "绑定品牌", "任务数", "采集成功 / 失败", "红人数", "邮件发送 / 失败", "回复 / 待处理", "最近活跃时间", "操作"]}
            rows={filteredItems.map((item) => [
              <span key="name" className="font-medium text-[#102033]">#{item.id} {item.username}</span>,
              getRoleLabel(item.role),
              <AdminStatusBadge key="status" meta={activeMeta[item.status] ?? activeMeta.disabled} />,
              formatAdminNumber(item.product_count),
              <span key="brands" className="block max-w-[260px] truncate">{item.bound_products.map((product) => product.name).join("、") || "暂无"}</span>,
              formatAdminNumber(item.collection_task_count),
              `${formatAdminNumber(item.collection_success_count)} / ${formatAdminNumber(item.collection_failed_count)}`,
              formatAdminNumber(item.influencer_count),
              `${formatAdminNumber(item.email_count)} / ${formatAdminNumber(item.email_failed_count)}`,
              `${formatAdminNumber(item.reply_count)} / ${formatAdminNumber(item.pending_reply_count)}`,
              formatAdminDate(item.last_active_at),
              <AdminCompactActions
                key="actions"
                primaryHref={`/admin/users/${item.id}`}
                primaryLabel="详情"
                items={[
                  { label: "分配品牌", disabled: true },
                  { label: item.is_active ? "禁用" : "启用", disabled: true, danger: item.is_active },
                  { label: "重置密码", disabled: true },
                  { label: "查看业绩", href: `/admin/users/${item.id}` },
                ]}
              />,
            ])}
            emptyMessage="暂无匹配的业务员。"
          />
        )}
      </AdminSection>
    </div>
  );
}
