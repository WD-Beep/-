import type { Metadata } from "next";

import { AdminUserDetailPanel } from "@/components/admin/admin-detail-panels";
import { AdminShell } from "@/components/admin/admin-shell";

export const metadata: Metadata = {
  title: "业务员详情 · 红人智采管理员后台",
  description: "管理员查看业务员详情。",
};

export default async function AdminUserDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <AdminShell>
      <AdminUserDetailPanel userId={Number(id)} />
    </AdminShell>
  );
}
