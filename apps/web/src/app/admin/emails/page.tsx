// 文件说明：前端管理员后台页面入口；当前文件：page
import { AdminEmailsPanel } from "@/components/admin/admin-detail-panels";
import { AdminShell } from "@/components/admin/admin-shell";

export default function AdminEmailsPage() {
  return (
    <AdminShell>
      <AdminEmailsPanel />
    </AdminShell>
  );
}
