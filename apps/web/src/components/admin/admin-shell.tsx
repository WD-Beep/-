import { AdminHeader } from "@/components/admin/admin-header";
import { AdminRouteGuard } from "@/components/admin/admin-route-guard";
import { AdminSidebar } from "@/components/admin/admin-sidebar";

type AdminShellProps = {
  children: React.ReactNode;
};

export function AdminShell({ children }: AdminShellProps) {
  return (
    <AdminRouteGuard>
      <div className="flex h-dvh overflow-hidden bg-[#F3F6FA] text-[#1F2937]">
        <AdminSidebar />
        <div className="flex min-w-0 flex-1 flex-col">
          <AdminHeader />
          <main className="min-h-0 flex-1 overflow-auto px-4 py-5 sm:px-6 lg:px-7">{children}</main>
        </div>
      </div>
    </AdminRouteGuard>
  );
}
