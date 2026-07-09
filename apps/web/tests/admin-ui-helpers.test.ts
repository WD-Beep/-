import assert from "node:assert/strict";
import test from "node:test";

import "./register-path-aliases.ts";

const {
  buildAdminDashboardView,
  filterAdminRows,
  formatAdminDate,
  formatAdminNumber,
  getCollectionTaskStatusMeta,
  getEmailStatusMeta,
  getProductStatusMeta,
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
