import type { TenantProduct } from "./api.ts";

const PRODUCT_OPTIONS_CACHE_KEY = "influencer_intel_tenant_products";

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

export function readCachedTenantProducts(): TenantProduct[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(PRODUCT_OPTIONS_CACHE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed) || !parsed.every(isTenantProduct)) {
      window.localStorage.removeItem(PRODUCT_OPTIONS_CACHE_KEY);
      return [];
    }
    return parsed;
  } catch {
    window.localStorage.removeItem(PRODUCT_OPTIONS_CACHE_KEY);
    return [];
  }
}

export function writeCachedTenantProducts(products: TenantProduct[]): void {
  if (typeof window === "undefined") return;
  if (products.length === 0) return;
  window.localStorage.setItem(PRODUCT_OPTIONS_CACHE_KEY, JSON.stringify(products));
}
