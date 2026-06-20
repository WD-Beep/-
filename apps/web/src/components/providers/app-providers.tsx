"use client";

import { ProductProvider } from "@/components/providers/product-provider";

export function AppProviders({ children }: { children: React.ReactNode }) {
  return <ProductProvider>{children}</ProductProvider>;
}
