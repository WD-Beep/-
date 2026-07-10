import type { Metadata } from "next";

import { AdminSalesWorkbenchPanel } from "@/components/admin/admin-sales-workbench-panel";
import { AdminShell } from "@/components/admin/admin-shell";

export const metadata: Metadata = {
  title: "业务员作业 · 红人智采管理员后台",
  description: "管理员按业务员追踪品牌、采集、红人、邮件、回复和异常情况。",
};

export default function AdminSalesWorkbenchPage() {
  return (
    <AdminShell>
      <AdminSalesWorkbenchPanel />
    </AdminShell>
  );
}
