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
  clearFailedOutreachQueue,
  fetchOutreachSendQueue,
  processTodayOutreachQueue,
  type OutreachSendQueueItem,
} from "@/lib/api";
import { translateEmailFailureReason } from "@/lib/email-log-helpers";
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

function getQueueTypeLabel(item: OutreachSendQueueItem): string {
  if (item.queue_type === "follow_up") {
    return item.follow_up_step ? `二次跟进 ${item.follow_up_step}` : "二次跟进";
  }
  return "首次外联";
}

export function OutreachSendQueueCard() {
  const [items, setItems] = useState<OutreachSendQueueItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [processing, setProcessing] = useState(false);
  const [clearingFailed, setClearingFailed] = useState(false);
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
    if (!window.confirm("确认开始发送今日待发邮件？系统会按每日限额逐封发送。")) return;
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

  async function handleClearFailed() {
    if (!window.confirm("确认删除发送失败的队列记录？不会删除已发送成功记录或回复记录。")) return;
    setClearingFailed(true);
    setError(null);
    setMessage(null);
    try {
      const result = await clearFailedOutreachQueue();
      setMessage(result.message);
      await loadQueue();
    } catch (err) {
      setError(translateErrorMessage(err instanceof Error ? err.message : "清空失败队列失败"));
    } finally {
      setClearingFailed(false);
    }
  }

  const pendingCount = items.filter((item) => item.status === "queued" || item.status === "scheduled").length;
  const sentCount = items.filter((item) => item.status === "sent").length;
  const failedCount = items.filter((item) => item.status === "failed").length;

  return (
    <Card className="queue-mini-panel shrink-0 overflow-hidden">
      <CardHeader className="queue-card-header">
        <CardTitle className="flex items-center gap-2 text-base">
          <Clock className="h-4 w-4" />
          今日待发送
        </CardTitle>
        <CardDescription>只显示最近队列，完整队列请进入发送队列页。</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3 px-4 py-3">
        {error ? <ErrorAlert message={error} /> : null}
        {message ? <SuccessAlert message={message} /> : null}
        <div className="queue-mini-toolbar">
          {[
            ["待发送", pendingCount],
            ["今日已发", sentToday],
            ["队列已发", sentCount],
            ["失败", failedCount],
          ].map(([label, count]) => (
            <div key={label} className="queue-mini-stat">
              <span>{label}</span>
              <strong>{count}</strong>
            </div>
          ))}
          <Button variant="default" size="sm" disabled={processing || pendingCount === 0} onClick={() => void handleProcessToday()}>
            {processing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            发送今日队列
          </Button>
          <Button variant="outline" size="sm" disabled={loading} onClick={() => void loadQueue()}>
            刷新
          </Button>
          {failedCount > 0 ? (
            <Button variant="outline" size="sm" disabled={clearingFailed} onClick={() => void handleClearFailed()}>
              {clearingFailed ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
              清空失败
            </Button>
          ) : null}
          <span className="text-xs text-muted-foreground">每日上限 {dailyLimit} 封。</span>
        </div>
        {loading ? (
          <p className="text-sm text-muted-foreground">加载队列...</p>
        ) : items.length === 0 ? (
          <p className="text-sm text-muted-foreground">暂无待发送邮件。</p>
        ) : (
          <div className="queue-mini-table-wrap">
            <table className="ops-table queue-mini-table min-w-[900px]">
              <thead>
                <tr>
                  <th className="py-2 pr-3 pl-3 font-medium">收件人</th>
                  <th className="py-2 pr-3 font-medium">标题</th>
                  <th className="py-2 pr-3 font-medium">类型</th>
                  <th className="py-2 pr-3 font-medium">状态</th>
                  <th className="py-2 pr-3 font-medium">计划时间</th>
                  <th className="py-2 pr-3 font-medium">失败原因</th>
                  <th className="py-2 pr-3 font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id} className="border-b align-top last:border-0">
                    <td className="py-2 pr-3 pl-3">
                      <EmailAddressCell email={item.recipient} />
                    </td>
                    <td className="max-w-[220px] py-2 pr-3">
                      <span className="block truncate" title={item.subject}>
                        {item.subject}
                      </span>
                    </td>
                    <td className="py-2 pr-3">
                      <Badge variant={item.queue_type === "follow_up" ? "warning" : "outline"}>{getQueueTypeLabel(item)}</Badge>
                    </td>
                    <td className="py-2 pr-3">
                      <Badge variant={item.status === "failed" ? "destructive" : "secondary"}>
                        {STATUS_LABELS[item.status] ?? item.status}
                      </Badge>
                    </td>
                    <td className="whitespace-nowrap py-2 pr-3">{formatDate(item.scheduled_at)}</td>
                    <td className="max-w-[260px] py-2 pr-3 text-xs text-destructive">
                      {item.error_message ? (
                        <span className="block truncate" title={item.error_message}>
                          {translateEmailFailureReason(item.error_message)}
                        </span>
                      ) : (
                        "-"
                      )}
                    </td>
                    <td className="py-2 pr-3">
                      {item.status === "queued" || item.status === "scheduled" ? (
                        <Button variant="ghost" size="sm" disabled={actionId === item.id} onClick={() => void handleCancel(item.id)}>
                          {actionId === item.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
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
