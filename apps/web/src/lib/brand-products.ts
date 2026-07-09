/** Real brand list mirrored from backend `app.data.brand_products`. */

export type BrandProductSeed = {
  name: string;
  brand: string;
  slug: string;
};

export const BRAND_PRODUCT_SEEDS: readonly BrandProductSeed[] = [
  { name: "\u73fa\u4e34", brand: "EPEDAL24", slug: "junlin-epedal24" },
  { name: "\u54c6\u83b1\u5a01", brand: "Aquorix", slug: "duolaiwei-aquorix" },
  { name: "\u54c6\u83b1\u745e", brand: "RecoverJoy", slug: "duolairui-recoverjoy" },
  { name: "\u94b1\u94b0", brand: "Scandihome", slug: "qianyu-scandihome" },
  { name: "\u591a\u83b1\u8fbe", brand: "ACESTRIKE", slug: "duolaida-acestrike" },
  { name: "\u6822\u535a", brand: "P.travel", slug: "baibo-p-travel" },
  { name: "OCE", brand: "OCE GEAR", slug: "oce-oce-gear" },
  { name: "\u73fa\u94b0", brand: "P.TRAVEL DESIGN", slug: "junyu-p-travel-design" },
  { name: "\u591a\u83b1\u5409", brand: "HOMEHIVE", slug: "duolaiji-homehive" },
  { name: "\u7396\u94b0", brand: "BBCREAT", slug: "jiuyu-bbcreat" },
  { name: "\u5f18\u535a\u6717", brand: "Hongbolang", slug: "hongbolang" },
] as const;

export function formatTenantProductLabel(name: string, brand?: string | null): string {
  const subject = (name || "").trim();
  const brandName = (brand || "").trim();
  if (subject && brandName) return `${subject} / ${brandName}`;
  return subject || brandName;
}
