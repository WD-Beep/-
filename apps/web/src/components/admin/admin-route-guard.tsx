// 文件说明：前端管理员后台组件；当前文件：admin route guard
"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { clearAuthSession, getStoredAuthSession } from "@/lib/auth";

type AdminRouteGuardProps = {
  children: React.ReactNode;
};

type GuardState = "checking" | "allowed" | "blocked";

export function AdminRouteGuard({ children }: AdminRouteGuardProps) {
  const router = useRouter();
  const [state, setState] = useState<GuardState>(() =>
    getStoredAuthSession()?.isAdmin ? "allowed" : "checking",
  );

  useEffect(() => {
    let cancelled = false;
    queueMicrotask(() => {
      if (cancelled) return;
      const allowed = Boolean(getStoredAuthSession()?.isAdmin);
      if (allowed) {
        setState("allowed");
      } else {
        clearAuthSession();
        setState("blocked");
        router.replace("/admin/login?error=admin_required");
      }
    });
    return () => {
      cancelled = true;
    };
  }, [router]);

  if (state !== "allowed") {
    return (
      <div className="flex h-dvh items-center justify-center bg-[#F4F7FB]">
        <p className="text-sm text-[#667085]">正在校验管理员权限...</p>
      </div>
    );
  }

  return <>{children}</>;
}
