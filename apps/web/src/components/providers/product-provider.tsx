// 文件说明：前端页面组件；当前文件：product provider
"use client";

import { createContext, useContext, useLayoutEffect, useMemo, useState } from "react";

import { getStoredAuthSession } from "@/lib/auth";
import { ALL_PRODUCTS_ID, readStoredProductIdFromStorage, setStoredProductId } from "@/lib/product-context";
import { readCachedTenantProducts } from "@/lib/product-options-cache";
import { resolveInitialProductIdFromCache } from "@/lib/product-provider-state";

type ProductContextValue = {
  productId: number;
  setProductId: (productId: number) => void;
};

const ProductContext = createContext<ProductContextValue | null>(null);

export function ProductProvider({ children }: { children: React.ReactNode }) {
  const [productId, setProductIdState] = useState<number>(ALL_PRODUCTS_ID);
  const [hydrated, setHydrated] = useState(false);

  useLayoutEffect(() => {
    queueMicrotask(() => {
      const session = getStoredAuthSession();
      const storedProductId = readStoredProductIdFromStorage();
      const resolvedProductId = resolveInitialProductIdFromCache(
        storedProductId,
        readCachedTenantProducts(session?.userId),
        session,
      );
      setProductIdState(resolvedProductId);
      setHydrated(true);
    });
  }, []);

  useLayoutEffect(() => {
    if (!hydrated) return;
    setStoredProductId(productId);
  }, [hydrated, productId]);

  const value = useMemo<ProductContextValue>(
    () => ({
      productId,
      setProductId: (next: number) => {
        setStoredProductId(next);
        setProductIdState(next);
      },
    }),
    [productId],
  );

  return <ProductContext.Provider value={value}>{children}</ProductContext.Provider>;
}

export function useActiveProductId(): number {
  const context = useContext(ProductContext);
  return context?.productId ?? ALL_PRODUCTS_ID;
}

export function useProductActions() {
  const context = useContext(ProductContext);
  if (!context) {
    throw new Error("useProductActions must be used within ProductProvider");
  }
  return { setProductId: context.setProductId };
}
