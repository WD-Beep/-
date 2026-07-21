// 文件说明：前端页面组件；当前文件：business route shell
"use client";

import { usePathname } from "next/navigation";

import { Sidebar } from "@/components/layout/sidebar";

export function BusinessRouteShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  if (pathname.startsWith("/admin") || pathname.startsWith("/login")) {
    return <>{children}</>;
  }

  return (
    <div className="flex h-screen overflow-hidden bg-[hsl(214_30%_95%)]">
      <Sidebar />
      <main className="min-w-0 flex-1 overflow-hidden">{children}</main>
    </div>
  );
}
