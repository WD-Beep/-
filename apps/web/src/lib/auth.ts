export const AUTH_COOKIE = "influencer_intel_auth";
export const AUTH_USERNAME = "admin";
export const AUTH_PASSWORD = "baibo";

const SESSION_MAX_AGE_SECONDS = 7 * 24 * 60 * 60;

export function validateCredentials(username: string, password: string): boolean {
  return username.trim() === AUTH_USERNAME && password === AUTH_PASSWORD;
}

export function setAuthSession(): void {
  document.cookie = `${AUTH_COOKIE}=1; path=/; max-age=${SESSION_MAX_AGE_SECONDS}; SameSite=Lax`;
}

export function clearAuthSession(): void {
  document.cookie = `${AUTH_COOKIE}=; path=/; max-age=0; SameSite=Lax`;
}
