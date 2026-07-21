// 文件说明：前端管理员后台页面入口；当前文件：page
import { AdminMonthlyReportPanel } from "@/components/admin/admin-monthly-report-panel";
import { AdminShell } from "@/components/admin/admin-shell";

export default function AdminMonthlyReportPage() {
  return (
    <AdminShell>
      <AdminMonthlyReportPanel />
    </AdminShell>
  );
}
