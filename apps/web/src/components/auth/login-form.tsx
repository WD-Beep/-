// 文件说明：前端页面组件；当前文件：login form
"use client";

import { useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { AlertCircle, ArrowRight, Eye, EyeOff, Loader2, ShieldCheck } from "lucide-react";

import { LoginPageBackdrop } from "@/components/auth/login-background";
import { LoginBrandPanel } from "@/components/auth/login-brand-panel";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  defaultPathForSession,
  loginWithCredentials,
  setAuthSession,
} from "@/lib/auth";
import { cn } from "@/lib/utils";

const inputClass = cn(
  "h-11 rounded-lg border-[#cfd8c8] bg-[#fbfcf8] px-3.5 text-sm text-slate-900 shadow-inner shadow-slate-900/[0.015]",
  "placeholder:text-slate-400",
  "focus-visible:border-[#245E4F] focus-visible:ring-2 focus-visible:ring-[#245E4F]/14",
);

export function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const redirectTo = searchParams.get("from") || "/";

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [rememberMe, setRememberMe] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

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

    try {
      const session = await loginWithCredentials(trimmedUsername, password);
      setAuthSession(session);
      const target = redirectTo.startsWith("/") && redirectTo !== "/" ? redirectTo : defaultPathForSession(session);
      router.replace(target);
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录成功，但权限信息加载失败，请稍后重试。");
      setSubmitting(false);
      return;
    }
  }

  return (
    <div className="login-shell relative min-h-dvh overflow-x-hidden">
      <LoginPageBackdrop />

      <div className="relative z-10 flex min-h-dvh items-center justify-center px-5 py-8 md:px-8">
        <div
          className={cn(
            "login-card relative grid w-full max-w-[1040px] overflow-hidden rounded-lg",
            "border border-white/72 bg-[#eef4e7]/78 shadow-[0_18px_60px_rgba(61,73,52,0.14)]",
            "md:grid-cols-[0.9fr_1.1fr]",
          )}
        >
          <div className="relative min-h-[360px] border-b border-white/64 bg-[linear-gradient(135deg,rgba(221,236,211,0.92),rgba(248,241,226,0.72))] p-7 md:border-b-0 md:border-r md:p-10">
            <div
              aria-hidden
              className="absolute inset-0 opacity-[0.34]"
              style={{
                backgroundImage: `
                  linear-gradient(to right, rgba(36, 94, 79, 0.12) 1px, transparent 1px),
                  linear-gradient(to bottom, rgba(36, 94, 79, 0.1) 1px, transparent 1px)
                `,
                backgroundSize: "34px 34px",
              }}
            />
            <div className="relative h-full">
              <LoginBrandPanel />
            </div>
          </div>

          <div className="relative flex flex-col justify-center bg-[#fbfcf8]/86 p-7 md:p-10">
            <div className="mb-7 flex items-start justify-between gap-4">
              <div>
                <p className="text-xs font-medium uppercase tracking-[0.16em] text-[#6a7a5e]">OPERATIONS LOGIN</p>
                <h2 className="mt-3 text-[24px] font-semibold tracking-normal text-slate-950">进入电商达人工作台</h2>
                <p className="mt-2 text-sm leading-6 text-slate-600">
                  查看采集任务、邮件回复和达人触达进度。
                </p>
              </div>
              <div className="hidden rounded-lg border border-emerald-900/10 bg-emerald-50/70 p-2.5 text-[#245E4F] sm:block">
                <ShieldCheck className="h-5 w-5" />
              </div>
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
                    placeholder="请输入密码"
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
                      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#245E4F]/15",
                      submitting && "pointer-events-none opacity-50",
                    )}
                    onClick={() => setShowPassword((current) => !current)}
                    aria-label={showPassword ? "隐藏密码" : "显示密码"}
                    tabIndex={-1}
                  >
                    {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
              </div>

              <label className="flex cursor-pointer items-center gap-2 text-sm text-slate-600">
                <input
                  type="checkbox"
                  checked={rememberMe}
                  onChange={(event) => setRememberMe(event.target.checked)}
                  className="h-3.5 w-3.5 rounded border-slate-300 text-[#245E4F] focus:ring-[#245E4F]/20"
                />
                记住我
              </label>

              {error ? (
                <div
                  role="alert"
                  className="flex items-start gap-2 rounded-lg border border-red-200/80 bg-red-50/85 px-3 py-2.5 text-sm text-red-600"
                >
                  <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>{error}</span>
                </div>
              ) : null}

              <button
                type="submit"
                disabled={submitting}
                className={cn(
                  "flex h-11 w-full items-center justify-center gap-2 rounded-lg",
                  "bg-[#245E4F] text-sm font-medium text-white",
                  "shadow-md shadow-emerald-900/18",
                  "hover:bg-[#1d4f42] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#245E4F]/25",
                  "disabled:pointer-events-none disabled:opacity-60",
                )}
              >
                {submitting ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    登录中
                  </>
                ) : (
                  <>
                    进入工作台
                    <ArrowRight className="h-4 w-4" />
                  </>
                )}
              </button>
            </form>

            <p className="mt-6 text-center text-[11px] text-slate-500">
              红人数据工作台 · 内部系统 v0.1.0
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
