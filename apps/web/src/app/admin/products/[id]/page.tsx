import type { Metadata } from "next";

import { AdminProductDetailPanel } from "@/components/admin/admin-detail-panels";
import { AdminShell } from "@/components/admin/admin-shell";

export const metadata: Metadata = {
  title: "品牌详情 · 红人智采管理员后台",
  description: "管理员查看品牌详情。",
};

export default async function AdminProductDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <AdminShell>
      <AdminProductDetailPanel productId={Number(id)} />
    </AdminShell>
  );
}
