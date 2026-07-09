"use client";

import { useEffect, useMemo, useState } from "react";
import { Search, Send, ShoppingBag } from "lucide-react";

import {
  AdminActionButton,
  AdminAvatarLabel,
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
  getProductStatusMeta,
  type StatusMeta,
} from "@/components/admin/admin-ui-helpers";
import { type AdminProduct, fetchAdminProducts } from "@/lib/api";

function deriveProductStatus(product: AdminProduct): StatusMeta {
  if (product.reply_count > 0) return { label: "已有回复", tone: "success" };
  if (product.email_count > 0) return { label: "待跟进", tone: "warning" };
  if (product.collection_task_count > 0) return { label: "采集中", tone: "info" };
  return getProductStatusMeta(product.status);
}

export function AdminProductsPanel() {
  const [items, setItems] = useState<AdminProduct[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState({ search: "", owner: "", status: "" });

  useEffect(() => {
    let active = true;
    fetchAdminProducts()
      .then((data) => {
        if (active) setItems(data);
      })
      .catch((err) => {
        if (active) setError(err instanceof Error ? err.message : "品牌列表加载失败。");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const enrichedItems = useMemo(
    () =>
      items.map((item) => ({
        ...item,
        name: item.name,
        owner: item.owner_names.join(" "),
        brand: item.name,
        operatorStatus: deriveProductStatus(item).label,
        rawStatus: item.status,
        createdAt: item.updated_at ?? item.created_at,
      })),
    [items],
  );

  const filteredItems = useMemo(
    () =>
      filterAdminRows(
        enrichedItems.map((item) => ({
          ...item,
          status: item.operatorStatus,
        })),
        filters,
      ),
    [enrichedItems, filters],
  );
  const activeCount = items.filter((item) => item.status === "active").length;
  const totalInfluencers = items.reduce((sum, item) => sum + item.influencer_count, 0);
  const repliedBrands = items.filter((item) => item.reply_count > 0).length;

  return (
    <div className="space-y-5">
      <AdminPageHeader
        label="品牌管理"
        title="品牌运营状态"
        description="按品牌追踪负责人、成员、采集任务、红人沉淀、邮件触达和回复进展，帮助管理员发现停滞或异常品牌。"
        actions={
          <>
            <AdminActionButton>
              <ShoppingBag className="h-3.5 w-3.5" />
              新增品牌
            </AdminActionButton>
            <AdminActionButton>
              <Send className="h-3.5 w-3.5" />
              批量分配
            </AdminActionButton>
          </>
        }
      />

      <AdminKpiGrid>
        <AdminKpiCard label="总品牌数" value={items.length} helper="全部品牌" icon={ShoppingBag} tone="info" />
        <AdminKpiCard label="启用品牌" value={activeCount} helper="可参与运营" icon={Search} tone="success" />
        <AdminKpiCard label="红人总数" value={totalInfluencers} helper="品牌下沉淀资料" icon={ShoppingBag} tone="info" />
        <AdminKpiCard label="已有回复品牌" value={repliedBrands} helper="可优先跟进" icon={Send} tone="success" />
      </AdminKpiGrid>

      <AdminFilterBar>
        <AdminFilterField label="搜索品牌 / SLUG" className="min-w-[240px] flex-1">
          <AdminInput
            value={filters.search}
            placeholder="输入品牌名、slug 或业务员"
            onChange={(event) => setFilters((prev) => ({ ...prev, search: event.target.value }))}
          />
        </AdminFilterField>
        <AdminFilterField label="业务员">
          <AdminInput
            value={filters.owner}
            placeholder="业务员"
            onChange={(event) => setFilters((prev) => ({ ...prev, owner: event.target.value }))}
          />
        </AdminFilterField>
        <AdminFilterField label="状态">
          <AdminSelect value={filters.status} onChange={(event) => setFilters((prev) => ({ ...prev, status: event.target.value }))}>
            <option value="">全部状态</option>
            <option value="启用">启用</option>
            <option value="采集中">采集中</option>
            <option value="待跟进">待发信</option>
            <option value="已有回复">已有回复</option>
            <option value="异常">异常</option>
            <option value="暂停">暂停</option>
          </AdminSelect>
        </AdminFilterField>
      </AdminFilterBar>

      <AdminSection title="品牌列表" description="用运营状态表达品牌进度，不直接暴露底层技术字段。">
        {loading ? (
          <AdminState type="loading" message="正在加载品牌..." />
        ) : error ? (
          <AdminState type="error" message={error} />
        ) : (
          <AdminTable
            minWidth={980}
            columns={["品牌", "负责人 / 成员", "任务", "红人", "邮件 / 回复", "状态", "更新时间", "操作"]}
            rows={filteredItems.map((item) => [
              <AdminAvatarLabel key="brand" name={item.name} subtitle={`#${item.id} · ${item.slug || "暂无 slug"}`} />,
              <span key="owner" className="block max-w-[220px]">
                <span className="block truncate font-medium text-[#102033]">{item.owner_names.join("、") || "暂无"}</span>
                <span className="block truncate text-xs text-[#667085]">
                  {item.members.map((member) => `${member.username}（${member.role}）`).join("、") || "暂无成员"}
                </span>
              </span>,
              formatAdminNumber(item.collection_task_count),
              formatAdminNumber(item.influencer_count),
              `${formatAdminNumber(item.email_count)} / ${formatAdminNumber(item.reply_count)}`,
              <AdminStatusBadge key="status" meta={deriveProductStatus({ ...item, status: item.rawStatus })} />,
              formatAdminDate(item.updated_at ?? item.created_at),
              <AdminCompactActions
                key="actions"
                primaryHref={`/admin/products/${item.id}`}
                primaryLabel="详情"
                items={[
                  { label: "分配业务员", disabled: true },
                  { label: "查看红人", href: "/admin/influencers" },
                  { label: "查看邮件", href: "/admin/emails" },
                  { label: item.rawStatus === "hidden" ? "启用" : "暂停", disabled: true, danger: item.rawStatus !== "hidden" },
                ]}
              />,
            ])}
            emptyMessage="暂无匹配的品牌。"
          />
        )}
      </AdminSection>
    </div>
  );
}
