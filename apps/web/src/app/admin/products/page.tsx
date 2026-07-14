import type { Metadata } from "next";

import { AdminProductsPanel } from "@/components/admin/admin-products-panel";
import { AdminShell } from "@/components/admin/admin-shell";

export const metadata: Metadata = {
  title: "业务员品牌进度 · 红人智采管理员后台",
  description: "管理员按业务员查看品牌跟进进度、邮件触达和回复情况。",
};

export default function AdminProductsPage() {
  return (
    <AdminShell>
      <AdminProductsPanel />
    </AdminShell>
  );
}
