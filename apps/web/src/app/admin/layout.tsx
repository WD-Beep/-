// 文件说明：前端管理员后台页面入口；当前文件：layout
import { AdminLayoutShell } from "@/components/admin/admin-layout-shell";

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return <AdminLayoutShell>{children}</AdminLayoutShell>;
}
