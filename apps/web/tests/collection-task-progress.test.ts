import "./register-path-aliases.ts";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  COLLECTION_TASK_TABLE_LAYOUT,
  collectionTaskProviderDiagnosticHint,
  collectionTaskSeedDiscoveryDiagnosticHint,
  collectionTaskDiscoveryContext,
  collectionTaskFunnelLine,
  collectionTaskProgressSummary,
  collectionTaskRunningHint,
  COLLECTION_TASK_SLOW_FALLBACK_MS,
  collectionTaskSlowApiHintLabel,
  formatCollectionResultLines,
  buildTaskResultBreakdown,
  formatInsertedVsTarget,
  isCollectionTaskSlowApi,
  isCollectionTaskSlowApiFromBackend,
} from "../src/lib/collection-task-progress.ts";
import {
  buildCollectionTaskCompletionMessage,
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
    require_email: false,
    require_contact: false,
    strict_quality_filter: false,
    insert_qualified_only: false,
    export_qualified_only: false,
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

test("candidate dialog wires youtube email enrichment buttons to API and refreshes list", () => {
  const apiSource = readFileSync(new URL("../src/lib/api.ts", import.meta.url), "utf8");
  assert.match(apiSource, /enrichYoutubeCandidateEmail/);
  assert.match(apiSource, /collection-tasks\/\$\{taskId\}\/candidates\/\$\{candidateId\}\/enrich-youtube-email/);
  assert.match(apiSource, /enrichYoutubeCandidateEmails/);
  assert.match(apiSource, /collection-tasks\/\$\{taskId\}\/candidates\/enrich-youtube-emails/);

  const dialogSource = readFileSync(
    new URL("../src/components/collection-tasks/task-candidates-dialog.tsx", import.meta.url),
    "utf8",
  );
  assert.match(dialogSource, /enrichYoutubeCandidateEmail/);
  assert.match(dialogSource, /enrichYoutubeCandidateEmails/);
  assert.match(dialogSource, /handleEnrichYoutubeEmail/);
  assert.match(dialogSource, /handleBatchEnrichYoutubeEmails/);
  assert.match(dialogSource, /补邮箱/);
  assert.match(dialogSource, /批量补 YouTube 邮箱/);
  assert.match(dialogSource, /refreshCandidates/);
});

test("candidate dialog avoids opening jitter from filter reset and loading layout changes", () => {
  const dialogSource = readFileSync(
    new URL("../src/components/collection-tasks/task-candidates-dialog.tsx", import.meta.url),
    "utf8",
  );

  assert.match(dialogSource, /filtersReady/);
  assert.match(dialogSource, /if \(!open \|\| !task \|\| !filtersReady\) return/);
  assert.match(dialogSource, /h-\[90vh\] max-h-\[760px\]/);
  assert.doesNotMatch(dialogSource, /queueMicrotask\(\(\) => \{\s*setExportError/);
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
  assert.match(hint!, /继续运行/);
});

test("running task shows current keyword from checkpoint", () => {
  const runningTask = task({
    run_checkpoint: {
      current_keyword: "amazon seller",
      discovery_provider: "apify",
      keywords_completed: 2,
      keywords_total: 10,
      slow_api: true,
      timeout_skipped_keywords_count: 1,
    },
  });
  const hint = collectionTaskRunningHint(runningTask, { elapsedMs: 0 });
  assert.ok(hint);
  assert.match(hint!, /amazon seller/);
  assert.match(hint!, /Apify YouTube/);
  assert.match(hint!, /2\/10/);
  assert.match(hint!, /正在等待 Apify 返回/);
  assert.match(hint!, /YouTube\/Facebook 响应较慢，系统会超时跳过慢关键词/);
  assert.match(hint!, /已跳过 1 个超时关键词/);
  assert.match(hint!, /接口响应较慢，继续处理/);
});

test("task form warns on many youtube or facebook keywords without blocking", () => {
  const source = readFileSync(
    new URL("../src/components/collection-tasks/task-form-dialog.tsx", import.meta.url),
    "utf8",
  );
  assert.match(source, /showSlowPlatformCreateHint/);
  assert.match(source, /YouTube\/Facebook 可能较慢，建议先用 2-3 个关键词验证/);
  assert.match(source, /系统会超时跳过慢关键词，不会阻断任务/);
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

test("link import funnel shows post link stage", () => {
  const funnel = collectionTaskFunnelLine(
    task({
      collection_mode: "link_import",
      discovered_count: 1,
      deduped_count: 1,
      post_count: 1,
      profile_fetched_count: 1,
      inserted_count: 1,
      discovery_limit: null as unknown as number,
    }),
  );
  assert.match(funnel, /发现 1 → 作品链接 1 → 主页 1 → 入库 1\/目标未设置/);
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

test("task result breakdown exposes structured funnel metrics", () => {
  const lines = buildTaskResultBreakdown(
    task({
      status: "partial_failed",
      collection_mode: "competitor_product",
      inserted_count: 21,
      result_count: 21,
      discovery_limit: 50,
      discovered_count: 574,
      deduped_count: 481,
      profile_fetched_count: 481,
      filtered_out_count: 109,
      email_count: 3,
      missing_contact_count: 18,
      failed_count: 12,
      status_summary: "Instagram API 失败",
    }),
  );

  assert.deepEqual(lines.primary, ["已入库 21 / 目标 50"]);
  assert.deepEqual(lines.funnel, ["发现 574", "去重 481", "主页 481", "过滤 109"]);
  assert.deepEqual(lines.contacts, ["邮箱 3", "缺联系方式 18", "失败 12"]);
  assert.equal(lines.reason, "主要原因：Instagram API 失败");
  assert.equal(lines.highValue, true);
});

test("zero-result diagnostics explain strict contact and quality filters", () => {
  const lines = formatCollectionResultLines(
    task({
      status: "completed_no_results",
      discovered_count: 29,
      deduped_count: 26,
      profile_fetched_count: 22,
      filtered_out_count: 22,
      inserted_count: 0,
      require_email: true,
      require_contact: true,
      run_checkpoint: {
        filtered_by_contact_count: 14,
        filtered_by_product_match_count: 5,
      },
      filtered_below_min_followers_count: 6,
      filtered_excluded_keyword_count: 2,
    }),
  );

  assert.ok(lines.hint);
  assert.match(lines.hint!, /发现 29 个候选/);
  assert.match(lines.hint!, /补全主页 22 个/);
  assert.match(lines.hint!, /最终入库 0/);
  assert.match(lines.hint!, /必须有邮箱\/联系方式/);
  assert.match(lines.hint!, /粉丝或互动条件/);
  assert.match(lines.hint!, /同款商品证据/);
  assert.match(lines.hint!, /关闭必须邮箱\/联系方式/);
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

test("competitor product diagnostics explain provider states and same-product filtering", () => {
  const apifyLimited = task({
    collection_mode: "competitor_product",
    status: "completed_no_results",
    status_summary: "多平台采集部分平台异常",
    run_checkpoint: {
      platform_api_counts: { tiktok: 1, facebook: 0 },
      provider_availability_state: {
        tiktok: {
          status: "provider_unavailable",
          reason: "apify_memory_limit_exceeded",
          message: "Apify 内存额度已满/并发 actor 过多",
          api_calls: 1,
        },
        facebook: {
          status: "provider_unavailable",
          reason: "provider_not_configured",
          message: "Facebook Apify 暂未配置（缺少 APIFY_TOKEN）",
          api_calls: 0,
        },
      },
    },
  });

  const hint = collectionTaskProviderDiagnosticHint(apifyLimited);
  assert.ok(hint);
  assert.match(hint!, /TikTok：Apify 额度不足\/并发 actor 过多，已跳过该通道（API 1 calls）/);
  assert.match(hint!, /Facebook：provider 未配置，已提前跳过（API 0 calls）/);
  assert.equal(formatCollectionResultLines(apifyLimited).hint, hint);

  const filtered = task({
    collection_mode: "competitor_product",
    status: "completed_no_results",
    status_summary: "youtube: no same-product results (API 4 calls)",
  });
  assert.equal(collectionTaskProviderDiagnosticHint(filtered), "找到相关类目红人但无同款证据，未入库");

  const missingAuthor = task({
    collection_mode: "competitor_product",
    status: "partial_failed",
    error_message: "[instagram] Hashtag 帖子 MISS111 post_author_missing: 无法提取作者主页 raw_fields=shortCode,owner.id",
  });
  assert.equal(collectionTaskProviderDiagnosticHint(missingAuthor), "找到帖子但未解析到作者，已记录 raw 字段诊断");
});

test("competitor product diagnostics explain Instagram cross-platform probe outcome", () => {
  const probed = task({
    collection_mode: "competitor_product",
    status: "completed_no_results",
    status_summary: "TikTok/YouTube found but Instagram empty",
    run_checkpoint: {
      competitor_product_instagram_fallback: {
        cross_platform_probe_candidates: [
          { platform: "tiktok", username: "allstarsteven" },
          { platform: "youtube", display_name: "Sew Simple Home" },
        ],
        probe_query_count: 8,
        probe_profile_url_count: 2,
        matched_instagram_count: 0,
        inherited_evidence_count: 0,
      },
    },
  });

  const hint = collectionTaskProviderDiagnosticHint(probed);
  assert.ok(hint);
  assert.match(hint!, /已找到 TikTok\/YouTube Amazon 带货证据/);
  assert.match(hint!, /Instagram 直接关键词未命中或未通过同款证据/);
  assert.match(hint!, /已尝试按 TikTok\/YouTube username\/display_name 反查 Instagram/);
  assert.match(hint!, /建议放宽互动率\/粉丝阈值，或启用跨平台证据继承/);
});

test("running competitor product context shows timed out platform provider", () => {
  const running = task({
    status: "running",
    collection_mode: "competitor_product",
    current_stage: "discovery",
    run_checkpoint: {
      platform_discovery_status: { youtube: "done", tiktok: "timeout_skipped" },
      provider_availability_state: {
        tiktok: {
          status: "provider_unavailable",
          reason: "timeout",
          message: "tiktok 平台发现超时（90s），已跳过该平台继续其他平台",
          api_calls: 0,
        },
      },
    },
  });

  const context = collectionTaskDiscoveryContext(running);
  assert.ok(context);
  assert.match(context!, /TikTok超时跳过/);
  assert.match(context!, /TikTok：平台 provider 超时，已跳过（API 0 calls）/);
});

test("link seed zero-result diagnostics explain missing seed search provider", () => {
  const seedTask = task({
    collection_mode: "link_seed_discovery",
    status: "completed_no_results",
    status_summary: "导购 seed 自动发现完成：发现 0 个 seed",
    run_checkpoint: {
      shopping_seed_discovery: {
        seed_search_disabled: true,
        zero_seed_reason: "seed_search_provider_not_configured",
        provider_call_count: 0,
        search_platforms: [],
        queries: [
          "B0D9W576KQ",
          "HOMEHIVE LTK",
          "HOMEHIVE ShopMy",
          "HOMEHIVE Amazon finds",
          "HOMEHIVE clear PVC jewelry bags",
        ],
      },
    },
  });

  const hint = collectionTaskSeedDiscoveryDiagnosticHint(seedTask);
  assert.ok(hint);
  assert.match(hint!, /未配置 LTK\/ShopMy\/Pinterest seed 搜索来源/);
  assert.match(hint!, /Amazon 商品查询词已生成但未执行外部搜索/);
  assert.match(hint!, /HOMEHIVE LTK/);
  assert.match(hint!, /HOMEHIVE ShopMy/);
  assert.match(hint!, /HOMEHIVE Amazon finds/);
  assert.doesNotMatch(hint!, /邮箱|粉丝|互动率/);

  const lines = formatCollectionResultLines(seedTask);
  assert.equal(lines.hint, hint);

  const toast = buildCollectionTaskCompletionMessage(seedTask);
  assert.equal(toast.tone, "warning");
  assert.equal(toast.message, hint);
  assert.doesNotMatch(toast.message, /未发现符合条件的红人/);
});

test("link seed zero-result diagnostics explain ShopMy keyword provider gap", () => {
  const seedTask = task({
    collection_mode: "link_seed_discovery",
    status: "completed_no_results",
    status_summary: "ShopMy keyword seed discovery completed: found 0 seeds.",
    run_checkpoint: {
      shopping_seed_discovery: {
        seed_search_disabled: false,
        zero_seed_reason: "shopmy_keyword_search_requires_authenticated_provider",
        provider_call_count: 10,
        search_platforms: ["public_web"],
        queries: ["amazon finds", "amazon storefront shopmy", "amazon influencer shopmy"],
      },
    },
  });

  const hint = collectionTaskSeedDiscoveryDiagnosticHint(seedTask);
  assert.ok(hint);
  assert.match(hint!, /ShopMy 关键词搜索未配置授权来源/);
  assert.match(hint!, /公共网页和 ShopMy 页面搜索/);
  assert.match(hint!, /amazon finds/);

  const lines = formatCollectionResultLines(seedTask);
  assert.equal(lines.hint, hint);
});

test("link seed diagnostics summarize Pinterest Apify network outage", () => {
  const seedTask = task({
    collection_mode: "link_seed_discovery",
    status: "completed_no_results",
    status_summary:
      "Seed search query amazon finds pinterest creator: pinterest_apify:Apify 网络错误: All connection attempts failed",
    error_message:
      "Seed search query amazon finds pinterest creator: pinterest_apify:Apify 网络错误: All connection attempts failed; Seed search query amazon storefront pinterest creator: pinterest_apify:Apify 网络错误: All connection attempts failed",
    run_checkpoint: {
      failed_queries: [
        "amazon finds pinterest creator",
        "amazon storefront pinterest creator",
        "amazon influencer pinterest creator",
      ],
      query_errors: {
        "amazon finds pinterest creator": [
          "pinterest_apify:network_unreachable:Apify 网络错误: All connection attempts failed",
        ],
        "amazon storefront pinterest creator": ["pinterest_apify:provider_unavailable:network_unreachable"],
        "amazon influencer pinterest creator": ["pinterest_apify:provider_unavailable:network_unreachable"],
      },
      provider_availability_state: {
        pinterest_apify: {
          status: "provider_unavailable",
          reason: "network_unreachable",
          message: "当前环境无法连接 Apify（api.apify.com:443）",
        },
      },
      shopping_seed_discovery: {
        seed_search_disabled: false,
        zero_seed_reason: "seed_search_no_profiles_returned",
        provider_call_count: 6,
        search_platforms: ["public_web", "pinterest_apify"],
        queries: ["amazon finds pinterest creator", "amazon storefront", "amazon influencer"],
      },
    },
  });

  const hint = collectionTaskSeedDiscoveryDiagnosticHint(seedTask);
  assert.ok(hint);
  assert.match(hint!, /Pinterest 搜索服务当前不可达，已跳过该通道/);
  assert.match(hint!, /当前环境无法连接 Apify（api\.apify\.com:443）/);
  assert.match(hint!, /已继续尝试其他可用搜索源/);
  assert.match(hint!, /3 条 Pinterest query 因网络不可达被跳过/);
  assert.doesNotMatch(hint!, /All connection attempts failed/);

  const lines = formatCollectionResultLines(seedTask);
  assert.equal(lines.hint, hint);
});

test("link seed diagnostics explain Apify timeout followed by empty public web fallback", () => {
  const seedTask = task({
    collection_mode: "link_seed_discovery",
    status: "completed_no_results",
    run_checkpoint: {
      completed_queries: ["HOMEHIVE LTK", "HOMEHIVE ShopMy", "site:shopmy.us HOMEHIVE clear PVC jewelry bags"],
      failed_queries: ["HOMEHIVE Pinterest"],
      query_errors: {
        "HOMEHIVE Pinterest": ["pinterest_apify:query_timeout"],
      },
      provider_availability_state: {
        pinterest_apify: {
          status: "provider_unavailable",
          reason: "query_timeout",
          message: "Pinterest Apify 搜索请求超时，已跳过后续 Pinterest Apify 查询",
        },
      },
      shopping_seed_discovery: {
        seed_search_disabled: false,
        zero_seed_reason: "provider_failed_but_fallback_no_results",
        provider_call_count: 8,
        public_web_query_count: 4,
        search_platforms: ["public_web", "pinterest_apify"],
        queries: ["HOMEHIVE LTK", "HOMEHIVE ShopMy", "site:shopmy.us HOMEHIVE clear PVC jewelry bags"],
      },
    },
  });

  const hint = collectionTaskSeedDiscoveryDiagnosticHint(seedTask);
  assert.ok(hint);
  assert.match(hint!, /Pinterest Apify 超时，已跳过该通道/);
  assert.match(hint!, /已继续尝试公共网页搜索 \/ LTK \/ ShopMy fallback/);
  assert.match(hint!, /公共搜索未返回可用 seed/);
  assert.match(hint!, /缩小商品词、保留品牌 \+ 强商品词/);
});

test("link seed diagnostics summarize Pinterest Apify memory limit", () => {
  const seedTask = task({
    collection_mode: "link_seed_discovery",
    status: "completed_no_results",
    run_checkpoint: {
      failed_queries: ["amazon finds pinterest creator", "amazon storefront pinterest creator"],
      query_errors: {
        "amazon finds pinterest creator": [
          "pinterest_apify:apify_memory_limit_exceeded:actor-memory-limit-exceeded",
        ],
        "amazon storefront pinterest creator": [
          "pinterest_apify:provider_unavailable:apify_memory_limit_exceeded",
        ],
      },
      provider_availability_state: {
        pinterest_apify: {
          status: "provider_unavailable",
          reason: "apify_memory_limit_exceeded",
          message: "Apify 内存额度已满/并发 actor 过多，已跳过后续 Pinterest Apify 查询",
        },
      },
      shopping_seed_discovery: {
        seed_search_disabled: false,
        zero_seed_reason: "seed_search_no_profiles_returned",
        provider_call_count: 2,
        search_platforms: ["pinterest_apify"],
        queries: ["amazon finds pinterest creator", "amazon storefront pinterest creator"],
      },
    },
  });

  const hint = collectionTaskSeedDiscoveryDiagnosticHint(seedTask);
  assert.ok(hint);
  assert.match(hint!, /Apify 内存额度已满\/并发 actor 过多/);
  assert.match(hint!, /未发现可用 seed/);
  assert.equal(formatCollectionResultLines(seedTask).hint, hint);
});

test("link seed diagnostics explain product evidence filtered seeds", () => {
  const seedTask = task({
    collection_mode: "link_seed_discovery",
    status: "completed_no_results",
    run_checkpoint: {
      seed_discovered_count: 0,
      seed_enriched_count: 0,
      filtered_by_product_match_count: 4,
      shopping_seed_discovery: {
        seed_search_disabled: false,
        zero_seed_reason: "seed_found_but_no_product_evidence",
        product_evidence_filtered_count: 4,
        product_evidence_verified_count: 0,
        query_count: 3,
      },
    },
  });

  const hint = collectionTaskSeedDiscoveryDiagnosticHint(seedTask);
  assert.ok(hint);
  assert.match(hint!, /找到 seed 但无同款证据/);
  assert.match(hint!, /过滤 4 个/);

  const breakdown = buildTaskResultBreakdown(seedTask);
  assert.ok(breakdown.funnel.some((item) => /商品证据过滤 4/.test(item)));
  assert.equal(formatCollectionResultLines(seedTask).hint, hint);
});

test("link seed diagnostics explain social enrichment failed seeds", () => {
  const seedTask = task({
    collection_mode: "link_seed_discovery",
    status: "completed_no_results",
    run_checkpoint: {
      seed_discovered_count: 5,
      seed_enriched_count: 0,
      shopping_seed_discovery: {
        seed_search_disabled: false,
        zero_seed_reason: "seed_found_but_social_enrichment_failed",
        query_count: 3,
      },
    },
  });

  const hint = collectionTaskSeedDiscoveryDiagnosticHint(seedTask);
  assert.ok(hint);
  assert.match(hint!, /找到 seed 但未补全社媒主页/);
});

test("running seed discovery context shows query seed enrichment and checkpoint counts", () => {
  const running = task({
    status: "running",
    collection_mode: "link_seed_discovery",
    current_stage: "discovery",
    run_checkpoint: {
      completed_queries: ["amazon finds", "amazon storefront"],
      failed_queries: ["amazon influencer pinterest creator"],
      query_errors: {
        "amazon influencer pinterest creator": ["pinterest_apify:provider_unavailable:network_unreachable"],
      },
      provider_availability_state: {
        pinterest_apify: { status: "provider_unavailable", reason: "network_unreachable" },
      },
      seed_discovered_count: 8,
      seed_enriched_count: 3,
      skipped_due_checkpoint_count: 2,
      shopping_seed_discovery: {
        query_count: 5,
        queries: ["amazon finds", "amazon storefront", "amazon influencer", "shopmy", "pinterest"],
      },
    },
  });

  const context = collectionTaskDiscoveryContext(running);
  assert.ok(context);
  assert.match(context!, /seed 查询 2\/5/);
  assert.match(context!, /失败 1/);
  assert.match(context!, /seed 8/);
  assert.match(context!, /已补全 3/);
  assert.match(context!, /Pinterest Apify 不可用/);
  assert.match(context!, /checkpoint 跳过 2/);
});

test("link seed result breakdown uses seed-specific metrics", () => {
  const seedTask = task({
    status: "completed_no_results",
    collection_mode: "link_seed_discovery",
    discovered_count: 12,
    profile_fetched_count: 4,
    inserted_count: 0,
    run_checkpoint: {
      completed_queries: ["home decor LTK", "home decor ShopMy"],
      failed_queries: ["home decor pinterest creator"],
      seed_discovered_count: 12,
      seed_enriched_count: 4,
      platform_failed_count: 1,
      skipped_platform_count: 2,
      shopping_seed_discovery: {
        query_count: 5,
        search_platforms: ["public_web", "pinterest_apify"],
      },
    },
  });

  const breakdown = buildTaskResultBreakdown(seedTask);
  assert.deepEqual(breakdown.funnel, [
    "seed 查询 2/5",
    "失败查询 1",
    "seed URL 12",
    "主页补全 4",
    "通道失败 1",
    "通道跳过 2",
  ]);
});

test("candidate dialog uses generic shopping seed enrichment copy", () => {
  const source = readFileSync(
    new URL("../src/components/collection-tasks/task-candidates-dialog.tsx", import.meta.url),
    "utf8",
  );
  assert.match(source, /导购 seed 补全/);
  assert.match(source, /Instagram\/TikTok\/YouTube\/Facebook/);
  assert.doesNotMatch(source, /LTK 补全/);
  assert.doesNotMatch(source, /补全 LTK seed/);
});
test("candidate dialog wires recrawl buttons to API and refreshes list", () => {
  const apiSource = readFileSync(new URL("../src/lib/api.ts", import.meta.url), "utf8");
  assert.match(apiSource, /recrawlCollectionTaskCandidate/);
  assert.match(apiSource, /collection-tasks\/\$\{taskId\}\/candidates\/\$\{candidateId\}\/recrawl/);
  assert.match(apiSource, /recrawlCollectionTaskFailedCandidates/);
  assert.match(apiSource, /collection-tasks\/\$\{taskId\}\/candidates\/recrawl-failed/);

  const dialogSource = readFileSync(
    new URL("../src/components/collection-tasks/task-candidates-dialog.tsx", import.meta.url),
    "utf8",
  );
  assert.match(dialogSource, /recrawlCollectionTaskCandidate/);
  assert.match(dialogSource, /recrawlCollectionTaskFailedCandidates/);
  assert.match(dialogSource, /handleRecrawlCandidate/);
  assert.match(dialogSource, /handleRecrawlFailedCandidates/);
  assert.match(dialogSource, /void loadCandidates/);
  assert.match(dialogSource, /canRecrawlCandidate/);
  assert.doesNotMatch(dialogSource, /platform\s*!==\s*["']instagram["']/);
  assert.doesNotMatch(dialogSource, /title="[^"]*后续支持[^"]*"/);
});
test("zero-result keyword task surfaces backend summary and attempted discovery terms", () => {
  const backendSummary =
    "任务完成，但未发现候选账号。系统已尝试 8 个发现词：makeup bag、makeupbag、cosmetic bag；建议降低粉丝门槛或改用链接导入/竞品发现。";
  const lines = formatCollectionResultLines(
    task({
      status: "completed_no_results",
      status_summary: backendSummary,
      run_checkpoint: {
        keyword_expansion: {
          original_keyword_count: 2,
          expanded_keyword_count: 8,
          attempted_keywords: ["makeup bag", "makeupbag", "cosmetic bag"],
        },
      },
    }),
  );

  assert.equal(lines.hint, backendSummary);

  const breakdown = buildTaskResultBreakdown(
    task({
      status: "completed_no_results",
      status_summary: null,
      run_checkpoint: {
        keyword_expansion: {
          original_keyword_count: 2,
          expanded_keyword_count: 8,
          attempted_keywords: ["makeup bag", "makeupbag", "cosmetic bag"],
        },
      },
    }),
  );

  assert.ok(breakdown.reason);
  assert.match(breakdown.reason!, /makeupbag/);
  assert.match(breakdown.reason!, /cosmetic bag/);
});
