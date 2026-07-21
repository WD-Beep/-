// 文件说明：前端公共工具和业务辅助函数；当前文件：product options cache
import type { TenantProduct } from "./api.ts";

const PRODUCT_OPTIONS_CACHE_KEY = "influencer_intel_tenant_products";

function cacheKeyForUser(userId?: number | null): string {
  return Number.isFinite(userId) ? `${PRODUCT_OPTIONS_CACHE_KEY}:${userId}` : PRODUCT_OPTIONS_CACHE_KEY;
}

function isTenantProduct(value: unknown): value is TenantProduct {
  if (!value || typeof value !== "object") return false;
  const item = value as Partial<TenantProduct>;
  return (
    typeof item.id === "number" &&
    typeof item.workspace_id === "number" &&
    typeof item.name === "string" &&
    typeof item.slug === "string"
  );
}

export function readCachedTenantProducts(userId?: number | null): TenantProduct[] {
  if (typeof window === "undefined") return [];
  try {
    const cacheKey = cacheKeyForUser(userId);
    const raw = window.localStorage.getItem(cacheKey);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed) || !parsed.every(isTenantProduct)) {
      window.localStorage.removeItem(cacheKey);
      return [];
    }
    return parsed;
  } catch {
    window.localStorage.removeItem(cacheKeyForUser(userId));
    return [];
  }
}

export function writeCachedTenantProducts(products: TenantProduct[], userId?: number | null): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(cacheKeyForUser(userId), JSON.stringify(products));
}

export function clearCachedTenantProducts(userId?: number | null): void {
  if (typeof window === "undefined") return;
  if (Number.isFinite(userId)) {
    window.localStorage.removeItem(cacheKeyForUser(userId));
    return;
  }

  const keysToRemove: string[] = [];
  for (let index = 0; index < window.localStorage.length; index += 1) {
    const key = window.localStorage.key(index);
    if (key === PRODUCT_OPTIONS_CACHE_KEY || key?.startsWith(`${PRODUCT_OPTIONS_CACHE_KEY}:`)) {
      keysToRemove.push(key);
    }
  }
  keysToRemove.forEach((key) => window.localStorage.removeItem(key));
}
