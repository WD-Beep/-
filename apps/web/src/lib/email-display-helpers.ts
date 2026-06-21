/** 邮箱展示：避免窄列把域名拆成奇怪片段 */

export function formatEmailDisplay(
  email: string | null | undefined,
  displayName?: string | null,
): string {
  const address = (email ?? "").trim();
  const name = (displayName ?? "").trim();
  if (name && address) {
    return `${name} <${address}>`;
  }
  return address || "-";
}
