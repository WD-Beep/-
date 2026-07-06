"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  AlertTriangle,
  CalendarClock,
  Clock3,
  Loader2,
  RefreshCw,
  Send,
  Settings,
  Sparkles,
  Users,
} from "lucide-react";

import { AdminShell } from "@/components/layout/admin-shell";
import { useActiveProductId } from "@/components/providers/product-provider";
import { ErrorAlert, SuccessAlert } from "@/components/shared/page-states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  createOutreachCampaign,
  bulkApproveOutreachCampaignDrafts,
  fetchOutreachWorkbench,
  fetchMessageTemplates,
  processOutreachCampaign,
  previewOutreachCampaign,
  queueOutreachCampaign,
  scheduleOutreachSendQueue,
  sendManualOutreachEmail,
  type MessageTemplate,
  type ManualOutreachSendMode,
  type OutreachCampaignCreatePayload,
  type OutreachCampaignPreviewResponse,
  type OutreachOneClickWorkbench,
} from "@/lib/api";
import { decodeFiltersFromSearchParams } from "@/lib/influencer-selection-helpers";
import { translateErrorMessage } from "@/lib/labels";
import { setStoredProductId } from "@/lib/product-context";
import {
  buildImmediateSendResultMessage,
  buildImmediateSendStartedMessage,
  buildLocalDateTime,
  buildManualOutreachConfirmMessage,
  buildManualOutreachPayload,
  buildOneClickCampaignName,
  buildOutreachCampaignPayload,
  buildApprovedDraftSendConfirmMessage,
  buildPreviewResultMessage,
  buildScheduledQueueSuccessMessage,
  buildScheduledSendCompletionMessage,
  buildScheduledOutreachQueuePayload,
  buildSkipReasonBreakdown,
  countApprovedOutreachDrafts,
  deriveOneClickQueueStatusFromCampaign,
  estimateCampaignEndTime,
  formatOneClickDateTime,
  getOutreachDraftStatusLabel,
  getOneClickContentSourceLabel,
  getOneClickCurrentStatusLabel,
  getOneClickPrimaryDisabledReason,
  humanizeOutreachFailureReason,
  parseManualOutreachRecipients,
  resolveOneClickSendLimit,
  type OneClickContentSource,
  type OneClickPrimaryActionKind,
  type OneClickQueueStatus,
} from "@/lib/outreach-campaign-helpers";
import { outreachWorkbenchStatusLabel } from "@/lib/outreach-workbench-view";
import { ALL_PRODUCTS_ID } from "@/lib/product-context";

type SourceMode = "filters" | "selected";
type SendMode = "now" | "scheduled";
type CopyMode = OneClickContentSource;
type ActionKind = "preview" | "send" | "queue" | "save";

const TIMEZONE = "Asia/Shanghai";

function todayInputValue(): string {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function timeInputValue(minutesFromNow = 30): string {
  const next = new Date(Date.now() + minutesFromNow * 60 * 1000);
  return `${String(next.getHours()).padStart(2, "0")}:${String(next.getMinutes()).padStart(2, "0")}`;
}

function statusVariant(status: string): "success" | "warning" | "destructive" | "secondary" {
  if (status === "normal") return "success";
  if (status === "error") return "destructive";
  if (status === "not_configured") return "warning";
  return "secondary";
}

function sendModeLabel(mode: SendMode): string {
  if (mode === "now") return "立即发送";
  return "定时发送";
}

function primaryIcon(action: OneClickPrimaryActionKind | "save") {
  if (action === "preview") return Sparkles;
  if (action === "send") return Send;
  if (action === "queue") return CalendarClock;
  if (action === "retry") return AlertTriangle;
  return RefreshCw;
}

function StepHeader({ step, title, desc }: { step: string; title: string; desc: string }) {
  return (
    <div className="campaign-step-header">
      <div className="campaign-step-number">
        {step}
      </div>
      <div>
        <CardTitle className="campaign-step-title">{title}</CardTitle>
        <p className="campaign-step-desc">{desc}</p>
      </div>
    </div>
  );
}

function MetricPill({
  label,
  value,
  status = "secondary",
}: {
  label: string;
  value: string;
  status?: "success" | "warning" | "destructive" | "secondary";
}) {
  const tone = {
    success: "border-emerald-200 bg-emerald-50 text-emerald-800",
    warning: "border-amber-200 bg-amber-50 text-amber-800",
    destructive: "border-red-200 bg-red-50 text-red-800",
    secondary: "border-slate-200 bg-slate-50 text-slate-700",
  }[status];
  return (
    <div className={`campaign-metric-pill ${tone}`}>
      <div className="campaign-metric-label">{label}</div>
      <div className="campaign-metric-value">{value}</div>
    </div>
  );
}

export function OutreachCampaignsPanel() {
  const productId = useActiveProductId();
  const searchParams = useSearchParams();

  const prefillIds = useMemo(() => {
    const raw = searchParams.get("ids");
    if (!raw) return [] as number[];
    return raw
      .split(",")
      .map((value) => Number(value.trim()))
      .filter((value) => Number.isFinite(value) && value > 0);
  }, [searchParams]);

  const selectAllByFilters = searchParams.get("select_all") === "1";
  const filterAllTotal = Number(searchParams.get("total") || "0");
  const filterSnapshot = useMemo(() => decodeFiltersFromSearchParams(searchParams), [searchParams]);

  const [workbench, setWorkbench] = useState<OutreachOneClickWorkbench | null>(null);
  const [templates, setTemplates] = useState<MessageTemplate[]>([]);
  const [preview, setPreview] = useState<OutreachCampaignPreviewResponse | null>(null);
  const [previewCampaignId, setPreviewCampaignId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyAction, setBusyAction] = useState<ActionKind | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const [sourceMode, setSourceMode] = useState<SourceMode>(
    selectAllByFilters || prefillIds.length === 0 ? "filters" : "selected",
  );
  const [sendMode, setSendMode] = useState<SendMode>("scheduled");
  const [copyMode, setCopyMode] = useState<CopyMode>("manual");
  const [manualSubject, setManualSubject] = useState("");
  const [manualBody, setManualBody] = useState("");
  const [selectedTemplateId, setSelectedTemplateId] = useState<number | null>(null);
  const [sendLimit, setSendLimit] = useState("");
  const [intervalMinutes, setIntervalMinutes] = useState("6");
  const [hourlyLimit, setHourlyLimit] = useState("10");
  const [dailyLimit, setDailyLimit] = useState("");
  const [scheduledDate, setScheduledDate] = useState(todayInputValue);
  const [scheduledTime, setScheduledTime] = useState(timeInputValue);
  const [windowStart, setWindowStart] = useState("09:00");
  const [windowEnd, setWindowEnd] = useState("18:00");
  const [skipNight, setSkipNight] = useState(true);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [queueStatus, setQueueStatus] = useState<OneClickQueueStatus>("not_queued");
  const [lastFailureReason, setLastFailureReason] = useState<string | null>(null);
  const [manualTestRecipients, setManualTestRecipients] = useState("");
  const [manualTestSubject, setManualTestSubject] = useState("");
  const [manualTestBody, setManualTestBody] = useState("");
  const [manualTestMode, setManualTestMode] = useState<ManualOutreachSendMode>("now");
  const [manualTestDate, setManualTestDate] = useState(todayInputValue);
  const [manualTestTime, setManualTestTime] = useState(timeInputValue);
  const [manualTestBusy, setManualTestBusy] = useState(false);
  const [manualTestOpen, setManualTestOpen] = useState(false);
  const [manualTestResult, setManualTestResult] = useState<string | null>(null);

  const requiresProduct = productId === ALL_PRODUCTS_ID;
  const selectedCount = prefillIds.length;
  const filterCount = filterAllTotal || workbench?.available_recipient_count || 0;
  const canUseFilters = Boolean(filterSnapshot || filterCount > 0);
  const canUseSelected = selectedCount > 0;
  const aiReady = workbench?.ai_generation.status === "normal";
  const smtpReady = workbench?.smtp.status === "normal";
  const selectedTemplate = templates.find((template) => template.id === selectedTemplateId) ?? null;
  const sourceAvailable =
    (sourceMode === "filters" && canUseFilters) ||
    (sourceMode === "selected" && canUseSelected);
  const estimatedSourceCount =
    sourceMode === "filters" ? filterCount : sourceMode === "selected" ? selectedCount : 0;
  const effectiveSendLimit = resolveOneClickSendLimit({
    configuredValue: sendLimit,
    sourceCount: estimatedSourceCount,
    fallbackCount: workbench?.available_recipient_count ?? 0,
  });
  const effectiveDailyLimit = resolveOneClickSendLimit({
    configuredValue: dailyLimit,
    sourceCount: effectiveSendLimit,
    fallbackCount: effectiveSendLimit,
  });
  const approvedDraftCount = preview ? countApprovedOutreachDrafts(preview.items) : 0;
  const sendCount = preview
    ? approvedDraftCount
    : Math.min(effectiveSendLimit, estimatedSourceCount || workbench?.available_recipient_count || 0);
  const skipBreakdown = preview ? buildSkipReasonBreakdown(preview.items) : { sent: 0, blacklisted: 0, invalid: 0, replied: 0, other: 0 };
  const scheduledAt = sendMode === "now" ? new Date() : buildLocalDateTime(scheduledDate, scheduledTime);
  const manualParsedRecipients = parseManualOutreachRecipients(manualTestRecipients);
  const manualScheduledAt =
    manualTestMode === "scheduled" ? buildLocalDateTime(manualTestDate, manualTestTime) : null;
  const estimatedEndAt =
    scheduledAt && sendCount > 0
      ? estimateCampaignEndTime({
          recipientCount: sendCount,
          startAt: scheduledAt,
          intervalMinutes: Number(intervalMinutes) || 1,
        })
      : null;
  const hasPreview = Boolean(preview);
  const effectiveQueueStatus =
    preview && preview.can_queue_count > 0 && queueStatus === "completed"
      ? "ready_to_send"
      : queueStatus;
  const aiStatusText = outreachWorkbenchStatusLabel({
    status: workbench?.ai_generation.status,
    loading,
    hasWorkbench: Boolean(workbench),
    hasError: Boolean(error),
  });
  const smtpStatusText = outreachWorkbenchStatusLabel({
    status: workbench?.smtp.status,
    loading,
    hasWorkbench: Boolean(workbench),
    hasError: Boolean(error),
  });

  const load = useCallback(async (options: { syncLatestCampaign?: boolean } = {}) => {
    setError(null);
    if (requiresProduct) {
      setWorkbench(null);
      setLoading(false);
      return;
    }
    setStoredProductId(productId);
    setLoading(true);
    try {
      const nextWorkbench = await fetchOutreachWorkbench();
      setWorkbench(nextWorkbench);
      const shouldSyncLatestCampaign =
        options.syncLatestCampaign ?? !(sourceAvailable && !previewCampaignId);
      const syncedQueueStatus = shouldSyncLatestCampaign
        ? deriveOneClickQueueStatusFromCampaign(nextWorkbench.latest_campaign)
        : "not_queued";
      setQueueStatus(syncedQueueStatus);
      if (syncedQueueStatus !== "failed") {
        setLastFailureReason(null);
      }
    } catch (err) {
      setError(translateErrorMessage(err instanceof Error ? err.message : "加载 AI 一键发邮件工作台失败"));
    } finally {
      setLoading(false);
    }
  }, [productId, previewCampaignId, requiresProduct, sourceAvailable]);

  useEffect(() => {
    queueMicrotask(() => {
      void load();
    });
  }, [load]);

  useEffect(() => {
    if (requiresProduct) {
      queueMicrotask(() => {
        setTemplates([]);
        setSelectedTemplateId(null);
      });
      return;
    }
    let cancelled = false;
    fetchMessageTemplates({ pageSize: 50 })
      .then((data) => {
        if (cancelled) return;
        setTemplates(data.items);
        setSelectedTemplateId((current) => current ?? data.items[0]?.id ?? null);
      })
      .catch(() => {
        if (!cancelled) setTemplates([]);
      });
    return () => {
      cancelled = true;
    };
  }, [requiresProduct, productId]);

  function clearPreview() {
    setPreview(null);
    setPreviewCampaignId(null);
    setQueueStatus("not_queued");
    setLastFailureReason(null);
  }

  function chooseSource(next: SourceMode) {
    setSourceMode(next);
    clearPreview();
  }

  function buildSourcePayload() {
    return buildOutreachCampaignPayload({
      name: buildOneClickCampaignName(),
      influencerIds: sourceMode === "selected" ? prefillIds : undefined,
      selectAllByFilters: sourceMode === "filters",
      influencerFilters:
        sourceMode === "filters"
          ? {
              platform: filterSnapshot?.platform,
              category: filterSnapshot?.category,
              niche: filterSnapshot?.niche,
              tag: filterSnapshot?.tag,
              source_discovery_type: filterSnapshot?.sourceDiscoveryType,
              has_email: filterSnapshot?.hasEmail,
              high_value: filterSnapshot?.highValue,
              value_tier: filterSnapshot?.valueTier,
              email_status: filterSnapshot?.emailStatus,
              search: filterSnapshot?.search,
              collection_task_id: filterSnapshot?.collectionTaskId,
              created_within_hours: filterSnapshot?.createdWithinHours,
              collected_within_days: filterSnapshot?.collectedWithinDays,
              exclude_terminal_statuses: filterSnapshot?.excludeTerminalStatuses,
            }
          : undefined,
      dailyLimit: effectiveDailyLimit || effectiveSendLimit || 1,
      messageTemplateId: copyMode === "template" ? selectedTemplateId : undefined,
      sendWindowStart: skipNight ? windowStart : "00:00",
      sendWindowEnd: skipNight ? windowEnd : "23:59",
      skipSent: true,
      skipReplied: true,
      skipBlacklisted: true,
      skipInvalid: true,
      allowResend: false,
    }) as OutreachCampaignCreatePayload;
  }

  async function ensurePreview(): Promise<{ campaignId: number; preview: OutreachCampaignPreviewResponse }> {
    if (preview && previewCampaignId) return { campaignId: previewCampaignId, preview };
    const created = await createOutreachCampaign(buildSourcePayload());
    const nextPreview = await previewOutreachCampaign(
      created.id,
      copyMode === "manual"
        ? {
            content_source: "manual",
            subject: manualSubject.trim(),
            body: manualBody.trim(),
          }
        : copyMode === "template"
          ? { content_source: "template" }
          : { content_source: "ai" },
    );
    setPreview(nextPreview);
    setPreviewCampaignId(created.id);
    return { campaignId: created.id, preview: nextPreview };
  }

  async function queuePreviewItems(input: {
    campaignId: number;
    preview: OutreachCampaignPreviewResponse;
    startAt: Date;
  }) {
    const approvedIds = input.preview.items
      .filter((item) => item.draft_status === "approved" && item.can_queue)
      .map((item) => item.influencer_id);
    if (approvedIds.length === 0) {
      throw new Error("没有已批准草稿。请先审核并批准草稿，再发送。");
    }
    return queueOutreachCampaign(input.campaignId, {
      confirm: true,
      influencer_ids: approvedIds,
    });
  }

  function disabledReasonFor(action: ActionKind): string | null {
    if (copyMode === "manual" && (action === "send" || action === "queue" || action === "preview" || action === "save")) {
      if (!manualSubject.trim()) return "请先填写邮件主题";
      if (!manualBody.trim()) return "请先填写邮件正文";
    }
    if (copyMode === "template" && (action === "send" || action === "queue" || action === "preview" || action === "save")) {
      if (!selectedTemplateId) return "请先选择话术库模板";
    }
    if (copyMode === "ai" && (action === "send" || action === "queue") && !hasPreview) {
      return "请先生成话术并检查，确认预览后再发送";
    }
    if (action === "queue" && !buildLocalDateTime(scheduledDate, scheduledTime)) {
      return "请先选择发送日期和具体时间";
    }
    if (requiresProduct) return "请先选择具体产品/品牌";
    return getOneClickPrimaryDisabledReason({
      recipientCount: estimatedSourceCount || preview?.can_queue_count || 0,
      sourceAvailable,
      smtpReady: Boolean(smtpReady),
      aiReady: Boolean(aiReady),
      generationMode: copyMode === "ai" ? "ai" : "template",
      action,
      scheduledAt,
    });
  }

  async function runAction(action: ActionKind) {
    const reason = disabledReasonFor(action);
    if (reason) {
      setError(reason);
      return;
    }
    if (action === "send" && !window.confirm(`确认立即发送给 ${sendCount} 位收件人？点击确认后邮件会马上发出。`)) {
      return;
    }
    if (action === "queue" && !window.confirm(`确认设置定时发送给 ${sendCount} 位收件人？到时间会自动发送，不需要再手动点。`)) {
      return;
    }

    setBusyAction(action);
    setError(null);
    setMessage(null);
    setLastFailureReason(null);
    try {
      if (action === "send") {
        setQueueStatus("sending");
        const generated = await ensurePreview();
        if (generated.preview.can_queue_count <= 0) {
          setQueueStatus("failed");
          throw new Error("没有邮件发出。所有收件人都被规则跳过，请查看跳过原因。");
        }
        await queuePreviewItems({
          campaignId: generated.campaignId,
          preview: generated.preview,
          startAt: new Date(),
        });
        setMessage(buildImmediateSendStartedMessage());
        const processed = await processOutreachCampaign(generated.campaignId);
        const skipped = generated.preview.skip_count + processed.skipped;
        setQueueStatus(processed.failed > 0 && processed.sent === 0 ? "failed" : "completed");
        const resultMessage = buildImmediateSendResultMessage({
          sent: processed.sent,
          failed: processed.failed,
          skipped,
        });
        if (processed.failed > 0 && processed.sent === 0) {
          setError(resultMessage);
          setLastFailureReason(resultMessage);
        } else {
          setMessage(resultMessage);
          if (processed.failed > 0) setLastFailureReason(resultMessage);
        }
      } else {
        const generated = await ensurePreview();
        const actionPreview = generated.preview;
        if (action === "preview") {
          setQueueStatus(actionPreview.can_queue_count > 0 ? "ready_to_send" : "failed");
          setMessage(
            buildPreviewResultMessage({
              total: actionPreview.total,
              canQueueCount: actionPreview.can_queue_count,
              skipCount: actionPreview.skip_count,
            }),
          );
        } else if (action === "save") {
          setMessage("草稿已保存，邮件尚未发出。确认发送时间后再开始发送。");
        } else {
          const scheduleStart = buildLocalDateTime(scheduledDate, scheduledTime) ?? new Date();
          const payload = buildScheduledOutreachQueuePayload({
            campaignId: generated.campaignId,
            preview: actionPreview,
            startAt: scheduleStart,
            intervalMinutes: Number(intervalMinutes) || 6,
            dailyLimit: effectiveDailyLimit || effectiveSendLimit || 1,
            hourlyLimit: Number(hourlyLimit) || 10,
            sendWindowStart: skipNight ? windowStart : "00:00",
            sendWindowEnd: skipNight ? windowEnd : "23:59",
            allowResend: false,
          });
          if (payload.items.length === 0) {
            setQueueStatus("failed");
            setLastFailureReason("没有邮件发出。所有收件人都被规则跳过，请查看跳过原因。");
            setError("没有邮件发出。所有收件人都被规则跳过，请查看跳过原因。");
          } else {
            const scheduled = await scheduleOutreachSendQueue(payload);
            setQueueStatus("waiting");
            setMessage(buildScheduledQueueSuccessMessage({
              createdCount: scheduled.created_count,
              skippedCount: scheduled.skipped_count,
              startAt: scheduled.first_scheduled_at ?? scheduleStart,
            }));
          }
        }
      }
      await load({ syncLatestCampaign: true });
    } catch (err) {
      const nextError = translateErrorMessage(err instanceof Error ? err.message : "操作失败");
      setQueueStatus("failed");
      setLastFailureReason(nextError);
      setError(nextError);
    } finally {
      setBusyAction(null);
    }
  }

  const primaryAction: { action: ActionKind; label: string } =
    copyMode === "ai" && !hasPreview
      ? { action: "preview", label: "生成话术并检查" }
      : { action: "send", label: copyMode === "ai" ? "确认并立即发送" : "立即发送" };
  const primaryDisabledReason = disabledReasonFor(primaryAction.action);
  const scheduleDisabledReason = disabledReasonFor("queue");
  const saveDisabledReason = disabledReasonFor("save");
  const primaryActionLabel =
    busyAction === primaryAction.action
      ? primaryAction.action === "preview"
        ? "生成中..."
        : "发送中..."
      : primaryAction.label;
  async function runReviewedAction(action: ActionKind) {
    const reason = disabledReasonFor(action);
    if (reason) {
      setError(reason);
      return;
    }
    if ((action === "send" || action === "queue") && !window.confirm(buildApprovedDraftSendConfirmMessage(sendCount))) {
      return;
    }

    setBusyAction(action);
    setError(null);
    setMessage(null);
    setLastFailureReason(null);
    try {
      const generated = await ensurePreview();
      const actionPreview = generated.preview;
      if (action === "preview") {
        setQueueStatus(actionPreview.can_queue_count > 0 ? "ready_to_send" : "failed");
        setMessage(
          buildPreviewResultMessage({
            total: actionPreview.total,
            canQueueCount: actionPreview.can_queue_count,
            skipCount: actionPreview.skip_count,
          }),
        );
      } else if (action === "save") {
        setMessage("草稿已保存，邮件尚未发出。请审核并批准草稿后再发送。");
      } else {
        const approvedCount = countApprovedOutreachDrafts(actionPreview.items);
        if (approvedCount <= 0) {
          setQueueStatus("failed");
          throw new Error("没有已批准草稿。请先审核并批准草稿，再发送。");
        }
        const queued = await queuePreviewItems({
          campaignId: generated.campaignId,
          preview: actionPreview,
          startAt: action === "send" ? new Date() : buildLocalDateTime(scheduledDate, scheduledTime) ?? new Date(),
        });
        if (action === "send") {
          setQueueStatus("sending");
          setMessage(buildImmediateSendStartedMessage());
          const processed = await processOutreachCampaign(generated.campaignId);
          const skipped = actionPreview.skip_count + processed.skipped + queued.skipped;
          setQueueStatus(processed.failed > 0 && processed.sent === 0 ? "failed" : "completed");
          const resultMessage = buildImmediateSendResultMessage({
            sent: processed.sent,
            failed: processed.failed,
            skipped,
          });
          if (processed.failed > 0 && processed.sent === 0) {
            setError(resultMessage);
            setLastFailureReason(resultMessage);
          } else {
            setMessage(resultMessage);
            if (processed.failed > 0) setLastFailureReason(resultMessage);
          }
        } else {
          setQueueStatus("waiting");
          setMessage(`已将 ${queued.queued} 封已批准邮件加入发送队列，跳过 ${queued.skipped} 封。`);
        }
      }
      await load({ syncLatestCampaign: true });
    } catch (err) {
      const nextError = translateErrorMessage(err instanceof Error ? err.message : "操作失败");
      setQueueStatus("failed");
      setLastFailureReason(nextError);
      setError(nextError);
    } finally {
      setBusyAction(null);
    }
  }

  void runAction;

  async function bulkApproveCurrentPreview() {
    if (!previewCampaignId || !preview) {
      setError("请先生成草稿预览。");
      return;
    }
    setBusyAction("save");
    setError(null);
    setMessage(null);
    try {
      const result = await bulkApproveOutreachCampaignDrafts(previewCampaignId, { confirm: true });
      const updated = await previewOutreachCampaign(previewCampaignId);
      setPreview(updated);
      setMessage(`${result.message}。高价值红人需要先打开草稿详情后手动批准。`);
    } catch (err) {
      setError(translateErrorMessage(err instanceof Error ? err.message : "批量批准失败"));
    } finally {
      setBusyAction(null);
    }
  }

  async function runManualTestSend() {
    setError(null);
    setManualTestResult(null);
    if (requiresProduct) {
      setError("请先选择具体产品/品牌");
      return;
    }
    if (manualParsedRecipients.valid.length === 0) {
      setError("请先填写至少 1 个有效收件邮箱");
      return;
    }
    if (manualParsedRecipients.invalid.length > 0) {
      setError(`有 ${manualParsedRecipients.invalid.length} 个邮箱格式不正确，请先修改`);
      return;
    }
    if (manualParsedRecipients.overLimit) {
      setError("自定义测试发送一次最多支持 10 个收件邮箱");
      return;
    }
    if (!manualTestSubject.trim()) {
      setError("请先填写测试邮件主题");
      return;
    }
    if (!manualTestBody.trim()) {
      setError("请先填写测试邮件正文");
      return;
    }
    if (manualTestMode === "scheduled" && !manualScheduledAt) {
      setError("请先选择定时发送日期和时间");
      return;
    }
    if (!smtpReady) {
      setError("邮件没有发出。原因：SMTP 未配置，请先在设置中配置发件邮箱。");
      return;
    }
    if (!window.confirm(buildManualOutreachConfirmMessage(manualParsedRecipients.valid.length, manualTestMode))) {
      return;
    }

    setManualTestBusy(true);
    try {
      const payload = buildManualOutreachPayload({
        recipientsText: manualTestRecipients,
        subject: manualTestSubject,
        body: manualTestBody,
        sendMode: manualTestMode,
        scheduledAt: manualScheduledAt,
      });
      const result = await sendManualOutreachEmail(payload);
      setManualTestResult(result.message);
      await load({ syncLatestCampaign: false });
    } catch (err) {
      setError(translateErrorMessage(err instanceof Error ? err.message : "自定义测试邮件发送失败"));
    } finally {
      setManualTestBusy(false);
    }
  }

  const previewItems = preview?.items.slice(0, 5) ?? [];
  const isFullySkippedPreview = Boolean(
    preview &&
      preview.total > 0 &&
      preview.can_queue_count === 0 &&
      preview.skip_count >= preview.total,
  );
  const scheduledCompletionMessage =
    workbench?.latest_campaign && workbench.latest_campaign.queued_count > 0
    ? buildScheduledSendCompletionMessage({
        queuedCount: workbench.latest_campaign.queued_count,
        sentCount: workbench.latest_campaign.sent_count,
        failedCount: workbench.latest_campaign.failed_count,
      })
    : null;
  const currentStatusLabel = getOneClickCurrentStatusLabel({
    busyAction,
    copyMode,
    hasPreview,
    queueStatus: effectiveQueueStatus,
    preview,
  });
  const currentStatusTone =
    effectiveQueueStatus === "failed"
      ? "destructive"
      : isFullySkippedPreview
        ? "warning"
        : effectiveQueueStatus === "completed"
          ? "success"
          : effectiveQueueStatus === "not_queued"
            ? "secondary"
            : "warning";
  const currentStatusBadgeVariant =
    currentStatusTone === "secondary" ? "outline" : currentStatusTone;

  return (
    <AdminShell
      title="AI 批量发邮件"
      description="选择收件人，自己填写、选择话术库或使用 AI 生成，然后在当前页面立即发送或设置定时发送。"
    >
      {requiresProduct ? <ErrorAlert message="请先在左侧选择具体产品/品牌" className="mb-4" /> : null}
      {error ? <ErrorAlert message={error} className="mb-4" /> : null}
      {!message && !error && scheduledCompletionMessage ? (
        <SuccessAlert message={scheduledCompletionMessage} className="mb-4" />
      ) : null}
      {message ? <SuccessAlert message={message} className="mb-4" /> : null}

      <div className="campaign-workbench">
        <div className="campaign-status-strip">
          <div className="campaign-status-main">
            <div className="campaign-status-metrics">
              <MetricPill
                label="AI 话术"
                value={aiStatusText}
                status={statusVariant(workbench?.ai_generation.status ?? "not_configured")}
              />
              <MetricPill
                label="SMTP"
                value={smtpStatusText}
                status={statusVariant(workbench?.smtp.status ?? "not_configured")}
              />
              <MetricPill label="可发送邮箱" value={`${workbench?.available_recipient_count ?? 0} 个`} />
              <MetricPill
                label="当前状态"
                value={currentStatusLabel}
                status={currentStatusTone}
              />
              <MetricPill
                label="发送方式"
                value={sendModeLabel(sendMode)}
              />
            </div>
            <div className="campaign-status-actions">
              <div className="campaign-manual-test-summary">
                <div>
                  <div className="text-xs font-medium text-slate-500">SMTP</div>
                  <div className="mt-0.5 text-sm font-semibold text-slate-900">{smtpStatusText}</div>
                </div>
                <div className="min-w-0">
                  <div className="text-xs font-medium text-slate-500">{"\u6700\u8fd1\u6d4b\u8bd5"}</div>
                  <div className="mt-0.5 truncate text-sm text-slate-600">{manualTestResult ?? "\u6682\u65e0"}</div>
                </div>
              </div>
              <Button
                variant="outline"
                onClick={() => setManualTestOpen((open) => !open)}
                aria-expanded={manualTestOpen}
              >
                <Send className="h-4 w-4" />
                {"\u6d4b\u8bd5\u53d1\u9001"}
              </Button>
              <Button variant="outline" onClick={() => void load()} disabled={loading}>
                {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                {"\u5237\u65b0"}
              </Button>
            </div>
          </div>
        </div>

        {manualTestOpen ? (
          <div className="campaign-manual-test-panel">
            <div className="campaign-manual-test-grid">
              <label className="space-y-1">
                <span className="text-xs font-medium text-slate-600">{"\u6536\u4ef6\u90ae\u7bb1\uff08\u6700\u591a 10 \u4e2a\uff0c\u53ef\u6362\u884c\u6216\u9017\u53f7\u5206\u9694\uff09"}</span>
                <Textarea
                  value={manualTestRecipients}
                  onChange={(event) => {
                    setManualTestRecipients(event.target.value);
                    setManualTestResult(null);
                  }}
                  rows={2}
                  placeholder={`creator@example.com\npartner@example.com`}
                />
              </label>
              <label className="space-y-1">
                <span className="text-xs font-medium text-slate-600">{"\u90ae\u4ef6\u4e3b\u9898"}</span>
                <Input
                  value={manualTestSubject}
                  onChange={(event) => setManualTestSubject(event.target.value)}
                  placeholder={"\u6d4b\u8bd5\u5408\u4f5c\u90ae\u4ef6\u6807\u9898"}
                />
              </label>
              <label className="space-y-1 campaign-manual-test-body">
                <span className="text-xs font-medium text-slate-600">{"\u90ae\u4ef6\u6b63\u6587"}</span>
                <Textarea
                  value={manualTestBody}
                  onChange={(event) => setManualTestBody(event.target.value)}
                  rows={4}
                  placeholder={"\u586b\u5199\u8981\u771f\u5b9e\u53d1\u9001\u7ed9\u8fd9\u4e9b\u90ae\u7bb1\u7684\u6b63\u6587"}
                />
              </label>
            </div>

            <div className="campaign-manual-test-controls">
              <div className="campaign-segmented inline-grid grid-cols-2">
                {(["now", "scheduled"] as ManualOutreachSendMode[]).map((mode) => (
                  <button
                    key={mode}
                    type="button"
                    onClick={() => setManualTestMode(mode)}
                    className={`h-9 rounded px-4 text-sm font-medium transition-colors ${
                      manualTestMode === mode
                        ? "bg-[hsl(210_30%_99%)] text-blue-700 shadow-sm"
                        : "text-slate-600 hover:text-slate-950"
                    }`}
                  >
                    {mode === "now" ? "\u7acb\u5373\u53d1\u9001" : "\u5b9a\u65f6\u53d1\u9001"}
                  </button>
                ))}
              </div>
              {manualTestMode === "scheduled" ? (
                <div className="campaign-manual-test-time">
                  <Input
                    type="date"
                    value={manualTestDate}
                    onChange={(event) => setManualTestDate(event.target.value)}
                  />
                  <Input
                    type="time"
                    value={manualTestTime}
                    onChange={(event) => setManualTestTime(event.target.value)}
                  />
                </div>
              ) : null}
              <Button onClick={() => void runManualTestSend()} disabled={manualTestBusy || requiresProduct}>
                {manualTestBusy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                {manualTestMode === "now" ? "\u53d1\u9001\u6d4b\u8bd5\u90ae\u4ef6" : "\u52a0\u5165\u5b9a\u65f6\u6d4b\u8bd5"}
              </Button>
            </div>

            <div className="campaign-hint-row campaign-manual-test-hint">
              <span>{"\u6709\u6548\u90ae\u7bb1\uff1a"}{manualParsedRecipients.valid.length}</span>
              <span>{"\u683c\u5f0f\u9519\u8bef\uff1a"}{manualParsedRecipients.invalid.length}</span>
              <span>{manualParsedRecipients.overLimit ? "\u5df2\u8d85\u8fc7 10 \u4e2a\u4e0a\u9650" : "\u4e0a\u9650 10 \u4e2a"}</span>
              {manualTestMode === "scheduled" ? (
                <span>
                  <CalendarClock className="mr-1 inline h-3.5 w-3.5" />
                  {manualScheduledAt ? formatOneClickDateTime(manualScheduledAt) : "\u672a\u9009\u62e9\u65f6\u95f4"}
                </span>
              ) : null}
            </div>
            {manualTestResult ? <SuccessAlert message={manualTestResult} /> : null}
          </div>
        ) : null}

        <div className="campaign-layout-grid">
          <div className="campaign-main-flow">
            <Card className="campaign-step-card">
              <CardHeader className="campaign-step-card-header">
                <StepHeader step="1" title="选择发送对象" desc="从红人库带入筛选或勾选结果，系统会自动排除不可发送对象。" />
              </CardHeader>
              <CardContent className="campaign-step-content space-y-4">
                <div className="campaign-recipient-panel">
                  <div>
                    <div className="text-xs font-medium text-slate-500">本次可发送人数</div>
                    <div className="mt-1 text-2xl font-semibold text-slate-950">{sendCount} 人</div>
                  </div>
                  <div>
                    <div className="text-xs font-medium text-slate-500">跳过人数</div>
                    <div className="mt-1 text-2xl font-semibold text-slate-950">{preview?.skip_count ?? 0} 人</div>
                  </div>
                  <div className="campaign-source-cell">
                    <div className="text-xs font-medium text-slate-500">来源</div>
                    <div className="mt-2 campaign-source-toggle">
                      <button
                        type="button"
                        data-active={sourceMode === "selected"}
                        onClick={() => chooseSource("selected")}
                      >
                        已勾选红人 {selectedCount}
                      </button>
                      <button
                        type="button"
                        data-active={sourceMode === "filters"}
                        onClick={() => chooseSource("filters")}
                      >
                        当前筛选 {filterCount}
                      </button>
                    </div>
                  </div>
                  <div className="campaign-recipient-actions">
                    <Button variant="outline" asChild>
                      <Link href="/influencers">
                        <Users className="h-4 w-4" />
                        去红人库选择
                      </Link>
                    </Button>
                    <Button variant="outline" onClick={() => void runReviewedAction("preview")} disabled={busyAction !== null}>
                      {busyAction === "preview" ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                      重新检查
                    </Button>
                  </div>
                </div>
                <div className="campaign-skip-overview">
                  <span>已发送：{skipBreakdown.sent}</span>
                  <span>已回复：{skipBreakdown.replied}</span>
                  <span>无邮箱：{skipBreakdown.other}</span>
                  <span>黑名单：{skipBreakdown.blacklisted}</span>
                  <span>无效邮箱：{skipBreakdown.invalid}</span>
                </div>
              </CardContent>
            </Card>

            <Card className="campaign-step-card">
              <CardHeader className="campaign-step-card-header">
                <StepHeader step="2" title="编辑邮件内容" desc="选择内容来源。自己填写和话术库可直接发送，AI 生成需先预览确认。" />
              </CardHeader>
              <CardContent className="campaign-step-content space-y-4">
                <div className="campaign-ai-panel">
                  <Sparkles className="h-4 w-4 text-blue-600" />
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-slate-900">
                      你可以直接填写标题和正文，也可以套用话术库；只有选择 AI 生成时才需要先生成话术。
                    </p>
                    <p className="mt-1 text-xs text-slate-500">
                      点击“立即发送”会马上发出；点击“定时发送”会到指定时间自动发出。
                    </p>
                  </div>
                </div>
                <div className="campaign-copy-mode-grid">
                  <button
                    type="button"
                    className="campaign-choice-card"
                    data-active={copyMode === "manual"}
                    onClick={() => {
                      setCopyMode("manual");
                      clearPreview();
                    }}
                  >
                    <span className="campaign-choice-title">自己填写</span>
                    <span className="campaign-choice-desc">使用你写好的统一标题和正文，确认后可立即发送。</span>
                  </button>
                  <button
                    type="button"
                    className="campaign-choice-card"
                    data-active={copyMode === "template"}
                    onClick={() => {
                      setCopyMode("template");
                      clearPreview();
                    }}
                  >
                    <span className="campaign-choice-title">话术库</span>
                    <span className="campaign-choice-desc">选择模板并预览变量替换后的内容。</span>
                  </button>
                  <button
                    type="button"
                    className="campaign-choice-card"
                    data-active={copyMode === "ai"}
                    onClick={() => {
                      setCopyMode("ai");
                      clearPreview();
                    }}
                  >
                    <span className="campaign-choice-title">AI 生成</span>
                    <span className="campaign-choice-desc">根据红人资料、品牌资料和知识库生成不同邮件。</span>
                  </button>
                </div>
                {copyMode === "manual" ? (
                  <div className="campaign-manual-copy">
                    <label className="space-y-1">
                      <span className="text-xs font-medium text-slate-600">邮件主题</span>
                      <Input
                        value={manualSubject}
                        onChange={(event) => {
                          setManualSubject(event.target.value);
                          clearPreview();
                        }}
                        placeholder="例如：想和你聊聊品牌合作"
                      />
                    </label>
                    <label className="space-y-1">
                      <span className="text-xs font-medium text-slate-600">邮件正文</span>
                      <Textarea
                        value={manualBody}
                        onChange={(event) => {
                          setManualBody(event.target.value);
                          clearPreview();
                        }}
                        rows={7}
                        placeholder="写入要批量发送的正文，系统会发给本次可发送的邮箱。"
                      />
                    </label>
                  </div>
                ) : null}
                {copyMode === "template" ? (
                  <div className="campaign-manual-copy">
                    <label className="space-y-1">
                      <span className="text-xs font-medium text-slate-600">选择话术模板</span>
                      <select
                        className="h-10 rounded-md border border-input bg-background px-3 text-sm"
                        value={selectedTemplateId ?? ""}
                        onChange={(event) => {
                          setSelectedTemplateId(Number(event.target.value) || null);
                          clearPreview();
                        }}
                      >
                        {templates.length === 0 ? <option value="">暂无可用模板</option> : null}
                        {templates.map((template) => (
                          <option key={template.id} value={template.id}>
                            {template.title}
                          </option>
                        ))}
                      </select>
                    </label>
                    <div className="campaign-preview-item">
                      <div className="text-xs font-medium text-slate-500">模板预览</div>
                      <div className="mt-2 text-sm font-semibold text-slate-900">
                        {selectedTemplate?.title ?? "请选择模板"}
                      </div>
                      <p className="mt-2 line-clamp-4 whitespace-pre-wrap text-sm leading-6 text-slate-600">
                        {selectedTemplate?.content ?? "话术库为空时，请先到话术库新增模板。"}
                      </p>
                    </div>
                  </div>
                ) : null}
                {copyMode === "ai" && !aiReady ? (
                  <div className="campaign-inline-warning flex gap-2 text-sm">
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                    AI 模型未配置，暂时无法自动优化话术。
                  </div>
                ) : null}
                <div className="campaign-hint-row">
                  <span>
                    {copyMode === "ai"
                      ? "AI 生成必须先预览确认"
                      : "可直接立即发送，也可先定时发送"}
                  </span>
                </div>
              </CardContent>
            </Card>

            <Card className="campaign-step-card">
              <CardHeader className="campaign-step-card-header">
                <StepHeader step="3" title="选择发送方式" desc="立即发送会马上发出；定时发送会到指定时间自动发送，不需要再进发送队列手动处理。" />
              </CardHeader>
              <CardContent className="campaign-step-content space-y-4">
                <div className="campaign-segmented inline-grid sm:grid-cols-2">
                  {(["now", "scheduled"] as SendMode[]).map((mode) => (
                    <button
                      key={mode}
                      type="button"
                      onClick={() => setSendMode(mode)}
                      className={`h-9 rounded px-4 text-sm font-medium transition-colors ${
                        sendMode === mode ? "bg-[hsl(210_30%_99%)] text-blue-700 shadow-sm" : "text-slate-600 hover:text-slate-950"
                      }`}
                    >
                      {sendModeLabel(mode)}
                    </button>
                  ))}
                </div>

                {sendMode === "scheduled" ? (
                  <div className="campaign-subpanel grid gap-3 md:grid-cols-[180px_160px_1fr]">
                    <label className="space-y-1">
                      <span className="text-xs font-medium text-slate-600">日期</span>
                      <Input type="date" value={scheduledDate} onChange={(event) => setScheduledDate(event.target.value)} />
                    </label>
                    <label className="space-y-1">
                      <span className="text-xs font-medium text-slate-600">时间</span>
                      <Input type="time" value={scheduledTime} onChange={(event) => setScheduledTime(event.target.value)} />
                    </label>
                    <div className="flex items-end text-sm text-slate-500">
                      <Clock3 className="mr-2 h-4 w-4" />
                      时区：{TIMEZONE}，到时间系统自动发送
                    </div>
                  </div>
                ) : null}

                <div className="campaign-advanced">
                  <button type="button" onClick={() => setAdvancedOpen((value) => !value)}>
                    <Settings className="h-4 w-4" />
                    高级设置
                    <span>{advancedOpen ? "收起" : "展开"}</span>
                  </button>
                  {advancedOpen ? (
                    <div className="mt-3 grid gap-3 md:grid-cols-4">
                      <label className="space-y-1">
                        <span className="text-xs font-medium text-slate-600">每封间隔分钟</span>
                        <Input value={intervalMinutes} onChange={(event) => setIntervalMinutes(event.target.value)} />
                      </label>
                      <label className="space-y-1">
                        <span className="text-xs font-medium text-slate-600">每小时上限</span>
                        <Input value={hourlyLimit} onChange={(event) => setHourlyLimit(event.target.value)} />
                      </label>
                      <label className="space-y-1">
                        <span className="text-xs font-medium text-slate-600">每日上限</span>
                        <Input
                          value={dailyLimit}
                          onChange={(event) => setDailyLimit(event.target.value)}
                          placeholder={`默认 ${effectiveDailyLimit || 0}`}
                        />
                      </label>
                      <label className="space-y-1">
                        <span className="text-xs font-medium text-slate-600">本次上限</span>
                        <Input
                          value={sendLimit}
                          onChange={(event) => setSendLimit(event.target.value)}
                          placeholder={`默认 ${effectiveSendLimit || 0}`}
                        />
                      </label>
                      <label className="space-y-1">
                        <span className="text-xs font-medium text-slate-600">发送窗口开始</span>
                        <Input type="time" value={windowStart} onChange={(event) => setWindowStart(event.target.value)} />
                      </label>
                      <label className="space-y-1">
                        <span className="text-xs font-medium text-slate-600">发送窗口结束</span>
                        <Input type="time" value={windowEnd} onChange={(event) => setWindowEnd(event.target.value)} />
                      </label>
                      <label className="flex items-center gap-2 text-sm text-slate-700 md:col-span-2">
                        <input type="checkbox" checked={skipNight} onChange={(event) => setSkipNight(event.target.checked)} />
                        跳过夜间，按发送窗口执行
                      </label>
                    </div>
                  ) : null}
                </div>
              </CardContent>
            </Card>

            <Card className="campaign-step-card">
              <CardHeader className="campaign-step-card-header">
                <StepHeader step="4" title="确认并发送" desc="这里显示前 5 封邮件样例、跳过原因和最终发送结果。" />
              </CardHeader>
              <CardContent className="campaign-step-content">
                {previewItems.length > 0 ? (
                  <div className="space-y-3">
                    <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm">
                      <span className="text-slate-600">
                        已批准 {approvedDraftCount} 封。高价值红人必须打开草稿详情确认后才能批准。
                      </span>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => void bulkApproveCurrentPreview()}
                        disabled={busyAction !== null}
                      >
                        批量批准普通草稿
                      </Button>
                    </div>
                    {previewItems.map((item) => (
                      <div key={item.influencer_id} className="campaign-preview-item">
                        <div className="flex flex-wrap items-start justify-between gap-2">
                          <div>
                            <div className="text-sm font-semibold text-slate-900">
                              {item.display_name || item.username}
                              <span className="ml-2 text-xs font-normal text-slate-500">{item.recipient || "无邮箱"}</span>
                            </div>
                            <div className="mt-1 text-sm text-slate-700">{item.subject || "未生成标题"}</div>
                          </div>
                          <div className="flex flex-wrap gap-2">
                            {item.is_high_value ? <Badge variant="warning">高价值</Badge> : null}
                            <Badge variant={item.draft_status === "approved" ? "success" : item.can_queue ? "secondary" : "warning"}>
                              {getOutreachDraftStatusLabel(item.draft_status)}
                            </Badge>
                          </div>
                        </div>
                        <p className="mt-2 line-clamp-3 whitespace-pre-wrap text-sm leading-6 text-slate-600">
                          {item.body || humanizeOutreachFailureReason(item.skip_reason || item.reason)}
                        </p>
                        {!item.can_queue ? (
                          <p className="mt-2 text-xs text-amber-700">
                            跳过原因：{humanizeOutreachFailureReason(item.skip_reason || item.reason)}
                          </p>
                        ) : null}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="campaign-empty-preview">
                    {copyMode === "ai"
                      ? "点击生成话术并检查后，这里会显示前 5 封邮件样例。"
                      : "点击立即发送或定时发送前，系统会自动检查收件人并生成预览。"}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          <aside className="campaign-summary-column xl:sticky xl:top-4 xl:self-start">
            <Card className="campaign-summary-card">
              <CardHeader className="campaign-summary-header">
                <div className="flex items-center gap-2">
                  <Settings className="h-4 w-4 text-slate-500" />
                  <CardTitle className="text-[15px]">发送摘要</CardTitle>
                </div>
              </CardHeader>
              <CardContent className="campaign-summary-content space-y-4">
                <div className="grid grid-cols-2 gap-2 text-sm">
                  <div className="campaign-summary-stat">
                    <div className="text-xs text-slate-500">收件人数量</div>
                    <div className="mt-1 text-xl font-semibold">{sendCount}</div>
                  </div>
                  <div className="campaign-summary-stat">
                    <div className="text-xs text-slate-500">跳过人数</div>
                    <div className="mt-1 text-xl font-semibold">{preview?.skip_count ?? 0}</div>
                  </div>
                </div>

                <div className="campaign-summary-list space-y-2 text-sm">
                  <div className="flex justify-between gap-3">
                    <span className="text-slate-500">内容来源</span>
                    <span className="font-medium">{getOneClickContentSourceLabel(copyMode)}</span>
                  </div>
                  <div className="flex justify-between gap-3">
                    <span className="text-slate-500">发送方式</span>
                    <span className="font-medium">{sendModeLabel(sendMode)}</span>
                  </div>
                  <div className="flex justify-between gap-3">
                    <span className="text-slate-500">定时时间</span>
                    <span className="font-medium">{sendMode === "now" ? "立即开始" : formatOneClickDateTime(scheduledAt)}</span>
                  </div>
                  <div className="flex justify-between gap-3">
                    <span className="text-slate-500">SMTP 状态</span>
                    <span className="font-medium">{smtpStatusText}</span>
                  </div>
                  <div className="flex justify-between gap-3">
                    <span className="text-slate-500">预计发送数量</span>
                    <span className="font-medium">{sendCount} 封</span>
                  </div>
                  <div className="flex justify-between gap-3">
                    <span className="text-slate-500">预计完成</span>
                    <span className="font-medium">{formatOneClickDateTime(estimatedEndAt)}</span>
                  </div>
                  <div className="flex justify-between gap-3">
                    <span className="text-slate-500">当前状态</span>
                    <Badge variant={currentStatusBadgeVariant}>
                      {currentStatusLabel}
                    </Badge>
                  </div>
                </div>

                <div className="campaign-skip-box text-sm">
                  <div className="mb-2 font-medium text-slate-900">跳过原因</div>
                  <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-slate-600">
                    <span>已发送：{skipBreakdown.sent}</span>
                    <span>黑名单：{skipBreakdown.blacklisted}</span>
                    <span>无效邮箱：{skipBreakdown.invalid}</span>
                    <span>已回复：{skipBreakdown.replied}</span>
                  </div>
                </div>

                {primaryDisabledReason ? (
                  <div className="campaign-inline-warning flex gap-2 text-sm">
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                    {primaryDisabledReason}
                  </div>
                ) : null}
                {lastFailureReason ? (
                  <div className="campaign-inline-error flex gap-2 text-sm">
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                    {lastFailureReason}
                  </div>
                ) : null}
                {scheduledCompletionMessage ? (
                  <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm font-medium text-emerald-800">
                    {scheduledCompletionMessage}
                  </div>
                ) : null}

                <div className="campaign-action-stack grid gap-2">
                  <div className="campaign-secondary-actions">
                    <Button variant="ghost" onClick={() => void runReviewedAction("save")} disabled={Boolean(saveDisabledReason) || busyAction !== null}>
                      保存草稿
                    </Button>
                    <Button
                      variant="outline"
                      onClick={() => {
                        setSendMode("scheduled");
                        void runReviewedAction("queue");
                      }}
                      disabled={Boolean(scheduleDisabledReason) || busyAction !== null}
                    >
                      {busyAction === "queue" ? <Loader2 className="h-4 w-4 animate-spin" /> : <CalendarClock className="h-4 w-4" />}
                      定时发送
                    </Button>
                  </div>
                  <Button
                    onClick={() => {
                      if (primaryAction.action === "send") setSendMode("now");
                      void runReviewedAction(primaryAction.action);
                    }}
                    disabled={Boolean(primaryDisabledReason) || busyAction !== null}
                  >
                    {busyAction === primaryAction.action ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      (() => {
                        const Icon = primaryIcon(primaryAction.action);
                        return <Icon className="h-4 w-4" />;
                      })()
                    )}
                    {primaryActionLabel}
                  </Button>
                  <Button variant="outline" asChild>
                    <Link href="/outreach-send-queue">发送队列（高级管理）</Link>
                  </Button>
                </div>
              </CardContent>
            </Card>
          </aside>
        </div>
      </div>
    </AdminShell>
  );
}
