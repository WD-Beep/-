"use client";

import { createContext, useContext, useLayoutEffect, useMemo, useState } from "react";

import { ALL_PRODUCTS_ID, setStoredProductId } from "@/lib/product-context";

type ProductContextValue = {
  productId: number;
  setProductId: (productId: number) => void;
};

const ProductContext = createContext<ProductContextValue | null>(null);

export function ProductProvider({ children }: { children: React.ReactNode }) {
  const [productId, setProductIdState] = useState<number>(ALL_PRODUCTS_ID);

  useLayoutEffect(() => {
    setStoredProductId(ALL_PRODUCTS_ID);
    setProductIdState(ALL_PRODUCTS_ID);
  }, []);

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
