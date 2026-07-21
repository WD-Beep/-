// 文件说明：前端邮件记录和发送队列组件；当前文件：email logs panel
"use client";

import Link from "next/link";
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Copy, ListChecks, Loader2, MailCheck, MailX, MoreHorizontal, RefreshCw, Reply, Send, Trash2 } from "lucide-react";

import { SaveEmailAsTemplateDialog } from "@/components/email-logs/save-email-as-template-dialog";
import { OutreachSendQueueCard } from "@/components/email-logs/outreach-send-queue-card";
import { AdminShell } from "@/components/layout/admin-shell";
import { useActiveProductId } from "@/components/providers/product-provider";
import { EmptyState, ErrorAlert, LoadingState, SuccessAlert } from "@/components/shared/page-states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  bulkSecondFollowUpOutreachRecords,
  deleteEmailLogs,
  deleteEmailLogsByStatus,
  fetchCollectionTasks,
  fetchEmailLogs,
  fetchEmailReplies,
  fetchSettingsStatus,
  markOutreachRecordReplied,
  markOutreachRecordUnreplied,
  scheduleOutreachRecordFollowUp,
  sendEmailReplyResponse,
  stopOutreachRecordFollowUp,
  updateEmailReply,
  type CollectionTask,
  type EmailLog,
  type EmailReply,
} from "@/lib/api";
import {
  buildEmailLogSummary,
  buildOutreachRecordsUrl,
  filterEmailLogsByView,
  getEmailLogReplyActions,
  getEmailLogViewTabs,
  getOutreachSummaryMetrics,
  parseEmailLogView,
  translateEmailFailureReason,
  type EmailLogView,
} from "@/lib/email-log-helpers";
import { buildEmailReplyResponseDraft } from "@/lib/email-reply-helpers";
import { EmailAddressCell } from "@/lib/email-address-cell";
import { EMAIL_LOG_STATUS_LABELS, translateErrorMessage } from "@/lib/labels";

const LOGS_PAGE_SIZE = 20;

const FOLLOW_UP_STATUS_LABELS: Record<string, string> = {
  none: "未开启",
  pending_check: "待检查",
  scheduled: "已排期",
  sent: "已跟进",
  stopped: "已停止",
  completed: "已完成",
  failed: "失败",
};

const STOP_REASON_LABELS: Record<string, string> = {
  replied: "红人已回复",
  manually_stopped: "手动停止",
  max_followups_reached: "达到上限",
  bounced: "退信",
  unsubscribed: "已退订",
  invalid_email: "邮箱无效",
};

type LogWithReply = EmailLog & { reply?: EmailReply | null };

function formatDate(value: string | null): string {
  if (!value) return "-";
  return new Date(value).toLocaleString("zh-CN");
}

function statusMeta(status: keyof typeof EMAIL_LOG_STATUS_LABELS) {
  return EMAIL_LOG_STATUS_LABELS[status] ?? EMAIL_LOG_STATUS_LABELS.pending;
}

function truncate(text: string, max = 120): string {
  if (text.length <= max) return text;
  return `${text.slice(0, max)}...`;
}

function getFollowUpStatusLabel(status: string | null): string {
  return FOLLOW_UP_STATUS_LABELS[status ?? "none"] ?? status ?? "未开启";
}

function getStopReasonLabel(reason: string | null): string {
  return STOP_REASON_LABELS[reason ?? ""] ?? reason ?? "-";
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
      <pre className="max-w-[360px] whitespace-pre-wrap break-all text-xs text-muted-foreground">
        {expanded ? body : truncate(body)}
      </pre>
      <div className="flex gap-2">
        {body.length > 120 ? (
          <button type="button" className="text-xs text-primary hover:underline" onClick={() => setExpanded((v) => !v)}>
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

function RecordMetricPill({
  label,
  count,
  view,
  recordsOnly,
  active,
  onSelect,
}: {
  label: string;
  count: number;
  view: EmailLogView;
  recordsOnly: boolean;
  active?: boolean;
  onSelect: (view: EmailLogView) => void;
}) {
  const className =
    `outreach-metric ${active ? "outreach-metric-active" : ""}`;
  const content = (
    <>
      <span className="outreach-metric-label">{label}</span>
      <span className="outreach-metric-value">{count}</span>
    </>
  );

  if (!recordsOnly) {
    return (
      <Link href={buildOutreachRecordsUrl(view)} className={className}>
        {content}
      </Link>
    );
  }

  return (
    <button type="button" className={className} onClick={() => onSelect(view)}>
      {content}
    </button>
  );
}

function EmailLogsMetricCard({
  label,
  value,
  helper,
  icon,
  tone = "default",
  onClick,
}: {
  label: string;
  value: number;
  helper: string;
  icon: ReactNode;
  tone?: "default" | "success" | "danger" | "warning";
  onClick?: () => void;
}) {
  return (
    <button type="button" className="email-log-kpi" data-tone={tone} onClick={onClick}>
      <span className="email-log-kpi-icon">{icon}</span>
      <span className="email-log-kpi-copy">
        <span className="email-log-kpi-label">{label}</span>
        <strong>{value}</strong>
        <span className="email-log-kpi-helper">{helper}</span>
      </span>
    </button>
  );
}

export function EmailLogsPanel({
  initialView = "all",
  recordsOnly = false,
}: {
  initialView?: EmailLogView | string | null;
  recordsOnly?: boolean;
}) {
  const productId = useActiveProductId();
  const [logs, setLogs] = useState<EmailLog[]>([]);
  const [repliesByLogId, setRepliesByLogId] = useState<Map<number, EmailReply>>(new Map());
  const [tasks, setTasks] = useState<CollectionTask[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [smtpConfigured, setSmtpConfigured] = useState<boolean | null>(null);
  const [saveLog, setSaveLog] = useState<EmailLog | null>(null);
  const [saveDuplicateHint, setSaveDuplicateHint] = useState(false);
  const [activeView, setActiveView] = useState<EmailLogView>(() => parseEmailLogView(initialView));
  const [expandedRows, setExpandedRows] = useState<Set<number>>(new Set());
  const [selectedLogIds, setSelectedLogIds] = useState<Set<number>>(new Set());
  const [deleting, setDeleting] = useState(false);
  const [bulkFollowingUp, setBulkFollowingUp] = useState(false);
  const [recordActionId, setRecordActionId] = useState<number | null>(null);
  const [replyDetail, setReplyDetail] = useState<{ reply: EmailReply; log: LogWithReply } | null>(null);
  const [responseBody, setResponseBody] = useState("");
  const [responseDraftGenerated, setResponseDraftGenerated] = useState(false);
  const [sendingResponse, setSendingResponse] = useState(false);
  const [success, setSuccess] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const recordsRef = useRef<HTMLDivElement | null>(null);

  const taskNameMap = useMemo(() => {
    const map = new Map<number, string>();
    for (const task of tasks) map.set(task.id, task.name);
    return map;
  }, [tasks]);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [logsData, tasksData, settings, repliesResult] = await Promise.all([
        fetchEmailLogs(1, 100),
        fetchCollectionTasks(1, 100),
        fetchSettingsStatus(),
        fetchEmailReplies({ page: 1, pageSize: 200 }).catch(() => ({ items: [], total: 0, page: 1, page_size: 200 })),
      ]);
      setLogs(logsData.items);
      setTotal(logsData.total);
      setTasks(tasksData.items);
      setSmtpConfigured(settings.smtp.configured);

      const replyMap = new Map<number, EmailReply>();
      for (const reply of repliesResult.items) {
        if (reply.email_log_id && !replyMap.has(reply.email_log_id)) replyMap.set(reply.email_log_id, reply);
      }
      setRepliesByLogId(replyMap);
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
      setPage(1);
      void loadData();
    });
  }, [loadData, productId]);

  useEffect(() => {
    queueMicrotask(() => {
      setActiveView(parseEmailLogView(initialView));
      setPage(1);
    });
  }, [initialView]);

  function resolveTaskName(taskId: number | null): string {
    if (!taskId) return "系统邮件";
    return taskNameMap.get(taskId) ?? `任务 #${taskId}`;
  }

  function toggleExpandedRow(logId: number) {
    setExpandedRows((prev) => {
      const next = new Set(prev);
      if (next.has(logId)) next.delete(logId);
      else next.add(logId);
      return next;
    });
  }

  const logsWithReplies: LogWithReply[] = useMemo(
    () =>
      logs.map((log) => ({
        ...log,
        reply: repliesByLogId.get(log.id) ?? null,
      })),
    [logs, repliesByLogId],
  );

  const summary = buildEmailLogSummary(logsWithReplies, 0);
  const tabs = getEmailLogViewTabs(summary);
  const summaryMetrics = getOutreachSummaryMetrics(summary, activeView);
  const visibleLogs = filterEmailLogsByView(logsWithReplies, activeView) as LogWithReply[];
  const latestSentLog = logsWithReplies
    .filter((log) => log.sent_at)
    .sort((a, b) => new Date(b.sent_at ?? 0).getTime() - new Date(a.sent_at ?? 0).getTime())[0];
  const latestReplyLog = logsWithReplies
    .filter((log) => log.reply?.received_at)
    .sort((a, b) => new Date(b.reply?.received_at ?? 0).getTime() - new Date(a.reply?.received_at ?? 0).getTime())[0];
  const totalPages = Math.max(1, Math.ceil(visibleLogs.length / LOGS_PAGE_SIZE));
  const currentPage = Math.min(page, totalPages);
  const pagedLogs = visibleLogs.slice((currentPage - 1) * LOGS_PAGE_SIZE, currentPage * LOGS_PAGE_SIZE);
  const visibleLogIds = useMemo(() => pagedLogs.map((log) => log.id), [pagedLogs]);
  const selectedVisibleCount = visibleLogIds.filter((id) => selectedLogIds.has(id)).length;
  const allVisibleSelected = visibleLogIds.length > 0 && selectedVisibleCount === visibleLogIds.length;

  function jumpToRecords(view: EmailLogView) {
    setActiveView(view);
    setPage(1);
    window.setTimeout(() => recordsRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 0);
  }

  function toggleSelectedLog(logId: number) {
    setSelectedLogIds((prev) => {
      const next = new Set(prev);
      if (next.has(logId)) next.delete(logId);
      else next.add(logId);
      return next;
    });
  }

  function toggleAllVisibleLogs() {
    setSelectedLogIds((prev) => {
      const next = new Set(prev);
      if (allVisibleSelected) {
        for (const id of visibleLogIds) next.delete(id);
      } else {
        for (const id of visibleLogIds) next.add(id);
      }
      return next;
    });
  }

  async function runRecordAction(logId: number, action: () => Promise<EmailLog>) {
    setRecordActionId(logId);
    setError(null);
    setSuccess(null);
    try {
      await action();
      await loadData();
    } catch (err) {
      setError(translateErrorMessage(err instanceof Error ? err.message : "外联记录操作失败"));
    } finally {
      setRecordActionId(null);
    }
  }

  async function handleBulkSecondFollowUp() {
    const recordIds = Array.from(selectedLogIds);
    if (recordIds.length === 0) return;
    const confirmed = window.confirm(`确认给已选 ${recordIds.length} 条发送记录创建第二次跟进？已回复、已停止、失败或不可发的记录会由后端跳过。`);
    if (!confirmed) return;

    setBulkFollowingUp(true);
    setError(null);
    setSuccess(null);
    try {
      const result = await bulkSecondFollowUpOutreachRecords(recordIds);
      setSelectedLogIds(new Set());
      await loadData();
      setSuccess(`已创建 ${result.created_count} 条第二次跟进，跳过 ${result.skipped_count} 条。`);
    } catch (err) {
      setError(translateErrorMessage(err instanceof Error ? err.message : "批量创建第二次跟进失败"));
    } finally {
      setBulkFollowingUp(false);
    }
  }

  async function markReplyViewed(reply: EmailReply): Promise<EmailReply> {
    if (reply.viewed_at) return reply;
    const updated = await updateEmailReply(reply.id, { mark_viewed: true });
    setRepliesByLogId((current) => {
      const next = new Map(current);
      if (updated.email_log_id) next.set(updated.email_log_id, updated);
      return next;
    });
    window.dispatchEvent(new Event("email-replies:work-count-changed"));
    return updated;
  }

  async function openReplyDetail(log: LogWithReply) {
    if (!log.reply) return;
    setError(null);
    setSuccess(null);
    try {
      const reply = await markReplyViewed(log.reply);
      setReplyDetail({ reply, log: { ...log, reply } });
      setResponseBody("");
      setResponseDraftGenerated(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "打开回复详情失败");
    }
  }

  async function openReplyComposer(log: LogWithReply) {
    if (!log.reply) return;
    setError(null);
    setSuccess(null);
    try {
      const reply = await markReplyViewed(log.reply);
      setReplyDetail({ reply, log: { ...log, reply } });
      setResponseBody(
        buildEmailReplyResponseDraft({
          influencerName: log.influencer_username || null,
          intentStatus: reply.intent_status,
        }),
      );
      setResponseDraftGenerated(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "打开回复编辑失败");
    }
  }

  function handleGenerateResponseDraft() {
    if (!replyDetail) return;
    setResponseBody(
      buildEmailReplyResponseDraft({
        influencerName: replyDetail.log.influencer_username || null,
        intentStatus: replyDetail.reply.intent_status,
      }),
    );
    setResponseDraftGenerated(true);
  }

  async function handleSendResponse() {
    if (!replyDetail) return;
    if (!responseBody.trim()) {
      setError("请先填写回复正文");
      return;
    }
    setSendingResponse(true);
    setError(null);
    setSuccess(null);
    try {
      const result = await sendEmailReplyResponse(replyDetail.reply.id, {
        body: responseBody,
        use_ai_draft: responseDraftGenerated,
        mark_processed: true,
      });
      if (!result.sent) {
        setError(result.error || "发送回复失败");
        return;
      }
      setSuccess("回复已发送，已记录到该红人的邮件回复中。");
      setReplyDetail(null);
      setResponseBody("");
      setResponseDraftGenerated(false);
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "发送回复失败");
    } finally {
      setSendingResponse(false);
    }
  }

  async function handleDeleteLogs(ids: number[], label: string) {
    const uniqueIds = Array.from(new Set(ids));
    if (uniqueIds.length === 0 || deleting) return;
    if (!window.confirm(`确认删除${label} ${uniqueIds.length} 条记录吗？此操作不可恢复。`)) return;
    setDeleting(true);
    setError(null);
    try {
      const result = await deleteEmailLogs(uniqueIds);
      setSelectedLogIds((prev) => {
        const next = new Set(prev);
        for (const id of result.deleted_ids) next.delete(id);
        return next;
      });
      setExpandedRows((prev) => {
        const next = new Set(prev);
        for (const id of result.deleted_ids) next.delete(id);
        return next;
      });
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除外联记录失败");
    } finally {
      setDeleting(false);
    }
  }

  async function handleDeleteCurrentFilter() {
    if (deleting) return;
    if (activeView === "sent" || activeView === "failed") {
      const label = activeView === "sent" ? "已发送记录" : "失败记录";
      if (!window.confirm(`确认删除当前产品下的${label}吗？此操作不可恢复。`)) return;
      setDeleting(true);
      setError(null);
      try {
        const result = await deleteEmailLogsByStatus(activeView);
        setSelectedLogIds((prev) => {
          const next = new Set(prev);
          for (const id of result.deleted_ids) next.delete(id);
          return next;
        });
        setExpandedRows((prev) => {
          const next = new Set(prev);
          for (const id of result.deleted_ids) next.delete(id);
          return next;
        });
        await loadData();
      } catch (err) {
        setError(err instanceof Error ? err.message : "删除当前筛选结果失败");
      } finally {
        setDeleting(false);
      }
      return;
    }
    await handleDeleteLogs(visibleLogIds, "当前筛选结果");
  }

  return (
    <AdminShell
      title={recordsOnly ? "发送记录" : "邮件日志"}
      description={recordsOnly ? "查看已发送邮件、回复和二次跟进状态" : "查看邮件发送历史和待发送队列"}
      actions={
        recordsOnly ? (
          <>
            <span className="text-[13px] text-slate-500">{loading ? "正在同步" : `当前筛选 ${visibleLogs.length} 条`}</span>
            <Button variant="outline" onClick={loadData} disabled={loading}>
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              刷新
            </Button>
            <Button asChild>
              <Link href="/outreach-send-queue">
                <ListChecks className="h-4 w-4" />
                发送队列
              </Link>
            </Button>
          </>
        ) : (
          <>
            <span className="text-[13px] text-slate-500">{loading ? "正在同步" : `共 ${total} 条日志`}</span>
            <Button variant="outline" onClick={loadData} disabled={loading}>
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              刷新
            </Button>
            <Button variant="secondary" asChild>
              <Link href="/outreach-records">查看发送记录</Link>
            </Button>
          </>
        )
      }
    >
      <div className={recordsOnly ? "outreach-records-workbench" : "email-logs-workbench"}>
        {error ? <ErrorAlert message={error} className={recordsOnly ? "outreach-inline-alert" : "shrink-0"} /> : null}
        {success ? <SuccessAlert message={success} className={recordsOnly ? "outreach-inline-alert" : "shrink-0"} /> : null}

        {!recordsOnly ? (
          <section className="email-logs-overview">
            <div className="email-log-kpi-grid">
              <EmailLogsMetricCard
                label="已发送"
                value={summary.sent}
                helper="成功发出的外联邮件"
                tone="default"
                icon={<Send className="h-4 w-4" />}
                onClick={() => jumpToRecords("sent")}
              />
              <EmailLogsMetricCard
                label="发送失败"
                value={summary.failed}
                helper="需要检查邮箱或频率"
                tone="danger"
                icon={<MailX className="h-4 w-4" />}
                onClick={() => jumpToRecords("failed")}
              />
              <EmailLogsMetricCard
                label="已回复"
                value={summary.replied}
                helper="红人已经回复的记录"
                tone="success"
                icon={<Reply className="h-4 w-4" />}
                onClick={() => jumpToRecords("replied")}
              />
              <EmailLogsMetricCard
                label="未回复"
                value={summary.unreplied}
                helper="可继续安排二次跟进"
                tone="warning"
                icon={<MailCheck className="h-4 w-4" />}
                onClick={() => jumpToRecords("unreplied")}
              />
            </div>
            <aside className="email-logs-status-panel">
              <div>
                <p className="email-logs-status-label">邮箱状态</p>
                <div className="mt-1 flex flex-wrap items-center gap-2">
                  <Badge variant={smtpConfigured ? "success" : "warning"}>{smtpConfigured ? "SMTP 已配置" : "SMTP 未确认"}</Badge>
                  <span className="text-xs text-slate-500">发送后会自动进入发送记录。</span>
                </div>
              </div>
              <div className="email-logs-status-grid">
                <div>
                  <span>最近发送</span>
                  <strong>{latestSentLog ? formatDate(latestSentLog.sent_at) : "-"}</strong>
                </div>
                <div>
                  <span>最近回复</span>
                  <strong>{latestReplyLog?.reply ? formatDate(latestReplyLog.reply.received_at) : "-"}</strong>
                </div>
              </div>
            </aside>
          </section>
        ) : null}

        <section className={recordsOnly ? "outreach-summary-panel" : "hidden"}>
          <div className={recordsOnly ? "outreach-summary-heading" : "px-5 py-3"}>
            <div>
              <h2 className={recordsOnly ? "outreach-section-title" : "text-base font-semibold"}>
                {recordsOnly ? "外联概览" : "发送概览"}
              </h2>
              <p className={recordsOnly ? "outreach-section-note" : "mt-1 text-sm text-muted-foreground"}>
                {recordsOnly ? "快速切换发送、回复和跟进状态。" : "点击指标可进入发送记录页。"}
              </p>
            </div>
            {recordsOnly ? <span className="outreach-summary-total">共 {total} 条日志</span> : null}
          </div>
          <div className={recordsOnly ? "outreach-metrics-grid" : "flex flex-wrap gap-2 px-5 pb-4"}>
            {summaryMetrics.map((metric) => (
              <RecordMetricPill
                key={metric.key}
                label={metric.label}
                count={metric.count}
                view={metric.key}
                recordsOnly={recordsOnly}
                active={metric.active}
                onSelect={jumpToRecords}
              />
            ))}
          </div>
        </section>

        {!recordsOnly ? <OutreachSendQueueCard /> : null}

        <section ref={recordsRef} className={recordsOnly ? "outreach-records-panel" : "ops-panel email-logs-records-panel"}>
          <div className={recordsOnly ? "outreach-records-header" : "shrink-0 px-5 py-3"}>
            <div>
              <h2 className={recordsOnly ? "outreach-section-title" : "text-base font-semibold"}>
                {recordsOnly ? "外联记录" : "发送记录"}
              </h2>
              <p className={recordsOnly ? "outreach-section-note" : "mt-1 text-sm text-muted-foreground"}>
                共 {total} 条日志，当前筛选 {visibleLogs.length} 条，每页 {LOGS_PAGE_SIZE} 条。
              </p>
            </div>
          </div>
          <div className="flex min-h-0 flex-1 flex-col p-0">
            {loading ? (
              <LoadingState label="加载邮件日志..." />
            ) : visibleLogs.length === 0 ? (
              <EmptyState title="暂无邮件记录" description="发送后记录会显示在这里。" />
            ) : (
              <>
                <div className={recordsOnly ? "outreach-table-toolbar" : "flex shrink-0 flex-wrap items-center justify-between gap-2 border-y bg-muted/20 px-4 py-2"}>
                  <div className={recordsOnly ? "outreach-segmented-tabs" : "flex flex-wrap gap-1"}>
                    {tabs.map((tab) => (
                      <button
                        key={tab.key}
                        type="button"
                        className={
                          recordsOnly
                            ? "outreach-tab"
                            : activeView === tab.key
                              ? "inline-flex h-8 items-center justify-center gap-2 whitespace-nowrap rounded-md bg-blue-600 px-3 text-xs font-medium text-white shadow-[0_1px_1px_rgba(15,23,42,0.08)] transition-colors hover:bg-blue-700"
                              : "inline-flex h-8 items-center justify-center gap-2 whitespace-nowrap rounded-md border border-slate-200 bg-[hsl(210_30%_99%)] px-3 text-xs font-medium text-slate-800 transition-colors hover:border-slate-300 hover:bg-slate-50"
                        }
                        data-active={recordsOnly && activeView === tab.key ? "true" : undefined}
                        onClick={() => {
                          setActiveView(tab.key);
                          setPage(1);
                        }}
                      >
                        <span>{tab.label}</span>
                        <span className={recordsOnly ? "outreach-tab-count" : ""}>{tab.count}</span>
                      </button>
                    ))}
                  </div>
                  <div className={recordsOnly ? "outreach-bulk-actions" : "flex flex-wrap items-center gap-2 text-xs text-muted-foreground"}>
                    <span className={recordsOnly ? "outreach-selection-note" : ""}>
                      本页 {pagedLogs.length} / 筛选 {visibleLogs.length}，已选 {selectedLogIds.size}
                    </span>
                    <Button type="button" variant="outline" size="sm" onClick={toggleAllVisibleLogs} disabled={pagedLogs.length === 0 || deleting}>
                      {allVisibleSelected ? "取消本页选择" : "选择本页"}
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={selectedLogIds.size === 0 || deleting || bulkFollowingUp}
                      onClick={() => void handleBulkSecondFollowUp()}
                    >
                      {bulkFollowingUp ? <Loader2 className="h-4 w-4 animate-spin" /> : <Reply className="h-4 w-4" />}
                      批量第二次跟进
                    </Button>
                    <Button
                      type="button"
                      variant="destructive"
                      size="sm"
                      disabled={selectedLogIds.size === 0 || deleting}
                      onClick={() => void handleDeleteLogs(Array.from(selectedLogIds), "已选记录")}
                    >
                      {deleting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
                      删除已选
                    </Button>
                    <Button type="button" variant="outline" size="sm" disabled={visibleLogs.length === 0 || deleting} onClick={() => void handleDeleteCurrentFilter()}>
                      删除当前筛选
                    </Button>
                  </div>
                </div>

                <div className={recordsOnly ? "outreach-table-wrap" : "ops-table-wrap"}>
                  <table className={recordsOnly ? "outreach-table" : "ops-table email-logs-table min-w-[1040px]"}>
                    <thead>
                      <tr>
                        <th className="w-10">
                          <input type="checkbox" aria-label="选择本页记录" checked={allVisibleSelected} onChange={toggleAllVisibleLogs} />
                        </th>
                        <th className="w-[22%]">红人 / 收件人</th>
                        <th className="w-[30%]">标题 / 摘要</th>
                        <th className="w-[24%]">状态 / 跟进</th>
                        <th className="w-[14%]">时间</th>
                        <th className="w-[10%]">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {pagedLogs.map((log) => {
                        const status = statusMeta(log.status);
                        const reply = log.reply;
                        const hasReplied = log.has_replied || Boolean(reply);
                        const followUpStatus = log.follow_up_status ?? "none";
                        const canScheduleFollowUp =
                          log.status === "sent" && !hasReplied && !log.stop_follow_up && followUpStatus !== "pending_check";
                        const canStopFollowUp = !log.stop_follow_up && followUpStatus !== "none";
                        const canMarkReplied = !hasReplied && log.status === "sent";
                        const canSaveTemplate = Boolean(log.generated_by_ai && log.status === "sent" && log.body);
                        const expanded = expandedRows.has(log.id);
                        const moreOpen = expandedRows.has(-log.id);
                        const failureText = log.status === "failed" ? translateEmailFailureReason(log.error_message) : null;
                        const replySummary = reply?.snippet ?? log.reply_summary ?? null;
                        const replyActions = getEmailLogReplyActions(log);

                        return (
                          <Fragment key={log.id}>
                            <tr className={recordsOnly ? "outreach-data-row" : "align-top"}>
                              <td>
                                <input
                                  type="checkbox"
                                  aria-label={`选择记录 ${log.id}`}
                                  checked={selectedLogIds.has(log.id)}
                                  onChange={() => toggleSelectedLog(log.id)}
                                />
                              </td>
                              <td>
                                <div className="space-y-1.5">
                                  <p className="break-all text-sm font-medium text-foreground">
                                    {log.influencer_username ? `@${log.influencer_username}` : "-"}
                                  </p>
                                  <EmailAddressCell email={log.recipients[0] ?? null} />
                                </div>
                              </td>
                              <td>
                                <div className="space-y-1.5">
                                  <p className="line-clamp-2 max-w-[340px] break-words text-sm font-medium leading-5">{log.subject}</p>
                                  {failureText ? <p className="line-clamp-1 max-w-[340px] text-xs text-destructive">失败：{failureText}</p> : null}
                                  {replySummary ? <p className="line-clamp-1 max-w-[340px] text-xs text-muted-foreground">回复：{truncate(replySummary, 90)}</p> : null}
                                </div>
                              </td>
                              <td>
                                <div className="space-y-2">
                                  <div className="flex flex-wrap gap-1.5">
                                    <Badge variant={status.variant}>{status.label}</Badge>
                                    {hasReplied ? <Badge variant="success">已回复</Badge> : <Badge variant="outline">未回复</Badge>}
                                    <Badge variant={followUpStatus === "stopped" ? "warning" : "secondary"}>
                                      {getFollowUpStatusLabel(followUpStatus)}
                                    </Badge>
                                  </div>
                                  <div className="space-y-0.5 text-xs text-muted-foreground">
                                    <p>跟进次数：{log.follow_up_count}/{log.max_followups}</p>
                                    <p>下次跟进：{formatDate(log.next_follow_up_at)}</p>
                                    {log.stop_follow_up ? <p>停止原因：{getStopReasonLabel(log.stop_reason)}</p> : null}
                                  </div>
                                </div>
                              </td>
                              <td className={recordsOnly ? "outreach-time-cell" : "whitespace-nowrap text-xs text-muted-foreground"}>
                                <div className="space-y-1">
                                  <p>发送：{formatDate(log.sent_at)}</p>
                                  {reply ? <p>回复：{formatDate(reply.received_at)}</p> : null}
                                </div>
                              </td>
                              <td>
                                <div className={recordsOnly ? "outreach-row-actions" : "flex min-w-[132px] flex-wrap items-center gap-1.5"}>
                                  <Button variant={recordsOnly ? "outline" : "ghost"} size="sm" onClick={() => toggleExpandedRow(log.id)}>
                                    {expanded ? "收起" : "详情"}
                                  </Button>
                                  {replyActions.canViewReply && reply ? (
                                    <Button variant="outline" size="sm" onClick={() => void openReplyDetail(log)}>
                                      看回复
                                    </Button>
                                  ) : null}
                                  {replyActions.canSendResponse && reply ? (
                                    <Button variant="outline" size="sm" onClick={() => void openReplyComposer(log)}>
                                      回复
                                    </Button>
                                  ) : null}
                                  {canScheduleFollowUp ? (
                                    <Button
                                      variant="outline"
                                      size="sm"
                                      disabled={recordActionId === log.id}
                                      onClick={() =>
                                        void runRecordAction(log.id, () =>
                                          scheduleOutreachRecordFollowUp(log.id, { after_days: 3, max_followups: 2 }),
                                        )
                                      }
                                    >
                                      二次跟进
                                    </Button>
                                  ) : canMarkReplied ? (
                                    <Button
                                      variant="outline"
                                      size="sm"
                                      disabled={recordActionId === log.id}
                                      onClick={() => void runRecordAction(log.id, () => markOutreachRecordReplied(log.id))}
                                    >
                                      标记回复
                                    </Button>
                                  ) : null}
                                  <div className="relative">
                                    <Button variant="ghost" size="sm" aria-label="更多操作" onClick={() => toggleExpandedRow(-log.id)}>
                                      {recordsOnly ? <MoreHorizontal className="h-4 w-4" /> : moreOpen ? "收起" : "更多"}
                                    </Button>
                                    {moreOpen ? (
                                      <div className="outreach-more-menu">
                                        {hasReplied ? (
                                          <button
                                            type="button"
                                            className="outreach-menu-item"
                                            disabled={recordActionId === log.id}
                                            onClick={() => void runRecordAction(log.id, () => markOutreachRecordUnreplied(log.id))}
                                          >
                                            标记未回复
                                          </button>
                                        ) : null}
                                        {canStopFollowUp ? (
                                          <button
                                            type="button"
                                            className="outreach-menu-item"
                                            disabled={recordActionId === log.id}
                                            onClick={() =>
                                              void runRecordAction(log.id, () =>
                                                stopOutreachRecordFollowUp(log.id, { reason: "manually_stopped" }),
                                              )
                                            }
                                          >
                                            停止跟进
                                          </button>
                                        ) : null}
                                        {canSaveTemplate ? (
                                          <button
                                            type="button"
                                            className="outreach-menu-item"
                                            onClick={() => {
                                              setSaveDuplicateHint(false);
                                              setSaveLog(log);
                                            }}
                                          >
                                            保存为话术
                                          </button>
                                        ) : null}
                                        <button
                                          type="button"
                                          className="outreach-menu-item outreach-menu-danger"
                                          disabled={deleting}
                                          onClick={() => void handleDeleteLogs([log.id], "这条记录")}
                                        >
                                          删除
                                        </button>
                                      </div>
                                    ) : null}
                                  </div>
                                </div>
                              </td>
                            </tr>
                            {expanded ? (
                              <tr className={recordsOnly ? "outreach-detail-row" : "border-b bg-muted/20"}>
                                <td colSpan={6} className="space-y-3 py-3 pr-4 pl-4 text-xs">
                                  <div className="grid gap-3 lg:grid-cols-3">
                                    <div>
                                      <p className="font-medium">发件人</p>
                                      <EmailAddressCell email={log.sender_email} />
                                    </div>
                                    <div>
                                      <p className="font-medium">任务</p>
                                      <p className="text-muted-foreground">{resolveTaskName(log.task_id)}</p>
                                    </div>
                                    <div>
                                      <p className="font-medium">错误信息</p>
                                      <p className="break-all text-muted-foreground">{translateErrorMessage(log.error_message) || "-"}</p>
                                    </div>
                                  </div>
                                  <div className="grid gap-3 lg:grid-cols-2">
                                    <div>
                                      <p className="font-medium">正文</p>
                                      <EmailBodyCell body={log.body} />
                                    </div>
                                    <div>
                                      <p className="font-medium">AI 和附件</p>
                                      <div className="mt-1 space-y-1 text-muted-foreground">
                                        <p>{log.generated_by_ai ? "AI 生成" : log.body ? "模板邮件" : "-"}</p>
                                        {log.ai_reason ? <p>理由：{truncate(log.ai_reason, 160)}</p> : null}
                                        {log.matched_knowledge && log.matched_knowledge.length > 0 ? (
                                          <p>知识库：{log.matched_knowledge.map((k) => k.document).join(" / ")}</p>
                                        ) : null}
                                        {log.risk_notes && log.risk_notes.length > 0 ? (
                                          <p className="text-amber-700">风险：{log.risk_notes.join(" / ")}</p>
                                        ) : null}
                                        <p>附件：{log.attachment_path ?? "-"}</p>
                                        {reply ? <p>回复时间：{formatDate(reply.received_at)}</p> : null}
                                      </div>
                                    </div>
                                  </div>
                                  {reply ? (
                                    <div className="rounded-md border border-blue-100 bg-blue-50/50 p-3">
                                      <div className="flex flex-wrap items-center justify-between gap-2">
                                        <p className="font-medium text-blue-900">红人回复全文</p>
                                        <Button type="button" variant="outline" size="sm" onClick={() => void openReplyComposer(log)}>
                                          回复这封邮件
                                        </Button>
                                      </div>
                                      <div className="mt-2 grid gap-2 text-muted-foreground md:grid-cols-3">
                                        <p className="break-all">来自：{reply.from_address}</p>
                                        <p className="break-all">收件：{reply.to_address}</p>
                                        <p>时间：{formatDate(reply.received_at)}</p>
                                      </div>
                                      <pre className="mt-3 max-h-60 overflow-auto whitespace-pre-wrap break-words rounded-md border bg-white p-3 leading-6 text-slate-700">
                                        {reply.body || reply.snippet || "没有正文内容"}
                                      </pre>
                                    </div>
                                  ) : null}
                                </td>
                              </tr>
                            ) : null}
                          </Fragment>
                        );
                      })}
                    </tbody>
                  </table>
                </div>

                <div className={recordsOnly ? "outreach-pagination" : "flex shrink-0 items-center justify-between border-t px-4 py-2 text-xs text-muted-foreground"}>
                  <span>
                    第 {currentPage} / {totalPages} 页
                  </span>
                  <div className="flex gap-2">
                    <Button type="button" variant="outline" size="sm" disabled={currentPage <= 1} onClick={() => setPage((value) => Math.max(1, value - 1))}>
                      上一页
                    </Button>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={currentPage >= totalPages}
                      onClick={() => setPage((value) => Math.min(totalPages, value + 1))}
                    >
                      下一页
                    </Button>
                  </div>
                </div>
              </>
            )}
          </div>
        </section>

        {replyDetail ? (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
            <div className="flex max-h-[88vh] w-full max-w-4xl flex-col overflow-hidden rounded-lg border bg-background shadow-xl">
              <div className="flex shrink-0 flex-wrap items-start justify-between gap-3 border-b px-6 py-4">
                <div>
                  <h2 className="text-lg font-semibold">{replyDetail.reply.subject || "红人回复"}</h2>
                  <p className="mt-1 break-all text-sm text-muted-foreground">
                    {replyDetail.reply.from_address} → {replyDetail.reply.to_address} · {formatDate(replyDetail.reply.received_at)}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {replyDetail.log.influencer_username ? `@${replyDetail.log.influencer_username}` : "未关联红人"} · 原邮件：{replyDetail.log.subject}
                  </p>
                </div>
                <Button
                  variant="outline"
                  onClick={() => {
                    setReplyDetail(null);
                    setResponseBody("");
                    setResponseDraftGenerated(false);
                  }}
                  disabled={sendingResponse}
                >
                  关闭
                </Button>
              </div>

              <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
                <div className="space-y-2">
                  <p className="text-sm font-semibold">红人回复内容</p>
                  <pre className="max-h-[34vh] overflow-auto whitespace-pre-wrap break-words rounded-md border bg-muted/20 p-4 text-sm leading-6">
                    {replyDetail.reply.body || replyDetail.reply.snippet || "没有正文内容"}
                  </pre>
                </div>

                <div className="mt-4 space-y-3 rounded-md border bg-muted/10 p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div>
                      <h3 className="text-sm font-semibold">业务员回复</h3>
                      <p className="mt-1 break-all text-xs text-muted-foreground">
                        会回复到：{replyDetail.reply.from_address}
                      </p>
                    </div>
                    {!replyDetail.log.influencer_username ? <Badge variant="warning">请确认红人身份</Badge> : null}
                  </div>
                  <textarea
                    className="min-h-36 w-full resize-y rounded-md border bg-background p-3 text-sm leading-6"
                    value={responseBody}
                    onChange={(event) => {
                      setResponseBody(event.target.value);
                      setResponseDraftGenerated(false);
                    }}
                    placeholder="在这里编辑要发给红人的回复内容"
                  />
                  <div className="flex flex-wrap justify-end gap-2">
                    <Button type="button" variant="outline" onClick={handleGenerateResponseDraft} disabled={sendingResponse}>
                      生成回复话术
                    </Button>
                    <Button type="button" onClick={() => void handleSendResponse()} disabled={sendingResponse || !responseBody.trim()}>
                      {sendingResponse ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                      发送回复
                    </Button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        ) : null}

        {saveLog ? (
          <SaveEmailAsTemplateDialog
            log={saveLog}
            open={Boolean(saveLog)}
            duplicateHint={saveDuplicateHint}
            onClose={() => setSaveLog(null)}
            onSaved={() => setSaveLog(null)}
          />
        ) : null}
      </div>
    </AdminShell>
  );
}
