import "./register-path-aliases.ts";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { resolveInfluencerEmail } from "../src/lib/outreach-email-helpers.ts";
import {
  canDeleteMessageTemplate,
  canEditMessageTemplate,
} from "../src/lib/message-template-helpers.ts";
import {
  buildCampaignStatsLine,
  buildCampaignBusinessSummary,
  buildGenerateAndSendResultMessage,
  buildOutreachCampaignPayload,
  buildScheduledOutreachQueuePayload,
  buildLocalDateTime,
  buildSkipReasonBreakdown,
  buildScheduledQueueSuccessMessage,
  buildScheduledSendCompletionMessage,
  buildImmediateSendResultMessage,
  buildManualOutreachConfirmMessage,
  buildManualOutreachPayload,
  parseManualOutreachRecipients,
  getOneClickContentSourceLabel,
  getOneClickCurrentStatusLabel,
  buildOneClickCampaignName,
  buildPreviewResultMessage,
  buildSkipReasonSummary,
  CAMPAIGN_AUTO_SEND_CONFIRM_MESSAGE,
  CAMPAIGN_LIST_FLOW_STEPS,
  CAMPAIGN_OPERATOR_GUIDE,
  CAMPAIGN_PAGE_DESCRIPTION,
  CAMPAIGN_PREVIEW_BUTTON_LABEL,
  CAMPAIGN_PROCESS_CONFIRM_MESSAGE,
  CAMPAIGN_QUEUE_CONFIRM_MESSAGE,
  countQueueablePreviewItems,
  deriveOneClickQueueStatusFromCampaign,
  getCampaignPhaseLabel,
  getCampaignPrimaryAction,
  getOneClickQueueStatusLabel,
  getOneClickWorkbenchPrimaryAction,
  getOneClickPrimaryDisabledReason,
  getReplyStatusLabel,
  hasRealEmailReplyEvidence,
  hasRealSendResultEvidence,
  humanizeOutreachFailureReason,
  estimateCampaignEndTime,
  formatDurationMinutes,
  resolveOneClickSendLimit,
} from "../src/lib/outreach-campaign-helpers.ts";
import {
  buildOutreachCampaignsUrl,
  CAMPAIGN_CANCEL_CONFIRM_MESSAGE,
} from "../src/lib/influencer-selection-helpers.ts";
import {
  CAMPAIGN_DETAIL_TABS,
  filterCampaignDetailRows,
  paginateCampaignDetailRows,
} from "../src/lib/outreach-campaign-detail-helpers.ts";

test("manual outreach test UI stays as a collapsed status-strip tool", () => {
  const source = readFileSync(
    new URL("../src/components/outreach-campaigns/outreach-campaigns-panel.tsx", import.meta.url),
    "utf8",
  );
  const statusStripIndex = source.indexOf("campaign-status-strip");
  const manualSummaryIndex = source.indexOf("campaign-manual-test-summary");
  const manualPanelIndex = source.indexOf("campaign-manual-test-panel");
  const mainFlowIndex = source.indexOf("campaign-layout-grid");

  assert.ok(statusStripIndex >= 0, "status strip should exist");
  assert.ok(manualSummaryIndex > statusStripIndex, "manual test entry should live in the status strip");
  assert.ok(manualPanelIndex > manualSummaryIndex, "manual test form should render as an expandable panel");
  assert.ok(manualPanelIndex < mainFlowIndex, "manual test panel should not interrupt the main campaign flow");
  assert.ok(source.includes("manualTestOpen ?"), "manual test form should be collapsed by default");
  assert.ok(source.includes("rows={2}"), "recipient textarea should stay compact");
  assert.ok(source.includes("rows={4}"), "body textarea should stay compact");
});

test("resolveInfluencerEmail priority final > business > public > email", () => {
  assert.equal(
    resolveInfluencerEmail({
      final_email: "final@example.com",
      business_email: "biz@example.com",
      public_email: "pub@example.com",
      email: "legacy@example.com",
    }),
    "final@example.com",
  );
  assert.equal(
    resolveInfluencerEmail({
      final_email: null,
      business_email: "biz@example.com",
      public_email: "pub@example.com",
      email: "legacy@example.com",
    }),
    "biz@example.com",
  );
  assert.equal(
    resolveInfluencerEmail({
      final_email: null,
      business_email: null,
      public_email: "pub@example.com",
      email: "legacy@example.com",
    }),
    "pub@example.com",
  );
  assert.equal(
    resolveInfluencerEmail({
      final_email: null,
      business_email: null,
      public_email: null,
      email: "legacy@example.com",
    }),
    "legacy@example.com",
  );
});

test("manual outreach recipients parse lines commas and semicolons with limit", () => {
  const parsed = parseManualOutreachRecipients("a@example.com, b@example.com\nc@example.com; bad-value");
  assert.deepEqual(parsed.valid, ["a@example.com", "b@example.com", "c@example.com"]);
  assert.deepEqual(parsed.invalid, ["bad-value"]);
  assert.equal(parsed.overLimit, false);

  const over = parseManualOutreachRecipients(
    Array.from({ length: 11 }, (_, index) => `creator${index}@example.com`).join("\n"),
  );
  assert.equal(over.valid.length, 10);
  assert.equal(over.overLimit, true);
});

test("manual outreach payload and confirmation distinguish immediate and scheduled sends", () => {
  const nowPayload = buildManualOutreachPayload({
    recipientsText: "creator@example.com",
    subject: "Hello",
    body: "Body",
    sendMode: "now",
  });
  assert.deepEqual(nowPayload, {
    recipients: ["creator@example.com"],
    subject: "Hello",
    body: "Body",
    send_mode: "now",
  });
  assert.equal(buildManualOutreachConfirmMessage(1, "now"), "本次将立即发送 1 封自定义测试邮件。确认发送？");

  const scheduled = new Date("2026-07-03T10:30:00.000Z");
  const scheduledPayload = buildManualOutreachPayload({
    recipientsText: "creator@example.com",
    subject: "Hello",
    body: "Body",
    sendMode: "scheduled",
    scheduledAt: scheduled,
  });
  assert.equal(scheduledPayload.scheduled_at, "2026-07-03T10:30:00.000Z");
  assert.equal(
    buildManualOutreachConfirmMessage(3, "scheduled"),
    "本次将定时发送 3 封自定义测试邮件。到时间后会自动发送，确认入队？",
  );
});

test("buildOutreachCampaignPayload defaults skip flags to true and allow_resend to false", () => {
  const payload = buildOutreachCampaignPayload({
    name: "default rules",
    influencerIds: [1],
  });
  assert.equal(payload.daily_limit, 50);
  assert.equal(payload.skip_sent, true);
  assert.equal(payload.skip_replied, true);
  assert.equal(payload.skip_blacklisted, true);
  assert.equal(payload.skip_invalid, true);
  assert.equal(payload.allow_resend, false);
});

test("buildOutreachCampaignPayload passes explicit false skip flags", () => {
  const payload = buildOutreachCampaignPayload({
    name: "no skips",
    influencerIds: [2],
    skipSent: false,
    skipReplied: false,
    skipBlacklisted: false,
    skipInvalid: false,
  });
  assert.equal(payload.skip_sent, false);
  assert.equal(payload.skip_replied, false);
  assert.equal(payload.skip_blacklisted, false);
  assert.equal(payload.skip_invalid, false);
});

test("buildOutreachCampaignPayload includes daily limit send window and source references", () => {
  const payload = buildOutreachCampaignPayload({
    name: "spring outreach",
    influencerIds: [1, 2, 3],
    dailyLimit: 15,
    sendWindowStart: "09:00",
    sendWindowEnd: "17:00",
    skipSent: true,
    skipReplied: false,
    skipBlacklisted: true,
    skipInvalid: true,
    allowResend: true,
    knowledgeBaseId: 5,
    messageTemplateId: 9,
  });
  assert.equal(payload.name, "spring outreach");
  assert.deepEqual(payload.influencer_ids, [1, 2, 3]);
  assert.equal(payload.daily_limit, 15);
  assert.equal(payload.send_window_start, "09:00");
  assert.equal(payload.send_window_end, "17:00");
  assert.equal(payload.skip_sent, true);
  assert.equal(payload.skip_replied, false);
  assert.equal(payload.skip_blacklisted, true);
  assert.equal(payload.skip_invalid, true);
  assert.equal(payload.allow_resend, true);
  assert.equal(payload.knowledge_base_id, 5);
  assert.equal(payload.message_template_id, 9);
});

test("AI one-click workbench can opt into resending previously contacted creators", () => {
  const payload = buildOutreachCampaignPayload({
    name: "resend batch",
    influencerIds: [1, 2],
    skipSent: false,
    allowResend: true,
  });

  assert.equal(payload.skip_sent, false);
  assert.equal(payload.allow_resend, true);
});

test("campaign confirmation messages explain queue and send boundaries", () => {
  assert.match(CAMPAIGN_QUEUE_CONFIRM_MESSAGE, /不会立即发送/);
  assert.match(CAMPAIGN_PROCESS_CONFIRM_MESSAGE, /一键 AI 批量发送/);
  assert.match(CAMPAIGN_PROCESS_CONFIRM_MESSAGE, /专属邮件/);
  assert.match(CAMPAIGN_PROCESS_CONFIRM_MESSAGE, /逐封发送/);
  assert.match(CAMPAIGN_AUTO_SEND_CONFIRM_MESSAGE, /定时自动发送/);
  assert.match(CAMPAIGN_AUTO_SEND_CONFIRM_MESSAGE, /逐封发送/);
  assert.match(CAMPAIGN_AUTO_SEND_CONFIRM_MESSAGE, /不会群发同一封/);
});

test("countQueueablePreviewItems ignores can_queue=false rows", () => {
  const count = countQueueablePreviewItems([
    { can_queue: true },
    { can_queue: false },
    { can_queue: true },
    { can_queue: false },
  ]);
  assert.equal(count, 2);
});

test("humanizeOutreachFailureReason explains already sent rows in plain language", () => {
  assert.equal(
    humanizeOutreachFailureReason("已有成功发信记录"),
    "为避免重复骚扰，系统跳过",
  );
});

test("buildGenerateAndSendResultMessage explains all skipped recipients", () => {
  const message = buildGenerateAndSendResultMessage({
    preview: {
      total: 20,
      can_queue_count: 0,
      skip_count: 20,
      items: [
        {
          influencer_id: 1,
          username: "creator",
          display_name: null,
          recipient: "creator@example.com",
          subject: "",
          body: "",
          reason: "",
          matched_knowledge: [],
          template_title: "",
          can_queue: false,
          skip_reason: "已有成功发信记录",
        },
      ],
      campaign_id: 1,
    },
    queued: 0,
    sent: 0,
    failed: 0,
    message: "raw",
  });

  assert.equal(message, "没有发送新邮件：20 人都已发送过，为避免重复骚扰，系统已跳过。");
});

test("buildOutreachCampaignPayload supports filter-all mode", () => {
  const payload = buildOutreachCampaignPayload({
    name: "filter all",
    selectAllByFilters: true,
    influencerFilters: { has_email: true, platform: "tiktok" },
  });
  assert.equal(payload.select_all_by_filters, true);
  assert.deepEqual(payload.influencer_filters, { has_email: true, platform: "tiktok" });
  assert.equal("influencer_ids" in payload, false);
});

test("one click campaign name uses sales-facing language", () => {
  assert.match(buildOneClickCampaignName(new Date("2026-06-24T08:00:00+08:00")), /^AI 一键发邮件 /);
  assert.doesNotMatch(buildOneClickCampaignName(new Date("2026-06-24T08:00:00+08:00")), /campaign|queue|batch/i);
});

test("buildOutreachCampaignPayload includes auto send fields", () => {
  const payload = buildOutreachCampaignPayload({
    name: "scheduled",
    influencerIds: [1],
    autoSendEnabled: true,
    autoSendTime: "10:30",
  });
  assert.equal(payload.auto_send_enabled, true);
  assert.equal(payload.auto_send_time, "10:30");
});

test("buildScheduledOutreachQueuePayload maps queueable preview rows to scheduled queue items", () => {
  const payload = buildScheduledOutreachQueuePayload({
    campaignId: 9,
    preview: {
      items: [
        {
          influencer_id: 101,
          recipient: "creator@example.com",
          subject: "Hello",
          body: "Body",
          can_queue: true,
          matched_knowledge: [{ document: "Guide", summary: "Point" }],
          reason: "good fit",
        },
        {
          influencer_id: 102,
          recipient: "skip@example.com",
          subject: "Skip",
          body: "Skip body",
          can_queue: false,
          matched_knowledge: [],
          reason: null,
        },
      ],
    },
    startAt: new Date("2026-06-26T10:00:00+08:00"),
    intervalMinutes: 7,
    dailyLimit: 30,
    hourlyLimit: 10,
    sendWindowStart: "09:00",
    sendWindowEnd: "18:00",
    allowResend: true,
  });

  assert.equal(payload.campaign_id, 9);
  assert.equal(payload.items.length, 1);
  assert.equal(payload.items[0].product_influencer_id, 101);
  assert.equal(payload.items[0].recipient, "creator@example.com");
  assert.equal(payload.items[0].subject, "Hello");
  assert.equal(payload.items[0].body, "Body");
  assert.equal(payload.items[0].allow_resend, true);
  assert.equal(payload.items[0].dedupe_key, "campaign:9:influencer:101");
  assert.deepEqual(payload.items[0].matched_knowledge, [{ document: "Guide", summary: "Point" }]);
  assert.equal(payload.schedule_config.start_at, "2026-06-26T02:00:00.000Z");
  assert.equal(payload.schedule_config.timezone, "Asia/Shanghai");
  assert.equal(payload.schedule_config.interval_minutes, 7);
  assert.equal(payload.schedule_config.daily_limit, 30);
  assert.equal(payload.schedule_config.hourly_limit, 10);
});

test("one click workbench builds exact local scheduled datetime", () => {
  const value = buildLocalDateTime("2026-06-26", "17:30");
  assert.ok(value);
  assert.equal(value.getFullYear(), 2026);
  assert.equal(value.getMonth(), 5);
  assert.equal(value.getDate(), 26);
  assert.equal(value.getHours(), 17);
  assert.equal(value.getMinutes(), 30);
  assert.equal(buildLocalDateTime("2026/06/26", "17:30"), null);
});

test("one click workbench estimates end time and duration", () => {
  const start = new Date("2026-06-26T17:30:00+08:00");
  const end = estimateCampaignEndTime({ recipientCount: 4, startAt: start, intervalMinutes: 6 });
  assert.equal(end.getTime(), new Date("2026-06-26T17:48:00+08:00").getTime());
  assert.equal(formatDurationMinutes(18), "18 分钟");
  assert.equal(formatDurationMinutes(125), "2 小时 5 分钟");
});

test("one click send limit defaults to the current source size instead of 50", () => {
  assert.equal(resolveOneClickSendLimit({ configuredValue: "", sourceCount: 1668 }), 1668);
  assert.equal(resolveOneClickSendLimit({ configuredValue: "200", sourceCount: 1668 }), 200);
});

test("one click workbench explains disabled primary actions", () => {
  assert.equal(
    getOneClickPrimaryDisabledReason({
      recipientCount: 0,
      sourceAvailable: false,
      smtpReady: true,
      aiReady: true,
      generationMode: "ai",
      action: "send",
    }),
    "没有邮件发出。没有可发送对象，请回到红人库选择收件人。",
  );
  assert.equal(
    getOneClickPrimaryDisabledReason({
      recipientCount: 10,
      sourceAvailable: true,
      smtpReady: false,
      aiReady: true,
      generationMode: "ai",
      action: "send",
    }),
    "邮件没有发出。原因：SMTP 未配置，请先在设置中配置发件邮箱。",
  );
  assert.equal(
    getOneClickPrimaryDisabledReason({
      recipientCount: 10,
      sourceAvailable: true,
      smtpReady: false,
      aiReady: true,
      generationMode: "ai",
      action: "preview",
    }),
    null,
  );
});

test("one click workbench exposes exactly one primary action by state", () => {
  assert.deepEqual(
    getOneClickWorkbenchPrimaryAction({
      hasPreview: false,
      sendMode: "scheduled",
      queueStatus: "not_queued",
    }),
    { action: "preview", label: "生成话术并预览" },
  );
  assert.deepEqual(
    getOneClickWorkbenchPrimaryAction({
      hasPreview: true,
      sendMode: "now",
      queueStatus: "not_queued",
    }),
    { action: "send", label: "确认开始发送" },
  );
  assert.deepEqual(
    getOneClickWorkbenchPrimaryAction({
      hasPreview: true,
      sendMode: "scheduled",
      queueStatus: "not_queued",
    }),
    { action: "queue", label: "确认定时发送" },
  );
  assert.deepEqual(
    getOneClickWorkbenchPrimaryAction({
      hasPreview: true,
      sendMode: "scheduled",
      queueStatus: "waiting",
    }),
    { action: "progress", label: "查看发送进度" },
  );
  assert.deepEqual(
    getOneClickWorkbenchPrimaryAction({
      hasPreview: true,
      sendMode: "now",
      queueStatus: "failed",
    }),
    { action: "retry", label: "查看失败原因 / 重试发送" },
  );
});

test("deriveOneClickQueueStatusFromCampaign treats sent latest campaign as completed", () => {
  assert.equal(
    deriveOneClickQueueStatusFromCampaign({
      status: "completed",
      total_count: 20,
      can_queue_count: 4,
      queued_count: 4,
      sent_count: 4,
      failed_count: 0,
      skipped_count: 16,
      previewed_at: "2026-06-27T03:00:24Z",
    }),
    "completed",
  );
});

test("deriveOneClickQueueStatusFromCampaign does not mark duplicate-only campaign as failed", () => {
  assert.equal(
    deriveOneClickQueueStatusFromCampaign({
      status: "completed",
      total_count: 20,
      can_queue_count: 0,
      queued_count: 0,
      sent_count: 0,
      failed_count: 0,
      skipped_count: 20,
      previewed_at: "2026-06-27T03:00:24Z",
    }),
    "completed",
  );
});

test("one click workbench queue messages do not imply mail was sent", () => {
  assert.equal(getOneClickQueueStatusLabel("not_queued"), "未发送");
  assert.equal(getOneClickQueueStatusLabel("waiting"), "已定时");
  assert.equal(getOneClickQueueStatusLabel("completed"), "已完成");
  assert.match(
    buildScheduledQueueSuccessMessage({
      createdCount: 12,
      skippedCount: 2,
      startAt: new Date("2026-06-27T17:30:00+08:00"),
    }),
    /不需要再手动点/,
  );
});

test("one click current status distinguishes all-skipped batches from sent mail", () => {
  assert.equal(
    getOneClickCurrentStatusLabel({
      busyAction: null,
      copyMode: "manual",
      hasPreview: true,
      queueStatus: "completed",
      preview: { total: 3, can_queue_count: 0, skip_count: 3 },
    }),
    "本批无可发送",
  );
  assert.equal(
    getOneClickCurrentStatusLabel({
      busyAction: null,
      copyMode: "manual",
      hasPreview: true,
      queueStatus: "completed",
      preview: { total: 3, can_queue_count: 2, skip_count: 1 },
    }),
    "已完成",
  );
});

test("one click workbench messages explain direct send and scheduled send clearly", () => {
  assert.equal(
    buildImmediateSendResultMessage({ sent: 38, failed: 0, skipped: 2 }),
    "已成功发送 38 封邮件，跳过 2 人。",
  );
  assert.equal(
    buildImmediateSendResultMessage({ sent: 38, failed: 2, skipped: 0 }),
    "成功 38 封，失败 2 封。点击查看失败原因。",
  );
  assert.match(
    buildScheduledQueueSuccessMessage({
      createdCount: 12,
      skippedCount: 1,
      startAt: new Date("2026-06-29T17:30:00+08:00"),
    }),
    /^已设置定时发送：/,
  );
});

test("scheduled send completion message tells sales when mail actually went out", () => {
  assert.equal(
    buildScheduledSendCompletionMessage({
      queuedCount: 12,
      sentCount: 12,
      failedCount: 0,
    }),
    "定时发送已完成，发送成功：已发出 12 封邮件。",
  );
  assert.equal(
    buildScheduledSendCompletionMessage({
      queuedCount: 12,
      sentCount: 10,
      failedCount: 2,
    }),
    "定时发送已完成，发送成功 10 封，失败 2 封。请到发送队列查看失败原因。",
  );
  assert.equal(
    buildScheduledSendCompletionMessage({
      queuedCount: 12,
      sentCount: 0,
      failedCount: 0,
    }),
    null,
  );
});

test("content source labels separate manual template and AI copy", () => {
  assert.equal(getOneClickContentSourceLabel("manual"), "自己填写");
  assert.equal(getOneClickContentSourceLabel("template"), "话术库");
  assert.equal(getOneClickContentSourceLabel("ai"), "AI生成");
});

test("one click workbench groups skipped recipient reasons", () => {
  assert.deepEqual(
    buildSkipReasonBreakdown([
      { skip_reason: "已有成功发信记录" },
      { skip_reason: "红人已回复，跟进中" },
      { skip_reason: "邮箱格式无效" },
      { skip_reason: "黑名单" },
      { skip_reason: "缺少邮箱" },
    ]),
    { sent: 1, blacklisted: 1, invalid: 1, replied: 1, other: 1 },
  );
});

test("campaign cancel confirm message remains available", () => {
  assert.match(CAMPAIGN_CANCEL_CONFIRM_MESSAGE, /确认取消/);
  assert.match(CAMPAIGN_CANCEL_CONFIRM_MESSAGE, /不会删除/);
});

test("buildPreviewResultMessage covers empty partial and full success", () => {
  assert.equal(
    buildPreviewResultMessage({ total: 0, canQueueCount: 0, skipCount: 0 }),
    "生成完成：当前活动没有可生成邮件的红人",
  );
  assert.match(
    buildPreviewResultMessage({ total: 5, canQueueCount: 3, skipCount: 2 }),
    /3 人可入队，2 人已跳过/,
  );
  assert.equal(
    buildPreviewResultMessage({ total: 4, canQueueCount: 4, skipCount: 0 }),
    "已生成草稿：4 人可加入发送队列",
  );
});

test("getCampaignPhaseLabel reflects generate queue send phases", () => {
  assert.equal(
    getCampaignPhaseLabel({
      status: "draft",
      previewed_at: null,
      total_count: 10,
      queued_count: 0,
      sent_count: 0,
      auto_send_enabled: false,
    }),
    "待生成",
  );
  assert.match(
    getCampaignPhaseLabel({
      status: "ready",
      previewed_at: "2026-01-01",
      total_count: 19,
      queued_count: 0,
      sent_count: 0,
      auto_send_enabled: false,
    }),
    /已生成草稿/,
  );
  assert.match(
    getCampaignPhaseLabel({
      status: "running",
      previewed_at: "2026-01-01",
      total_count: 19,
      queued_count: 5,
      sent_count: 0,
      auto_send_enabled: true,
    }),
    /定时发送中/,
  );
});

test("buildOutreachCampaignsUrl encodes select_all filters", () => {
  const url = buildOutreachCampaignsUrl({
    selectAll: true,
    total: 42,
    filters: { hasEmail: true, platform: "youtube" },
  });
  assert.match(url, /select_all=1/);
  assert.match(url, /total=42/);
  assert.match(url, /has_email=true/);
  assert.match(url, /platform=youtube/);
});

test("campaign page copy explains AI personalized batch outreach", () => {
  assert.equal(
    CAMPAIGN_PAGE_DESCRIPTION,
    "从红人库选人后，一键 AI 自动生成每人不同邮件并逐封发送。",
  );
  assert.equal(CAMPAIGN_PREVIEW_BUTTON_LABEL, "生成/查看每人专属邮件");
  assert.deepEqual(CAMPAIGN_LIST_FLOW_STEPS, [
    "选择红人：可批量选择",
    "一键 AI 批量发送：自动生成专属邮件",
    "记录结果：成功、失败、跳过原因都可查看",
    "接收回复：红人回复后记录到活动、邮件日志和红人详情",
  ]);
});

test("operator guide answers how to batch send and view replies", () => {
  assert.deepEqual(CAMPAIGN_OPERATOR_GUIDE, [
    {
      title: "怎么批量发",
      description: "从红人库选人后，点击一键 AI 批量发送，系统会自动生成每人专属邮件并逐封发送。",
    },
    {
      title: "发出去的是什么",
      description: "不是同一封群发邮件，系统会按红人信息、产品、知识库和话术生成不同标题和正文。",
    },
    {
      title: "怎么看回复",
      description: "点击活动右侧的查看谁回复了，进入回复跟进表，看已回复、未回复、感兴趣和待跟进红人。",
    },
  ]);
});

test("campaign stats line uses real API fields", () => {
  assert.equal(
    buildCampaignStatsLine({
      total_count: 19,
      draft_count: 19,
      can_queue_count: 12,
      queued_count: 12,
      sent_count: 5,
      failed_count: 0,
      skipped_count: 7,
      reply_count: 2,
      interested_count: 1,
      unreplied_count: 10,
    }),
    "总 19 | 草稿 19 | 可入队 12 | 队列 12 | 已发 5 | 失败 0 | 回复 2 | 感兴趣 1 | 未回复 10 | 跳过 7",
  );
});

test("campaign business summary speaks in sales workflow language", () => {
  assert.deepEqual(
    buildCampaignBusinessSummary({
      total_count: 19,
      draft_count: 19,
      can_queue_count: 12,
      queued_count: 12,
      sent_count: 5,
      failed_count: 0,
      skipped_count: 7,
      reply_count: 2,
      interested_count: 1,
      unreplied_count: 10,
    }),
    [
      "本批次 19 位红人",
      "12 封可发送 · 7 人跳过 · 5 封已发送",
      "2 人已回复 · 1 人感兴趣 · 10 人待跟进",
    ],
  );
});

test("campaign primary action follows the next best step", () => {
  assert.deepEqual(
    getCampaignPrimaryAction({
      status: "draft",
      previewed_at: null,
      queued_count: 0,
      sent_count: 0,
      reply_count: 0,
    }),
    {
      kind: "send",
      label: "一键 AI 批量发送",
      hint: "系统会自动生成每人专属邮件，并逐封发送给可发送红人",
    },
  );
  assert.equal(
    getCampaignPrimaryAction({
      status: "ready",
      previewed_at: "2026-06-22",
      total_count: 5,
      can_queue_count: 5,
      skipped_count: 0,
      queued_count: 0,
      sent_count: 0,
      reply_count: 0,
    }).label,
    "一键 AI 批量发送",
  );
  assert.equal(
    getCampaignPrimaryAction({
      status: "running",
      previewed_at: "2026-06-22",
      queued_count: 3,
      sent_count: 0,
      reply_count: 0,
    }).label,
    "一键 AI 批量发送",
  );
  assert.equal(
    getCampaignPrimaryAction({
      status: "running",
      previewed_at: "2026-06-22",
      queued_count: 3,
      sent_count: 3,
      reply_count: 1,
    }).label,
    "查看谁回复了",
  );
});

test("campaign primary action explains fully skipped batches instead of pretending to send", () => {
  assert.deepEqual(
    getCampaignPrimaryAction({
      status: "running",
      previewed_at: "2026-06-23",
      total_count: 20,
      can_queue_count: 0,
      skipped_count: 20,
      queued_count: 0,
      sent_count: 0,
      reply_count: 0,
    }),
    {
      kind: "preview",
      label: "查看为什么没发送",
      hint: "本批没有可发送红人，20 人都被规则跳过。点击查看每个人的跳过原因。",
    },
  );
});

test("skip reason summary groups real preview rows", () => {
  const summary = buildSkipReasonSummary([
    { skip_reason: "缺少邮箱" },
    { skip_reason: "缺少邮箱" },
    { skip_reason: "AI 生成失败：timeout" },
    { skip_reason: null },
  ]);
  assert.deepEqual(summary, [
    { reason: "缺少邮箱", count: 2 },
    { reason: "AI 生成失败：timeout", count: 1 },
  ]);
});

test("humanizeOutreachFailureReason translates technical causes for sales users", () => {
  assert.equal(
    humanizeOutreachFailureReason("535 authentication failed"),
    "邮箱授权码或 SMTP 配置不对，邮件没有发出去",
  );
  assert.equal(humanizeOutreachFailureReason("缺少邮箱"), "该红人没有可用邮箱");
  assert.equal(humanizeOutreachFailureReason("该红人已有成功发信记录，已跳过重复发送"), "为避免重复骚扰，系统跳过");
  assert.equal(humanizeOutreachFailureReason("红人已回复，跟进中，已跳过"), "该红人已回复，进入跟进，不重复发送");
  assert.equal(humanizeOutreachFailureReason("收件人邮箱格式无效"), "邮箱格式或域名不符合规则");
  assert.equal(humanizeOutreachFailureReason("AI 生成失败：timeout"), "GPT 没有生成可用标题或正文");
});

test("reply status labels are clear for sales follow-up", () => {
  assert.equal(getReplyStatusLabel("unreplied"), "未回复");
  assert.equal(getReplyStatusLabel("replied"), "已回复");
  assert.equal(getReplyStatusLabel("interested"), "感兴趣");
  assert.equal(getReplyStatusLabel("skipped"), "已跳过");
});

test("reply follow-up only shows rows backed by real email reply data", () => {
  assert.equal(
    hasRealEmailReplyEvidence({
      reply_time: null,
      reply_snippet: null,
      reply_body: null,
    }),
    false,
  );
  assert.equal(
    hasRealEmailReplyEvidence({
      reply_time: null,
      reply_snippet: "   ",
      reply_body: "",
    }),
    false,
  );
  assert.equal(
    hasRealEmailReplyEvidence({
      reply_time: "2026-06-24T10:00:00Z",
      reply_snippet: null,
      reply_body: null,
    }),
    true,
  );
  assert.equal(
    hasRealEmailReplyEvidence({
      reply_time: null,
      reply_snippet: "Interested, send details",
      reply_body: null,
    }),
    true,
  );
});

test("send results hide pure skip rows from the one-click workbench", () => {
  assert.equal(hasRealSendResultEvidence({ status: "skipped", sent_at: null, subject: null }), false);
  assert.equal(hasRealSendResultEvidence({ status: "pending", sent_at: null, subject: "Waiting" }), true);
  assert.equal(hasRealSendResultEvidence({ status: "sent", sent_at: null, subject: null }), true);
  assert.equal(hasRealSendResultEvidence({ status: "failed", sent_at: null, subject: null }), true);
  assert.equal(hasRealSendResultEvidence({ status: "skipped", sent_at: "2026-06-24T10:00:00Z", subject: null }), true);
});

test("message template defaults can be edited but not deleted", () => {
  assert.equal(canEditMessageTemplate({ is_system_default: true }), true);
  assert.equal(canDeleteMessageTemplate({ is_system_default: true }), false);
  assert.equal(canEditMessageTemplate({ is_system_default: false }), true);
  assert.equal(canDeleteMessageTemplate({ is_system_default: false }), true);
});

test("campaign detail tabs use sales-friendly result buckets", () => {
  assert.deepEqual(
    CAMPAIGN_DETAIL_TABS.map((tab) => [tab.key, tab.label]),
    [
      ["all", "全部"],
      ["sent", "已发送"],
      ["skipped", "自动跳过"],
      ["failed", "发送失败"],
      ["replied", "已回复"],
      ["unreplied", "未回复"],
    ],
  );
});

test("campaign detail filters rows by send and reply status", () => {
  const rows = [
    { influencer_id: 1, send_status: "sent", reply_status: "unreplied" },
    { influencer_id: 2, send_status: "failed", reply_status: "unreplied" },
    { influencer_id: 3, send_status: "skipped", reply_status: "skipped" },
    { influencer_id: 4, send_status: "sent", reply_status: "replied" },
    { influencer_id: 5, send_status: "sent", reply_status: "interested" },
  ];

  assert.deepEqual(filterCampaignDetailRows(rows, "all").map((row) => row.influencer_id), [1, 2, 3, 4, 5]);
  assert.deepEqual(filterCampaignDetailRows(rows, "sent").map((row) => row.influencer_id), [1, 4, 5]);
  assert.deepEqual(filterCampaignDetailRows(rows, "failed").map((row) => row.influencer_id), [2]);
  assert.deepEqual(filterCampaignDetailRows(rows, "skipped").map((row) => row.influencer_id), [3]);
  assert.deepEqual(filterCampaignDetailRows(rows, "replied").map((row) => row.influencer_id), [4, 5]);
  assert.deepEqual(filterCampaignDetailRows(rows, "unreplied").map((row) => row.influencer_id), [1, 2]);
});

test("campaign detail pagination clamps page boundaries", () => {
  const rows = Array.from({ length: 45 }, (_, index) => ({ influencer_id: index + 1 }));

  assert.deepEqual(
    paginateCampaignDetailRows(rows, { page: 1, pageSize: 20 }),
    {
      items: rows.slice(0, 20),
      page: 1,
      pageSize: 20,
      total: 45,
      totalPages: 3,
    },
  );
  assert.equal(paginateCampaignDetailRows(rows, { page: 99, pageSize: 20 }).page, 3);
  assert.equal(paginateCampaignDetailRows(rows, { page: 0, pageSize: 20 }).page, 1);
});
