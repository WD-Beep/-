"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2, Mail, RefreshCw } from "lucide-react";

import { AdminShell } from "@/components/layout/admin-shell";
import { ErrorAlert, LoadingState, SuccessAlert } from "@/components/shared/page-states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { fetchSettingsStatus, sendTestEmail, type SettingsStatus } from "@/lib/api";
import { aiModeLabel, collectorModeLabel, translateBackendMessage } from "@/lib/labels";

const SMTP_NOT_CONFIGURED = "邮件服务未配置，请先在环境变量中配置 SMTP。";

function StatusBadge({ configured }: { configured: boolean }) {
  return (
    <Badge variant={configured ? "success" : "warning"}>
      {configured ? "已配置" : "未配置"}
    </Badge>
  );
}

function ConfigCard({
  title,
  description,
  configured,
  message,
  children,
}: {
  title: string;
  description: string;
  configured: boolean;
  message: string;
  children?: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <CardTitle>{title}</CardTitle>
          <StatusBadge configured={configured} />
        </div>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p className={configured ? "text-muted-foreground" : "text-amber-700"}>
          {translateBackendMessage(message)}
        </p>
        {children}
      </CardContent>
    </Card>
  );
}

export function SettingsPanel() {
  const [status, setStatus] = useState<SettingsStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [testEmail, setTestEmail] = useState("");
  const [sending, setSending] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadStatus = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchSettingsStatus();
      setStatus(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载配置状态失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    queueMicrotask(() => {
      void loadStatus();
    });
  }, [loadStatus]);

  async function handleSendTestEmail() {
    setMessage(null);
    setError(null);

    if (!status?.smtp.configured) {
      setError(SMTP_NOT_CONFIGURED);
      return;
    }

    if (!testEmail.trim()) {
      setError("请输入测试邮箱地址");
      return;
    }

    setSending(true);
    try {
      const result = await sendTestEmail(testEmail.trim());
      if (result.success) {
        setMessage(result.message || `测试邮件已发送至 ${result.recipient ?? testEmail}`);
      } else {
        setError(result.message || "测试邮件发送失败");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "测试邮件发送失败");
    } finally {
      setSending(false);
    }
  }

  return (
    <AdminShell title="系统设置" description="查看服务配置与测试邮件">
      <div className="mb-4">
        <Button variant="outline" onClick={loadStatus} disabled={loading}>
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          刷新状态
        </Button>
      </div>

      {message ? <SuccessAlert message={message} className="mb-4" /> : null}
      {error ? <ErrorAlert message={error} className="mb-4" /> : null}

      {loading && !status ? <LoadingState label="加载配置状态..." /> : null}

      {status ? (
        <div className="space-y-6">
          <div className="grid gap-6 lg:grid-cols-2">
            <ConfigCard
              title="SMTP 配置"
              description="邮件发送服务"
              configured={status.smtp.configured}
              message={translateBackendMessage(status.smtp.configured ? status.smtp.message : SMTP_NOT_CONFIGURED)}
            >
              {status.smtp.configured ? (
                <div className="space-y-3">
                  {status.smtp.from_user_mismatch && status.smtp.warning ? (
                    <ErrorAlert message={status.smtp.warning} />
                  ) : null}
                  <div className="grid gap-2 rounded-lg border bg-muted/30 p-4">
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">服务器</span>
                      <span>{status.smtp.host ?? "-"}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">端口</span>
                      <span>{status.smtp.port ?? "-"}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">登录账号</span>
                      <span>{status.smtp.user_address ?? "-"}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">发件地址</span>
                      <span>{status.smtp.from_address ?? "-"}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">TLS</span>
                      <span>{status.smtp.use_tls ? "启用" : "关闭"}</span>
                    </div>
                  </div>
                </div>
              ) : null}
            </ConfigCard>

            <ConfigCard
              title="AI 配置"
              description="红人 AI 分析（OpenAI 优先，失败降级启发式评分）"
              configured={status.ai.configured}
              message={
                status.ai.configured
                  ? "OpenAI API 已配置，采集后将写入 AI 画像；失败时自动降级为本地启发式评分。"
                  : "未配置 OPENAI_API_KEY，采集后使用本地启发式评分（不生成模拟文案）。"
              }
            >
              <div className="grid gap-2 rounded-lg border bg-muted/30 p-4">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">服务商</span>
                  <span>{status.ai.provider === "openai" ? "OpenAI" : aiModeLabel(status.ai.provider)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">运行模式</span>
                  <Badge variant="secondary">{aiModeLabel(status.ai.mode)}</Badge>
                </div>
                {status.ai.configured && status.ai.model ? (
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">模型</span>
                    <span>{status.ai.model}</span>
                  </div>
                ) : null}
              </div>
            </ConfigCard>

            <ConfigCard
              title="Apify 采集"
              description="Instagram / YouTube 优先数据源"
              configured={status.apify.configured}
              message={translateBackendMessage(status.apify.message)}
            >
              <div className="grid gap-2 rounded-lg border bg-muted/30 p-4 text-sm">
                <div className="flex justify-between gap-3">
                  <span className="text-muted-foreground">Instagram</span>
                  <Badge variant="secondary">{status.collection.instagram_data_provider}</Badge>
                </div>
                <div className="flex justify-between gap-3">
                  <span className="text-muted-foreground">YouTube</span>
                  <Badge variant="secondary">{status.collection.youtube_data_provider}</Badge>
                </div>
              </div>
            </ConfigCard>

            <ConfigCard
              title="Instagram 采集"
              description="当前 Instagram 实际数据源"
              configured={status.collection.instagram_collector_configured}
              message={translateBackendMessage(status.collection.instagram_message)}
            />

            <ConfigCard
              title="Facebook 采集"
              description="当前 Facebook 实际数据源"
              configured={status.collection.facebook_collector_configured ?? false}
              message={translateBackendMessage(
                status.collection.facebook_message ??
                  (status.collection.facebook_collector_configured
                    ? "Facebook 采集已就绪"
                    : "Facebook 采集未配置完整"),
              )}
            >
              <div className="grid gap-2 rounded-lg border bg-muted/30 p-4 text-sm">
                <div className="flex justify-between gap-3">
                  <span className="text-muted-foreground">数据源</span>
                  <Badge variant="secondary">{status.collection.facebook_data_provider ?? "apify"}</Badge>
                </div>
              </div>
            </ConfigCard>

            <ConfigCard
              title="采集器模式"
              description="多平台采集总开关"
              configured={status.collection.instagram_collector_configured || status.apify.configured}
              message={translateBackendMessage(status.collector.message)}
            >
              <div className="rounded-lg border bg-muted/30 p-4 text-sm">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">模式</span>
                  <Badge variant="secondary">{collectorModeLabel(status.collector.mode)}</Badge>
                </div>
              </div>
            </ConfigCard>
          </div>

          <Card>
            <CardHeader>
              <CardTitle>测试邮件</CardTitle>
              <CardDescription>输入测试邮箱验证 SMTP 是否可用</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {!status.smtp.configured ? (
                <p className="text-sm text-amber-700">{SMTP_NOT_CONFIGURED}</p>
              ) : null}

              <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
                <div className="flex-1 space-y-2">
                  <Label htmlFor="test_email">测试邮箱</Label>
                  <Input
                    id="test_email"
                    type="email"
                    value={testEmail}
                    onChange={(e) => setTestEmail(e.target.value)}
                    placeholder="you@example.com"
                    disabled={!status.smtp.configured || sending}
                  />
                </div>
                <Button
                  onClick={handleSendTestEmail}
                  disabled={!status.smtp.configured || sending}
                >
                  {sending ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Mail className="h-4 w-4" />
                  )}
                  发送测试邮件
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      ) : null}
    </AdminShell>
  );
}
