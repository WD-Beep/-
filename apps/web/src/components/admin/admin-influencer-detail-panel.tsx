"use client";

import { useCallback, useEffect, useState } from "react";

import { AdminFeedbackBanner } from "@/components/admin/admin-crud";
import { InfluencerEditDrawer } from "@/components/admin/admin-entity-management";
import { AdminPageHeader, AdminState } from "@/components/admin/admin-ui";
import { InfluencerDetail } from "@/components/influencers/influencer-detail";
import {
  fetchAdminProducts,
  fetchAdminUsers,
  fetchInfluencer,
  type AdminProduct,
  type AdminUser,
  type Influencer,
} from "@/lib/api";

export function AdminInfluencerDetailPanel({ influencerId }: { influencerId: number }) {
  const [influencer, setInfluencer] = useState<Influencer | null>(null);
  const [products, setProducts] = useState<AdminProduct[]>([]);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [editOpen, setEditOpen] = useState(false);

  const reload = useCallback(async () => {
    const [item, productRows, userRows] = await Promise.all([
      fetchInfluencer(influencerId),
      fetchAdminProducts(),
      fetchAdminUsers(),
    ]);
    setInfluencer(item);
    setProducts(productRows);
    setUsers(userRows);
  }, [influencerId]);

  useEffect(() => {
    let active = true;
    queueMicrotask(() => {
      if (!active) return;
      void reload().catch((err) => {
        if (active) setError(err instanceof Error ? err.message : "红人详情加载失败。");
      });
    });
    return () => {
      active = false;
    };
  }, [reload]);

  if (error) return <AdminState type="error" message={error} />;
  if (!influencer) return <AdminState type="loading" message="正在加载红人详情..." />;

  return (
    <div className="space-y-4">
      <AdminPageHeader
        label="红人详情"
        title={influencer.display_name || influencer.username}
        description={`@${influencer.username} · ${influencer.platform}`}
        backFallback="/admin/influencers"
        actions={
          <button
            type="button"
            onClick={() => setEditOpen(true)}
            className="inline-flex h-9 items-center rounded-md border border-[#DDE6F0] bg-white px-3 text-sm font-medium text-[#344054] hover:border-[#2563EB] hover:text-[#2563EB]"
          >
            编辑红人
          </button>
        }
      />
      <AdminFeedbackBanner message={successMessage} />
      <InfluencerDetail
        initial={influencer}
        embedded
        backFallback="/admin/influencers"
        onEdit={() => setEditOpen(true)}
      />
      <InfluencerEditDrawer
        open={editOpen}
        influencerId={influencer.id}
        products={products}
        users={users}
        onClose={() => setEditOpen(false)}
        onSaved={async (saved) => {
          setInfluencer(saved);
          setSuccessMessage("红人资料已更新。");
        }}
      />
    </div>
  );
}
