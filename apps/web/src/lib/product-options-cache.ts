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
