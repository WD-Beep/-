import type { Metadata } from "next";

import { AdminShell } from "@/components/admin/admin-shell";
import { AdminUsersPanel } from "@/components/admin/admin-users-panel";

export const metadata: Metadata = {
  title: "业务员管理 · 红人智采管理员后台",
  description: "管理员查看业务员账号和业务数据。",
};

export default function AdminUsersPage() {
  return (
    <AdminShell>
      <AdminUsersPanel />
    </AdminShell>
  );
}
