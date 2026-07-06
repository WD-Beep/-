export function shouldDisableProductSelector({
  hasHydrated,
  productsLoading,
  productCount,
}: {
  hasHydrated: boolean;
  productsLoading: boolean;
  productCount: number;
}): boolean {
  return !hasHydrated || (productsLoading && productCount === 0);
}
