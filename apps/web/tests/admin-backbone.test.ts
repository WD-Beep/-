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
  assert.match(panel, /编辑业务员/);
  assert.match(panel, /新增品牌/);
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
    assert.match(api, new RegExp(field));
  }

  const helpers = source("../src/components/admin/admin-ui-helpers.ts");
  assert.match(helpers, /buildSalespersonBrandProgressView/);
  assert.match(helpers, /getAdminWorkStatusMeta/);

  assert.match(products, /业务员品牌进度/);
  assert.match(products, /buildSalespersonBrandProgressView/);
  assert.match(products, /AdminDrawer/);
  assert.match(products, /未分配/);
  assert.match(products, /collection_task_count/);
  assert.match(products, /AdminSalespersonLabel/);
  assert.match(products, /AdminBrandLabel/);
  assert.match(products, /新增业务员/);
  assert.match(products, /admin-products-management/);
});

test("browser long-running API calls use the long-running proxy by default", () => {
  const api = source("../src/lib/api.ts");
  const dockerfile = source("../Dockerfile");
  const compose = source("../../../docker-compose.yml");

  assert.doesNotMatch(api, /NEXT_PUBLIC_LONG_RUNNING_API_URL[\s\S]*127\.0\.0\.1:8000/);
  assert.match(api, /NEXT_PUBLIC_LONG_RUNNING_API_URL[\s\S]*\?\? "\/api-long"/);
  assert.match(dockerfile, /ARG NEXT_PUBLIC_LONG_RUNNING_API_URL=\/api-long/);
  assert.match(compose, /NEXT_PUBLIC_LONG_RUNNING_API_URL: \$\{NEXT_PUBLIC_LONG_RUNNING_API_URL:-\/api-long\}/);
});

test("link knowledge fetch and script generation use the long-running proxy", () => {
  const api = source("../src/lib/api.ts");
  const refreshFunction = api.match(/export async function refreshLinkKnowledgeBase[\s\S]*?return response\.json\(\);\r?\n}/)?.[0] ?? "";
  const generateFunction = api.match(/export async function generateLinkScripts[\s\S]*?return response\.json\(\);\r?\n}/)?.[0] ?? "";
  const regenerateFunction = api.match(/export async function regenerateLinkScript[\s\S]*?return response\.json\(\);\r?\n}/)?.[0] ?? "";

  assert.match(refreshFunction, /LONG_RUNNING_API_URL/);
  assert.doesNotMatch(refreshFunction, /`\$\{API_URL\}\/api\/link-knowledge-bases\/\$\{id\}\/refresh`/);
  assert.match(generateFunction, /LONG_RUNNING_API_URL/);
  assert.doesNotMatch(generateFunction, /`\$\{API_URL\}\/api\/link-knowledge-bases\/\$\{id\}\/generate-scripts`/);
  assert.match(regenerateFunction, /LONG_RUNNING_API_URL/);
  assert.doesNotMatch(regenerateFunction, /`\$\{API_URL\}\/api\/link-script-results\/\$\{id\}\/regenerate`/);
});

test("inbox polling uses the long-running proxy to avoid false request timeouts", () => {
  const api = source("../src/lib/api.ts");
  const pollFunction = api.match(/export async function pollImapInbox[\s\S]*?return response\.json\(\);\r?\n}/)?.[0] ?? "";

  assert.match(pollFunction, /LONG_RUNNING_API_URL/);
  assert.doesNotMatch(pollFunction, /`\$\{API_URL\}\/api\/email-inbound\/poll-imap/);
});

test("long-running proxy returns structured timeout and connection errors", () => {
  const route = source("../src/app/api-long/[...path]/route.ts");

  assert.match(route, /LONG_PROXY_TIMEOUT/);
  assert.match(route, /后端长任务请求超时/);
  assert.match(route, /status:\s*504/);
  assert.match(route, /LONG_PROXY_UNAVAILABLE/);
  assert.match(route, /无法连接后端长任务服务/);
  assert.match(route, /status:\s*502/);
});

test("standard api proxy returns structured timeout and connection errors", () => {
  const route = source("../src/app/api-proxy/[...path]/route.ts");

  assert.match(route, /PROXY_TIMEOUT/);
  assert.match(route, /PROXY_UNAVAILABLE/);
  assert.match(route, /try\s*\{/);
  assert.match(route, /catch \(error\)/);
  assert.match(route, /status:\s*504/);
  assert.match(route, /status:\s*502/);
});

test("docker web service waits for the API healthcheck", () => {
  const compose = source("../../../docker-compose.yml");

  assert.match(compose, /api:[\s\S]*healthcheck:/);
  assert.match(compose, /web:[\s\S]*depends_on:[\s\S]*api:[\s\S]*condition: service_healthy/);
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
  assert.match(detailPanels, /待跟进中心/);
  assert.match(detailPanels, /EmailEditDrawer/);
  assert.match(detailPanels, /AdminFollowUpWorkbench/);
  assert.match(detailPanels, /InfluencerEditDrawer/);
  assert.match(detailPanels, /admin-work-queue/);
  assert.match(detailPanels, /backFallback/);
});

test("admin shared crud shell exposes back navigation and work queue", () => {
  const crud = source("../src/components/admin/admin-crud.tsx");
  const ui = source("../src/components/admin/admin-ui.tsx");
  const workQueue = source("../src/lib/admin-work-queue.ts");
  const followUp = source("../src/components/admin/admin-follow-up-workbench.tsx");
  const influencerDetailPage = source("../src/app/admin/influencers/[id]/page.tsx");

  assert.match(crud, /AdminBackButton/);
  assert.match(crud, /router\.back/);
  assert.match(ui, /createPortal/);
  assert.match(ui, /AdminBackButton/);
  assert.match(ui, /backFallback = "\/admin\/dashboard"/);
  assert.match(workQueue, /reminded/);
  assert.match(workQueue, /remindCount/);
  assert.match(followUp, /全部待跟进/);
  assert.match(followUp, /邮件待跟进/);
  assert.match(followUp, /回复待处理/);
  assert.match(influencerDetailPage, /AdminInfluencerDetailPanel/);
});

test("admin shared navigation actions use client-side links", () => {
  const ui = source("../src/components/admin/admin-ui.tsx");
  const monthlyReport = source("../src/components/admin/admin-monthly-report-panel.tsx");

  assert.match(ui, /import Link from "next\/link"/);
  assert.match(ui, /<Link[\s\S]*href=\{href\}/);
  assert.doesNotMatch(ui, /<a\s+href=\{href\}/);
  assert.doesNotMatch(ui, /<a\s+[\s\S]*href=\{item\.href\}/);

  assert.match(monthlyReport, /import Link from "next\/link"/);
  assert.doesNotMatch(monthlyReport, /<a\s+/);
});

test("admin account dialogs save editable usernames and expose brand management", () => {
  const userDialogs = source("../src/components/admin/admin-user-dialogs.tsx");
  const productManagement = source("../src/components/admin/admin-products-management.tsx");
  const usersPanel = source("../src/components/admin/admin-users-panel.tsx");

  assert.match(userDialogs, /username: username\.trim\(\)/);
  assert.doesNotMatch(userDialogs, /disabled=\{Boolean\(user\)\}/);
  assert.doesNotMatch(userDialogs, /账号创建后不可修改|璐﹀彿鍒涘缓鍚庝笉鍙/);
  assert.match(userDialogs, /AdminBrandManagementDrawer/);
  assert.match(usersPanel, /users=\{items\}/);
  assert.match(usersPanel, /onProductsChanged=\{reloadProducts\}/);

  assert.match(productManagement, /export function AdminBrandManagementDrawer/);
  assert.match(productManagement, /WorkbenchBrandDrawer/);
  assert.match(productManagement, /deleteBrandSafely/);
  assert.match(productManagement, /clearCachedTenantProducts/);
});

test("salesperson brand assignment drawer exposes shared brand management", () => {
  const productManagement = source("../src/components/admin/admin-products-management.tsx");

  assert.match(productManagement, /AdminBrandManagementDrawer/);
  assert.match(productManagement, /setBrandManagementOpen\(true\)/);
  assert.match(productManagement, /onProductsChanged/);
});

test("admin salesperson contact fields accept arbitrary bounded text", () => {
  const userDialogs = source("../src/components/admin/admin-user-dialogs.tsx");
  const productManagement = source("../src/components/admin/admin-products-management.tsx");

  assert.match(userDialogs, /邮箱 \/ 手机 \/ 联系方式/);
  assert.doesNotMatch(userDialogs, /邮箱格式不正确/);
  assert.doesNotMatch(userDialogs, /\^\[\^\\s@\]\+@/);
  assert.doesNotMatch(userDialogs, /inputMode="email"/);

  assert.match(productManagement, /邮箱 \/ 手机 \/ 联系方式/);
  assert.doesNotMatch(productManagement, /contact\.includes\("@"\)/);
  assert.doesNotMatch(productManagement, /<AdminInput type="email"/);
});

test("salesperson deletion uses a simple confirmation and refreshes lists", () => {
  const productManagement = source("../src/components/admin/admin-products-management.tsx");
  const productsPanel = source("../src/components/admin/admin-products-panel.tsx");
  const usersPanel = source("../src/components/admin/admin-users-panel.tsx");
  const deleteDialog = productManagement.match(
    /export function SalespersonDeleteDialog[\s\S]*?export async function disableSalesperson/,
  )?.[0] ?? "";

  assert.match(deleteDialog, /登录账号/);
  assert.match(deleteDialog, /关联品牌/);
  assert.match(deleteDialog, /关联任务/);
  assert.match(deleteDialog, /确认删除/);
  assert.doesNotMatch(deleteDialog, /停用业务员/);
  assert.doesNotMatch(deleteDialog, /转移名下品牌/);
  assert.doesNotMatch(productsPanel, /salespersonHasRelatedData\(panelAction\.user, panelAction\.row\)/);
  assert.match(productsPanel, /await reload\(\)/);
  assert.match(usersPanel, /deleteAdminUser/);
  assert.match(usersPanel, /删除/);
  assert.match(usersPanel, /await reloadAll\(\)/);
});

test("admin users page does not block initial list on product permission loading", () => {
  const usersPanel = source("../src/components/admin/admin-users-panel.tsx");

  assert.doesNotMatch(usersPanel, /Promise\.all\(\[fetchAdminUsers\(\), fetchAdminProducts\(\)\]\)/);
  assert.match(usersPanel, /ensureProductsLoaded/);
});

test("admin route guard clears non-admin sessions before showing admin pages", () => {
  const guard = source("../src/components/admin/admin-route-guard.tsx");

  assert.match(guard, /getStoredAuthSession\(\)\?\.isAdmin/);
  assert.match(guard, /useState<GuardState>\(\(\) =>/);
  assert.match(guard, /\? "allowed" : "checking"/);
  assert.match(guard, /clearAuthSession\(\)/);
  assert.match(guard, /\/admin\/login\?error=admin_required/);
});

test("admin login page is not server-redirected by a stale auth cookie", () => {
  const middleware = source("../src/middleware.ts");
  const adminLoginBlock = middleware.match(/if \(isAdminLoginPage\) \{[\s\S]*?\n  \}/)?.[0] ?? "";

  assert.match(adminLoginBlock, /return NextResponse\.next\(\)/);
  assert.doesNotMatch(adminLoginBlock, /\/admin\/dashboard/);
});

test("admin login redirects without a blocking router refresh", () => {
  const loginForm = source("../src/components/auth/admin-login-form.tsx");

  assert.match(loginForm, /const redirectTo = searchParams\.get\("from"\) \|\| "\/admin\/dashboard"/);
  assert.match(loginForm, /router\.replace\(redirectTo\)/);
  assert.doesNotMatch(loginForm, /router\.refresh\(\)/);
});

test("sales login page is not server-redirected by a stale auth cookie", () => {
  const middleware = source("../src/middleware.ts");
  const loginBlock = middleware.match(/if \(isLoginPage\) \{[\s\S]*?\n  \}/)?.[0] ?? "";

  assert.match(loginBlock, /return NextResponse\.next\(\)/);
  assert.doesNotMatch(loginBlock, /NextResponse\.redirect\(new URL\("\/"/);
});

test("sales sidebar reuses product options across route remounts", () => {
  const sidebar = source("../src/components/layout/sidebar.tsx");

  assert.match(sidebar, /PRODUCT_OPTIONS_MEMORY_CACHE_TTL_MS/);
  assert.match(sidebar, /productOptionsInflight/);
  assert.match(sidebar, /readFreshProductOptionsMemoryCache/);
  assert.match(sidebar, /fetchTenantProductsShared/);
  assert.match(sidebar, /setProductsLoading\(false\)/);
});

test("sales sidebar shows current sender email without blocking navigation", () => {
  const sidebar = source("../src/components/layout/sidebar.tsx");

  assert.match(sidebar, /fetchMySmtpAccount/);
  assert.match(sidebar, /smtpAccountInflight/);
  assert.match(sidebar, /邮箱配置/);
  assert.match(sidebar, /当前发件/);
  assert.match(sidebar, /\/settings/);
});

test("settings page exposes optional salesperson email configuration", () => {
  const settings = source("../src/components/settings/settings-panel.tsx");
  const api = source("../src/lib/api.ts");

  assert.match(settings, /我的发件邮箱/);
  assert.match(settings, /邮箱地址/);
  assert.match(settings, /发信授权码/);
  assert.match(settings, /收信授权码/);
  assert.match(settings, /收信授权码与发信授权码相同/);
  assert.match(settings, /saveMySmtpAccount/);
  assert.match(settings, /testMySmtpAccount/);
  assert.match(api, /imap_password/);
  assert.match(api, /provider\?:/);
});

test("link script results show simple outreach copy instead of raw JSON", () => {
  const panel = source("../src/components/link-knowledge-bases/link-knowledge-panels.tsx");

  assert.match(panel, /getPrimaryLinkScriptText/);
  assert.match(panel, /getPrimaryLinkScriptKey/);
  assert.match(panel, /FULL_LINK_SCRIPT_MIN_WORDS/);
  assert.match(panel, /Why I thought of you/);
  assert.match(panel, /Collaboration idea/);
  assert.match(panel, /primary_script/);
  assert.match(panel, /复制话术/);
  assert.doesNotMatch(panel, /复制 JSON/);
  assert.doesNotMatch(panel, /setEditText\(stringifyJson\(selected\.edited_content \?\? selected\.generated_content\)\)/);
});
