// 文件说明：前端公共工具和业务辅助函数；当前文件：product context
export type ProductOption = {
  id: number;
  name: string;
  slug: string;
  brand?: string | null;
  is_default?: boolean;
};

export const ALL_PRODUCTS_ID = 0;
const PRODUCT_STORAGE_KEY = "influencer_intel_product_id";
const USER_STORAGE_KEY = "influencer_intel_user_id";
const AUTH_SESSION_STORAGE_KEY = "influencer_intel_auth_session";

function readStoredProductIdValue(): number {
  if (typeof window === "undefined") return ALL_PRODUCTS_ID;
  const raw = window.localStorage.getItem(PRODUCT_STORAGE_KEY);
  const parsed = Number(raw);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : ALL_PRODUCTS_ID;
}

let activeProductId: number = readStoredProductIdValue();

export function readStoredProductIdFromStorage(): number {
  activeProductId = readStoredProductIdValue();
  return activeProductId;
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

export function clearStoredUserId(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(USER_STORAGE_KEY);
}

function readStoredToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(AUTH_SESSION_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { token?: unknown };
    return typeof parsed.token === "string" && parsed.token.trim() ? parsed.token : null;
  } catch {
    return null;
  }
}

function readStoredSessionUserId(): number | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(AUTH_SESSION_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { userId?: unknown };
    const userId = Number(parsed.userId);
    return Number.isFinite(userId) && userId > 0 ? userId : null;
  } catch {
    return null;
  }
}

export function tenantHeaders(): Record<string, string> {
  const userId = readStoredSessionUserId() ?? getStoredUserId();
  const headers: Record<string, string> = {
    "X-User-Id": String(userId),
    "X-Product-Id": String(getActiveProductId()),
  };
  const token = readStoredToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  return headers;
}

export async function ensureTenantProductId(): Promise<number> {
  return getActiveProductId();
}

export function assertConcreteProductSelected(action = "该操作"): number {
  const productId = getActiveProductId();
  if (productId === ALL_PRODUCTS_ID) {
    throw new Error(`${action}需要先选择具体产品/品牌`);
  }
  return productId;
}
