"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Copy, Loader2, RefreshCw } from "lucide-react";

import { AdminShell } from "@/components/layout/admin-shell";
import { useActiveProductId } from "@/components/providers/product-provider";
import { EmptyState, ErrorAlert, LoadingState, SuccessAlert } from "@/components/shared/page-states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  fetchCollectionTasks,
  fetchEmailLogs,
  fetchSettingsStatus,
  type CollectionTask,
  type EmailLog,
} from "@/lib/api";
import { EMAIL_LOG_STATUS_LABELS, translateErrorMessage } from "@/lib/labels";

function formatDate(value: string | null): string {
  if (!value) return "-";
  return new Date(value).toLocaleString("zh-CN");
}

function statusMeta(status: keyof typeof EMAIL_LOG_STATUS_LABELS) {
  return EMAIL_LOG_STATUS_LABELS[status] ?? EMAIL_LOG_STATUS_LABELS.pending;
}

function truncate(text: string, max = 120): string {
  if (text.length <= max) return text;
  return `${text.slice(0, max)}…`;
}

function EmailBodyCell({ body }: { body: string | null | undefined }) {
  const [expanded, setExpanded] = useState(false);
  const [copied, setCopied] = useState(false);

  if (!body) return <span className="text-muted-foreground">-</span>;

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(body ?? "");
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* ignore */
    }
  }

  return (
    <div className="space-y-1">
      <pre className="max-w-[320px] whitespace-pre-wrap break-all text-xs text-muted-foreground">
        {expanded ? body : truncate(body)}
      </pre>
      <div className="flex gap-2">
        {body.length > 120 ? (
          <button
            type="button"
            className="text-xs text-primary hover:underline"
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? "收起" : "展开"}
          </button>
        ) : null}
        <button
          type="button"
          className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
          onClick={() => void handleCopy()}
        >
          <Copy className="h-3 w-3" />
          {copied ? "已复制" : "复制"}
        </button>
      </div>
    </div>
  );
}

export function EmailLogsPanel() {
  const productId = useActiveProductId();
  const [logs, setLogs] = useState<EmailLog[]>([]);
  const [tasks, setTasks] = useState<CollectionTask[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [smtpConfigured, setSmtpConfigured] = useState<boolean | null>(null);

  const taskNameMap = useMemo(() => {
    const map = new Map<number, string>();
    for (const task of tasks) {
      map.set(task.id, task.name);
    }
    return map;
  }, [tasks]);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [logsData, tasksData, settings] = await Promise.all([
        fetchEmailLogs(1, 100),
        fetchCollectionTasks(1, 100),
        fetchSettingsStatus(),
      ]);
      setLogs(logsData.items);
      setTotal(logsData.total);
      setTasks(tasksData.items);
      setSmtpConfigured(settings.smtp.configured);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载邮件日志失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (productId === null) {
      queueMicrotask(() => setLoading(false));
      return;
    }
    queueMicrotask(() => {
      setLogs([]);
      setTasks([]);
      setTotal(0);
      void loadData();
    });
  }, [loadData, productId]);

  function resolveTaskName(taskId: number | null): string {
    if (!taskId) return "系统邮件";
    return taskNameMap.get(taskId) ?? `任务 #${taskId}`;
  }

  return (
    <AdminShell title="邮件日志" description="查看发送记录与状态">
      <div className="mb-4">
        <Button variant="outline" onClick={loadData} disabled={loading}>
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          刷新列表
        </Button>
      </div>

      {error ? <ErrorAlert message={error} className="mb-4" /> : null}
      {smtpConfigured ? (
        <SuccessAlert
          message="SMTP 已配置。下方为历史发送记录，旧失败记录不会自动更新；重新发信后会新增一条记录。"
          className="mb-4"
        />
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>发送记录</CardTitle>
          <CardDescription>共 {total} 条邮件日志</CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <LoadingState label="加载邮件日志..." />
          ) : logs.length === 0 ? (
            <EmptyState
              title="暂无邮件记录"
              description="采集任务手动发信或定时发信后，记录会显示在此处。"
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[1300px] text-sm">
                <thead>
                  <tr className="border-b text-left text-muted-foreground">
                    <th className="pb-3 pr-4 font-medium">任务名</th>
                    <th className="pb-3 pr-4 font-medium">发件人</th>
                    <th className="pb-3 pr-4 font-medium">红人账号</th>
                    <th className="pb-3 pr-4 font-medium">收件人</th>
                    <th className="pb-3 pr-4 font-medium">邮件标题</th>
                    <th className="pb-3 pr-4 font-medium">正文</th>
                    <th className="pb-3 pr-4 font-medium">AI</th>
                    <th className="pb-3 pr-4 font-medium">状态</th>
                    <th className="pb-3 pr-4 font-medium">附件路径</th>
                    <th className="pb-3 pr-4 font-medium">错误信息</th>
                    <th className="pb-3 font-medium">发送时间</th>
                  </tr>
                </thead>
                <tbody>
                  {logs.map((log) => {
                    const status = statusMeta(log.status);
                    return (
                      <tr key={log.id} className="border-b align-top last:border-0">
                        <td className="py-3 pr-4 font-medium">{resolveTaskName(log.task_id)}</td>
                        <td className="max-w-[200px] py-3 pr-4">
                          <p className="break-all">{log.sender_email || "-"}</p>
                        </td>
                        <td className="py-3 pr-4 text-xs">
                          {log.influencer_username ? `@${log.influencer_username}` : "-"}
                        </td>
                        <td className="max-w-[200px] py-3 pr-4">
                          <p className="break-all">{log.recipients.join(", ") || "-"}</p>
                        </td>
                        <td className="max-w-[240px] py-3 pr-4">
                          <p className="break-all">{log.subject}</p>
                        </td>
                        <td className="py-3 pr-4">
                          <EmailBodyCell body={log.body} />
                        </td>
                        <td className="max-w-[200px] py-3 pr-4 text-xs">
                          {log.generated_by_ai ? (
                            <Badge variant="default" className="mb-1">AI</Badge>
                          ) : log.body ? (
                            <Badge variant="secondary" className="mb-1">模板</Badge>
                          ) : (
                            <span className="text-muted-foreground">-</span>
                          )}
                          {log.ai_reason ? (
                            <p className="break-all text-muted-foreground">{truncate(log.ai_reason, 80)}</p>
                          ) : null}
                          {log.matched_knowledge && log.matched_knowledge.length > 0 ? (
                            <p className="mt-1 break-all text-muted-foreground">
                              知识库：{log.matched_knowledge.map((k) => k.document).join(" · ")}
                            </p>
                          ) : null}
                          {log.risk_notes && log.risk_notes.length > 0 ? (
                            <p className="mt-1 break-all text-amber-700">{log.risk_notes.join(" · ")}</p>
                          ) : null}
                        </td>
                        <td className="py-3 pr-4">
                          <Badge variant={status.variant}>{status.label}</Badge>
                        </td>
                        <td className="max-w-[200px] py-3 pr-4">
                          <p className="break-all text-muted-foreground">
                            {log.attachment_path ?? "-"}
                          </p>
                        </td>
                        <td className="max-w-[220px] py-3 pr-4">
                          <p
                            className={
                              log.status === "failed"
                                ? "break-all text-destructive"
                                : "break-all text-muted-foreground"
                            }
                          >
                            {translateErrorMessage(log.error_message) || "-"}
                          </p>
                        </td>
                        <td className="py-3 whitespace-nowrap">{formatDate(log.sent_at)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </AdminShell>
  );
}
