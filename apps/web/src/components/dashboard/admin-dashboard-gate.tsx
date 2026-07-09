"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { OperationsHomePanel } from "@/components/dashboard/operations-home-panel";
import { clearAuthSession, getStoredAuthSession } from "@/lib/auth";

export function AdminDashboardGate() {
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
      <div className="flex h-dvh items-center justify-center bg-[#F5F8FC]">
        <p className="text-sm text-[#6B7280]">Checking administrator access...</p>
      </div>
    );
  }

  return <OperationsHomePanel />;
}
