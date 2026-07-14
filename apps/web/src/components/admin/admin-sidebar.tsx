"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  BarChart3,
  BriefcaseBusiness,
  CalendarDays,
  Database,
  Inbox,
  LayoutDashboard,
  Mail,
  PanelLeftClose,
  PanelLeftOpen,
  Settings,
  ShoppingBag,
  Users,
} from "lucide-react";
import { useEffect, useState } from "react";

import { cn } from "@/lib/utils";

export const adminNavItems = [
  { href: "/admin/dashboard", label: "后台首页", description: "全局概览", icon: LayoutDashboard },
  { href: "/admin/monthly-report", label: "月度总结", description: "月报复盘", icon: CalendarDays },
  { href: "/admin/sales-workbench", label: "业务员作业", description: "作业追踪", icon: BriefcaseBusiness },
  { href: "/admin/users", label: "业务员管理", description: "账号与业绩", icon: Users },
  { href: "/admin/products", label: "品牌管理", description: "业务员进度", icon: ShoppingBag },
  { href: "/admin/collection-tasks", label: "采集任务", description: "任务监控", icon: BarChart3 },
  { href: "/admin/influencers", label: "红人数据", description: "资料库", icon: Database },
  { href: "/admin/emails", label: "邮件回复", description: "跟进工作台", icon: Inbox },
  { href: "/admin/settings", label: "系统信息", description: "状态与模块", icon: Settings },
];

export function AdminSidebar() {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [hovered, setHovered] = useState(false);
  const isCompact = collapsed && !hovered;

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const saved = window.localStorage.getItem("admin-sidebar-collapsed");
      if (saved) setCollapsed(saved === "1");
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  function toggleCollapsed() {
    setCollapsed((value) => {
      const next = !value;
      window.localStorage.setItem("admin-sidebar-collapsed", next ? "1" : "0");
      return next;
    });
  }

  return (
    <aside
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      className={cn(
        "hidden h-dvh shrink-0 flex-col border-r border-[#0B1727] bg-[#102033] text-[#E6EDF5] shadow-[8px_0_24px_rgba(16,32,51,0.14)] transition-[width] duration-200 ease-out md:flex",
        isCompact ? "w-[76px]" : "w-[264px]",
      )}
    >
      <div className={cn("border-b border-white/10 py-5", isCompact ? "px-3" : "px-5")}>
        <div className={cn("flex items-center", isCompact ? "justify-center" : "gap-3")}>
          <div className="flex h-9 w-9 items-center justify-center rounded-md bg-[#2563EB] shadow-[0_8px_18px_rgba(37,99,235,0.28)]">
            <Activity className="h-4 w-4" />
          </div>
          <div className={cn("overflow-hidden whitespace-nowrap transition-opacity duration-150", isCompact && "pointer-events-none w-0 opacity-0")}>
            <p className="text-sm font-semibold">红人智采</p>
            <p className="text-xs text-[#9FB1C5]">管理员后台</p>
          </div>
        </div>
      </div>
      <nav className="flex-1 space-y-1 px-3 py-4">
        {adminNavItems.map((item) => {
          const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              title={isCompact ? item.label : undefined}
              className={cn(
                "flex items-center rounded-md px-3 py-2.5 text-sm transition",
                isCompact ? "justify-center gap-0" : "gap-3",
                active
                  ? "bg-[#1D4ED8] text-white shadow-[0_8px_18px_rgba(29,78,216,0.24)]"
                  : "text-[#C7D3E0] hover:bg-white/8 hover:text-white",
              )}
            >
              <Icon className="h-4 w-4 shrink-0" />
              <span className={cn("min-w-0 overflow-hidden whitespace-nowrap transition-opacity duration-150", isCompact && "pointer-events-none w-0 opacity-0")}>
                <span className="block font-medium leading-5">{item.label}</span>
                <span className="block text-xs leading-4 text-[#9FB1C5]">{item.description}</span>
              </span>
            </Link>
          );
        })}
      </nav>
      <div className={cn("border-t border-white/10 py-4 text-xs leading-5 text-[#9FB1C5]", isCompact ? "px-3" : "px-5")}>
        <button
          type="button"
          onClick={toggleCollapsed}
          title={collapsed ? "固定展开" : "收起侧栏"}
          className={cn(
            "flex w-full items-center rounded-md px-2 py-2 transition hover:bg-white/8 hover:text-white",
            isCompact ? "justify-center" : "gap-2",
          )}
        >
          {collapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
          <span className={cn("overflow-hidden whitespace-nowrap transition-opacity duration-150", isCompact && "pointer-events-none w-0 opacity-0")}>
            {collapsed ? "固定展开" : "收起侧栏"}
          </span>
        </button>
        <div className={cn("mt-2 flex items-center gap-2 overflow-hidden whitespace-nowrap transition-opacity duration-150", isCompact && "pointer-events-none h-0 opacity-0")}>
          <Mail className="h-3.5 w-3.5" />
          每日运营工作台
        </div>
      </div>
    </aside>
  );
}

export function AdminMobileNav() {
  const pathname = usePathname();
  return (
    <nav className="fixed inset-x-0 bottom-0 z-40 flex h-16 items-stretch overflow-x-auto border-t border-[#D8E2EE] bg-white/95 shadow-[0_-8px_24px_rgba(16,32,51,0.08)] backdrop-blur md:hidden">
      {adminNavItems.map((item) => {
        const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
        const Icon = item.icon;
        return <Link key={item.href} href={item.href} className={cn("flex min-w-[76px] flex-1 flex-col items-center justify-center gap-1 px-2 text-[11px] font-medium", active ? "text-[#2563EB]" : "text-[#667085]")}><Icon className="h-4 w-4" /><span className="whitespace-nowrap">{item.label}</span></Link>;
      })}
    </nav>
  );
}
