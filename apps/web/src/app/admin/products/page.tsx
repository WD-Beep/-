import type { Metadata } from "next";

import { AdminProductsPanel } from "@/components/admin/admin-products-panel";
import { AdminShell } from "@/components/admin/admin-shell";

export const metadata: Metadata = {
  title: "品牌管理 · 红人智采管理员后台",
  description: "管理员查看所有品牌和运营数据。",
};

export default function AdminProductsPage() {
  return (
    <AdminShell>
      <AdminProductsPanel />
    </AdminShell>
  );
}
