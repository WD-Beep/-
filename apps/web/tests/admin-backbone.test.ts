import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";
import { fileURLToPath } from "node:url";

function source(path: string): string {
  return readFileSync(fileURLToPath(new URL(path, import.meta.url)), "utf8");
}

function exists(path: string): boolean {
  return existsSync(fileURLToPath(new URL(path, import.meta.url)));
}

test("admin dashboard no longer renders the sales operations home panel", () => {
  const page = source("../src/app/admin/dashboard/page.tsx");

  assert.doesNotMatch(page, /OperationsHomePanel/);
  assert.doesNotMatch(page, /components\/dashboard\/admin-dashboard-gate/);
  assert.match(page, /AdminDashboardPanel/);
});

test("admin shell files exist and do not import sales workspace controls", () => {
  assert.equal(exists("../src/components/admin/admin-shell.tsx"), true);
  assert.equal(exists("../src/components/admin/admin-sidebar.tsx"), true);
  assert.equal(exists("../src/components/admin/admin-header.tsx"), true);

  const shell = source("../src/components/admin/admin-shell.tsx");
  const sidebar = source("../src/components/admin/admin-sidebar.tsx");
  const combined = `${shell}\n${sidebar}`;

  assert.doesNotMatch(combined, /components\/layout\/sidebar/);
  assert.doesNotMatch(combined, /ProductCreateDialog/);
  assert.doesNotMatch(combined, /ProductProvider|useProductActions|setProductId/);
  assert.doesNotMatch(combined, /新增品牌|当前产品|当前品牌/);
  assert.match(combined, /\/admin\/dashboard/);
  assert.match(combined, /\/admin\/sales-workbench/);
  assert.match(combined, /\/admin\/users/);
  assert.match(combined, /\/admin\/products/);
});

test("admin users and products pages render dedicated admin panels", () => {
  assert.equal(exists("../src/app/admin/users/page.tsx"), true);
  assert.equal(exists("../src/app/admin/products/page.tsx"), true);
  assert.equal(exists("../src/app/admin/users/[id]/page.tsx"), true);
  assert.equal(exists("../src/app/admin/products/[id]/page.tsx"), true);

  assert.match(source("../src/app/admin/users/page.tsx"), /AdminUsersPanel/);
  assert.match(source("../src/app/admin/products/page.tsx"), /AdminProductsPanel/);
  assert.match(source("../src/app/admin/users/[id]/page.tsx"), /AdminUserDetailPanel/);
  assert.match(source("../src/app/admin/products/[id]/page.tsx"), /AdminProductDetailPanel/);
});

test("admin sales workbench has a dedicated route and strengthened detail view", () => {
  assert.equal(exists("../src/app/admin/sales-workbench/page.tsx"), true);

  const page = source("../src/app/admin/sales-workbench/page.tsx");
  const panel = source("../src/components/admin/admin-sales-workbench-panel.tsx");
  const detail = source("../src/components/admin/admin-detail-panels.tsx");

  assert.match(page, /AdminSalesWorkbenchPanel/);
  assert.match(panel, /业务员作业看板/);
  assert.match(panel, /今日有动作业务员/);
  assert.match(panel, /外联不足/);
  assert.match(panel, /查看作业明细/);
  assert.match(panel, /AdminCompactActions/);
  assert.match(detail, /负责品牌进度/);
  assert.match(detail, /采集任务/);
  assert.match(detail, /异常记录/);
});

test("admin dashboard and lists expose required real-data fields", () => {
  const dashboard = source("../src/components/admin/admin-dashboard-panel.tsx");
  const users = source("../src/components/admin/admin-users-panel.tsx");
  const products = source("../src/components/admin/admin-products-panel.tsx");
  const api = source("../src/lib/api.ts");

  assert.match(dashboard, /管理员数据看板/);
  assert.match(dashboard, /total_sales/);
  assert.match(dashboard, /total_products/);
  assert.match(dashboard, /total_collection_tasks/);

  for (const field of [
    "bound_products",
    "collection_success_count",
    "collection_failed_count",
    "email_failed_count",
    "pending_reply_count",
    "created_at",
  ]) {
    assert.match(api, new RegExp(field));
    assert.match(users, new RegExp(field));
  }

  for (const field of ["members", "owner_names", "collection_task_count", "influencer_count", "email_count", "reply_count"]) {
    assert.match(products, new RegExp(field));
  }
});

test("browser long-running API calls use the public proxy by default", () => {
  const api = source("../src/lib/api.ts");
  const dockerfile = source("../Dockerfile");
  const compose = source("../../../docker-compose.yml");

  assert.doesNotMatch(api, /NEXT_PUBLIC_LONG_RUNNING_API_URL[\s\S]*127\.0\.0\.1:8000/);
  assert.match(api, /NEXT_PUBLIC_LONG_RUNNING_API_URL[\s\S]*\?\? API_URL/);
  assert.match(dockerfile, /ARG NEXT_PUBLIC_LONG_RUNNING_API_URL=\/api-proxy/);
  assert.match(compose, /NEXT_PUBLIC_LONG_RUNNING_API_URL: \$\{NEXT_PUBLIC_LONG_RUNNING_API_URL:-\/api-proxy\}/);
});

test("admin placeholder modules were replaced with real data panels", () => {
  const collectionTasks = source("../src/app/admin/collection-tasks/page.tsx");
  const influencers = source("../src/app/admin/influencers/page.tsx");
  const emails = source("../src/app/admin/emails/page.tsx");
  const settings = source("../src/app/admin/settings/page.tsx");

  assert.doesNotMatch(`${collectionTasks}\n${influencers}\n${emails}`, /AdminPlaceholderPanel/);
  assert.match(collectionTasks, /AdminCollectionTasksPanel/);
  assert.match(influencers, /AdminInfluencersPanel/);
  assert.match(emails, /AdminEmailsPanel/);
  assert.match(settings, /AdminSettingsPanel/);
});

test("admin influencers page exposes product selector and creation entry", () => {
  const detailPanels = source("../src/components/admin/admin-detail-panels.tsx");

  assert.match(detailPanels, /fetchAdminProducts/);
  assert.match(detailPanels, /ProductCreateDialog/);
  assert.match(detailPanels, /setProductCreateOpen\(true\)/);
  assert.match(detailPanels, /value=\{filters\.brand\}/);
  assert.match(detailPanels, /brandOptions\.map/);
});

test("admin route guard clears non-admin sessions before showing admin pages", () => {
  const guard = source("../src/components/admin/admin-route-guard.tsx");

  assert.match(guard, /getStoredAuthSession\(\)\?\.isAdmin/);
  assert.match(guard, /useState<GuardState>\("checking"\)/);
  assert.match(guard, /clearAuthSession\(\)/);
  assert.match(guard, /\/admin\/login\?error=admin_required/);
});
