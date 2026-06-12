"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertCircle, CheckCircle2, Loader2, ServerCrash } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
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
      detail: `前端正在请求 ${API_URL}，但没有收到有效响应。通常是 FastAPI 未启动，或 Next.js 代理无法连到后端。`,
      action:
        "建议先启动后端：cd apps/api 后运行 uvicorn app.main:app --reload --host 0.0.0.0 --port 8000。" +
        "前端通过 /api-proxy 同源代理访问后端，请确认 apps/web/.env.local 中 INTERNAL_API_URL=http://127.0.0.1:8000 。",
    };
  }

  return {
    title: "接口返回异常",
    detail: message,
    action: "打开后端日志或 /docs 看具体接口错误；如果是 403/401，多半是第三方 API Key 或配额问题。",
  };
}

export function HealthStatus() {
  const [health, setHealth] = useState<HealthState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;

    async function checkHealth() {
      try {
        const data = await fetchHealth();
        if (!cancelled) {
          setHealth({ status: "connected", data });
        }
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

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          后端连接状态
          {health.status === "loading" && <Loader2 className="h-4 w-4 animate-spin" />}
          {health.status === "connected" && (
            <CheckCircle2 className="h-4 w-4 text-emerald-600" />
          )}
          {health.status === "error" && <AlertCircle className="h-4 w-4 text-destructive" />}
        </CardTitle>
        <CardDescription>实时检测 FastAPI 的 /health 接口</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm text-muted-foreground">API 地址</span>
          <code className="rounded bg-muted px-2 py-1 text-xs">{API_URL}</code>
        </div>

        {health.status === "loading" && <Badge variant="secondary">检测中...</Badge>}

        {health.status === "connected" && (
          <div className="space-y-2">
            <Badge variant="success">连接正常</Badge>
            <dl className="grid gap-2 text-sm">
              <div className="flex justify-between gap-4">
                <dt className="text-muted-foreground">服务</dt>
                <dd>{health.data.service}</dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-muted-foreground">状态</dt>
                <dd>{healthStatusLabel(health.data.status)}</dd>
              </div>
              <div className="flex justify-between gap-4">
                <dt className="text-muted-foreground">检测时间</dt>
                <dd className="font-mono text-xs">{health.data.timestamp}</dd>
              </div>
            </dl>
          </div>
        )}

        {errorInfo ? (
          <div className="space-y-2 rounded-md border border-destructive/20 bg-destructive/5 p-3">
            <div className="flex items-center gap-2 text-sm font-medium text-destructive">
              <ServerCrash className="h-4 w-4" />
              {errorInfo.title}
            </div>
            <p className="text-sm text-muted-foreground">{errorInfo.detail}</p>
            <p className="text-xs leading-5 text-muted-foreground">{errorInfo.action}</p>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
