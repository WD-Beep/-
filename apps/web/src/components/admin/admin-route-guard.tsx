"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { clearAuthSession, getStoredAuthSession } from "@/lib/auth";

type AdminRouteGuardProps = {
  children: React.ReactNode;
};

export function AdminRouteGuard({ children }: AdminRouteGuardProps) {
  const router = useRouter();
  const [allowed] = useState(() => Boolean(getStoredAuthSession()?.isAdmin));

  useEffect(() => {
    if (!allowed) {
      clearAuthSession();
      router.replace("/admin/login?error=admin_required");
    }
  }, [allowed, router]);

  if (!allowed) {
    return (
      <div className="flex h-dvh items-center justify-center bg-[#F4F7FB]">
        <p className="text-sm text-[#667085]">Checking administrator access...</p>
      </div>
    );
  }

  return <>{children}</>;
}
