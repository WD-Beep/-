import assert from "node:assert/strict";
import test from "node:test";

import {
  cleanBackendErrorMessage,
  deleteAdminUser,
  fetchDashboardSummary,
} from "../src/lib/api.ts";

async function getDashboardErrorMessage(response: Response): Promise<string> {
  const originalFetch = globalThis.fetch;
  let caught: unknown;
  globalThis.fetch = (async () => response) as typeof fetch;
  try {
    await fetchDashboardSummary();
  } catch (error) {
    caught = error;
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.ok(caught instanceof Error);
  return caught.message;
}

test("link import validation errors are shown as friendly task-form guidance", () => {
  assert.equal(
    cleanBackendErrorMessage("body: Value error, 链接导入至少需要一个链接"),
    "请先粘贴至少一个链接，或切回关键词发现模式。",
  );
});

test("405 errors do not expose the English Method Not Allowed message", async () => {
  const message = await getDashboardErrorMessage(
    new Response("Method Not Allowed", { status: 405 }),
  );

  assert.equal(message, "请求方法不被允许，请检查接口是否支持该操作。");
  assert.doesNotMatch(message, /Method Not Allowed/i);
});

test("admin delete 405 errors use the unified Chinese message", async () => {
  const originalFetch = globalThis.fetch;
  let caught: unknown;
  globalThis.fetch = (async () =>
    new Response("Method Not Allowed", { status: 405 })) as typeof fetch;
  try {
    await deleteAdminUser(12);
  } catch (error) {
    caught = error;
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.ok(caught instanceof Error);
  assert.equal(caught.message, "请求方法不被允许，请检查接口是否支持该操作。");
  assert.doesNotMatch(caught.message, /Method Not Allowed/i);
});

test("admin user deletion uses the long-running proxy to avoid false timeouts", async () => {
  const originalFetch = globalThis.fetch;
  let requestedUrl = "";
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    requestedUrl = String(input);
    return new Response(
      JSON.stringify({
        success: true,
        deleted_user_id: 12,
        released_products: 0,
        released_tasks: 0,
        cancelled_campaigns: 0,
        cancelled_queue_items: 0,
        preserved_history_records: true,
        preserved_history_count: 0,
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  }) as typeof fetch;
  try {
    await deleteAdminUser(12);
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.match(requestedUrl, /^\/api-long\/api\/admin\/users\/12$/);
});

test("admin deletion permission errors explain the admin session problem", async () => {
  const originalFetch = globalThis.fetch;
  let caught: unknown;
  globalThis.fetch = (async () =>
    new Response(JSON.stringify({ detail: "Admin access required" }), {
      status: 403,
      headers: { "Content-Type": "application/json" },
    })) as typeof fetch;
  try {
    await deleteAdminUser(12);
  } catch (error) {
    caught = error;
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.ok(caught instanceof Error);
  assert.equal(caught.message, "管理员登录状态已失效或被业务员账号覆盖，请重新登录后台后再操作。");
});

test("Pydantic email validation errors are shown as understandable Chinese", async () => {
  const message = await getDashboardErrorMessage(
    new Response(
      JSON.stringify({
        detail: [
          {
            type: "value_error",
            loc: ["body", "email"],
            msg: "value is not a valid email address: An email address must have an @-sign.",
          },
        ],
      }),
      { status: 422 },
    ),
  );

  assert.equal(message, "邮箱格式不正确，请输入有效的邮箱地址。");
  assert.doesNotMatch(message, /valid email|address|@-sign/i);
});

test("Chinese backend error messages are preserved for the UI", () => {
  assert.equal(cleanBackendErrorMessage("用户名已存在"), "用户名已存在");
  assert.equal(
    cleanBackendErrorMessage("该业务员仍有关联数据，请先转移品牌和任务，或选择停用账号。"),
    "该业务员仍有关联数据，请先转移品牌和任务，或选择停用账号。",
  );
});

test("unknown backend error text is replaced instead of leaking to the UI", async () => {
  const backendMessage = "sqlalchemy.exc.OperationalError: connection refused at internal-db";
  const message = await getDashboardErrorMessage(
    new Response(backendMessage, { status: 400 }),
  );

  assert.equal(message, "请求失败，请稍后重试。");
  assert.doesNotMatch(message, /sqlalchemy|connection refused|internal-db/i);
});

