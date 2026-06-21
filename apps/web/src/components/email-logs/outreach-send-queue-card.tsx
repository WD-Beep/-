"use client";

import { useCallback, useEffect, useState } from "react";
import { Clock, Loader2, Play, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorAlert, SuccessAlert } from "@/components/shared/page-states";
import { EmailAddressCell } from "@/lib/email-address-cell";
import {
  cancelOutreachQueueItem,
  fetchOutreachSendQueue,
  processTodayOutreachQueue,
  type OutreachSendQueueItem,
} from "@/lib/api";
import { translateErrorMessage } from "@/lib/labels";

const STATUS_LABELS: Record<string, string> = {
  queued: "待发送",
  scheduled: "已计划",
  sending: "发送中",
  sent: "已发送",
  failed: "失败",
  cancelled: "已取消",
  skipped: "已跳过",
};

function formatDate(value: string | null): string {
  if (!value) return "-";
  return new Date(value).toLocaleString("zh-CN");
}

export function OutreachSendQueueCard() {
  const [items, setItems] = useState<OutreachSendQueueItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [processing, setProcessing] = useState(false);
  const [actionId, setActionId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [dailyLimit, setDailyLimit] = useState(20);
  const [sentToday, setSentToday] = useState(0);

  const loadQueue = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchOutreachSendQueue({ page: 1, pageSize: 50 });
      setItems(data.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载发送队列失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    queueMicrotask(() => {
      void loadQueue();
    });
  }, [loadQueue]);

  async function handleProcessToday() {
    if (!window.confirm("确认手动发送今日队列？将按每日限额逐封校验并发送，不会自动群发。")) {
      return;
    }
    setProcessing(true);
    setError(null);
    setMessage(null);
    try {
      const result = await processTodayOutreachQueue();
      setMessage(result.message);
      setDailyLimit(result.daily_limit);
      setSentToday(result.sent_today);
      await loadQueue();
    } catch (err) {
      setError(translateErrorMessage(err instanceof Error ? err.message : "发送失败"));
    } finally {
      setProcessing(false);
    }
  }

  async function handleCancel(id: number) {
    setActionId(id);
    try {
      await cancelOutreachQueueItem(id);
      await loadQueue();
    } catch (err) {
      setError(translateErrorMessage(err instanceof Error ? err.message : "取消失败"));
    } finally {
      setActionId(null);
    }
  }

  const pendingCount = items.filter((item) => item.status === "queued" || item.status === "scheduled").length;

  return (
    <Card className="mb-4">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Clock className="h-4 w-4" />
          发送队列（今日手动发送）
        </CardTitle>
        <CardDescription>
          需先在 AI 邮件弹窗预览并确认后加入队列。每日上限 {dailyLimit} 封，今日已发 {sentToday} 封。
          待发送 {pendingCount} 条。
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {error ? <ErrorAlert message={error} /> : null}
        {message ? <SuccessAlert message={message} /> : null}
        <div className="flex gap-2">
          <Button
            variant="default"
            disabled={processing || pendingCount === 0}
            onClick={() => void handleProcessToday()}
          >
            {processing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            发送今日队列
          </Button>
          <Button variant="outline" disabled={loading} onClick={() => void loadQueue()}>
            刷新
          </Button>
        </div>
        {loading ? (
          <p className="text-sm text-muted-foreground">加载队列…</p>
        ) : items.length === 0 ? (
          <p className="text-sm text-muted-foreground">暂无队列项。在红人 AI 邮件弹窗中预览后可「加入发送队列」。</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] text-sm">
              <thead>
                <tr className="border-b text-left text-muted-foreground">
                  <th className="pb-2 pr-3 font-medium">收件人</th>
                  <th className="pb-2 pr-3 font-medium">标题</th>
                  <th className="pb-2 pr-3 font-medium">状态</th>
                  <th className="pb-2 pr-3 font-medium">计划时间</th>
                  <th className="pb-2 pr-3 font-medium">错误</th>
                  <th className="pb-2 font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id} className="border-b align-top last:border-0">
                    <td className="py-2 pr-3">
                      <EmailAddressCell email={item.recipient} />
                    </td>
                    <td className="max-w-[220px] py-2 pr-3">
                      <span className="block truncate" title={item.subject}>
                        {item.subject}
                      </span>
                    </td>
                    <td className="py-2 pr-3">
                      <Badge variant={item.status === "failed" ? "destructive" : "secondary"}>
                        {STATUS_LABELS[item.status] ?? item.status}
                      </Badge>
                    </td>
                    <td className="py-2 pr-3 whitespace-nowrap">{formatDate(item.scheduled_at)}</td>
                    <td className="max-w-[200px] py-2 pr-3 text-xs text-destructive">
                      {item.error_message ? (
                        <span className="block truncate" title={item.error_message}>
                          {item.error_message}
                        </span>
                      ) : (
                        "-"
                      )}
                    </td>
                    <td className="py-2">
                      {item.status === "queued" || item.status === "scheduled" ? (
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={actionId === item.id}
                          onClick={() => void handleCancel(item.id)}
                        >
                          {actionId === item.id ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          ) : (
                            <Trash2 className="h-3.5 w-3.5" />
                          )}
                          取消
                        </Button>
                      ) : (
                        "-"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
