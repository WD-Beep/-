export type ProductOption = {
  id: number;
  name: string;
  slug: string;
  brand?: string | null;
  is_default?: boolean;
};

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "/api-proxy";
const SERVER_API_URL =
  process.env.INTERNAL_API_URL?.replace(/\/$/, "") ?? "http://127.0.0.1:8000";
export const ALL_PRODUCTS_ID = 0;
const PRODUCT_STORAGE_KEY = "influencer_intel_product_id";
const USER_STORAGE_KEY = "influencer_intel_user_id";

let activeProductId: number = ALL_PRODUCTS_ID;

function resolveApiUrl(): string {
  return typeof window === "undefined" ? SERVER_API_URL : API_URL;
}

export function getActiveProductId(): number {
  return activeProductId;
}

export function getStoredProductId(): number | null {
  return activeProductId;
}

export function setStoredProductId(productId: number): void {
  activeProductId = productId;
  if (typeof window === "undefined") return;
  window.localStorage.setItem(PRODUCT_STORAGE_KEY, String(productId));
}

export function getStoredUserId(): number {
  if (typeof window === "undefined") return 1;
  const raw = window.localStorage.getItem(USER_STORAGE_KEY);
  const parsed = Number(raw);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 1;
}

export function setStoredUserId(userId: number): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(USER_STORAGE_KEY, String(userId));
}

export function tenantHeaders(): Record<string, string> {
  return {
    "X-User-Id": String(getStoredUserId()),
    "X-Product-Id": String(getActiveProductId()),
  };
}

export async function ensureTenantProductId(): Promise<number> {
  return getActiveProductId();
}
