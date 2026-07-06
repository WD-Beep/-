import assert from "node:assert/strict";
import test from "node:test";

import {
  buildMonthlyReportExportCsv,
  buildMonthlyReportSections,
  monthlyReportReviewNotice,
  monthlyReportSectionsFromApi,
} from "../src/lib/monthly-report.ts";

test("monthly report includes outreach recap instead of a separate outreach dashboard", () => {
  const sections = buildMonthlyReportSections();

  assert.equal(sections.overview.title, "运营总览");
  assert.equal(sections.outreachRecap.title, "外联运营复盘");
  assert.deepEqual(
    sections.outreachRecap.funnel.map((step) => step.label),
    ["AI 生成草稿", "已审核", "已批准", "已入队", "已发送", "已回复", "有合作意向"],
  );
});

test("monthly report makes skip reasons and high value follow-up explicit", () => {
  const sections = buildMonthlyReportSections();

  assert.deepEqual(
    sections.skipReasons.items.map((item) => item.label),
    ["缺邮箱", "无效邮箱", "黑名单", "已发送", "已回复", "高价值未确认", "草稿未批准"],
  );
  assert.ok(sections.draftQuality.cards.some((card) => card.label === "高价值待确认" && card.tone === "warning"));
  assert.ok(sections.todos.some((todo) => todo.title.includes("高价值草稿未确认")));
});

test("monthly report states that sending still belongs to draft review flow", () => {
  assert.match(monthlyReportReviewNotice, /发送仍然必须在草稿审核页完成/);
});

test("monthly report export contains selected month and outreach recap data", () => {
  const csv = buildMonthlyReportExportCsv("2026-07", "2026-07-03 09:00");

  assert.ok(csv.startsWith("\uFEFF"));
  assert.match(csv, /2026-07/);
  assert.match(csv, /外联运营复盘/);
  assert.match(csv, /AI 生成草稿/);
  assert.match(csv, /高价值待确认/);
});

test("monthly report maps backend data and keeps detail links actionable", () => {
  const sections = monthlyReportSectionsFromApi({
    month: "2026-06",
    updated_at: "2026-07-03T09:00:00Z",
    review_notice: monthlyReportReviewNotice,
    overview: {
      title: "运营总览",
      cards: [
        { label: "邮箱覆盖率", value: "66.7%", helper: "有邮箱 2 人", href: "/influencers?has_email=true", tone: "success" },
      ],
    },
    outreach_recap: {
      title: "外联运营复盘",
      funnel: [{ label: "有合作意向", value: 3, href: "/email-replies?intent_status=interested" }],
    },
    draft_quality: {
      title: "草稿审核质量",
      cards: [{ label: "高价值待确认", value: "1", helper: "需要打开确认", href: "/outreach-campaigns", tone: "warning" }],
    },
    queue_performance: {
      title: "发送队列表现",
      cards: [{ label: "发送失败数", value: "2", helper: "需要处理", href: "/outreach-send-queue?status=failed", tone: "danger" }],
    },
    skip_reasons: {
      title: "跳过原因分析",
      items: [{ label: "缺邮箱", value: 4, helper: "补充联系方式", href: "/influencers?missing_contact=true", tone: "primary" }],
    },
    reply_progress: {
      title: "回复与合作进展",
      cards: [{ label: "感兴趣", value: "3", helper: "优先跟进", href: "/email-replies?intent_status=interested", tone: "success" }],
    },
    todos: [
      {
        title: "1 个高价值草稿未确认",
        description: "打开草稿详情逐条确认",
        href: "/outreach-campaigns",
        action_label: "去确认",
        tone: "warning",
      },
    ],
  });

  assert.equal(sections.overview.cards[0].href, "/influencers?has_email=true");
  assert.equal(sections.outreachRecap.funnel[0].href, "/email-replies?intent_status=interested");
  assert.equal(sections.skipReasons.items[0].href, "/influencers?missing_contact=true");
  assert.equal(sections.todos[0].actionLabel, "去确认");
  assert.equal(sections.draftQuality.cards[0].tone, "warning");
});
