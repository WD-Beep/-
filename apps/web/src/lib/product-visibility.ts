import { BRAND_PRODUCT_SEEDS } from "./brand-products.ts";
import { ALL_PRODUCTS_ID } from "./product-context.ts";

export type VisibleProductLike = {
  id: number;
  name: string;
  slug: string;
  brand?: string | null;
  is_default?: boolean;
  is_archived?: boolean;
  is_hidden?: boolean;
  is_test?: boolean;
  display_order?: number | null;
};

const HASH_SUFFIX_RE = /-[0-9a-f]{8}$/i;
const TEST_KEYWORDS = [
  "测试产品",
  "新品测试",
  "话术测试",
  "amazon跨产品",
  "test",
  "demo",
  "mock",
  "temp",
  "临时",
  "示例",
] as const;

const SEED_SLUGS = new Set(BRAND_PRODUCT_SEEDS.map((item) => item.slug));
const SYSTEM_SLUGS = new Set(["default"]);

function combinedText(product: Pick<VisibleProductLike, "name" | "slug" | "brand">): string {
  return `${product.name} ${product.slug} ${product.brand ?? ""}`.toLowerCase();
}

export function looksLikeTestProduct(
  product: Pick<VisibleProductLike, "name" | "slug" | "brand">,
): boolean {
  const slug = (product.slug || "").trim().toLowerCase();
  if (SYSTEM_SLUGS.has(slug) || SEED_SLUGS.has(slug)) {
    return false;
  }

  const text = combinedText(product);
  if (TEST_KEYWORDS.some((keyword) => text.includes(keyword.toLowerCase()))) {
    return true;
  }
  if (HASH_SUFFIX_RE.test(product.name) || HASH_SUFFIX_RE.test(slug)) {
    return true;
  }
  if (slug.startsWith("test-product") || slug.startsWith("dup-slug-")) {
    return true;
  }
  return false;
}

export function isVisibleTenantProduct(
  product: VisibleProductLike,
  options?: { includeTest?: boolean },
): boolean {
  if (options?.includeTest) {
    return true;
  }
  if (product.is_archived || product.is_hidden || product.is_test) {
    return false;
  }
  return !looksLikeTestProduct(product);
}

export function filterVisibleTenantProducts<T extends VisibleProductLike>(products: T[]): T[] {
  return products.filter((product) => isVisibleTenantProduct(product));
}

export function sortTenantProducts<T extends VisibleProductLike>(products: T[]): T[] {
  return [...products].sort((left, right) => {
    const leftDefault = left.is_default ? 0 : 1;
    const rightDefault = right.is_default ? 0 : 1;
    if (leftDefault !== rightDefault) return leftDefault - rightDefault;

    const leftOrder = left.display_order ?? 10_000;
    const rightOrder = right.display_order ?? 10_000;
    if (leftOrder !== rightOrder) return leftOrder - rightOrder;

    return left.name.localeCompare(right.name, "zh-CN");
  });
}

export function prepareTenantProductOptions<T extends VisibleProductLike>(products: T[]): T[] {
  return sortTenantProducts(filterVisibleTenantProducts(products));
}

export function resolveStoredProductId<T extends VisibleProductLike>(
  storedProductId: number,
  visibleProducts: T[],
): number {
  if (storedProductId === ALL_PRODUCTS_ID) {
    return ALL_PRODUCTS_ID;
  }
  if (visibleProducts.some((product) => product.id === storedProductId)) {
    return storedProductId;
  }
  const defaultProduct = visibleProducts.find((product) => product.is_default);
  if (defaultProduct) {
    return defaultProduct.id;
  }
  if (visibleProducts.length > 0) {
    return visibleProducts[0].id;
  }
  return ALL_PRODUCTS_ID;
}

export function formatHiddenProductLabel(name: string, brand?: string | null): string {
  const subject = (name || "").trim();
  const brandName = (brand || "").trim();
  const label = subject && brandName ? `${subject} · ${brandName}` : subject || brandName;
  return label ? `${label}（已隐藏/测试数据）` : "该产品已隐藏/测试数据";
}
