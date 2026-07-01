import { clearStoredUserId, setStoredUserId } from "./product-context.ts";

export const AUTH_COOKIE = "influencer_intel_auth";
export const AUTH_USERNAME = "admin";
export const AUTH_PASSWORD = "baibo";

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
    label: "管理员",
  },
  ...Array.from({ length: 10 }, (_, index) => {
    const salesNumber = index + 1;
    return {
      username: `sales${salesNumber}`,
      password: AUTH_PASSWORD,
      userId: salesNumber + 1,
      role: "sales" as const,
      label: `业务员 ${salesNumber}`,
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

export function validateCredentials(username: string, password: string): boolean {
  return resolveAuthAccount(username, password) !== null;
}

export function setAuthSession(userId = 1): void {
  setStoredUserId(userId);
  document.cookie = `${AUTH_COOKIE}=1; path=/; max-age=${SESSION_MAX_AGE_SECONDS}; SameSite=Lax`;
}

export function clearAuthSession(): void {
  clearStoredUserId();
  document.cookie = `${AUTH_COOKIE}=; path=/; max-age=0; SameSite=Lax`;
}
