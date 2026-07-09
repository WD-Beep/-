import { Suspense } from "react";
import type { Metadata } from "next";

import { AdminLoginForm } from "@/components/auth/admin-login-form";

export const metadata: Metadata = {
  title: "管理员登录 · 红人智采",
  description: "红人智采管理员安全登录。",
};

function AdminLoginFallback() {
  return (
    <div className="flex h-dvh min-w-[1280px] items-center justify-center bg-[#F5F8FC]">
      <p className="text-sm text-[#6B7280]">正在加载管理员登录...</p>
    </div>
  );
}

export default function AdminLoginPage() {
  return (
    <Suspense fallback={<AdminLoginFallback />}>
      <AdminLoginForm />
    </Suspense>
  );
}
