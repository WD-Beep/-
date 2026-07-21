// 文件说明：前端页面组件；当前文件：app providers
"use client";

import { ProductProvider } from "@/components/providers/product-provider";

export function AppProviders({ children }: { children: React.ReactNode }) {
  return <ProductProvider>{children}</ProductProvider>;
}
