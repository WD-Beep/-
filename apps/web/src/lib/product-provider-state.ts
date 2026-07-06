import type { TenantProduct } from "./api.ts";
import { ALL_PRODUCTS_ID } from "./product-context.ts";
import { prepareTenantProductOptions, resolveStoredProductId } from "./product-visibility.ts";

export function resolveInitialProductIdFromCache(
  storedProductId: number,
  cachedProducts: TenantProduct[],
): number {
  const options = prepareTenantProductOptions(cachedProducts);
  if (options.length === 0) return storedProductId;
  const resolved = resolveStoredProductId(storedProductId, options);
  return resolved === ALL_PRODUCTS_ID ? (options.find((item) => item.is_default)?.id ?? options[0].id) : resolved;
}
