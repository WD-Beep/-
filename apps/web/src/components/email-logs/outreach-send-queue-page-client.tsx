// 文件说明：前端邮件记录和发送队列组件；当前文件：outreach send queue page client
"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  CalendarClock,
  Eye,
  Loader2,
  Pause,
  Play,
  RefreshCw,
  RotateCw,
  Send,
  Trash2,
  X,
} from "lucide-react";

import { AdminShell } from "@/components/layout/admin-shell";
import { ErrorAlert, SuccessAlert } from "@/components/shared/page-states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  cancelScheduledOutreachQueueItem,
  fetchOutreachSendQueue,
  pauseOutreachQueueItem,
  rescheduleOutreachQueueItem,
  resumeOutreachQueueItem,
  sendOutreachQueueItemNow,
  type OutreachSendQueueItem,
} from "@/lib/api";
import { translateEmailFailureReason } from "@/lib/email-log-helpers";
import { translateErrorMessage } from "@/lib/labels";

const STATUS_LABELS: Record<string, string> = {
  draft: "草稿",
  queued: "待发送",
  scheduled: "待发送",
  sending: "发送中",
  sent: "已发送",
  failed: "失败",
  paused: "已暂停",
  cancelled: "已取消",
  skipped: "已跳过",
};

const STATUS_OPTIONS = [
  { value: "", label: "全部状态" },
  { value: "scheduled", label: "待发送" },
  { value: "sending", label: "发送中" },
  { value: "sent", label: "已发送" },
  { value: "failed", label: "失败" },
  { value: "paused", label: "已暂停" },
  { value: "cancelled", label: "已取消" },
  { value: "skipped", label: "已跳过" },
];

function formatDate(value: string | null): string {
  if (!value) return "-";
  return new Date(value).toLocaleString("zh-CN");
}

function localDateTimeToIso(value: string): string {
  return new Date(value).toISOString();
}

function StatusBadge({ status }: { status: string }) {
  const variant = status === "failed" ? "destructive" : status === "sent" ? "success" : "secondary";
  return <Badge variant={variant}>{STATUS_LABELS[status] ?? status}</Badge>;
}

function getQueueTypeLabel(item: OutreachSendQueueItem): string {
  if (item.queue_type === "follow_up") {
    return item.follow_up_step ? `二次跟进 ${item.follow_up_step}` : "二次跟进";
  }
  return "首次外联";
}

function getQueueErrorMessage(item: OutreachSendQueueItem): string {
  return translateEmailFailureReason(item.error_message);
}

function ModalShell({
  children,
  title,
  onClose,
}: {
  children: React.ReactNode;
  title: string;
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/35 p-4">
      <div className="max-h-[90vh] w-full max-w-xl overflow-y-auto rounded-lg border bg-background shadow-xl">
        <div className="sticky top-0 z-10 flex items-center justify-between border-b bg-background px-5 py-4">
          <h2 className="text-base font-semibold">{title}</h2>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="关闭">
            <X className="h-4 w-4" />
          </Button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function OutreachSendQueuePageClient() {
  const [items, setItems] = useState<OutreachSendQueueItem[]>([]);
  const [status, setStatus] = useState("");
  const [recipientEmail, setRecipientEmail] = useState("");
  const [campaignId, setCampaignId] = useState("");
  const [appliedFilters, setAppliedFilters] = useState({ status: "", recipientEmail: "", campaignId: "" });
  const [loading, setLoading] = useState(true);
  const [actionId, setActionId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [previewItem, setPreviewItem] = useState<OutreachSendQueueItem | null>(null);
  const [rescheduleItem, setRescheduleItem] = useState<OutreachSendQueueItem | null>(null);
  const [rescheduleAt, setRescheduleAt] = useState("");
  const [rescheduling, setRescheduling] = useState(false);

  const loadQueue = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchOutreachSendQueue({
        page: 1,
        pageSize: 100,
        status: appliedFilters.status || undefined,
        recipientEmail: appliedFilters.recipientEmail || undefined,
        campaignId: appliedFilters.campaignId ? Number(appliedFilters.campaignId) : undefined,
      });
      setItems(data.items);
    } catch (err) {
      setError(translateErrorMessage(err instanceof Error ? err.message : "加载发送队列失败"));
    } finally {
      setLoading(false);
    }
  }, [appliedFilters]);

  useEffect(() => {
    queueMicrotask(() => {
      void loadQueue();
    });
  }, [loadQueue]);

  const stats = useMemo(() => {
    const counts: Record<string, number> = {
      scheduled: 0,
      sending: 0,
      sent: 0,
      failed: 0,
      paused: 0,
      cancelled: 0,
      skipped: 0,
    };
    for (const item of items) {
      if (item.status === "queued") counts.scheduled += 1;
      else if (counts[item.status] !== undefined) counts[item.status] += 1;
    }
    return counts;
  }, [items]);

  async function runItemAction(id: number, action: () => Promise<OutreachSendQueueItem>, success: string) {
    setActionId(id);
    setError(null);
    setMessage(null);
    try {
      await action();
      setMessage(success);
      await loadQueue();
    } catch (err) {
      setError(translateErrorMessage(err instanceof Error ? err.message : "操作失败"));
    } finally {
      setActionId(null);
    }
  }

  function applyFilters() {
    setAppliedFilters({ status, recipientEmail, campaignId });
  }

  function resetFilters() {
    setStatus("");
    setRecipientEmail("");
    setCampaignId("");
    setAppliedFilters({ status: "", recipientEmail: "", campaignId: "" });
  }

  async function handleReschedule() {
    if (!rescheduleItem || !rescheduleAt) return;
    setRescheduling(true);
    setError(null);
    setMessage(null);
    try {
      await rescheduleOutreachQueueItem(rescheduleItem.id, localDateTimeToIso(rescheduleAt));
      setMessage("已重新排期");
      setRescheduleItem(null);
      setRescheduleAt("");
      await loadQueue();
    } catch (err) {
      setError(translateErrorMessage(err instanceof Error ? err.message : "重新排期失败"));
    } finally {
      setRescheduling(false);
    }
  }

  return (
    <AdminShell title="发送队列" description="查看待发送、二次跟进和失败重试中的外联邮件">
      <div className="ops-page queue-workbench">
        <div className="queue-topbar">
          <Button variant="ghost" asChild>
            <Link href="/outreach-records">
              <ArrowLeft className="h-4 w-4" />
              返回发送记录
            </Link>
          </Button>
          <Button variant="outline" disabled={loading} onClick={() => void loadQueue()}>
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            刷新
          </Button>
        </div>

        {error ? <ErrorAlert message={error} className="shrink-0" /> : null}
        {message ? <SuccessAlert message={message} className="shrink-0" /> : null}

        <div className="asset-summary queue-summary shrink-0">
          {[
            ["待发送", stats.scheduled],
            ["发送中", stats.sending],
            ["已发送", stats.sent],
            ["失败", stats.failed],
            ["已暂停", stats.paused],
            ["已跳过", stats.skipped],
          ].map(([label, count]) => (
            <div key={label} className="asset-summary-item">
              <div className="asset-summary-label">{label}</div>
              <div className="asset-summary-value">{count}</div>
            </div>
          ))}
        </div>

        <Card className="queue-filter-panel shrink-0">
          <CardHeader className="queue-card-header">
            <CardTitle className="text-base">筛选队列</CardTitle>
          </CardHeader>
          <CardContent className="queue-filter-body">
            <div className="grid gap-3 md:grid-cols-[180px_minmax(220px,1fr)_160px_auto_auto] md:items-end">
              <div className="space-y-1">
                <Label htmlFor="queueStatus">状态</Label>
                <select
                  id="queueStatus"
                  value={status}
                  onChange={(event) => setStatus(event.target.value)}
                  className="flex h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                >
                  {STATUS_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-1">
                <Label htmlFor="recipientEmail">收件人</Label>
                <Input
                  id="recipientEmail"
                  value={recipientEmail}
                  onChange={(event) => setRecipientEmail(event.target.value)}
                  placeholder="name@example.com"
                />
              </div>
              <div className="space-y-1">
                <Label htmlFor="campaignIdFilter">活动 ID</Label>
                <Input
                  id="campaignIdFilter"
                  value={campaignId}
                  onChange={(event) => setCampaignId(event.target.value)}
                  inputMode="numeric"
                />
              </div>
              <Button onClick={applyFilters}>筛选</Button>
              <Button variant="outline" onClick={resetFilters}>重置</Button>
            </div>
          </CardContent>
        </Card>

        <Card className="queue-table-panel flex min-h-0 flex-1 flex-col overflow-hidden">
          <CardHeader className="queue-card-header shrink-0">
            <CardTitle className="text-base">队列列表</CardTitle>
          </CardHeader>
          <CardContent className="min-h-0 flex-1 p-0">
            {loading ? (
              <div className="p-8 text-sm text-muted-foreground">加载队列中...</div>
            ) : items.length === 0 ? (
              <div className="m-4 rounded-md border border-dashed p-8 text-sm text-muted-foreground">
                暂无符合条件的队列邮件。
              </div>
            ) : (
              <div className="ops-table-wrap">
                <table className="ops-table queue-table min-w-[1080px]">
                  <thead>
                    <tr>
                      <th className="py-2.5 pr-3 pl-4 font-medium">计划时间</th>
                      <th className="py-2.5 pr-3 font-medium">收件人</th>
                      <th className="py-2.5 pr-3 font-medium">主题</th>
                      <th className="py-2.5 pr-3 font-medium">邮件类型</th>
                      <th className="py-2.5 pr-3 font-medium">状态</th>
                      <th className="py-2.5 pr-3 font-medium">重试</th>
                      <th className="py-2.5 pr-3 font-medium">失败原因</th>
                      <th className="py-2.5 pr-4 font-medium">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((item) => (
                      <tr key={item.id}>
                        <td className="whitespace-nowrap py-3 pr-3 pl-4">{formatDate(item.scheduled_at)}</td>
                        <td className="py-3 pr-3">
                          <div className="font-medium">{item.recipient}</div>
                          <div className="text-xs text-muted-foreground">
                            红人 #{item.product_influencer_id}
                            {item.campaign_id ? ` / 活动 #${item.campaign_id}` : ""}
                          </div>
                        </td>
                        <td className="max-w-[260px] py-3 pr-3">
                          <span className="block truncate" title={item.subject}>
                            {item.subject}
                          </span>
                        </td>
                        <td className="py-3 pr-3">
                          <Badge variant={item.queue_type === "follow_up" ? "warning" : "outline"}>
                            {getQueueTypeLabel(item)}
                          </Badge>
                        </td>
                        <td className="py-3 pr-3">
                          <StatusBadge status={item.status} />
                        </td>
                        <td className="whitespace-nowrap py-3 pr-3">
                          {item.retry_count}/{item.max_retries}
                        </td>
                        <td className="max-w-[260px] py-3 pr-3 text-xs text-destructive">
                          {item.error_message ? (
                            <span className="block truncate" title={item.error_message}>
                              {getQueueErrorMessage(item)}
                            </span>
                          ) : (
                            <span className="text-muted-foreground">-</span>
                          )}
                        </td>
                        <td className="py-3 pr-4">
                          <div className="queue-row-actions">
                            <Button variant="ghost" size="sm" onClick={() => setPreviewItem(item)}>
                              <Eye className="h-3.5 w-3.5" />
                              查看
                            </Button>
                            {item.status === "scheduled" || item.status === "queued" ? (
                              <>
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  disabled={actionId === item.id}
                                  onClick={() =>
                                    void runItemAction(item.id, () => pauseOutreachQueueItem(item.id), "已暂停发送")
                                  }
                                >
                                  <Pause className="h-3.5 w-3.5" />
                                  暂停
                                </Button>
                                <Button variant="ghost" size="sm" onClick={() => setRescheduleItem(item)}>
                                  <CalendarClock className="h-3.5 w-3.5" />
                                  改期
                                </Button>
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  disabled={actionId === item.id}
                                  onClick={() =>
                                    void runItemAction(item.id, () => cancelScheduledOutreachQueueItem(item.id), "已取消发送")
                                  }
                                >
                                  <Trash2 className="h-3.5 w-3.5" />
                                  取消
                                </Button>
                              </>
                            ) : null}
                            {item.status === "paused" ? (
                              <Button
                                variant="ghost"
                                size="sm"
                                disabled={actionId === item.id}
                                onClick={() =>
                                  void runItemAction(item.id, () => resumeOutreachQueueItem(item.id), "已恢复发送")
                                }
                              >
                                <Play className="h-3.5 w-3.5" />
                                恢复
                              </Button>
                            ) : null}
                            {item.status === "failed" ? (
                              <Button
                                variant="ghost"
                                size="sm"
                                disabled={actionId === item.id}
                                onClick={() =>
                                  void runItemAction(item.id, () => sendOutreachQueueItemNow(item.id), "已重新加入发送")
                                }
                              >
                                <RotateCw className="h-3.5 w-3.5" />
                                重试
                              </Button>
                            ) : null}
                            {item.status !== "sent" &&
                            item.status !== "sending" &&
                            item.status !== "cancelled" &&
                            item.status !== "skipped" ? (
                              <Button
                                variant="ghost"
                                size="sm"
                                disabled={actionId === item.id}
                                onClick={() =>
                                  void runItemAction(item.id, () => sendOutreachQueueItemNow(item.id), "已发送或进入发送流程")
                                }
                              >
                                <Send className="h-3.5 w-3.5" />
                                立即发送
                              </Button>
                            ) : null}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>

        {previewItem ? (
          <ModalShell title="邮件内容" onClose={() => setPreviewItem(null)}>
            <div className="space-y-4 p-5 text-sm">
              <div>
                <p className="text-xs text-muted-foreground">收件人</p>
                <p className="font-medium">{previewItem.recipient}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">主题</p>
                <p className="font-medium">{previewItem.subject}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">正文</p>
                <pre className="mt-1 whitespace-pre-wrap rounded-md border bg-muted/20 p-3 text-xs">{previewItem.body}</pre>
              </div>
            </div>
          </ModalShell>
        ) : null}

        {rescheduleItem ? (
          <ModalShell title="重新排期" onClose={() => setRescheduleItem(null)}>
            <div className="space-y-4 p-5">
              <div className="space-y-1">
                <Label htmlFor="rescheduleAt">新的发送时间</Label>
                <Input
                  id="rescheduleAt"
                  type="datetime-local"
                  value={rescheduleAt}
                  onChange={(event) => setRescheduleAt(event.target.value)}
                />
              </div>
              <div className="flex justify-end gap-2">
                <Button variant="outline" onClick={() => setRescheduleItem(null)}>
                  取消
                </Button>
                <Button disabled={!rescheduleAt || rescheduling} onClick={() => void handleReschedule()}>
                  {rescheduling ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                  保存
                </Button>
              </div>
            </div>
          </ModalShell>
        ) : null}
      </div>
    </AdminShell>
  );
}
