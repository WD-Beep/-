"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { CheckCircle2, Loader2, Mail, RefreshCw, Server, Settings2, ShieldCheck } from "lucide-react";

import { AdminShell } from "@/components/layout/admin-shell";
import { ErrorAlert, LoadingState, SuccessAlert } from "@/components/shared/page-states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { fetchSettingsStatus, pollImapInbox, sendTestEmail, type SettingsStatus } from "@/lib/api";
import { aiModeLabel, collectorModeLabel, translateBackendMessage } from "@/lib/labels";

const SMTP_NOT_CONFIGURED = "邮件服务未配置，请先在环境变量中配置 SMTP。";

function StatusBadge({ configured }: { configured: boolean }) {
  return (
    <Badge variant={configured ? "success" : "warning"}>
      {configured ? "已配置" : "未配置"}
    </Badge>
  );
}

function ConfigRow({
  label,
  value,
  badge,
}: {
  label: string;
  value?: React.ReactNode;
  badge?: React.ReactNode;
}) {
  return (
    <div className="grid grid-cols-[120px_minmax(0,1fr)] items-center gap-3 border-b py-2 text-sm last:border-0">
      <span className="text-muted-foreground">{label}</span>
      <div className="min-w-0 text-right font-medium">{badge ?? value ?? "-"}</div>
    </div>
  );
}

function ServiceTile({
  title,
  description,
  configured,
  message,
}: {
  title: string;
  description: string;
  configured: boolean;
  message: string;
}) {
  return (
    <div className="rounded-lg border bg-background p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-semibold">{title}</p>
          <p className="mt-1 truncate text-xs text-muted-foreground">{description}</p>
        </div>
        <StatusBadge configured={configured} />
      </div>
      <p className={configured ? "mt-3 line-clamp-2 text-xs leading-5 text-muted-foreground" : "mt-3 line-clamp-2 text-xs leading-5 text-amber-700"}>
        {translateBackendMessage(message)}
      </p>
    </div>
  );
}

function SectionHeader({
  icon: Icon,
  title,
  description,
}: {
  icon: typeof Settings2;
  title: string;
  description: string;
}) {
  return (
    <div className="flex items-start gap-3 border-b px-4 py-3">
      <div className="mt-0.5 flex h-8 w-8 items-center justify-center rounded-md border bg-muted/30">
        <Icon className="h-4 w-4 text-primary" />
      </div>
      <div>
        <h2 className="text-base font-semibold">{title}</h2>
        <p className="mt-1 text-sm text-muted-foreground">{description}</p>
      </div>
    </div>
  );
}

export function SettingsPanel() {
  const [status, setStatus] = useState<SettingsStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [testEmail, setTestEmail] = useState("");
  const [sending, setSending] = useState(false);
  const [polling, setPolling] = useState(false);
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

  async function handlePollImap() {
    setMessage(null);
    setError(null);
    setPolling(true);
    try {
      const result = await pollImapInbox(false);
      setMessage(
        `IMAP 轮询完成：处理 ${result.processed} 封，入库 ${result.ingested} 封，跳过 ${result.skipped} 封，失败 ${result.failed} 封。`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "IMAP 轮询失败");
    } finally {
      setPolling(false);
    }
  }

  const configuredCount = useMemo(() => {
    if (!status) return 0;
    return [
      status.smtp.configured,
      status.inbound_email.configured,
      status.ai.configured,
      status.apify.configured,
      status.collection.instagram_collector_configured,
      status.collection.facebook_collector_configured ?? false,
    ].filter(Boolean).length;
  }, [status]);

  return (
    <AdminShell title="系统设置" description="查看服务配置与测试邮件">
      <div className="flex h-full min-h-0 flex-col">
        <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b px-4 py-3 lg:px-5">
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" onClick={loadStatus} disabled={loading}>
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              刷新状态
            </Button>
            {status ? (
              <div className="inline-flex h-9 items-center gap-2 rounded-md border bg-muted/30 px-3 text-sm">
                <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                <span className="text-muted-foreground">已配置</span>
                <span className="font-semibold">{configuredCount}/6</span>
              </div>
            ) : null}
          </div>
          <p className="text-xs text-muted-foreground">只展示配置状态，不显示密钥明文。</p>
        </div>

        <div className="min-h-0 flex-1 overflow-auto p-4 lg:p-5">
          {message ? <SuccessAlert message={message} className="mb-3" /> : null}
          {error ? <ErrorAlert message={error} className="mb-3" /> : null}
          {loading && !status ? <LoadingState label="加载配置状态..." /> : null}

          {status ? (
            <div className="grid gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(340px,1fr)]">
              <div className="space-y-4">
                <section className="overflow-hidden rounded-xl border bg-background shadow-sm">
                  <SectionHeader
                    icon={Mail}
                    title="邮件服务"
                    description="SMTP 负责发送，IMAP 或 inbound webhook 负责识别红人回复。"
                  />
                  <div className="grid gap-3 p-3 lg:grid-cols-2">
                    <ServiceTile
                      title="SMTP 配置"
                      description="邮件发送服务"
                      configured={status.smtp.configured}
                      message={status.smtp.configured ? status.smtp.message : SMTP_NOT_CONFIGURED}
                    />
                    <ServiceTile
                      title="收信配置"
                      description="IMAP 轮询或 inbound webhook"
                      configured={status.inbound_email.configured}
                      message={status.inbound_email.message}
                    />
                  </div>
                  <div className="grid gap-4 border-t p-4 lg:grid-cols-2">
                    <div>
                      <h3 className="mb-2 text-sm font-semibold">SMTP 详情</h3>
                      {status.smtp.from_user_mismatch && status.smtp.warning ? (
                        <ErrorAlert message={status.smtp.warning} className="mb-2" />
                      ) : null}
                      <div className="rounded-lg border bg-muted/20 px-3">
                        <ConfigRow label="服务器" value={status.smtp.host} />
                        <ConfigRow label="端口" value={status.smtp.port} />
                        <ConfigRow label="登录账号" value={status.smtp.user_address} />
                        <ConfigRow label="发件地址" value={status.smtp.from_address} />
                        <ConfigRow label="TLS" value={status.smtp.use_tls ? "启用" : "关闭"} />
                        <ConfigRow label="测试收件" value={status.smtp.test_recipient ?? "-"} />
                        <ConfigRow
                          label="定时测试"
                          value={
                            status.smtp.test_schedule_enabled
                              ? `已启用，${status.smtp.test_interval_minutes ?? 1440} 分钟/封`
                              : "未启用"
                          }
                        />
                      </div>
                    </div>
                    <div>
                      <h3 className="mb-2 text-sm font-semibold">收信详情</h3>
                      <div className="rounded-lg border bg-muted/20 px-3">
                        <ConfigRow label="收信地址" value={status.inbound_email.inbound_address} />
                        <ConfigRow label="IMAP" value={status.inbound_email.imap_configured ? "已配置" : "未配置"} />
                        <ConfigRow label="Webhook" value={status.inbound_email.webhook_configured ? "已配置" : "未配置"} />
                        {status.inbound_email.imap_configured ? (
                          <>
                            <ConfigRow
                              label="IMAP 服务"
                              value={`${status.inbound_email.imap_host}:${status.inbound_email.imap_port}`}
                            />
                            <ConfigRow label="文件夹" value={status.inbound_email.imap_folder ?? "INBOX"} />
                          </>
                        ) : null}
                      </div>
                      <div className="mt-3 flex flex-wrap gap-2">
                        <Button
                          size="sm"
                          variant="secondary"
                          disabled={!status.inbound_email.imap_configured || polling}
                          onClick={() => void handlePollImap()}
                        >
                          {polling ? <Loader2 className="h-4 w-4 animate-spin" /> : <Mail className="h-4 w-4" />}
                          立即轮询 IMAP
                        </Button>
                        {status.inbound_email.webhook_configured ? (
                          <span className="text-xs leading-8 text-muted-foreground">
                            Webhook：POST /api/email-inbound/webhook
                          </span>
                        ) : null}
                      </div>
                    </div>
                  </div>
                </section>

                <section className="overflow-hidden rounded-xl border bg-background shadow-sm">
                  <SectionHeader
                    icon={Server}
                    title="采集与 AI 服务"
                    description="红人画像、平台采集源和多平台采集总开关集中在这里。"
                  />
                  <div className="grid gap-3 p-3 md:grid-cols-2 xl:grid-cols-3">
                    <ServiceTile
                      title="AI 配置"
                      description="OpenAI 优先，失败降级启发式评分"
                      configured={status.ai.configured}
                      message={
                        status.ai.configured
                          ? "OpenAI API 已配置，采集后将写入 AI 画像；失败时自动降级为本地启发式评分。"
                          : "未配置 OPENAI_API_KEY，采集后使用本地启发式评分。"
                      }
                    />
                    <ServiceTile
                      title="Apify 采集"
                      description="Instagram / YouTube / TikTok / Facebook 数据源"
                      configured={status.apify.configured}
                      message={status.apify.message}
                    />
                    <ServiceTile
                      title="Instagram 采集"
                      description="当前 Instagram 实际数据源"
                      configured={status.collection.instagram_collector_configured}
                      message={status.collection.instagram_message}
                    />
                    <ServiceTile
                      title="Facebook 采集"
                      description="当前 Facebook 实际数据源"
                      configured={status.collection.facebook_collector_configured ?? false}
                      message={
                        status.collection.facebook_message ??
                        (status.collection.facebook_collector_configured ? "Facebook 采集已就绪" : "Facebook 采集未配置完整")
                      }
                    />
                    <ServiceTile
                      title="采集器模式"
                      description="多平台采集总开关"
                      configured={status.collection.instagram_collector_configured || status.apify.configured}
                      message={status.collector.message}
                    />
                  </div>
                  <div className="grid gap-4 border-t p-4 lg:grid-cols-2">
                    <div>
                      <h3 className="mb-2 text-sm font-semibold">AI 运行状态</h3>
                      <div className="rounded-lg border bg-muted/20 px-3">
                        <ConfigRow label="服务商" value={status.ai.provider === "openai" ? "OpenAI" : aiModeLabel(status.ai.provider)} />
                        <ConfigRow label="运行模式" badge={<Badge variant="secondary">{aiModeLabel(status.ai.mode)}</Badge>} />
                        {status.ai.configured && status.ai.model ? <ConfigRow label="模型" value={status.ai.model} /> : null}
                      </div>
                    </div>
                    <div>
                      <h3 className="mb-2 text-sm font-semibold">平台数据源</h3>
                      <div className="rounded-lg border bg-muted/20 px-3">
                        <ConfigRow label="Instagram" badge={<Badge variant="secondary">{status.collection.instagram_data_provider}</Badge>} />
                        <ConfigRow label="YouTube" badge={<Badge variant="secondary">{status.collection.youtube_data_provider}</Badge>} />
                        <ConfigRow label="Facebook" badge={<Badge variant="secondary">{status.collection.facebook_data_provider ?? "apify"}</Badge>} />
                        <ConfigRow label="采集模式" badge={<Badge variant="secondary">{collectorModeLabel(status.collector.mode)}</Badge>} />
                      </div>
                    </div>
                  </div>
                </section>
              </div>

              <div className="space-y-4">
                <Card>
                  <CardHeader className="py-3">
                    <CardTitle className="text-base">测试邮件</CardTitle>
                    <CardDescription>用于验证 SMTP，不会作为红人外联邮件发送。</CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-4">
                    {!status.smtp.configured ? (
                      <p className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-700">
                        {SMTP_NOT_CONFIGURED}
                      </p>
                    ) : null}
                    <div className="space-y-2">
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
                      className="w-full"
                      onClick={handleSendTestEmail}
                      disabled={!status.smtp.configured || sending || !testEmail.trim()}
                    >
                      {sending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Mail className="h-4 w-4" />}
                      发送测试邮件
                    </Button>
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader className="py-3">
                    <CardTitle className="flex items-center gap-2 text-base">
                      <ShieldCheck className="h-4 w-4 text-primary" />
                      配置检查
                    </CardTitle>
                    <CardDescription>上线前优先确认邮件发送、回复识别、采集和 AI。</CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-2 text-sm">
                    {[
                      ["SMTP 发信", status.smtp.configured],
                      ["回复识别", status.inbound_email.configured],
                      ["AI 画像", status.ai.configured],
                      ["Apify 采集", status.apify.configured],
                      ["Instagram 采集", status.collection.instagram_collector_configured],
                    ].map(([label, ok]) => (
                      <div key={String(label)} className="flex items-center justify-between rounded-md border bg-muted/20 px-3 py-2">
                        <span>{label}</span>
                        <StatusBadge configured={Boolean(ok)} />
                      </div>
                    ))}
                  </CardContent>
                </Card>
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </AdminShell>
  );
}
