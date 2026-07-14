"use client";

import { usePathname } from "next/navigation";

import { AdminHeader } from "@/components/admin/admin-header";
import { AdminRouteGuard } from "@/components/admin/admin-route-guard";
import { AdminMobileNav, AdminSidebar } from "@/components/admin/admin-sidebar";

export function AdminLayoutShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  if (pathname.startsWith("/admin/login")) {
    return <>{children}</>;
  }

  return (
    <AdminRouteGuard>
      <div className="flex h-dvh overflow-hidden bg-[#F3F6FA] text-[#1F2937]">
        <AdminSidebar />
        <div className="flex min-w-0 flex-1 flex-col">
          <AdminHeader />
          <main className="min-h-0 flex-1 space-y-0 overflow-auto px-3 py-3 pb-20 sm:px-4 md:pb-4 lg:px-5 [&_>_.space-y-5]:space-y-3">
            {children}
          </main>
        </div>
        <AdminMobileNav />
      </div>
    </AdminRouteGuard>
  );
}
