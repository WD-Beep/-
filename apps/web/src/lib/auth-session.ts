// 文件说明：前端公共工具和业务辅助函数；当前文件：auth session
import type { TenantProduct } from "./api.ts";

export type UserRole = "admin" | "sales";

export type AuthSession = {
  token: string | null;
  userId: number;
  username: string;
  role: UserRole;
  isAdmin: boolean;
  accessibleProducts: TenantProduct[];
};

export const AUTH_SESSION_STORAGE_KEY = "influencer_intel_auth_session";

function parseSession(raw: string | null): AuthSession | null {
  if (!raw) return null;
  try {
    const value = JSON.parse(raw) as Partial<AuthSession>;
    const userId = Number(value.userId);
    const role = value.isAdmin || value.role === "admin" ? "admin" : "sales";
    if (!Number.isFinite(userId) || userId <= 0 || !value.username) {
      return null;
    }
    return {
      token: typeof value.token === "string" && value.token.trim() ? value.token : null,
      userId,
      username: String(value.username),
      role,
      isAdmin: role === "admin",
      accessibleProducts: Array.isArray(value.accessibleProducts) ? value.accessibleProducts : [],
    };
  } catch {
    return null;
  }
}

export function getStoredAuthSession(): AuthSession | null {
  if (typeof window === "undefined") return null;
  return parseSession(window.localStorage.getItem(AUTH_SESSION_STORAGE_KEY));
}

export function writeStoredAuthSession(session: AuthSession): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(AUTH_SESSION_STORAGE_KEY, JSON.stringify(session));
}

export function clearStoredAuthSession(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(AUTH_SESSION_STORAGE_KEY);
}
