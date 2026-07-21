// 文件说明：前端公共工具和业务辅助函数；当前文件：sidebar product selector
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
