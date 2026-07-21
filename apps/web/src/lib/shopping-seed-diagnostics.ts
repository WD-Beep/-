// 文件说明：前端公共工具和业务辅助函数；当前文件：shopping seed diagnostics
import type { CollectionTask } from "./api";

type ShoppingSeedDiscoveryDiagnostics = {
  zero_seed_reason?: unknown;
  queries?: unknown;
  provider_availability_state?: unknown;
  product_evidence_filtered_count?: unknown;
};

const SEED_PROVIDER_NOT_CONFIGURED = "seed_search_provider_not_configured";
const SHOPMY_PROVIDER_REQUIRES_AUTH = "shopmy_keyword_search_requires_authenticated_provider";
const PINTEREST_APIFY = "pinterest_apify";
const NETWORK_UNREACHABLE = "network_unreachable";
const QUERY_TIMEOUT = "query_timeout";
const APIFY_MEMORY_LIMIT_EXCEEDED = "apify_memory_limit_exceeded";
const PROVIDER_FAILED_BUT_FALLBACK_NO_RESULTS = "provider_failed_but_fallback_no_results";
const SEED_FOUND_BUT_NO_PRODUCT_EVIDENCE = "seed_found_but_no_product_evidence";
const SEED_FOUND_BUT_SOCIAL_ENRICHMENT_FAILED = "seed_found_but_social_enrichment_failed";

function getShoppingSeedDiscoveryDiagnostics(
  task: Pick<CollectionTask, "collection_mode" | "run_checkpoint">,
): ShoppingSeedDiscoveryDiagnostics | null {
  if (task.collection_mode !== "link_seed_discovery") return null;
  const diagnostics = task.run_checkpoint?.shopping_seed_discovery;
  if (!diagnostics || typeof diagnostics !== "object" || Array.isArray(diagnostics)) return null;
  return diagnostics as ShoppingSeedDiscoveryDiagnostics;
}

function diagnosticQueries(diagnostics: ShoppingSeedDiscoveryDiagnostics): string[] {
  if (!Array.isArray(diagnostics.queries)) return [];
  return diagnostics.queries
    .filter((query): query is string => typeof query === "string")
    .map((query) => query.trim())
    .filter(Boolean);
}

function pickDisplayQueries(queries: string[]): string[] {
  const preferred = queries.filter((query) => /\b(LTK|ShopMy|Amazon finds)\b/i.test(query));
  return (preferred.length > 0 ? preferred : queries).slice(0, 3);
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function asNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function pinterestApifyState(
  task: Pick<CollectionTask, "collection_mode" | "run_checkpoint">,
  diagnostics: ShoppingSeedDiscoveryDiagnostics | null,
): Record<string, unknown> | null {
  const checkpoint = task.run_checkpoint ?? {};
  const topLevel = asRecord(checkpoint.provider_availability_state)?.[PINTEREST_APIFY];
  const nested = asRecord(diagnostics?.provider_availability_state)?.[PINTEREST_APIFY];
  return asRecord(topLevel) ?? asRecord(nested);
}

function pinterestNetworkSkippedCount(task: Pick<CollectionTask, "collection_mode" | "run_checkpoint">): number {
  const queryErrors = asRecord(task.run_checkpoint?.query_errors);
  if (!queryErrors) return 0;
  let count = 0;
  for (const errors of Object.values(queryErrors)) {
    if (!Array.isArray(errors)) continue;
    if (
      errors.some(
        (error) =>
          typeof error === "string" &&
          error.includes(PINTEREST_APIFY) &&
          (error.includes(NETWORK_UNREACHABLE) || error.includes("All connection attempts failed")),
      )
    ) {
      count += 1;
    }
  }
  return count;
}

export function collectionTaskSeedDiscoveryDiagnosticHint(
  task: Pick<CollectionTask, "collection_mode" | "run_checkpoint">,
): string | null {
  const diagnostics = getShoppingSeedDiscoveryDiagnostics(task);
  const queries = pickDisplayQueries(diagnosticQueries(diagnostics ?? {}));
  const apifyState = pinterestApifyState(task, diagnostics);

  if (
    diagnostics?.zero_seed_reason === PROVIDER_FAILED_BUT_FALLBACK_NO_RESULTS &&
    apifyState?.reason === QUERY_TIMEOUT
  ) {
    return [
      "Pinterest Apify 超时，已跳过该通道。",
      "已继续尝试公共网页搜索 / LTK / ShopMy fallback。",
      "公共搜索未返回可用 seed。",
      "建议：缩小商品词、保留品牌 + 强商品词，或暂时只跑 LTK / ShopMy。",
    ].join("");
  }

  if (diagnostics?.zero_seed_reason === PROVIDER_FAILED_BUT_FALLBACK_NO_RESULTS) {
    const providerMessage =
      apifyState?.reason === NETWORK_UNREACHABLE
        ? "Pinterest Apify 网络不可达，已跳过该通道。"
        : apifyState?.reason === APIFY_MEMORY_LIMIT_EXCEEDED
          ? "Apify 内存额度已满/并发 actor 过多，已跳过 Pinterest Apify 通道。"
          : "部分 seed provider 失败，已跳过失败通道。";
    return [
      providerMessage,
      "已继续尝试公共网页搜索 / LTK / ShopMy fallback。",
      "公共搜索未返回可用 seed。",
      "建议：缩小商品词、保留品牌 + 强商品词，或暂时只跑 LTK / ShopMy。",
    ].join("");
  }

  if (apifyState?.reason === NETWORK_UNREACHABLE) {
    const skippedCount = pinterestNetworkSkippedCount(task);
    const skipped = skippedCount > 0 ? `${skippedCount} 条 Pinterest query 因网络不可达被跳过。` : "";
    const noSeed =
      diagnostics?.zero_seed_reason === "seed_search_no_profiles_returned"
        ? "未发现可用 seed；Pinterest 通道不可达，其余搜索源未返回可用主页。"
        : "";
    return [
      "Pinterest 搜索服务当前不可达，已跳过该通道。",
      "当前环境无法连接 Apify（api.apify.com:443）。",
      "已继续尝试其他可用搜索源。",
      skipped,
      noSeed,
    ]
      .filter(Boolean)
      .join("");
  }

  if (apifyState?.reason === APIFY_MEMORY_LIMIT_EXCEEDED) {
    const message =
      typeof apifyState.message === "string" && apifyState.message.trim()
        ? apifyState.message.trim()
        : "Apify 内存额度已满/并发 actor 过多，已跳过 Pinterest Apify seed 搜索通道。";
    const noSeed =
      diagnostics?.zero_seed_reason === "seed_search_no_profiles_returned"
        ? "未发现可用 seed；Pinterest Apify 已短路，其余搜索源未返回可用主页。"
        : "";
    return [message, noSeed].filter(Boolean).join("");
  }

  if (diagnostics?.zero_seed_reason === SHOPMY_PROVIDER_REQUIRES_AUTH) {
    const base =
      "ShopMy 关键词搜索未配置授权来源；已执行公共网页和 ShopMy 页面搜索，但没有返回可解析的 ShopMy 创作者主页。可尝试更具体的主题、品牌、商品词，或直接提供 ShopMy seed 链接。";
    if (queries.length === 0) return base;
    return `${base}查询词：${queries.join("、")}`;
  }

  if (diagnostics?.zero_seed_reason === SEED_FOUND_BUT_NO_PRODUCT_EVIDENCE) {
    const filtered =
      asNumber(diagnostics.product_evidence_filtered_count) ??
      asNumber(task.run_checkpoint?.filtered_by_product_match_count);
    const suffix = filtered != null && filtered > 0 ? `\uff0c\u5df2\u8fc7\u6ee4 ${filtered} \u4e2a` : "";
    return `\u627e\u5230 seed \u4f46\u65e0\u540c\u6b3e\u8bc1\u636e${suffix}\u3002`;
  }

  if (diagnostics?.zero_seed_reason === SEED_FOUND_BUT_SOCIAL_ENRICHMENT_FAILED) {
    return "\u627e\u5230 seed \u4f46\u672a\u8865\u5168\u793e\u5a92\u4e3b\u9875\uff0c\u672a\u80fd\u6210\u529f\u5173\u8054 Instagram / TikTok / YouTube / Facebook\u3002";
  }

  if (diagnostics?.zero_seed_reason !== SEED_PROVIDER_NOT_CONFIGURED) return null;

  const base =
    "未配置 LTK/ShopMy/Pinterest seed 搜索来源，当前仅解析已提供的 seed 链接；Amazon 商品查询词已生成但未执行外部搜索。";
  if (queries.length === 0) return base;
  return `${base}查询词：${queries.join("、")}`;
}
