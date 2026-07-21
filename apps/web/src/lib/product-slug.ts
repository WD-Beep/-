// 文件说明：前端公共工具和业务辅助函数；当前文件：product slug
export function slugifyProductName(name: string): string {
  const ascii = name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  if (ascii) return ascii.slice(0, 100);
  return `product-${Date.now().toString(36)}`;
}
