import "./register-path-aliases.ts";
import assert from "node:assert/strict";
import test from "node:test";

import {
  buildInfluencerExportUrl,
  influencerFilterQueryParams,
} from "../src/lib/api.ts";
import {
  INFLUENCER_ONE_CLICK_EMAIL_BUTTON_LABEL,
  buildOneClickCampaignName,
  buildOneClickCampaignPayload,
  buildOutreachCampaignResultUrl,
  buildOutreachCampaignsUrl,
  resolveBulkDeleteSelection,
  resolveBulkOutreachSelection,
} from "../src/lib/influencer-selection-helpers.ts";

test("valueTier maps to value_tier query param", () => {
  const params = influencerFilterQueryParams({ valueTier: "direct_contact" });
  assert.equal(params.value_tier, "direct_contact");
});

test("highValue still maps to high_value query param", () => {
  const params = influencerFilterQueryParams({ highValue: true });
  assert.equal(params.high_value, true);
});

test("emailStatus maps to email_status query param", () => {
  const params = influencerFilterQueryParams({ emailStatus: "sent" });
  assert.equal(params.email_status, "sent");
});

test("export URL includes value_tier and high_value filters", () => {
  const url = buildInfluencerExportUrl({
    valueTier: "manual_research",
    highValue: true,
    collectionTaskId: 52,
    platform: "tiktok",
    search: "travel",
  });

  assert.equal(url.includes("value_tier=manual_research"), true);
  assert.equal(url.includes("high_value=true"), true);
  assert.equal(url.includes("collection_task_id=52"), true);
  assert.equal(url.includes("platform=tiktok"), true);
  assert.equal(url.includes("keyword=travel"), true);
});

test("export URL includes skip tier filter", () => {
  const url = buildInfluencerExportUrl({ valueTier: "skip" });
  assert.equal(url.includes("value_tier=skip"), true);
});

test("export URL includes email status filter", () => {
  const url = buildInfluencerExportUrl({ emailStatus: "unsent" });
  assert.equal(url.includes("email_status=unsent"), true);
});

test("influencerFilterQueryParams includes exclude_terminal_statuses", () => {
  const params = influencerFilterQueryParams({ excludeTerminalStatuses: true });
  assert.equal(params.exclude_terminal_statuses, true);
});

test("buildOutreachCampaignsUrl without selection has no ids", () => {
  const url = buildOutreachCampaignsUrl({});
  assert.equal(url, "/outreach-campaigns");
});

test("buildOutreachCampaignResultUrl preserves checked recipients after one-click send", () => {
  const url = buildOutreachCampaignResultUrl({
    campaignId: 500,
    message: "已一键生成并发送",
    ids: [3, 7, 9],
  });

  assert.match(url, /^\/outreach-campaigns\?/);
  assert.match(url, /highlight=500/);
  assert.match(url, /ids=3%2C7%2C9/);
  assert.doesNotMatch(url, /select_all=1/);
});

test("buildOutreachCampaignResultUrl preserves filter-all recipients after one-click send", () => {
  const url = buildOutreachCampaignResultUrl({
    campaignId: 501,
    message: "已一键生成并发送",
    selectAll: true,
    total: 158,
    filters: { platform: "instagram", hasEmail: true },
  });

  assert.match(url, /highlight=501/);
  assert.match(url, /select_all=1/);
  assert.match(url, /total=158/);
  assert.match(url, /platform=instagram/);
  assert.match(url, /has_email=true/);
  assert.doesNotMatch(url, /ids=/);
});

test("resolveBulkOutreachSelection keeps partial page selection scoped to checked rows", () => {
  const selection = resolveBulkOutreachSelection({
    mode: "page",
    selectedIds: [1],
    total: 41,
    filters: { platform: "tiktok", hasEmail: true },
  });

  assert.equal(selection.count, 1);
  assert.equal(selection.selectAll, false);
  assert.deepEqual(selection.ids, [1]);
});

test("resolveBulkOutreachSelection sends full filtered result only after select-all", () => {
  const selection = resolveBulkOutreachSelection({
    mode: "filter_all",
    selectedIds: Array.from({ length: 20 }, (_, index) => index + 1),
    total: 174,
    filters: { hasEmail: true, excludeTerminalStatuses: true },
  });

  assert.equal(selection.count, 174);
  assert.equal(selection.selectAll, true);
  assert.deepEqual(selection.filters, { hasEmail: true, excludeTerminalStatuses: true });
  assert.equal("ids" in selection, false);
});

test("resolveBulkDeleteSelection only deletes explicitly checked page rows", () => {
  assert.deepEqual(resolveBulkDeleteSelection([3, 2, 3], "page"), [3, 2]);
  assert.deepEqual(resolveBulkDeleteSelection([3, 2], "filter_all"), [3, 2]);
});

test("buildOneClickCampaignPayload uses selected ids for one-click send", () => {
  const payload = buildOneClickCampaignPayload({
    name: "一键发送测试",
    ids: [1, 2, 3],
  });

  assert.deepEqual(payload.influencer_ids, [1, 2, 3]);
  assert.equal(payload.name, "一键发送测试");
  assert.equal(payload.skip_sent, false);
  assert.equal(payload.skip_replied, true);
  assert.equal(payload.skip_blacklisted, true);
  assert.equal(payload.skip_invalid, true);
  assert.equal(payload.allow_resend, true);
  assert.equal(payload.send_window_start, "00:00");
  assert.equal(payload.send_window_end, "23:59");
  assert.equal(payload.daily_limit, 1000);
});

test("buildOneClickCampaignPayload supports current filtered selection", () => {
  const payload = buildOneClickCampaignPayload({
    name: "筛选全选",
    selectAll: true,
    filters: { hasEmail: true, platform: "instagram", excludeTerminalStatuses: true },
  });

  assert.equal(payload.select_all_by_filters, true);
  assert.deepEqual(payload.influencer_filters, {
    has_email: true,
    platform: "instagram",
    exclude_terminal_statuses: true,
  });
  assert.equal("influencer_ids" in payload, false);
});

test("buildOneClickCampaignName is readable for sales users", () => {
  assert.match(buildOneClickCampaignName(new Date("2026-06-23T10:20:00+08:00")), /一键批量发送/);
});

test("influencer bulk email entry points to one-click workbench instead of preview dialog", () => {
  assert.equal(INFLUENCER_ONE_CLICK_EMAIL_BUTTON_LABEL, "AI一键发邮件");
  assert.doesNotMatch(INFLUENCER_ONE_CLICK_EMAIL_BUTTON_LABEL, /预览|batch|批量/i);
});
