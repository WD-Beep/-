import type { TenantProduct } from "./api.ts";
import {
  clearStoredAuthSession,
  getStoredAuthSession,
  writeStoredAuthSession,
  type AuthSession,
} from "./auth-session.ts";
import { clearStoredUserId, setStoredUserId } from "./product-context.ts";

export const AUTH_COOKIE = "influencer_intel_auth";
export const AUTH_USERNAME = "admin";
export const AUTH_PASSWORD = "baibo";
export const ADMIN_AUTH_PASSWORD = "admin";
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "/api-proxy";

const SESSION_MAX_AGE_SECONDS = 7 * 24 * 60 * 60;

export type AuthAccount = {
  username: string;
  password: string;
  userId: number;
  role: "admin" | "sales";
  label: string;
};

export const AUTH_ACCOUNTS: AuthAccount[] = [
  {
    username: AUTH_USERNAME,
    password: AUTH_PASSWORD,
    userId: 1,
    role: "admin",
    label: "Administrator",
  },
  ...Array.from({ length: 10 }, (_, index) => {
    const salesNumber = index + 1;
    return {
      username: `sales${salesNumber}`,
      password: AUTH_PASSWORD,
      userId: salesNumber + 1,
      role: "sales" as const,
      label: `Sales ${salesNumber}`,
    };
  }),
];

export function resolveAuthAccount(username: string, password: string): AuthAccount | null {
  const normalizedUsername = username.trim().toLowerCase();
  return (
    AUTH_ACCOUNTS.find(
      (account) => account.username.toLowerCase() === normalizedUsername && account.password === password,
    ) ?? null
  );
}

export function resolveAdminAuthAccount(username: string, password: string): AuthAccount | null {
  const normalizedUsername = username.trim().toLowerCase();
  const account = AUTH_ACCOUNTS.find(
    (item) => item.username.toLowerCase() === normalizedUsername && item.role === "admin",
  );
  if (!account || password !== ADMIN_AUTH_PASSWORD) return null;
  return { ...account, password: ADMIN_AUTH_PASSWORD };
}

export function validateCredentials(username: string, password: string): boolean {
  return resolveAuthAccount(username, password) !== null;
}

export type TenantUserResponse = {
  id: number;
  username: string;
  display_name?: string | null;
  is_admin?: boolean;
  role?: "admin" | "sales";
};

export function buildAuthSession(
  account: AuthAccount,
  user: TenantUserResponse,
  accessibleProducts: TenantProduct[],
  token: string | null = null,
): AuthSession {
  const isAdmin = Boolean(user.is_admin ?? account.role === "admin");
  return {
    token,
    userId: user.id,
    username: user.username || account.username,
    role: isAdmin ? "admin" : "sales",
    isAdmin,
    accessibleProducts,
  };
}

export function defaultPathForSession(session: AuthSession): string {
  if (session.isAdmin) return "/";
  return session.accessibleProducts.length > 0 ? "/collection-tasks" : "/";
}

export async function loadBackendAuthSession(account: AuthAccount): Promise<AuthSession> {
  const headers = { "X-User-Id": String(account.userId) };
  const [userResponse, productsResponse] = await Promise.all([
    fetch(`${API_URL}/api/tenant/me`, { headers, cache: "no-store" }),
    fetch(`${API_URL}/api/tenant/products`, { headers, cache: "no-store" }),
  ]);
  if (!userResponse.ok || !productsResponse.ok) {
    throw new Error("Login succeeded, but backend permission data failed to load. Please try again.");
  }
  const token = userResponse.headers.get("x-auth-token") ?? productsResponse.headers.get("x-auth-token");
  return buildAuthSession(
    account,
    (await userResponse.json()) as TenantUserResponse,
    (await productsResponse.json()) as TenantProduct[],
    token,
  );
}

export function setAuthSession(sessionOrUserId: AuthSession | number = 1): void {
  const session = typeof sessionOrUserId === "number" ? null : sessionOrUserId;
  setStoredUserId(typeof sessionOrUserId === "number" ? sessionOrUserId : sessionOrUserId.userId);
  if (session) {
    writeStoredAuthSession(session);
  }
  if (typeof document !== "undefined") {
    document.cookie = `${AUTH_COOKIE}=1; path=/; max-age=${SESSION_MAX_AGE_SECONDS}; SameSite=Lax`;
  }
}

export function clearAuthSession(): void {
  clearStoredUserId();
  clearStoredAuthSession();
  if (typeof document !== "undefined") {
    document.cookie = `${AUTH_COOKIE}=; path=/; max-age=0; SameSite=Lax`;
  }
}

export { getStoredAuthSession, type AuthSession };
