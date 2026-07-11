import assert from "node:assert/strict";
import test from "node:test";

import "./register-path-aliases.ts";

const {
  buildAdminDashboardView,
  buildSalesWorkbenchDetailView,
  buildSalesWorkbenchView,
  filterAdminRows,
  formatAdminDate,
  formatAdminNumber,
  getCollectionTaskStatusMeta,
  getEmailStatusMeta,
  getReplyIntentStatusMeta,
  getReplyProcessingStatusMeta,
  getProductStatusMeta,
  isOutreachInsufficient,
} = await import("@/components/admin/admin-ui-helpers");

test("admin helpers localize technical statuses for operators", () => {
  assert.deepEqual(getCollectionTaskStatusMeta("completed_with_results"), {
    label: "有结果",
    tone: "success",
  });
  assert.deepEqual(getCollectionTaskStatusMeta("completed_without_results"), {
    label: "无结果",
    tone: "warning",
  });
  assert.deepEqual(getCollectionTaskStatusMeta("running"), {
    label: "采集中",
    tone: "info",
  });
  assert.deepEqual(getEmailStatusMeta("failed"), {
    label: "发送失败",
    tone: "danger",
  });
  assert.deepEqual(getProductStatusMeta("hidden"), {
    label: "暂停",
    tone: "muted",
  });
});

test("admin helpers localize reply processing and intent statuses", () => {
  assert.deepEqual(getReplyProcessingStatusMeta("unprocessed"), {
    label: "待处理",
    tone: "warning",
  });
  assert.deepEqual(getReplyProcessingStatusMeta("processed"), {
    label: "已处理",
    tone: "success",
  });
  assert.deepEqual(getReplyProcessingStatusMeta("read"), {
    label: "已查看",
    tone: "info",
  });
  assert.deepEqual(getReplyIntentStatusMeta("positive"), {
    label: "有意向",
    tone: "success",
  });
  assert.deepEqual(getReplyIntentStatusMeta("follow_up"), {
    label: "待跟进",
    tone: "warning",
  });
  assert.deepEqual(getReplyIntentStatusMeta("unmatched"), {
    label: "未匹配",
    tone: "muted",
  });
  assert.deepEqual(getReplyIntentStatusMeta(undefined), {
    label: "暂无",
    tone: "muted",
  });
});

test("admin helpers format missing and numeric values for Chinese tables", () => {
  assert.equal(formatAdminNumber(12800), "12,800");
  assert.equal(formatAdminNumber(null), "暂无");
  assert.equal(formatAdminDate(null), "暂无");
  assert.match(formatAdminDate("2026-07-09T08:30:00.000Z"), /2026/);
});

test("admin row filtering supports search, owner, brand, status, platform and date range", () => {
  const rows = [
    {
      name: "夏季红人采集",
      brand: "Scandi Home",
      owner: "alice",
      status: "running",
      platform: "instagram",
      createdAt: "2026-07-09T02:00:00.000Z",
    },
    {
      name: "旧品牌发信",
      brand: "Old Brand",
      owner: "bob",
      status: "failed",
      platform: "youtube",
      createdAt: "2026-07-01T02:00:00.000Z",
    },
  ];

  const result = filterAdminRows(rows, {
    search: "夏季",
    owner: "alice",
    brand: "scandi",
    status: "running",
    platform: "instagram",
    startDate: "2026-07-08",
    endDate: "2026-07-10",
  });

  assert.equal(result.length, 1);
  assert.equal(result[0].name, "夏季红人采集");
});

test("dashboard view derives success rate and exception count without backend changes", () => {
  const view = buildAdminDashboardView({
    total_users: 4,
    total_sales: 3,
    total_products: 8,
    total_collection_tasks: 20,
    total_influencers: 400,
    total_email_logs: 120,
    total_replies: 15,
    today_collection_tasks: 5,
    today_influencers: 25,
    today_email_logs: 18,
    today_replies: 4,
    failed_collection_tasks: 2,
    failed_email_logs: 3,
    pending_replies: 6,
    sales_rank: [{ id: 1, username: "alice", product_count: 4 }],
    product_rank: [{ id: 2, name: "Brand", influencer_count: 90 }],
  });

  assert.equal(view.successRateLabel, "90%");
  assert.equal(view.pendingExceptionCount, 11);
  assert.equal(view.kpis.length, 8);
  assert.equal(view.kpis[0].label, "总品牌数");
});

test("sales workbench view derives operator KPIs and action state from existing admin users", () => {
  const view = buildSalesWorkbenchView([
    {
      id: 1,
      username: "alice",
      display_name: null,
      email: "alice@example.com",
      role: "sales",
      is_admin: false,
      is_active: true,
      product_count: 2,
      bound_products: [
        { id: 10, name: "Alpha", slug: "alpha", role: "owner", status: "active", created_at: null },
        { id: 11, name: "Beta", slug: "beta", role: "owner", status: "active", created_at: null },
      ],
      collection_task_count: 4,
      collection_success_count: 3,
      collection_failed_count: 1,
      influencer_count: 18,
      email_count: 6,
      email_failed_count: 1,
      reply_count: 2,
      pending_reply_count: 1,
      last_active_at: "2026-07-09T08:00:00.000Z",
      created_at: null,
      updated_at: null,
      status: "active",
      recent_activity: {
        collection_tasks: [
          {
            id: 101,
            name: "today task",
            status: "completed_with_results",
            platform: "instagram",
            platforms: ["instagram"],
            keywords: [],
            product_id: 10,
            product_name: "Alpha",
            user_id: 1,
            username: "alice",
            success_count: 1,
            failed_count: 0,
            inserted_count: 3,
            result_count: 3,
            last_run_at: null,
            created_at: "2026-07-09T03:00:00.000Z",
            updated_at: "2026-07-09T03:30:00.000Z",
          },
        ],
        emails: [],
        replies: [],
      },
    },
    {
      id: 2,
      username: "root",
      display_name: null,
      email: "root@example.com",
      role: "admin",
      is_admin: true,
      is_active: true,
      product_count: 1,
      bound_products: [{ id: 12, name: "Gamma", slug: "gamma", role: "owner", status: "active", created_at: null }],
      collection_task_count: 1,
      collection_success_count: 1,
      collection_failed_count: 0,
      influencer_count: 2,
      email_count: 1,
      email_failed_count: 0,
      reply_count: 0,
      pending_reply_count: 0,
      last_active_at: "2026-07-01T08:00:00.000Z",
      created_at: null,
      updated_at: null,
      status: "active",
    },
  ], new Date("2026-07-09T12:00:00+08:00"));

  assert.equal(view.kpis.salesCount, 1);
  assert.equal(view.kpis.activeTodayCount, 1);
  assert.equal(view.kpis.productCount, 2);
  assert.equal(view.kpis.todayTaskCount, 1);
  assert.equal(view.kpis.successCount, 3);
  assert.equal(view.kpis.exceptionCount, 2);
  assert.equal(view.kpis.todayInfluencerCount, 0);
  assert.equal(view.kpis.pendingReplyCount, 1);
  assert.equal(view.rows[0].activityStatus, "active_today");
  assert.equal(view.rows[0].todayTaskCount, 1);
  assert.equal(view.rows[0].todayInfluencerCount, 0);
  assert.equal(view.hasPreciseTodayTaskData, true);
  assert.equal(view.hasPreciseTodayInfluencerData, false);
});

test("sales workbench view does not estimate today metrics from active accounts", () => {
  const view = buildSalesWorkbenchView([
    {
      id: 1,
      username: "alice",
      display_name: null,
      email: "alice@example.com",
      role: "sales",
      is_admin: false,
      is_active: true,
      product_count: 1,
      bound_products: [],
      collection_task_count: 99,
      collection_success_count: 0,
      collection_failed_count: 0,
      influencer_count: 42,
      email_count: 0,
      email_failed_count: 0,
      reply_count: 0,
      pending_reply_count: 0,
      last_active_at: "2026-07-09T08:00:00.000Z",
      created_at: null,
      updated_at: null,
      status: "active",
    },
  ], new Date("2026-07-09T12:00:00+08:00"));

  assert.equal(view.kpis.todayTaskCount, 0);
  assert.equal(view.kpis.todayInfluencerCount, 0);
  assert.equal(view.hasPreciseTodayTaskData, false);
  assert.equal(view.hasPreciseTodayInfluencerData, false);
});

test("sales workbench view summarizes daily distribution and attention levels", () => {
  const view = buildSalesWorkbenchView([
    {
      id: 1,
      username: "active",
      display_name: null,
      email: "active@example.com",
      role: "sales",
      is_admin: false,
      is_active: true,
      product_count: 1,
      bound_products: [{ id: 10, name: "Alpha", slug: "alpha", role: "owner", status: "active", created_at: null }],
      collection_task_count: 1,
      collection_success_count: 1,
      collection_failed_count: 0,
      influencer_count: 2,
      email_count: 1,
      email_failed_count: 0,
      reply_count: 1,
      pending_reply_count: 0,
      last_active_at: "2026-07-09T08:00:00.000Z",
      created_at: null,
      updated_at: null,
      status: "active",
    },
    {
      id: 2,
      username: "blocked",
      display_name: null,
      email: "blocked@example.com",
      role: "sales",
      is_admin: false,
      is_active: true,
      product_count: 1,
      bound_products: [{ id: 11, name: "Beta", slug: "beta", role: "owner", status: "active", created_at: null }],
      collection_task_count: 2,
      collection_success_count: 0,
      collection_failed_count: 1,
      influencer_count: 12,
      email_count: 2,
      email_failed_count: 1,
      reply_count: 0,
      pending_reply_count: 2,
      last_active_at: "2026-07-08T08:00:00.000Z",
      created_at: null,
      updated_at: null,
      status: "active",
    },
  ], new Date("2026-07-09T12:00:00+08:00"));

  assert.equal(view.kpis.inactiveTodayCount, 1);
  assert.deepEqual(view.activityDistribution.map((item) => [item.key, item.count]), [
    ["active_today", 1],
    ["inactive_today", 1],
    ["disabled", 0],
  ]);
  assert.deepEqual(view.riskDistribution.map((item) => [item.key, item.count]), [
    ["needs_attention", 1],
    ["working", 1],
    ["stable", 0],
  ]);
  assert.equal(view.rows[0].attentionLevel, "working");
  assert.equal(view.rows[1].attentionLevel, "needs_attention");
});

test("admin helpers identify brands with insufficient outreach", () => {
  assert.equal(isOutreachInsufficient({ influencerCount: 1, emailCount: 0, replyCount: 0 }), true);
  assert.equal(isOutreachInsufficient({ influencerCount: 12, emailCount: 5, replyCount: 1 }), true);
  assert.equal(isOutreachInsufficient({ influencerCount: 2, emailCount: 1, replyCount: 0 }), true);
  assert.equal(isOutreachInsufficient({ influencerCount: 12, emailCount: 8, replyCount: 1 }), false);
});

test("sales workbench detail view groups task and outreach progress by brand", () => {
  const detail = buildSalesWorkbenchDetailView({
    products: [
      {
        id: 10,
        name: "Alpha",
        subject: null,
        slug: "alpha",
        created_at: null,
        members: [],
        owner_names: [],
        collection_task_count: 0,
        influencer_count: 0,
        email_count: 0,
        reply_count: 0,
        status: "active",
      },
    ],
    tasks: [
      {
        id: 1,
        name: "Alpha IG",
        status: "completed_with_results",
        platform: "instagram",
        platforms: ["instagram"],
        keywords: [],
        product_id: 10,
        product_name: "Alpha",
        user_id: 1,
        username: "alice",
        success_count: 4,
        failed_count: 0,
        inserted_count: 7,
        result_count: 7,
        last_run_at: "2026-07-09T04:00:00.000Z",
        created_at: "2026-07-09T02:00:00.000Z",
        updated_at: "2026-07-09T04:10:00.000Z",
      },
    ],
    influencers: [
      {
        id: 1,
        product_id: 10,
        product_name: "Alpha",
        platform: "instagram",
        username: "creator",
        display_name: null,
        profile_url: "",
        followers_count: null,
        email: null,
        follow_status: "new",
        score: null,
        created_at: "2026-07-09T05:00:00.000Z",
        updated_at: "2026-07-09T05:00:00.000Z",
      },
    ],
    emails: [],
    replies: [],
  });

  assert.equal(detail.brandProgress.length, 1);
  assert.equal(detail.brandProgress[0].taskCount, 1);
  assert.equal(detail.brandProgress[0].latestTaskStatus, "completed_with_results");
  assert.equal(detail.brandProgress[0].influencerCount, 1);
  assert.equal(detail.brandProgress[0].exceptionCount, 0);
  assert.equal(detail.brandProgress[0].outreachInsufficient, true);
});
