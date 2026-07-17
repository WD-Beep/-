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
  Trash2,
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
  createMessageTemplate,
  deleteMessageTemplate,
  fetchOutreachWorkbench,
  fetchMessageTemplates,
  approveOutreachCampaignDraft,
  openOutreachCampaignDraft,
  previewOutreachCampaign,
  queueOutreachCampaign,
  regenerateOutreachCampaignDraft,
  scheduleOutreachSendQueue,
  sendOutreachCampaignNow,
  sendManualOutreachEmail,
  skipOutreachCampaignDraft,
  updateOutreachCampaignDraft,
  updateMessageTemplate,
  type MessageTemplate,
  type MessageTemplatePayload,
  type ManualOutreachSendMode,
  type OutreachCampaignCreatePayload,
  type OutreachCampaignPreviewItem,
  type OutreachCampaignPreviewResponse,
  type OutreachOneClickWorkbench,
} from "@/lib/api";
import { decodeFiltersFromSearchParams } from "@/lib/influencer-selection-helpers";
import { notifyInfluencerEmailSent } from "@/lib/influencer-email-sync";
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
  countQueueablePreviewItems,
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
type DraftFilter = "all" | "needs_review" | "edited" | "failed" | "sent";
type TemplateDraft = {
  title: string;
  content: string;
  note: string;
  language: string;
  tone: string;
  minLength: string;
  maxLength: string;
  bodyStructure: string;
  requiredContent: string;
  forbiddenContent: string;
  cta: string;
  isDefault: boolean;
};

const TIMEZONE = "Asia/Shanghai";
const DRAFT_PAGE_SIZE = 10;
const TEMPLATE_RECOMMENDED_MIN_LENGTH = 800;
const TEMPLATE_NOTE_MAX_LENGTH = 500;
const MANUAL_EMAIL_PRESET_SCENARIO = "outreach_manual_preset";
const MANUAL_EMAIL_PRESET_TAG = "manual-email-preset";
const DRAFT_FILTER_LABELS: Record<DraftFilter, string> = {
  all: "全部",
  needs_review: "待审核",
  edited: "已修改",
  failed: "失败",
  sent: "已发送",
};
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

function formatDraftPreviewText(value: string): string {
  return value
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n")
    .replace(/[ \t]+/g, " ")
    .replace(/([,;:])(?=\S)/g, "$1 ")
    .replace(/([.!?])(?=[A-Z][a-z])/g, "$1 ")
    .replace(/\s*(👉\s*Product Link:\s*)/gi, "\n\n$1")
    .replace(/\s*(Product Link:\s*)/gi, "\n\n$1")
    .replace(/([^\s])\s*(Looking forward\b)/gi, "$1\n\n$2")
    .trim();
}

function countTemplateCharacters(value: string): number {
  return Array.from(value).length;
}

function emptyTemplateDraft(): TemplateDraft {
  return {
    title: "",
    content: "",
    note: "",
    language: "",
    tone: "natural",
    minLength: "180",
    maxLength: "300",
    bodyStructure: "greeting → creator fit → product value → collaboration idea → soft CTA → signature",
    requiredContent: "",
    forbiddenContent: "",
    cta: "Would you be open to reviewing the details?",
    isDefault: false,
  };
}

function templateToDraft(template: MessageTemplate): TemplateDraft {
  return {
    title: template.title,
    content: template.content,
    note: template.note ?? "",
    language: template.generation_rules.language ?? template.language ?? "",
    tone: template.generation_rules.tone ?? "natural",
    minLength: String(template.generation_rules.min_length ?? 180),
    maxLength: String(template.generation_rules.max_length ?? 300),
    bodyStructure: template.generation_rules.body_structure ?? "",
    requiredContent: (template.generation_rules.required_content ?? []).join("\n"),
    forbiddenContent: (template.generation_rules.forbidden_content ?? []).join("\n"),
    cta: template.generation_rules.cta ?? "",
    isDefault: template.is_default,
  };
}

function splitTemplateRuleLines(value: string): string[] {
  return value
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function buildTemplatePayload(draft: TemplateDraft): MessageTemplatePayload {
  return {
    title: draft.title.trim(),
    scenario: "first_contact",
    platform: null,
    language: draft.language || null,
    tags: ["ai", "outreach"],
    content: draft.content.trim(),
    note: draft.note.trim() || null,
    generation_rules: {
      tone: draft.tone || null,
      language: draft.language || null,
      min_length: Number(draft.minLength) || null,
      max_length: Number(draft.maxLength) || null,
      body_structure: draft.bodyStructure.trim() || null,
      required_content: splitTemplateRuleLines(draft.requiredContent),
      forbidden_content: splitTemplateRuleLines(draft.forbiddenContent),
      cta: draft.cta.trim() || null,
    },
    is_default: draft.isDefault,
    source_filename: null,
  };
}

function parseManualEmailPreset(template: MessageTemplate): { subject: string; body: string } | null {
  try {
    const parsed = JSON.parse(template.content) as { subject?: unknown; body?: unknown };
    const subject = typeof parsed.subject === "string" ? parsed.subject : "";
    const body = typeof parsed.body === "string" ? parsed.body : "";
    if (!subject.trim() || !body.trim()) return null;
    return { subject, body };
  } catch {
    return null;
  }
}

function buildManualEmailPresetPayload(input: { subject: string; body: string }): MessageTemplatePayload {
  const subject = input.subject.trim();
  const body = input.body.trim();
  const title = subject.length > 60 ? `${subject.slice(0, 60)}...` : subject;
  return {
    title: title || "常用邮箱方案",
    scenario: MANUAL_EMAIL_PRESET_SCENARIO,
    platform: null,
    language: null,
    tags: [MANUAL_EMAIL_PRESET_TAG, "outreach"],
    content: JSON.stringify({ subject, body }),
    note: "批量发邮件页面保存的常用邮箱方案；不包含收件人。",
    generation_rules: {},
    is_default: false,
    source_filename: null,
  };
}

function validateTemplateDraft(draft: TemplateDraft): string | null {
  if (!draft.title.trim()) return "请填写模板名称";
  if (!draft.content.trim()) return "请粘贴话术模板正文";
  if (countTemplateCharacters(draft.note) > TEMPLATE_NOTE_MAX_LENGTH) {
    return `模板备注不能超过 ${TEMPLATE_NOTE_MAX_LENGTH} 字`;
  }
  if (Number(draft.minLength) > Number(draft.maxLength)) return "最短长度不能大于最长长度";
  return null;
}

function DraftBodyPreview({ value, compact = false }: { value: string; compact?: boolean }) {
  const formatted = formatDraftPreviewText(value);
  if (compact) {
    return <p className="campaign-email-body campaign-email-body-compact mt-2 text-sm leading-6 text-slate-600">{formatted}</p>;
  }
  const paragraphs = formatted.split(/\n{2,}/).filter(Boolean);
  return (
    <div className="campaign-email-body space-y-3 text-sm leading-6 text-slate-700">
      {paragraphs.length > 0 ? paragraphs.map((paragraph, index) => (
        <p key={`${index}-${paragraph.slice(0, 12)}`}>{paragraph}</p>
      )) : <p>{formatted}</p>}
    </div>
  );
}

function isCrossProductSelectionError(message: string): boolean {
  return /不存在或不属于当前产品|does not belong to current product/i.test(message);
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
  const sourceProductId = useMemo(() => {
    const raw = searchParams.get("product_id");
    const value = raw ? Number(raw) : null;
    return value && Number.isFinite(value) && value > 0 ? value : null;
  }, [searchParams]);
  const selectionMatchesCurrentProduct = !sourceProductId || sourceProductId === productId;
  const activePrefillIds = selectionMatchesCurrentProduct ? prefillIds : [];

  const [workbench, setWorkbench] = useState<OutreachOneClickWorkbench | null>(null);
  const [templates, setTemplates] = useState<MessageTemplate[]>([]);
  const [preview, setPreview] = useState<OutreachCampaignPreviewResponse | null>(null);
  const [previewCampaignId, setPreviewCampaignId] = useState<number | null>(null);
  const [draftFilter, setDraftFilter] = useState<DraftFilter>("all");
  const [draftPage, setDraftPage] = useState(1);
  const [expandedDraftIds, setExpandedDraftIds] = useState<Set<number>>(() => new Set());
  const [editingDraftId, setEditingDraftId] = useState<number | null>(null);
  const [draftEdits, setDraftEdits] = useState<Record<number, { subject: string; body: string }>>({});
  const [draftActionId, setDraftActionId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyAction, setBusyAction] = useState<ActionKind | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const [sourceMode, setSourceMode] = useState<SourceMode>(
    selectAllByFilters || activePrefillIds.length === 0 ? "filters" : "selected",
  );
  const [sendMode, setSendMode] = useState<SendMode>("scheduled");
  const [copyMode, setCopyMode] = useState<CopyMode>("manual");
  const [manualSubject, setManualSubject] = useState("");
  const [manualBody, setManualBody] = useState("");
  const [manualEmailPresets, setManualEmailPresets] = useState<MessageTemplate[]>([]);
  const [selectedManualPresetId, setSelectedManualPresetId] = useState<number | null>(null);
  const [manualPresetBusy, setManualPresetBusy] = useState(false);
  const [selectedTemplateId, setSelectedTemplateId] = useState<number | null>(null);
  const [templateDraft, setTemplateDraft] = useState<TemplateDraft>(() => emptyTemplateDraft());
  const [templateBusy, setTemplateBusy] = useState(false);
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
  const selectedCount = activePrefillIds.length;
  const filterCount = filterAllTotal || workbench?.available_recipient_count || 0;
  const canUseFilters = Boolean(filterSnapshot || filterCount > 0);
  const canUseSelected = selectedCount > 0;
  const aiReady = workbench?.ai_generation.status === "normal";
  const aiNotConfigured = workbench?.ai_generation.status === "not_configured";
  const smtpReady = workbench?.smtp.status === "normal";
  const workbenchStatusTone = (status: string | undefined) =>
    statusVariant(loading || !workbench ? "checking" : status ?? "checking");
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
  const queueableDraftCount = preview ? countQueueablePreviewItems(preview.items) : 0;
  const sendCount = preview
    ? queueableDraftCount
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
  const templateContentLength = countTemplateCharacters(templateDraft.content);
  const templateNoteLength = countTemplateCharacters(templateDraft.note);
  const templateLengthHint =
    templateContentLength > 0 && templateContentLength < TEMPLATE_RECOMMENDED_MIN_LENGTH
      ? `建议不少于 800 字，当前 ${templateContentLength} 字。系统不限制保存，但较短模板可能导致 AI 生成内容偏短。`
      : `当前 ${templateContentLength} 字，建议不少于 800 字。`;
  const latestCampaignHasSendResult = Boolean(
    workbench?.latest_campaign &&
      ((workbench.latest_campaign.sent_count ?? 0) > 0 || (workbench.latest_campaign.failed_count ?? 0) > 0),
  );
  const effectiveQueueStatus =
    preview && preview.can_queue_count > 0 && queueStatus === "completed" && !latestCampaignHasSendResult
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

  const loadTemplates = useCallback(async (preferredId?: number | null) => {
    if (requiresProduct) {
      setTemplates([]);
      setSelectedTemplateId(null);
      setTemplateDraft(emptyTemplateDraft());
      return;
    }
    const data = await fetchMessageTemplates({ pageSize: 100, scenario: "first_contact" });
    setTemplates(data.items);
    const nextId =
      preferredId && data.items.some((item) => item.id === preferredId)
        ? preferredId
        : data.items.find((item) => item.is_default)?.id ?? data.items[0]?.id ?? null;
    const nextTemplate = data.items.find((item) => item.id === nextId) ?? null;
    setSelectedTemplateId(nextTemplate?.id ?? null);
    setTemplateDraft(nextTemplate ? templateToDraft(nextTemplate) : emptyTemplateDraft());
  }, [requiresProduct]);

  useEffect(() => {
    let cancelled = false;
    queueMicrotask(() => {
      if (cancelled) return;
      void loadTemplates().catch(() => {
        if (!cancelled) setTemplates([]);
      });
    });
    return () => {
      cancelled = true;
    };
  }, [loadTemplates]);

  const loadManualEmailPresets = useCallback(async (preferredId?: number | null) => {
    if (requiresProduct) {
      setManualEmailPresets([]);
      setSelectedManualPresetId(null);
      return;
    }
    const data = await fetchMessageTemplates({ pageSize: 10, scenario: MANUAL_EMAIL_PRESET_SCENARIO });
    const validPresets = data.items.filter((item) => parseManualEmailPreset(item));
    setManualEmailPresets(validPresets);
    const nextId =
      preferredId && validPresets.some((item) => item.id === preferredId)
        ? preferredId
        : validPresets[0]?.id ?? null;
    setSelectedManualPresetId(nextId);
  }, [requiresProduct]);

  useEffect(() => {
    let cancelled = false;
    queueMicrotask(() => {
      if (cancelled) return;
      void loadManualEmailPresets().catch(() => {
        if (!cancelled) setManualEmailPresets([]);
      });
    });
    return () => {
      cancelled = true;
    };
  }, [loadManualEmailPresets]);

  function applyManualEmailPreset(id: number | null = selectedManualPresetId) {
    if (!id) return;
    const preset = manualEmailPresets.find((item) => item.id === id) ?? null;
    const content = preset ? parseManualEmailPreset(preset) : null;
    if (!preset || !content) {
      setError("常用邮箱方案内容无效，请重新保存。");
      return;
    }
    setSelectedManualPresetId(preset.id);
    setManualSubject(content.subject);
    setManualBody(content.body);
    setCopyMode("manual");
    clearPreview();
  }

  async function persistManualEmailPreset(options: { silent?: boolean } = {}) {
    const subject = manualSubject.trim();
    const body = manualBody.trim();
    if (!subject || !body) {
      if (!options.silent) setError("请先填写邮件主题和正文，再保存常用邮箱方案。");
      return null;
    }
    const alreadyExists = manualEmailPresets.some((preset) => {
      const content = parseManualEmailPreset(preset);
      return content?.subject.trim() === subject && content.body.trim() === body;
    });
    if (alreadyExists) return null;

    const saved = await createMessageTemplate(buildManualEmailPresetPayload({ subject, body }));
    await loadManualEmailPresets(saved.id);
    if (!options.silent) setMessage("常用邮箱方案已保存；只保存主题和正文，不保存收件人。");
    return saved;
  }

  async function saveManualEmailPreset() {
    setManualPresetBusy(true);
    setError(null);
    try {
      await persistManualEmailPreset({ silent: false });
    } catch (err) {
      setError(translateErrorMessage(err instanceof Error ? err.message : "保存常用邮箱方案失败"));
    } finally {
      setManualPresetBusy(false);
    }
  }

  async function deleteManualEmailPreset() {
    if (!selectedManualPresetId) return;
    const preset = manualEmailPresets.find((item) => item.id === selectedManualPresetId) ?? null;
    if (!preset) return;
    if (!window.confirm(`确认删除常用邮箱方案「${preset.title}」？已生成或已发送的邮件记录不会删除。`)) return;
    setManualPresetBusy(true);
    setError(null);
    try {
      await deleteMessageTemplate(preset.id);
      await loadManualEmailPresets(null);
      setMessage("常用邮箱方案已删除，不影响历史邮件。");
    } catch (err) {
      setError(translateErrorMessage(err instanceof Error ? err.message : "删除常用邮箱方案失败"));
    } finally {
      setManualPresetBusy(false);
    }
  }

  function handleSelectTemplate(value: string) {
    const nextId = Number(value) || null;
    const nextTemplate = templates.find((template) => template.id === nextId) ?? null;
    setSelectedTemplateId(nextTemplate?.id ?? null);
    setTemplateDraft(nextTemplate ? templateToDraft(nextTemplate) : emptyTemplateDraft());
    clearPreview();
  }

  function handleNewTemplateDraft() {
    setSelectedTemplateId(null);
    setTemplateDraft(emptyTemplateDraft());
    clearPreview();
  }

  async function handleSaveTemplateAsNew() {
    const validationError = validateTemplateDraft(templateDraft);
    if (validationError) {
      setError(validationError);
      return;
    }
    setTemplateBusy(true);
    setError(null);
    try {
      const saved = await createMessageTemplate(buildTemplatePayload(templateDraft));
      await loadTemplates(saved.id);
      setMessage("AI 话术模板已保存为新模板。");
      clearPreview();
    } catch (err) {
      setError(translateErrorMessage(err instanceof Error ? err.message : "保存模板失败"));
    } finally {
      setTemplateBusy(false);
    }
  }

  async function handleUpdateCurrentTemplate() {
    if (!selectedTemplate) return;
    const validationError = validateTemplateDraft(templateDraft);
    if (validationError) {
      setError(validationError);
      return;
    }
    setTemplateBusy(true);
    setError(null);
    try {
      const saved = await updateMessageTemplate(selectedTemplate.id, buildTemplatePayload(templateDraft));
      await loadTemplates(saved.id);
      setMessage("AI 话术模板已更新。");
      clearPreview();
    } catch (err) {
      setError(translateErrorMessage(err instanceof Error ? err.message : "更新模板失败"));
    } finally {
      setTemplateBusy(false);
    }
  }

  function handleClearTemplateNote() {
    setTemplateDraft((current) => ({ ...current, note: "" }));
  }

  async function handleSetDefaultTemplate() {
    if (!selectedTemplate) return;
    setTemplateBusy(true);
    try {
      const saved = await updateMessageTemplate(selectedTemplate.id, { is_default: true });
      await loadTemplates(saved.id);
      setMessage("已设为当前品牌默认 AI 模板。" );
    } finally {
      setTemplateBusy(false);
    }
  }

  async function handleDeleteTemplate() {
    if (!selectedTemplate || selectedTemplate.is_system_default) return;
    if (!window.confirm(`确认删除模板「${selectedTemplate.title}」？`)) return;
    setTemplateBusy(true);
    try {
      await deleteMessageTemplate(selectedTemplate.id);
      setSelectedTemplateId(null);
      await loadTemplates(null);
      setMessage("AI 话术模板已删除。" );
      clearPreview();
    } finally {
      setTemplateBusy(false);
    }
  }

  const resetDraftReviewState = useCallback(() => {
    setDraftFilter("all");
    setDraftPage(1);
    setExpandedDraftIds(new Set());
    setEditingDraftId(null);
    setDraftEdits({});
    setDraftActionId(null);
  }, []);

  const replacePreviewItem = useCallback((item: OutreachCampaignPreviewItem) => {
    setPreview((current) => {
      if (!current) return current;
      const items = current.items.map((row) =>
        row.influencer_id === item.influencer_id ? item : row,
      );
      return {
        ...current,
        items,
        can_queue_count: items.filter((row) => row.can_queue).length,
        skip_count: items.filter((row) => !row.can_queue).length,
      };
    });
  }, []);

  const clearPreview = useCallback(() => {
    setPreview(null);
    setPreviewCampaignId(null);
    setQueueStatus("not_queued");
    setLastFailureReason(null);
    resetDraftReviewState();
  }, [resetDraftReviewState]);

  function chooseSource(next: SourceMode) {
    setSourceMode(next);
    clearPreview();
  }

  useEffect(() => {
    if (!selectionMatchesCurrentProduct && sourceMode === "selected") {
      queueMicrotask(() => {
        setSourceMode("filters");
        clearPreview();
        setMessage("已切换到当前品牌的可发送邮箱；上一个品牌选中的红人不会用于本次发送。");
      });
    }
  }, [clearPreview, selectionMatchesCurrentProduct, sourceMode]);

  function buildSourcePayload() {
    return buildOutreachCampaignPayload({
      name: buildOneClickCampaignName(),
      influencerIds: sourceMode === "selected" ? activePrefillIds : undefined,
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
      messageTemplateId: copyMode === "template" || copyMode === "ai" ? selectedTemplateId : undefined,
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
    const queueableIds = input.preview.items
      .filter((item) => item.can_queue)
      .map((item) => item.influencer_id);
    if (queueableIds.length === 0) {
      throw new Error("没有可发送邮件。请先生成 AI 话术并检查跳过原因。");
    }
    return queueOutreachCampaign(input.campaignId, {
      confirm: true,
      influencer_ids: queueableIds,
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
    if (copyMode === "ai" && (action === "send" || action === "queue" || action === "preview" || action === "save")) {
      if (!selectedTemplateId) return "请先选择或创建 AI 话术模板";
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
      smtpStatus: workbench?.smtp.status,
      aiReady: Boolean(aiReady),
      configLoading: loading || !workbench,
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
        setMessage(buildImmediateSendStartedMessage());
        const processed = await sendOutreachCampaignNow(generated.campaignId, {
          confirm: true,
          influencer_ids: generated.preview.items
            .filter((item) => item.can_queue)
            .map((item) => item.influencer_id),
        });
        const skipped = generated.preview.skip_count + processed.skipped;
        setQueueStatus(processed.failed > 0 && processed.sent === 0 ? "failed" : "completed");
        const resultMessage = buildImmediateSendResultMessage({
          sent: processed.sent,
          failed: processed.failed,
          skipped,
          reason: processed.message,
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
      if ((action === "send" || action === "queue" || action === "save") && copyMode === "manual") {
        void persistManualEmailPreset({ silent: true }).catch(() => undefined);
      }
      await load({ syncLatestCampaign: true });
    } catch (err) {
      const nextError = translateErrorMessage(err instanceof Error ? err.message : "操作失败");
      if (sourceMode === "selected" && isCrossProductSelectionError(nextError)) {
        setSourceMode("filters");
        clearPreview();
        setMessage("已切换到当前品牌的可发送邮箱；上一个品牌选中的红人不会用于本次发送。");
        setError(null);
        return;
      }
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
    const confirmMessage =
      action === "send"
        ? `确认立即发送给 ${sendCount} 位收件人？点击确认后邮件会马上发出。`
        : buildApprovedDraftSendConfirmMessage(sendCount);
    if ((action === "send" || action === "queue") && !window.confirm(confirmMessage)) {
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
        setMessage("AI 话术已保存，邮件尚未发出。确认发送时间后可直接发送。");
      } else {
        const queueableCount = countQueueablePreviewItems(actionPreview.items);
        if (queueableCount <= 0) {
          setQueueStatus("failed");
          throw new Error("没有可发送邮件。请先生成 AI 话术并检查跳过原因。");
        }
        if (action === "send") {
          setQueueStatus("sending");
          setMessage(buildImmediateSendStartedMessage());
          const processed = await sendOutreachCampaignNow(generated.campaignId, {
            confirm: true,
            influencer_ids: actionPreview.items
              .filter((item) => item.can_queue)
              .map((item) => item.influencer_id),
          });
          const skipped = actionPreview.skip_count + processed.skipped;
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
            if (processed.sent > 0) notifyInfluencerEmailSent();
            setMessage(resultMessage);
            if (processed.failed > 0) setLastFailureReason(resultMessage);
          }
        } else {
          const queued = await queuePreviewItems({
            campaignId: generated.campaignId,
            preview: actionPreview,
            startAt: buildLocalDateTime(scheduledDate, scheduledTime) ?? new Date(),
          });
          setQueueStatus("waiting");
          setMessage(`已将 ${queued.queued} 封 AI 生成邮件加入发送队列，跳过 ${queued.skipped} 封。`);
        }
      }
      await load({ syncLatestCampaign: true });
    } catch (err) {
      const nextError = translateErrorMessage(err instanceof Error ? err.message : "操作失败");
      if (sourceMode === "selected" && isCrossProductSelectionError(nextError)) {
        setSourceMode("filters");
        clearPreview();
        setMessage("已切换到当前品牌的可发送邮箱；上一个品牌选中的红人不会用于本次发送。");
        setError(null);
        return;
      }
      setQueueStatus("failed");
      setLastFailureReason(nextError);
      setError(nextError);
    } finally {
      setBusyAction(null);
    }
  }

  void runAction;

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

  const draftFilterCounts = useMemo(() => {
    const items = preview?.items ?? [];
    return {
      all: items.length,
      needs_review: items.filter((item) => item.draft_status === "pending_review").length,
      edited: items.filter((item) => item.draft_status === "modified").length,
      failed: items.filter((item) => !item.can_queue || item.draft_status === "failed" || item.draft_status === "skipped").length,
      sent: items.filter((item) => item.draft_status === "sent").length,
    };
  }, [preview]);

  const filteredPreviewItems = useMemo(() => {
    const items = preview?.items ?? [];
    if (draftFilter === "needs_review") return items.filter((item) => item.draft_status === "pending_review");
    if (draftFilter === "edited") return items.filter((item) => item.draft_status === "modified");
    if (draftFilter === "failed") {
      return items.filter((item) => !item.can_queue || item.draft_status === "failed" || item.draft_status === "skipped");
    }
    if (draftFilter === "sent") return items.filter((item) => item.draft_status === "sent");
    return items;
  }, [draftFilter, preview]);

  const draftPageCount = Math.max(1, Math.ceil(filteredPreviewItems.length / DRAFT_PAGE_SIZE));
  const safeDraftPage = Math.min(draftPage, draftPageCount);
  const paginatedPreviewItems = useMemo(() => {
    const offset = (safeDraftPage - 1) * DRAFT_PAGE_SIZE;
    return filteredPreviewItems.slice(offset, offset + DRAFT_PAGE_SIZE);
  }, [filteredPreviewItems, safeDraftPage]);
  const draftPageStart = filteredPreviewItems.length === 0 ? 0 : (safeDraftPage - 1) * DRAFT_PAGE_SIZE + 1;
  const draftPageEnd = Math.min(filteredPreviewItems.length, safeDraftPage * DRAFT_PAGE_SIZE);

  function setDraftFilterAndResetPage(next: DraftFilter) {
    setDraftFilter(next);
    setDraftPage(1);
  }

  function toggleDraftExpanded(influencerId: number) {
    setExpandedDraftIds((current) => {
      const next = new Set(current);
      if (next.has(influencerId)) {
        next.delete(influencerId);
      } else {
        next.add(influencerId);
      }
      return next;
    });
  }

  function updateDraftEditField(influencerId: number, field: "subject" | "body", value: string) {
    setDraftEdits((current) => ({
      ...current,
      [influencerId]: {
        subject: current[influencerId]?.subject ?? "",
        body: current[influencerId]?.body ?? "",
        [field]: value,
      },
    }));
  }

  function startDraftEdit(item: OutreachCampaignPreviewItem) {
    setEditingDraftId(item.influencer_id);
    setDraftEdits((current) => ({
      ...current,
      [item.influencer_id]: {
        subject: item.subject ?? "",
        body: item.body ?? "",
      },
    }));
    setExpandedDraftIds((current) => new Set(current).add(item.influencer_id));
  }

  function cancelDraftEdit(influencerId: number) {
    setEditingDraftId(null);
    setDraftEdits((current) => {
      const next = { ...current };
      delete next[influencerId];
      return next;
    });
  }

  async function saveDraftEdit(item: OutreachCampaignPreviewItem) {
    if (!previewCampaignId) return;
    const edit = draftEdits[item.influencer_id];
    if (!edit) return;
    setDraftActionId(item.influencer_id);
    setError(null);
    try {
      const updated = await updateOutreachCampaignDraft(previewCampaignId, item.influencer_id, {
        subject: edit.subject,
        body: edit.body,
      });
      replacePreviewItem(updated);
      setEditingDraftId(null);
      setDraftEdits((current) => {
        const next = { ...current };
        delete next[item.influencer_id];
        return next;
      });
      setMessage("已保存当前收件人的邮件修改，发送时会使用修改后的内容。");
    } catch (err) {
      setError(translateErrorMessage(err instanceof Error ? err.message : "保存邮件草稿失败"));
    } finally {
      setDraftActionId(null);
    }
  }

  async function regenerateDraft(item: OutreachCampaignPreviewItem) {
    if (!previewCampaignId) return;
    if (item.draft_status === "modified" && !window.confirm("重新生成会覆盖这封邮件的人工修改，确认继续？")) {
      return;
    }
    setDraftActionId(item.influencer_id);
    setError(null);
    try {
      const regenerated = await regenerateOutreachCampaignDraft(previewCampaignId, item.influencer_id);
      replacePreviewItem(regenerated);
      setEditingDraftId(null);
      setDraftEdits((current) => {
        const next = { ...current };
        delete next[item.influencer_id];
        return next;
      });
      setMessage("已重新生成当前收件人的 AI 邮件。");
    } catch (err) {
      setError(translateErrorMessage(err instanceof Error ? err.message : "重新生成 AI 邮件失败"));
    } finally {
      setDraftActionId(null);
    }
  }

  async function approveDraft(item: OutreachCampaignPreviewItem) {
    if (!previewCampaignId) return;
    setDraftActionId(item.influencer_id);
    setError(null);
    try {
      const opened = item.opened_at
        ? item
        : await openOutreachCampaignDraft(previewCampaignId, item.influencer_id);
      const approved = await approveOutreachCampaignDraft(previewCampaignId, opened.influencer_id);
      replacePreviewItem(approved);
      setMessage("已标记当前邮件为已审核。");
    } catch (err) {
      setError(translateErrorMessage(err instanceof Error ? err.message : "审核邮件草稿失败"));
    } finally {
      setDraftActionId(null);
    }
  }

  async function skipDraft(item: OutreachCampaignPreviewItem) {
    if (!previewCampaignId) return;
    if (!window.confirm("确认跳过这封邮件？跳过后本次发送不会发给该收件人。")) {
      return;
    }
    setDraftActionId(item.influencer_id);
    setError(null);
    try {
      const skipped = await skipOutreachCampaignDraft(previewCampaignId, item.influencer_id);
      replacePreviewItem(skipped);
      setMessage("已跳过当前收件人。");
    } catch (err) {
      setError(translateErrorMessage(err instanceof Error ? err.message : "跳过邮件草稿失败"));
    } finally {
      setDraftActionId(null);
    }
  }

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
        sendMode,
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
      <div className="campaign-page">
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
                status={workbenchStatusTone(workbench?.ai_generation.status)}
              />
              <MetricPill
                label="SMTP"
                value={smtpStatusText}
                status={workbenchStatusTone(workbench?.smtp.status)}
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
                    <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                      <div className="flex flex-col gap-3 lg:flex-row lg:items-end">
                        <label className="min-w-0 flex-1 space-y-1">
                          <span className="text-xs font-medium text-slate-600">常用邮箱方案</span>
                          <select
                            className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                            value={selectedManualPresetId ?? ""}
                            onChange={(event) => setSelectedManualPresetId(Number(event.target.value) || null)}
                          >
                            <option value="">选择已保存的主题和正文</option>
                            {manualEmailPresets.map((preset) => (
                              <option key={preset.id} value={preset.id}>
                                {preset.title}
                              </option>
                            ))}
                          </select>
                        </label>
                        <div className="flex flex-wrap gap-2">
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            disabled={!selectedManualPresetId || manualPresetBusy}
                            onClick={() => applyManualEmailPreset()}
                          >
                            套用
                          </Button>
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            disabled={manualPresetBusy || !manualSubject.trim() || !manualBody.trim()}
                            onClick={() => void saveManualEmailPreset()}
                          >
                            保存为常用方案
                          </Button>
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            disabled={!selectedManualPresetId || manualPresetBusy}
                            onClick={() => void deleteManualEmailPreset()}
                          >
                            删除方案
                          </Button>
                        </div>
                      </div>
                      <p className="mt-2 text-xs text-slate-500">
                        只保存邮件主题和正文，不保存本次勾选的红人或收件人；下次可直接套用后再发送。
                      </p>
                    </div>
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
                {copyMode === "ai" ? (
                  <div className="campaign-manual-copy space-y-3">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div>
                        <div className="text-sm font-semibold text-slate-900">AI 话术模板</div>
                        <p className="text-xs text-slate-500">直接粘贴话术模板，AI 会结合每位红人资料按模板结构生成不同邮件。</p>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <Button type="button" size="sm" variant="outline" onClick={handleNewTemplateDraft} disabled={templateBusy}>
                          新建模板
                        </Button>
                        <Button type="button" size="sm" variant="outline" onClick={() => void handleSetDefaultTemplate()} disabled={!selectedTemplate || selectedTemplate.is_default || templateBusy}>
                          设为默认
                        </Button>
                        <Button type="button" size="sm" variant="outline" onClick={() => void handleDeleteTemplate()} disabled={!selectedTemplate || Boolean(selectedTemplate.is_system_default) || templateBusy}>
                          <Trash2 className="h-3.5 w-3.5" />
                          删除
                        </Button>
                      </div>
                    </div>
                    <label className="space-y-1">
                      <span className="text-xs font-medium text-slate-600">模板下拉框</span>
                      <select
                        className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                        value={selectedTemplateId ?? ""}
                        onChange={(event) => handleSelectTemplate(event.target.value)}
                      >
                        <option value="">新建模板（不覆盖旧模板）</option>
                        {templates.map((template) => (
                          <option key={template.id} value={template.id}>
                            {template.is_default ? "[默认] " : ""}{template.title}
                          </option>
                        ))}
                      </select>
                    </label>
                    <div className="grid gap-3 sm:grid-cols-2">
                      <label className="space-y-1">
                        <span className="text-xs font-medium text-slate-600">模板名称</span>
                        <Input
                          value={templateDraft.title}
                          onChange={(event) => setTemplateDraft((current) => ({ ...current, title: event.target.value }))}
                          placeholder="例如：Second Gentle Touch（副本）"
                        />
                      </label>
                      <label className="space-y-1">
                        <span className="text-xs font-medium text-slate-600">邮件语言</span>
                        <Input
                          value={templateDraft.language}
                          onChange={(event) => setTemplateDraft((current) => ({ ...current, language: event.target.value }))}
                          placeholder="例如 en / zh / auto"
                        />
                      </label>
                      <label className="space-y-1">
                        <span className="text-xs font-medium text-slate-600">语气</span>
                        <select
                          className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm"
                          value={templateDraft.tone}
                          onChange={(event) => setTemplateDraft((current) => ({ ...current, tone: event.target.value }))}
                        >
                          <option value="natural">自然</option>
                          <option value="formal">正式</option>
                          <option value="concise">简洁</option>
                          <option value="business">商务</option>
                          <option value="friendly">友好</option>
                        </select>
                      </label>
                      <div className="grid grid-cols-2 gap-2">
                        <label className="space-y-1">
                          <span className="text-xs font-medium text-slate-600">最短长度</span>
                          <Input
                            value={templateDraft.minLength}
                            onChange={(event) => setTemplateDraft((current) => ({ ...current, minLength: event.target.value }))}
                            inputMode="numeric"
                          />
                        </label>
                        <label className="space-y-1">
                          <span className="text-xs font-medium text-slate-600">最长长度</span>
                          <Input
                            value={templateDraft.maxLength}
                            onChange={(event) => setTemplateDraft((current) => ({ ...current, maxLength: event.target.value }))}
                            inputMode="numeric"
                          />
                        </label>
                      </div>
                    </div>
                    <label className="space-y-1">
                      <span className="text-xs font-medium text-slate-600">模板正文（复制粘贴，保留换行）</span>
                      <Textarea
                        value={templateDraft.content}
                        onChange={(event) => setTemplateDraft((current) => ({ ...current, content: event.target.value }))}
                        rows={10}
                        placeholder="请粘贴完整话术模板。支持变量：{红人名称}、{平台}、{粉丝数}、{品牌名称}、{合作方向}、{产品名称}、{产品卖点}、{红人主页}、{业务员名称}"
                      />
                      <span className={`text-xs ${templateContentLength < TEMPLATE_RECOMMENDED_MIN_LENGTH ? "text-amber-600" : "text-slate-500"}`}>
                        {templateLengthHint}
                      </span>
                    </label>
                    <label className="space-y-1">
                      <span className="text-xs font-medium text-slate-600">模板备注（内部说明，不直接发送给红人）</span>
                      <Textarea
                        value={templateDraft.note}
                        onChange={(event) => setTemplateDraft((current) => ({ ...current, note: event.target.value }))}
                        rows={3}
                        placeholder="记录适用场景、版本、修改原因、审核注意事项；没有备注时可留空。"
                      />
                      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
                        <span>{templateDraft.note.trim() ? `${templateNoteLength} / ${TEMPLATE_NOTE_MAX_LENGTH}` : "暂无备注"}</span>
                        <Button type="button" size="sm" variant="ghost" onClick={handleClearTemplateNote} disabled={!templateDraft.note || templateBusy}>
                          清空备注
                        </Button>
                      </div>
                    </label>
                    <label className="space-y-1">
                      <span className="text-xs font-medium text-slate-600">正文结构</span>
                      <Input
                        value={templateDraft.bodyStructure}
                        onChange={(event) => setTemplateDraft((current) => ({ ...current, bodyStructure: event.target.value }))}
                        placeholder="greeting → creator fit → product value → collaboration idea → soft CTA → signature"
                      />
                    </label>
                    <div className="grid gap-3 sm:grid-cols-2">
                      <label className="space-y-1">
                        <span className="text-xs font-medium text-slate-600">必须包含内容（每行一条）</span>
                        <Textarea
                          value={templateDraft.requiredContent}
                          onChange={(event) => setTemplateDraft((current) => ({ ...current, requiredContent: event.target.value }))}
                          rows={3}
                        />
                      </label>
                      <label className="space-y-1">
                        <span className="text-xs font-medium text-slate-600">禁止出现内容（每行一条）</span>
                        <Textarea
                          value={templateDraft.forbiddenContent}
                          onChange={(event) => setTemplateDraft((current) => ({ ...current, forbiddenContent: event.target.value }))}
                          rows={3}
                        />
                      </label>
                    </div>
                    <label className="space-y-1">
                      <span className="text-xs font-medium text-slate-600">CTA / 下一步行动</span>
                      <Input
                        value={templateDraft.cta}
                        onChange={(event) => setTemplateDraft((current) => ({ ...current, cta: event.target.value }))}
                        placeholder="Would you be open to reviewing the details?"
                      />
                    </label>
                    <label className="inline-flex items-center gap-2 text-sm text-slate-600">
                      <input
                        type="checkbox"
                        checked={templateDraft.isDefault}
                        onChange={(event) => setTemplateDraft((current) => ({ ...current, isDefault: event.target.checked }))}
                      />
                      保存后设为默认模板
                    </label>
                    <div className="flex flex-wrap gap-2">
                      <Button type="button" size="sm" onClick={() => void handleSaveTemplateAsNew()} disabled={templateBusy}>
                        保存为新模板
                      </Button>
                      <Button type="button" size="sm" variant="outline" onClick={() => void handleUpdateCurrentTemplate()} disabled={!selectedTemplate || templateBusy}>
                        更新当前模板
                      </Button>
                      {selectedTemplate?.source_filename ? <Badge variant="outline">旧模板来源：{selectedTemplate.source_filename}</Badge> : null}
                    </div>
                  </div>
                ) : null}
                {copyMode === "ai" && aiNotConfigured ? (
                  <div className="campaign-inline-warning flex gap-2 text-sm">
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                    AI 模型未配置，暂时无法自动优化话术。
                  </div>
                ) : null}
                <div className="campaign-hint-row">
                  <span>
                    {copyMode === "ai"
                      ? "AI 生成必须先预览确认，系统会为本次选中的红人逐个生成不同邮件。"
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
                <StepHeader step="4" title="确认并发送" desc="这里分页显示全部邮件，支持逐封审核、编辑、重生成和跳过。" />
              </CardHeader>
              <CardContent className="campaign-step-content">
                {preview && preview.items.length > 0 ? (
                  <div className="space-y-3">
                    <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm">
                      <span className="text-slate-600">
                        可发送 {queueableDraftCount} 封。AI 生成后无需审批草稿，点击发送会马上发出并留下发送记录。
                      </span>
                    </div>
                    <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-blue-100 bg-blue-50 px-3 py-2 text-sm">
                      <span className="text-blue-800">
                        全部 {preview.items.length} 封，当前筛选 {filteredPreviewItems.length} 封；显示第 {draftPageStart}-{draftPageEnd} 封。
                      </span>
                      <span className="text-xs text-blue-700">切换筛选和分页不会重新生成 AI 话术。</span>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {(Object.keys(DRAFT_FILTER_LABELS) as DraftFilter[]).map((filter) => (
                        <Button
                          key={filter}
                          type="button"
                          variant={draftFilter === filter ? "default" : "outline"}
                          onClick={() => setDraftFilterAndResetPage(filter)}
                        >
                          {DRAFT_FILTER_LABELS[filter]} {draftFilterCounts[filter]}
                        </Button>
                      ))}
                    </div>
                    {paginatedPreviewItems.map((item) => (
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
                            <Badge variant={item.draft_status === "modified" ? "warning" : "secondary"}>
                              {item.draft_status === "modified" ? "已人工修改" : "未人工修改"}
                            </Badge>
                            <Badge variant={item.can_queue ? "success" : "warning"}>
                              {item.can_queue ? "AI 已生成" : "生成失败/不可发送"}
                            </Badge>
                            <Button type="button" variant="outline" onClick={() => toggleDraftExpanded(item.influencer_id)}>
                              {expandedDraftIds.has(item.influencer_id) ? "收起" : "展开"}
                            </Button>
                          </div>
                        </div>
                        <DraftBodyPreview value={item.body || humanizeOutreachFailureReason(item.skip_reason || item.reason)} compact />
                        {expandedDraftIds.has(item.influencer_id) ? (
                          <div className="mt-3 space-y-3 rounded-lg border border-slate-200 bg-white p-3">
                            <div className="grid gap-2 text-xs text-slate-600 md:grid-cols-4">
                              <span>当前状态：{getOutreachDraftStatusLabel(item.draft_status)}</span>
                              <span>AI 状态：{item.can_queue ? "generated" : "failed"}</span>
                              <span>人工修改：{item.draft_status === "modified" ? "是" : "否"}</span>
                              <span>邮箱：{item.recipient || "无"}</span>
                            </div>
                            {editingDraftId === item.influencer_id ? (
                              <div className="space-y-2">
                                <Input
                                  value={draftEdits[item.influencer_id]?.subject ?? item.subject ?? ""}
                                  onChange={(event) => updateDraftEditField(item.influencer_id, "subject", event.target.value)}
                                  placeholder="邮件标题"
                                />
                                <Textarea
                                  rows={8}
                                  value={draftEdits[item.influencer_id]?.body ?? item.body ?? ""}
                                  onChange={(event) => updateDraftEditField(item.influencer_id, "body", event.target.value)}
                                  placeholder="邮件正文"
                                />
                              </div>
                            ) : (
                              <DraftBodyPreview value={item.body || humanizeOutreachFailureReason(item.skip_reason || item.reason)} />
                            )}
                            <div className="flex flex-wrap gap-2">
                              {editingDraftId === item.influencer_id ? (
                                <>
                                  <Button type="button" onClick={() => void saveDraftEdit(item)} disabled={draftActionId === item.influencer_id}>
                                    {draftActionId === item.influencer_id ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                                    保存修改
                                  </Button>
                                  <Button type="button" variant="outline" onClick={() => cancelDraftEdit(item.influencer_id)}>
                                    取消修改
                                  </Button>
                                </>
                              ) : (
                                <>
                                  <Button type="button" variant="outline" onClick={() => startDraftEdit(item)}>
                                    编辑
                                  </Button>
                                  <Button
                                    type="button"
                                    variant="outline"
                                    onClick={() => void regenerateDraft(item)}
                                    disabled={draftActionId === item.influencer_id}
                                  >
                                    {draftActionId === item.influencer_id ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                                    恢复/重新生成 AI 版本
                                  </Button>
                                  <Button
                                    type="button"
                                    variant="outline"
                                    onClick={() => void approveDraft(item)}
                                    disabled={!item.can_queue || draftActionId === item.influencer_id}
                                  >
                                    标记已审核
                                  </Button>
                                  <Button
                                    type="button"
                                    variant="outline"
                                    onClick={() => void skipDraft(item)}
                                    disabled={draftActionId === item.influencer_id}
                                  >
                                    跳过
                                  </Button>
                                </>
                              )}
                            </div>
                          </div>
                        ) : null}
                        {!item.can_queue ? (
                          <p className="mt-2 text-xs text-amber-700">
                            跳过原因：{humanizeOutreachFailureReason(item.skip_reason || item.reason)}
                          </p>
                        ) : null}
                      </div>
                    ))}
                    <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-slate-600">
                      <span>第 {safeDraftPage} / {draftPageCount} 页，每页 {DRAFT_PAGE_SIZE} 封</span>
                      <div className="flex gap-2">
                        <Button type="button" variant="outline" disabled={safeDraftPage <= 1} onClick={() => setDraftPage((page) => Math.max(1, page - 1))}>
                          上一页
                        </Button>
                        <Button type="button" variant="outline" disabled={safeDraftPage >= draftPageCount} onClick={() => setDraftPage((page) => page + 1)}>
                          下一页
                        </Button>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="campaign-empty-preview">
                    {copyMode === "ai"
                      ? "点击生成话术并检查后，这里会分页显示全部收件人的邮件。"
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
      </div>
    </AdminShell>
  );
}
