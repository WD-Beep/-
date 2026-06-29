"use client";

import { useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { AlertCircle, ArrowRight, Eye, EyeOff, Loader2 } from "lucide-react";

import { LoginPageBackdrop } from "@/components/auth/login-background";
import { LoginBrandPanel } from "@/components/auth/login-brand-panel";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  AUTH_PASSWORD,
  AUTH_USERNAME,
  setAuthSession,
  validateCredentials,
} from "@/lib/auth";
import { cn } from "@/lib/utils";

const inputClass = cn(
  "h-11 rounded-xl border-slate-200/90 bg-white px-3.5 text-sm shadow-sm shadow-slate-900/[0.02]",
  "placeholder:text-slate-400",
  "focus-visible:border-[#2563EB] focus-visible:ring-2 focus-visible:ring-[#2563EB]/12",
);

export function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const redirectTo = searchParams.get("from") || "/";

  const [username, setUsername] = useState(AUTH_USERNAME);
  const [password, setPassword] = useState(AUTH_PASSWORD);
  const [showPassword, setShowPassword] = useState(false);
  const [rememberMe, setRememberMe] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function fillDemoCredentials() {
    setUsername(AUTH_USERNAME);
    setPassword(AUTH_PASSWORD);
    setError(null);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;

    setError(null);

    const trimmedUsername = username.trim();
    if (!trimmedUsername) {
      setError("请输入用户名");
      return;
    }
    if (!password) {
      setError("请输入密码");
      return;
    }

    setSubmitting(true);
    await new Promise((resolve) => setTimeout(resolve, 280));

    if (!validateCredentials(trimmedUsername, password)) {
      setError("用户名或密码不正确，请检查后重试");
      setSubmitting(false);
      return;
    }

    setAuthSession();
    router.replace(redirectTo.startsWith("/") ? redirectTo : "/");
    router.refresh();
  }

  return (
    <div className="login-shell relative min-h-dvh">
      <LoginPageBackdrop />

      <div className="relative z-10 flex min-h-dvh items-center justify-center px-6 py-10">
        <div
          className={cn(
            "login-card relative flex w-full max-w-[920px] flex-col overflow-hidden rounded-3xl",
            "border border-white/80 bg-white/90 backdrop-blur-sm",
            "shadow-[0_12px_40px_rgba(15,23,42,0.08),0_2px_8px_rgba(15,23,42,0.04)]",
            "md:flex-row md:items-stretch",
          )}
        >
          {/* 左侧 — 轻量品牌引导区 */}
          <div className="relative flex items-center md:w-[42%]">
            <div
              aria-hidden
              className="pointer-events-none absolute inset-0 bg-gradient-to-br from-slate-50/60 to-transparent"
            />
            <div className="relative flex flex-1 flex-col justify-center p-8 md:p-10 md:pr-6">
              <LoginBrandPanel />
            </div>
            <div
              aria-hidden
              className="pointer-events-none absolute inset-y-10 right-0 hidden w-px bg-gradient-to-b from-transparent via-slate-200/40 to-transparent md:block"
            />
          </div>

          {/* 右侧 — 登录主视觉 */}
          <div className="relative flex flex-col justify-center p-8 md:w-[58%] md:p-10 md:pl-8">
            <div className="mb-7">
              <h2 className="text-[22px] font-semibold tracking-tight text-slate-900">
                登录管理后台
              </h2>
              <p className="mt-1.5 text-sm text-slate-500">使用管理员凭据进入工作台</p>
            </div>

            <form className="space-y-4" onSubmit={handleSubmit} noValidate>
              <div className="space-y-1.5">
                <Label htmlFor="username" className="text-sm font-medium text-slate-700">
                  用户名
                </Label>
                <Input
                  id="username"
                  name="username"
                  autoComplete="username"
                  value={username}
                  onChange={(event) => {
                    setUsername(event.target.value);
                    if (error) setError(null);
                  }}
                  disabled={submitting}
                  aria-invalid={Boolean(error)}
                  className={cn(inputClass, error && "border-destructive/50")}
                />
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="password" className="text-sm font-medium text-slate-700">
                  密码
                </Label>
                <div className="relative">
                  <Input
                    id="password"
                    name="password"
                    type={showPassword ? "text" : "password"}
                    autoComplete="current-password"
                    placeholder="••••••"
                    value={password}
                    onChange={(event) => {
                      setPassword(event.target.value);
                      if (error) setError(null);
                    }}
                    disabled={submitting}
                    className={cn(inputClass, "pr-10", error && "border-destructive/50")}
                    aria-invalid={Boolean(error)}
                  />
                  <button
                    type="button"
                    className={cn(
                      "absolute inset-y-0 right-0 flex w-10 items-center justify-center text-slate-400 hover:text-slate-600",
                      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#2563EB]/15",
                      submitting && "pointer-events-none opacity-50",
                    )}
                    onClick={() => setShowPassword((current) => !current)}
                    aria-label={showPassword ? "隐藏密码" : "显示密码"}
                    tabIndex={-1}
                  >
                    {showPassword ? (
                      <EyeOff className="h-4 w-4" />
                    ) : (
                      <Eye className="h-4 w-4" />
                    )}
                  </button>
                </div>
              </div>

              <label className="flex cursor-pointer items-center gap-2 text-sm text-slate-500">
                <input
                  type="checkbox"
                  checked={rememberMe}
                  onChange={(event) => setRememberMe(event.target.checked)}
                  className="h-3.5 w-3.5 rounded border-slate-300 text-[#2563EB] focus:ring-[#2563EB]/20"
                />
                记住我
              </label>

              {error ? (
                <div
                  role="alert"
                  className="flex items-start gap-2 rounded-xl border border-red-200/80 bg-red-50/80 px-3 py-2.5 text-sm text-red-600"
                >
                  <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>{error}</span>
                </div>
              ) : null}

              <button
                type="submit"
                disabled={submitting}
                className={cn(
                  "flex h-11 w-full items-center justify-center gap-2 rounded-[40px]",
                  "bg-[#2563EB] text-sm font-medium text-white",
                  "shadow-md shadow-blue-600/25",
                  "hover:bg-[#1d4ed8] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#2563EB]/25",
                  "disabled:pointer-events-none disabled:opacity-60",
                )}
              >
                {submitting ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    登录中…
                  </>
                ) : (
                  <>
                    进入工作台
                    <ArrowRight className="h-4 w-4" />
                  </>
                )}
              </button>
            </form>

            <div className="mt-5 flex items-center justify-between gap-3 rounded-2xl border border-slate-100 bg-slate-50/60 px-4 py-3">
              <div>
                <p className="text-sm font-medium text-slate-700">演示访问凭证</p>
                <p className="mt-0.5 text-sm text-slate-500">
                  {AUTH_USERNAME} / {AUTH_PASSWORD}
                </p>
              </div>
              <button
                type="button"
                onClick={fillDemoCredentials}
                disabled={submitting}
                className="shrink-0 rounded-[20px] border border-slate-200 bg-white px-3.5 py-1.5 text-xs font-medium text-slate-700 hover:border-slate-300 hover:bg-slate-50 disabled:opacity-50"
              >
                一键填入
              </button>
            </div>

            <p className="mt-6 text-center text-[11px] text-slate-400">
              红人数据工作台 · 内部系统 v0.1.0
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
