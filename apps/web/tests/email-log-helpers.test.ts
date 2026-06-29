import "./register-path-aliases.ts";
import assert from "node:assert/strict";
import test from "node:test";

import {
  buildEmailLogSummary,
  buildOutreachRecordsUrl,
  filterEmailLogsByView,
  getOutreachSummaryMetrics,
  getEmailLogViewTabs,
  parseEmailLogView,
  translateEmailFailureReason,
  type EmailLogListItem,
} from "../src/lib/email-log-helpers.ts";

const baseLog: EmailLogListItem = {
  id: 1,
  status: "sent",
  error_message: null,
};

test("buildEmailLogSummary returns sales-friendly counts", () => {
  const logs: EmailLogListItem[] = [
    { ...baseLog, id: 1, status: "sent" },
    { ...baseLog, id: 2, status: "sent", reply: { snippet: "Interested", received_at: "2026-06-22" } },
    { ...baseLog, id: 3, status: "failed", error_message: "smtp rejected" },
    { ...baseLog, id: 4, status: "pending" },
  ];

  assert.deepEqual(buildEmailLogSummary(logs, 5), {
    queued: 5,
    sent: 2,
    failed: 1,
    replied: 1,
    unreplied: 1,
  });
});

test("filterEmailLogsByView separates sent failed replied and unreplied rows", () => {
  const logs: EmailLogListItem[] = [
    { ...baseLog, id: 1, status: "sent" },
    { ...baseLog, id: 2, status: "sent", reply: { snippet: "Yes", received_at: "2026-06-22" } },
    { ...baseLog, id: 3, status: "failed", error_message: "smtp rejected" },
  ];

  assert.deepEqual(filterEmailLogsByView(logs, "all").map((log) => log.id), [1, 2, 3]);
  assert.deepEqual(filterEmailLogsByView(logs, "sent").map((log) => log.id), [1, 2]);
  assert.deepEqual(filterEmailLogsByView(logs, "failed").map((log) => log.id), [3]);
  assert.deepEqual(filterEmailLogsByView(logs, "replied").map((log) => log.id), [2]);
  assert.deepEqual(filterEmailLogsByView(logs, "unreplied").map((log) => log.id), [1]);
});

test("getEmailLogViewTabs labels the business filters clearly", () => {
  const tabs = getEmailLogViewTabs({
    queued: 4,
    sent: 3,
    failed: 2,
    replied: 1,
    unreplied: 2,
  });

  assert.deepEqual(tabs.map((tab) => tab.label), [
    "全部记录",
    "已发送",
    "发送失败",
    "已回复",
    "未回复",
  ]);
  assert.deepEqual(tabs.map((tab) => tab.count), [5, 3, 2, 1, 2]);
});

test("getOutreachSummaryMetrics exposes compact status metrics with active state", () => {
  const metrics = getOutreachSummaryMetrics(
    {
      queued: 0,
      sent: 100,
      failed: 0,
      replied: 6,
      unreplied: 94,
    },
    "unreplied",
  );

  assert.deepEqual(
    metrics.map((metric) => [metric.key, metric.label, metric.count, metric.active]),
    [
      ["sent", "已发送", 100, false],
      ["failed", "失败", 0, false],
      ["replied", "已回复", 6, false],
      ["unreplied", "未回复", 94, true],
    ],
  );
});

test("translateEmailFailureReason turns SMTP errors into readable business copy", () => {
  assert.equal(
    translateEmailFailureReason("smtp rejected"),
    "邮件服务器拒绝发送，邮件没有发出去。请检查收件邮箱、发件邮箱权限或发送频率限制。",
  );
  assert.equal(
    translateEmailFailureReason("SMTP not configured"),
    "发件邮箱未配置，邮件没有发出去。请先到系统设置完成 SMTP 配置。",
  );
  assert.equal(
    translateEmailFailureReason("535 authentication failed"),
    "SMTP 认证失败，邮件没有发出去。请检查企业邮箱客户端专用密码。",
  );
  assert.equal(translateEmailFailureReason(null), "-");
});

test("parseEmailLogView supports direct links to record views", () => {
  assert.equal(parseEmailLogView("sent"), "sent");
  assert.equal(parseEmailLogView("failed"), "failed");
  assert.equal(parseEmailLogView("replied"), "replied");
  assert.equal(parseEmailLogView("unreplied"), "unreplied");
  assert.equal(parseEmailLogView("bad-value"), "all");
  assert.equal(parseEmailLogView(null), "all");
});

test("buildOutreachRecordsUrl creates direct links for business record views", () => {
  assert.equal(buildOutreachRecordsUrl("sent"), "/outreach-records?view=sent");
  assert.equal(buildOutreachRecordsUrl("failed"), "/outreach-records?view=failed");
  assert.equal(buildOutreachRecordsUrl("replied"), "/outreach-records?view=replied");
  assert.equal(buildOutreachRecordsUrl("unreplied"), "/outreach-records?view=unreplied");
  assert.equal(buildOutreachRecordsUrl("all"), "/outreach-records");
});
