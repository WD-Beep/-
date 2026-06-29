"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertCircle, CheckCircle2, Loader2, ServerCrash } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { API_URL, fetchHealth, type HealthResponse } from "@/lib/api";
import { healthStatusLabel } from "@/lib/labels";

type HealthState =
  | { status: "loading" }
  | { status: "connected"; data: HealthResponse }
  | { status: "error"; message: string };

function getFriendlyError(message: string) {
  if (message.includes("Failed to fetch")) {
    return {
      title: "后端没有连上",
      detail: `前端正在请求 ${API_URL}，但没有收到有效响应。通常是 FastAPI 未启动，或 Next.js 代理没有连到后端。`,
      action:
        "建议先启动后端：cd apps/api 后运行 uvicorn app.main:app --reload --host 0.0.0.0 --port 8000。",
    };
  }

  return {
    title: "接口返回异常",
    detail: message,
    action: "打开后端日志或 /docs 查看具体接口错误；如果是 403/401，多半是 API Key 或权限问题。",
  };
}

export function HealthStatus() {
  const [health, setHealth] = useState<HealthState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;

    async function checkHealth() {
      try {
        const data = await fetchHealth();
        if (!cancelled) setHealth({ status: "connected", data });
      } catch (error) {
        if (!cancelled) {
          setHealth({
            status: "error",
            message: error instanceof Error ? error.message : "Unknown error",
          });
        }
      }
    }

    checkHealth();
    const interval = setInterval(checkHealth, 30000);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  const errorInfo = useMemo(
    () => (health.status === "error" ? getFriendlyError(health.message) : null),
    [health],
  );

  if (health.status === "loading") {
    return (
      <div className="flex h-full min-h-[150px] flex-col justify-between rounded-lg border bg-muted/20 p-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-sm font-semibold">后端连接</p>
            <p className="mt-1 text-xs text-muted-foreground">实时检测 FastAPI /health</p>
          </div>
          <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
        </div>
        <Badge variant="secondary" className="w-fit">检测中...</Badge>
      </div>
    );
  }

  if (health.status === "connected") {
    return (
      <div className="flex h-full min-h-[150px] flex-col justify-between rounded-lg border bg-emerald-50/40 p-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-sm font-semibold">后端连接</p>
            <p className="mt-1 text-xs text-muted-foreground">API 地址：{API_URL}</p>
          </div>
          <CheckCircle2 className="h-4 w-4 text-emerald-600" />
        </div>
        <div className="space-y-2">
          <Badge variant="success">连接正常</Badge>
          <dl className="grid gap-1 text-xs">
            <div className="flex justify-between gap-4">
              <dt className="text-muted-foreground">服务</dt>
              <dd className="truncate">{health.data.service}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-muted-foreground">状态</dt>
              <dd>{healthStatusLabel(health.data.status)}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-muted-foreground">检测时间</dt>
              <dd className="font-mono">{health.data.timestamp}</dd>
            </div>
          </dl>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-[150px] flex-col justify-between rounded-lg border border-destructive/20 bg-destructive/5 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-destructive">{errorInfo?.title}</p>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">{errorInfo?.detail}</p>
        </div>
        <AlertCircle className="h-4 w-4 text-destructive" />
      </div>
      <div className="mt-3 flex gap-2 rounded-md bg-background/70 p-2 text-xs leading-5 text-muted-foreground">
        <ServerCrash className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span>{errorInfo?.action}</span>
      </div>
    </div>
  );
}
