"use client";

import { useEffect, useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { AlertCircle, CheckCircle2, Eye, EyeOff, Loader2, LockKeyhole } from "lucide-react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  ADMIN_AUTH_PASSWORD,
  getStoredAuthSession,
  loadBackendAuthSession,
  resolveAdminAuthAccount,
  setAuthSession,
} from "@/lib/auth";
import { cn } from "@/lib/utils";

const inputClass = cn(
  "h-11 rounded-md border-[#D7E0EA] bg-[#FBFCFE] px-3.5 text-[14px] text-[#1F2937] shadow-none",
  "placeholder:text-[#9AA5B1]",
  "focus-visible:border-[#4A90D9] focus-visible:ring-2 focus-visible:ring-[#4A90D9]/15",
);

const adminRequiredMessage = "当前账号没有管理员权限，请联系超级管理员授权。";

export function AdminLoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState(ADMIN_AUTH_PASSWORD);
  const [showPassword, setShowPassword] = useState(false);
  const [rememberMe, setRememberMe] = useState(true);
  const [error, setError] = useState<string | null>(
    searchParams.get("error") === "admin_required" ? adminRequiredMessage : null,
  );
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const session = getStoredAuthSession();
    if (session?.isAdmin) {
      router.replace("/admin/dashboard");
    }
  }, [router]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;

    setError(null);
    const account = resolveAdminAuthAccount(username, password);
    if (!account) {
      setError(
        username.trim().toLowerCase().startsWith("sales")
          ? adminRequiredMessage
          : "管理员账号或密码不正确，请检查后重试。",
      );
      return;
    }

    setSubmitting(true);
    try {
      const session = await loadBackendAuthSession(account);
      if (!session.isAdmin) {
        setError(adminRequiredMessage);
        setSubmitting(false);
        return;
      }
      setAuthSession(session);
      router.replace("/admin/dashboard");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败，请稍后重试。");
      setSubmitting(false);
    }
  }

  return (
    <div className="flex h-dvh min-w-[1180px] items-center justify-center overflow-hidden bg-[#EEF3F8] px-8 text-[#1F2937]">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{
          background: "linear-gradient(135deg, #F8FAFD 0%, #EDF3F9 46%, #E7EEF7 100%)",
        }}
      />
      <main className="relative grid w-full max-w-[980px] grid-cols-[1fr_420px] overflow-hidden rounded-lg border border-[#DCE4EE] bg-[#FBFCFE] shadow-[0_24px_80px_rgba(26,42,58,0.12)]">
        <section className="flex flex-col justify-between bg-[#102033] p-10 text-[#E6EDF5]">
          <div>
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-md bg-[#2563EB]">
                <LockKeyhole className="h-5 w-5" />
              </div>
              <div>
                <p className="text-base font-semibold">红人智采</p>
                <p className="text-sm text-[#9FB1C5]">管理员后台</p>
              </div>
            </div>
            <div className="mt-16 max-w-[420px]">
              <p className="text-sm font-semibold tracking-[0.14em] text-[#9FB1C5]">内部运营工作台</p>
              <h1 className="mt-4 text-3xl font-semibold leading-tight text-white">登录管理员后台</h1>
              <p className="mt-4 text-sm leading-6 text-[#B8C6D6]">
                管理所有业务员、品牌、红人采集、AI 外联邮件和回复跟进数据。
              </p>
            </div>
          </div>
          <div className="inline-flex w-fit items-center gap-2 rounded-md border border-white/10 bg-white/8 px-3 py-2 text-xs text-[#C7D3E0]">
            <CheckCircle2 className="h-4 w-4 text-[#86EFAC]" />
            仅管理员账号可访问
          </div>
        </section>

        <section className="p-8">
          <div className="mb-7">
            <p className="text-xs font-semibold tracking-[0.14em] text-[#4F6B8A]">ADMIN</p>
            <h2 className="mt-2 text-2xl font-semibold text-[#102033]">账号登录</h2>
            <p className="mt-2 text-sm text-[#667085]">业务员账号会被拦截，无法进入后台。</p>
          </div>

          <form className="space-y-4" onSubmit={handleSubmit} noValidate>
            <div className="space-y-2">
              <Label htmlFor="admin-username" className="text-[13px] font-semibold text-[#374151]">
                账号
              </Label>
              <Input
                id="admin-username"
                value={username}
                onChange={(event) => {
                  setUsername(event.target.value);
                  if (error) setError(null);
                }}
                className={cn(
                  inputClass,
                  error && "border-[#E54C4C] bg-[#FFFCFC] focus-visible:border-[#E54C4C] focus-visible:ring-[#E54C4C]/12",
                )}
                autoComplete="username"
                disabled={submitting}
                aria-invalid={Boolean(error)}
                aria-describedby={error ? "admin-login-error" : undefined}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="admin-password" className="text-[13px] font-semibold text-[#374151]">
                密码
              </Label>
              <div className="relative">
                <Input
                  id="admin-password"
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(event) => {
                    setPassword(event.target.value);
                    if (error) setError(null);
                  }}
                  className={cn(inputClass, "pr-11")}
                  autoComplete="current-password"
                  disabled={submitting}
                />
                <button
                  type="button"
                  className="absolute inset-y-0 right-0 flex w-11 items-center justify-center rounded-r-lg text-[#7B8794] transition hover:text-[#102A43] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#2F80ED]/15"
                  onClick={() => setShowPassword((value) => !value)}
                  aria-label={showPassword ? "隐藏密码" : "显示密码"}
                  disabled={submitting}
                >
                  {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            </div>

            {error ? (
              <p
                id="admin-login-error"
                role="alert"
                className="flex items-center gap-1.5 rounded-md bg-[#FEF3F2] px-3 py-2 text-xs font-medium leading-5 text-[#B42318]"
              >
                <AlertCircle className="h-3.5 w-3.5" />
                {error}
              </p>
            ) : null}

            <div className="flex items-center justify-between pt-1 text-[13px]">
              <label className="inline-flex cursor-pointer items-center gap-2 text-[#5F6B7A]">
                <input
                  type="checkbox"
                  checked={rememberMe}
                  onChange={(event) => setRememberMe(event.target.checked)}
                  className="h-3.5 w-3.5 rounded border-[#CCD6E2] text-[#4A90D9] focus:ring-[#4A90D9]/20"
                />
                记住登录状态
              </label>
              <button type="button" className="text-[13px] font-medium text-[#6B7280] transition hover:text-[#2563EB]">
                忘记密码？
              </button>
            </div>

            <button
              type="submit"
              disabled={submitting}
              className="flex h-11 w-full items-center justify-center gap-2 rounded-md bg-[#1A2A3A] text-[14px] font-semibold text-white shadow-[0_10px_20px_rgba(26,42,58,0.16)] transition hover:bg-[#24384C] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#1A2A3A]/20 disabled:pointer-events-none disabled:opacity-55"
            >
              {submitting ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  正在登录
                </>
              ) : (
                "登录"
              )}
            </button>
          </form>

          <p className="mt-7 border-t border-[#E5EAF2] pt-4 text-xs text-[#8A94A3]">
            已启用角色权限保护，sales 账号不能访问后台页面。
          </p>
        </section>
      </main>
    </div>
  );
}
