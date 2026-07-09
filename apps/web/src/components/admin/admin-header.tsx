"use client";

import { LogOut, Menu, ShieldCheck } from "lucide-react";
import { useRouter } from "next/navigation";

import { clearAuthSession, getStoredAuthSession } from "@/lib/auth";

export function AdminHeader() {
  const router = useRouter();
  const session = getStoredAuthSession();

  function handleLogout() {
    clearAuthSession();
    router.replace("/admin/login?relogin=1");
  }

  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-[#D8E2EE] bg-[#FBFCFE] px-4 sm:px-6">
      <div className="flex items-center gap-2 text-sm font-semibold text-[#1A2A3A]">
        <Menu className="h-4 w-4 text-[#667085] md:hidden" />
        <ShieldCheck className="h-4 w-4 text-[#2563EB]" />
        管理员后台
      </div>
      <div className="flex items-center gap-3">
        <span className="hidden text-sm text-[#5F6B7A] sm:inline">{session?.username ?? "admin"}</span>
        <button
          type="button"
          onClick={handleLogout}
          className="inline-flex h-8 items-center gap-2 rounded-md border border-[#D8E2EE] bg-white px-3 text-xs font-medium text-[#344054] transition hover:bg-[#F3F6FA]"
        >
          <LogOut className="h-3.5 w-3.5" />
          退出登录
        </button>
      </div>
    </header>
  );
}
