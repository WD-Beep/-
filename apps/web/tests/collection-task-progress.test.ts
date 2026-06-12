import assert from "node:assert/strict";
import test from "node:test";

import {
  COLLECTION_TASK_TABLE_LAYOUT,
  collectionTaskDiscoveryContext,
  collectionTaskFunnelLine,
  collectionTaskProgressSummary,
  collectionTaskRunningHint,
  COLLECTION_TASK_SLOW_FALLBACK_MS,
  collectionTaskSlowApiHintLabel,
  formatCollectionResultLines,
  formatInsertedVsTarget,
  isCollectionTaskSlowApi,
  isCollectionTaskSlowApiFromBackend,
} from "../src/lib/collection-task-progress.ts";
import {
  buildInfluencerExportUrl,
  isCollectionTaskRunningStale,
  type CollectionTask,
} from "../src/lib/api.ts";
import { PLATFORM_LABELS } from "../src/lib/labels.ts";

function task(overrides: Partial<CollectionTask>): CollectionTask {
  return {
    id: 1,
    name: "test task",
    collection_mode: "keyword",
    platform: "youtube",
    platforms: ["youtube"],
    keywords: ["amazon seller"],
    input_urls: [],
    country: null,
    category: null,
    discovery_limit: 10,
    min_engagement_rate: 2,
    min_followers_count: 50000,
    max_followers_count: null,
    filter_include_keywords: [],
    filter_exclude_keywords: [],
    status: "running",
    schedule_enabled: false,
    schedule_cron: null,
    email_enabled: false,
    email_recipients: [],
    outreach_enabled: false,
    outreach_provider: "smtp",
    outreach_dry_run: true,
    outreach_templates: {},
    last_run_at: null,
    next_run_at: null,
    result_count: 0,
    email_count: 0,
    missing_contact_count: 0,
    discovered_count: 0,
    deduped_count: 0,
    profile_fetched_count: 0,
    profile_failed_count: 0,
    filtered_out_count: 0,
    inserted_count: 0,
    hashtag_count: 0,
    post_count: 0,
    comment_author_count: 0,
    filtered_below_min_followers_count: 0,
    filtered_excluded_keyword_count: 0,
    processed_count: 0,
    success_count: 0,
    failed_count: 0,
    skipped_count: 0,
    total_estimate: 0,
    current_stage: "discovery",
    last_error: null,
    run_checkpoint: {},
    stale: false,
    recoverable: false,
    stale_after_seconds: 300,
    status_summary: "发现候选中；可能原因：关键词搜索/API 调用中暂时无结果",
    error_message: null,
    comment_discovery_enabled: false,
    created_at: "2026-06-07T00:00:00Z",
    updated_at: "2026-06-07T00:00:00Z",
    ...overrides,
  };
}

test("running stale state is driven by backend flags", () => {
  assert.equal(
    isCollectionTaskRunningStale(
      task({
        updated_at: "2000-01-01T00:00:00Z",
        stale: false,
        recoverable: false,
      }),
    ),
    false,
  );
  assert.equal(isCollectionTaskRunningStale(task({ stale: true, recoverable: false })), true);
  assert.equal(isCollectionTaskRunningStale(task({ stale: false, recoverable: true })), true);
  assert.equal(isCollectionTaskRunningStale(task({ status: "failed", stale: true, recoverable: true })), false);
});

test("progress summary prioritizes structured progress fields", () => {
  const summary = collectionTaskProgressSummary(
    task({
      status: "running",
      current_stage: "persist",
      processed_count: 12,
      total_estimate: 20,
      success_count: 7,
      skipped_count: 3,
      failed_count: 2,
    }),
  );

  assert.equal(summary.hasStructuredProgress, true);
  assert.equal(summary.primary, "过滤入库 12/20");
  assert.equal(summary.detail, "成功 7 / 跳过 3 / 失败 2");
});

test("progress summary still shows a stage before counters move", () => {
  const summary = collectionTaskProgressSummary(task({ current_stage: "discovery", discovery_limit: 100 }));

  assert.equal(summary.hasStructuredProgress, true);
  assert.match(summary.primary, /正在采集|发现候选/);
});

test("progress helpers tolerate empty checkpoint fields", () => {
  const runningTask = task({
    run_checkpoint: undefined,
    status_summary: null,
    last_error: null,
  });
  assert.equal(collectionTaskDiscoveryContext(runningTask), null);
  assert.doesNotThrow(() => collectionTaskRunningHint(runningTask));
  assert.doesNotThrow(() => collectionTaskProgressSummary(runningTask));
  assert.doesNotThrow(() => formatCollectionResultLines(runningTask));
});

test("running rate limited task shows explicit retry message", () => {
  const summary = collectionTaskProgressSummary(
    task({
      current_stage: "discovery",
      discovered_count: 224,
      deduped_count: 194,
      profile_fetched_count: 194,
      run_checkpoint: { rate_limited: true },
      last_error: "API Direct 限流 (429)",
    }),
  );

  assert.equal(summary.rateLimited, true);
  assert.equal(summary.primary, "接口限流/降速重试");
  assert.match(summary.detail, /已入库 0 \/ 目标 10/);
  assert.match(summary.detail, /224/);
});

test("inserted vs target label is human readable", () => {
  assert.equal(formatInsertedVsTarget(task({ inserted_count: 0, discovery_limit: 28 })), "已入库 0 / 目标 28");
  assert.match(
    collectionTaskFunnelLine(
      task({
        discovered_count: 10,
        deduped_count: 8,
        profile_fetched_count: 8,
        discovery_limit: 28,
      }),
    ),
    /入库 0\/28/,
  );
});

test("stale recoverable running task is flagged", () => {
  const staleTask = task({ stale: true, recoverable: true });
  assert.equal(isCollectionTaskRunningStale(staleTask), true);
  const hint = collectionTaskRunningHint(staleTask);
  assert.ok(hint);
  assert.match(hint!, /重新运行继续/);
});

test("running task shows current keyword from checkpoint", () => {
  const runningTask = task({
    run_checkpoint: {
      current_keyword: "amazon seller",
      discovery_provider: "apify",
      keywords_completed: 2,
      keywords_total: 10,
      slow_api: true,
    },
  });
  const hint = collectionTaskRunningHint(runningTask, { elapsedMs: 0 });
  assert.ok(hint);
  assert.match(hint!, /amazon seller/);
  assert.match(hint!, /Apify YouTube/);
  assert.match(hint!, /2\/10/);
  assert.match(hint!, /接口响应较慢，继续处理/);
});

test("running facebook task shows hydration progress and partial skip", () => {
  const runningTask = task({
    platform: "facebook",
    platforms: ["facebook"],
    discovered_count: 7,
    run_checkpoint: {
      current_keyword: "brand page",
      discovery_provider: "apify",
      keywords_completed: 3,
      keywords_total: 10,
      profiles_hydrating_total: 7,
      profiles_hydrating_completed: 2,
      slow_api: true,
      partial_skip_note: "Facebook Apify 主页补采超时，已跳过该主页并继续",
    },
  });
  const context = collectionTaskDiscoveryContext(runningTask);
  assert.ok(context);
  assert.match(context!, /brand page/);
  assert.match(context!, /已发现 7 个候选/);
  assert.match(context!, /补采主页 2\/7/);

  const hint = collectionTaskRunningHint(runningTask, { elapsedMs: 0 });
  assert.ok(hint);
  assert.match(hint!, /接口响应较慢，继续处理/);
  assert.match(hint!, /部分已跳过，继续处理/);
});

test("slow api fallback uses 3 minute default threshold", () => {
  assert.equal(COLLECTION_TASK_SLOW_FALLBACK_MS, 180_000);
  const runningTask = task({});
  assert.equal(isCollectionTaskSlowApi(runningTask, 120_000), false);
  assert.equal(isCollectionTaskSlowApi(runningTask, 180_000), true);
  assert.equal(collectionTaskSlowApiHintLabel(runningTask, 120_000), null);
  assert.equal(
    collectionTaskSlowApiHintLabel(runningTask, 180_000),
    "等待较久，接口可能响应慢，请稍候",
  );
  const hint = collectionTaskRunningHint(runningTask, { elapsedMs: 180_000 });
  assert.ok(hint);
  assert.match(hint!, /等待较久，接口可能响应慢/);
});

test("backend slow_api flag triggers immediately without elapsed wait", () => {
  const runningTask = task({
    run_checkpoint: { slow_api: true },
  });
  assert.equal(isCollectionTaskSlowApiFromBackend(runningTask), true);
  assert.equal(isCollectionTaskSlowApi(runningTask, 0), true);
  assert.equal(collectionTaskSlowApiHintLabel(runningTask, 0), "接口响应较慢，继续处理");
  const hint = collectionTaskRunningHint(runningTask, { elapsedMs: 0 });
  assert.ok(hint);
  assert.match(hint!, /接口响应较慢，继续处理/);
  assert.doesNotMatch(hint!, /等待较久/);
});

test("collection result lines include inserted and funnel", () => {
  const lines = formatCollectionResultLines(
    task({
      discovered_count: 5,
      deduped_count: 4,
      profile_fetched_count: 3,
      filtered_out_count: 2,
      inserted_count: 1,
      discovery_limit: 10,
    }),
  );
  assert.equal(lines.primary, "已入库 1 / 目标 10");
  assert.match(lines.funnel, /发现 5 → 去重 4 → 主页 3 → 过滤 2 → 入库 1\/10/);
});

test("table layout classes keep status and actions readable", () => {
  assert.match(COLLECTION_TASK_TABLE_LAYOUT.statusCell, /min-w-\[88px\]/);
  assert.match(COLLECTION_TASK_TABLE_LAYOUT.statusBadge, /whitespace-nowrap/);
  assert.match(COLLECTION_TASK_TABLE_LAYOUT.actionsCell, /w-\[180px\]/);
  assert.match(COLLECTION_TASK_TABLE_LAYOUT.actionsGroup, /flex-nowrap/);
  assert.match(COLLECTION_TASK_TABLE_LAYOUT.actionButton, /shrink-0/);
});

test("high value export URL passes backend filter flag", () => {
  const url = buildInfluencerExportUrl({
    highValue: true,
    collectionTaskId: 52,
    platform: "facebook",
  });

  assert.equal(url.includes("high_value=true"), true);
  assert.equal(url.includes("collection_task_id=52"), true);
  assert.equal(url.includes("platform=facebook"), true);
});

test("platform labels include URL-only commerce platforms", () => {
  assert.equal(PLATFORM_LABELS.pinterest, "Pinterest");
  assert.equal(PLATFORM_LABELS.ltk, "LTK");
  assert.equal(PLATFORM_LABELS.shopmy, "ShopMy");
});

test("collection result lines preserve clearer youtube external-link explanation", () => {
  const lines = formatCollectionResultLines(
    task({
      status: "completed_no_results",
      discovered_count: 18,
      deduped_count: 12,
      profile_fetched_count: 12,
      filtered_out_count: 12,
      inserted_count: 0,
      status_summary:
        "已发现主页外链 12 个，其中商业外链 6 个（Amazon storefront、ShopMy、独立站），另有 Instagram、TikTok、Linktree；但多数仅有社媒跳转，缺少有效联系方式或商业落地页，暂未入库。",
    }),
  );

  assert.equal(lines.primary, "已入库 0 / 目标 10");
  assert.ok(lines.hint);
  assert.match(lines.hint!, /主页外链 12 个/);
  assert.match(lines.hint!, /Amazon storefront/);
  assert.match(lines.hint!, /Instagram/);
  assert.match(lines.hint!, /TikTok/);
  assert.match(lines.hint!, /Linktree/);
  assert.match(lines.hint!, /缺少有效联系方式或商业落地页/);
});
