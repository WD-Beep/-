import type { Metadata } from "next";

import { AdminDashboardPanel } from "@/components/admin/admin-dashboard-panel";
import { AdminShell } from "@/components/admin/admin-shell";

export const metadata: Metadata = {
  title: "管理员数据看板 · 红人智采",
  description: "红人智采管理员后台首页。",
};

export default function AdminDashboardPage() {
  return (
    <AdminShell>
      <AdminDashboardPanel />
    </AdminShell>
  );
}
