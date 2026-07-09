import type { TenantProduct } from "./api.ts";
import type { AuthSession } from "./auth-session.ts";
import { ALL_PRODUCTS_ID } from "./product-context.ts";
import {
  prepareTenantProductOptions,
  resolveProductIdForSession,
  resolveStoredProductId,
} from "./product-visibility.ts";

export function resolveInitialProductIdFromCache(
  storedProductId: number,
  cachedProducts: TenantProduct[],
  session: AuthSession | null = null,
): number {
  const sessionResolved = resolveProductIdForSession(storedProductId, session);
  if (sessionResolved !== null) return sessionResolved;
  const options = prepareTenantProductOptions(cachedProducts);
  if (options.length === 0) return storedProductId;
  const resolved = resolveStoredProductId(storedProductId, options);
  return resolved === ALL_PRODUCTS_ID ? (options.find((item) => item.is_default)?.id ?? options[0].id) : resolved;
}
