// 文件说明：前端页面路由入口；当前文件：page
import { Suspense } from "react";
import type { Metadata } from "next";

import { LoginForm } from "@/components/auth/login-form";

export const metadata: Metadata = {
  title: "登录 · 红人智采",
  description: "登录红人智采管理后台",
};

function LoginFallback() {
  return (
    <div className="flex h-dvh items-center justify-center bg-gradient-to-br from-[#eef2f8] to-[#e9eef6]">
      <p className="text-sm text-slate-500">加载中…</p>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<LoginFallback />}>
      <LoginForm />
    </Suspense>
  );
}
