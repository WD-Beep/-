import { AdminSettingsPanel } from "@/components/admin/admin-detail-panels";
import { AdminShell } from "@/components/admin/admin-shell";

export default function AdminSettingsPage() {
  return (
    <AdminShell>
      <AdminSettingsPanel />
    </AdminShell>
  );
}
