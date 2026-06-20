"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  Database,
  LayoutDashboard,
  Link2,
  LogOut,
  Mail,
  MessageSquareText,
  Plus,
  Search,
  Settings,
  Users,
  BookOpen,
} from "lucide-react";

import { ProductCreateDialog } from "@/components/layout/product-create-dialog";
import { Button } from "@/components/ui/button";
import { fetchTenantProducts, type TenantProduct } from "@/lib/api";
import { formatTenantProductLabel } from "@/lib/brand-products";
import { clearAuthSession } from "@/lib/auth";
import { ALL_PRODUCTS_ID } from "@/lib/product-context";
import {
  prepareTenantProductOptions,
  resolveStoredProductId,
} from "@/lib/product-visibility";
import { useActiveProductId, useProductActions } from "@/components/providers/product-provider";
import { cn } from "@/lib/utils";

const navItems = [
  { href: "/", label: "数据概览", icon: LayoutDashboard },
  { href: "/influencers", label: "红人库", icon: Users },
  { href: "/collection-tasks", label: "采集任务", icon: Search },
  { href: "/link-import", label: "链接导入", icon: Link2 },
  { href: "/email-logs", label: "邮件日志", icon: Mail },
  { href: "/message-templates", label: "话术库", icon: MessageSquareText },
  { href: "/knowledge-bases", label: "知识库", icon: BookOpen },
  { href: "/settings", label: "系统设置", icon: Settings },
];

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const productId = useActiveProductId();
  const { setProductId: setActiveProductId } = useProductActions();
  const [products, setProducts] = useState<TenantProduct[]>([]);
  const [createOpen, setCreateOpen] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const loadProducts = useCallback(async () => {
    try {
      const items = prepareTenantProductOptions(await fetchTenantProducts());
      setProducts(items);
      return items;
    } catch {
      setProducts([]);
      return [];
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    queueMicrotask(() => {
      void loadProducts().then((items) => {
        if (cancelled) return;
        const resolvedId = resolveStoredProductId(productId, items);
        if (resolvedId !== productId) {
          setActiveProductId(resolvedId);
          return;
        }
        if (items.length === 0) return;
        if (productId === ALL_PRODUCTS_ID) {
          const defaultProduct = items.find((item) => item.is_default) ?? items[0];
          if (defaultProduct) {
            setActiveProductId(defaultProduct.id);
          }
        }
      });
    });
    return () => {
      cancelled = true;
    };
  }, [loadProducts, productId, setActiveProductId]);

  function showToast(message: string) {
    setToast(message);
    window.setTimeout(() => setToast(null), 3000);
  }

  function handleLogout() {
    clearAuthSession();
    router.replace("/login");
    router.refresh();
  }

  async function handleProductCreated(product: TenantProduct) {
    await loadProducts();
    setActiveProductId(product.id);
    router.refresh();
    showToast("已创建并切换到新产品/品牌");
  }

  return (
    <aside className="flex h-screen w-64 shrink-0 flex-col border-r bg-sidebar text-sidebar-foreground">
      {toast ? (
        <div className="fixed bottom-6 right-6 z-50 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800 shadow-lg">
          {toast}
        </div>
      ) : null}

      <div className="flex h-16 items-center gap-2 border-b px-6">
        <Database className="h-5 w-5 text-primary" />
        <div>
          <p className="text-sm font-semibold">红人智采</p>
          <p className="text-xs text-muted-foreground">海外红人数据平台</p>
        </div>
      </div>

      <div className="space-y-2 border-b px-4 py-3">
        <div className="flex items-center justify-between gap-2">
          <label htmlFor="product-selector" className="text-xs font-medium text-muted-foreground">
            当前产品/品牌
          </label>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-7 gap-1 px-2 text-xs"
            onClick={() => setCreateOpen(true)}
          >
            <Plus className="h-3.5 w-3.5" />
            新增
          </Button>
        </div>
        <select
          id="product-selector"
          value={productId ?? ""}
          onChange={(e) => {
            const next = Number(e.target.value);
            if (!Number.isFinite(next) || next < 0) return;
            setActiveProductId(next);
            router.refresh();
          }}
          className="flex h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
        >
          <option value={ALL_PRODUCTS_ID}>全部产品（汇总）</option>
          {products.map((product) => (
            <option key={product.id} value={product.id}>
              {formatTenantProductLabel(product.name, product.brand)}
            </option>
          ))}
        </select>
        {products.length === 0 ? (
          <p className="text-[11px] text-muted-foreground">暂无正式产品，请新增产品/品牌</p>
        ) : null}
        {products.length === 0 ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="w-full gap-1.5"
            onClick={() => setCreateOpen(true)}
          >
            <Plus className="h-3.5 w-3.5" />
            新增产品/品牌
          </Button>
        ) : null}
        <p className="text-[11px] text-muted-foreground">
          {productId === ALL_PRODUCTS_ID
            ? "汇总显示所有产品的任务与红人数据"
            : "仅显示当前产品下的任务与红人数据"}
        </p>
      </div>

      <nav className="flex-1 space-y-1 p-4">
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive =
            item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);

          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-3 whitespace-nowrap rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                isActive
                  ? "bg-sidebar-accent text-sidebar-accent-foreground"
                  : "text-muted-foreground hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground",
              )}
            >
              <Icon className="h-4 w-4" />
              {item.label}
            </Link>
          );
        })}
      </nav>

      <div className="space-y-3 border-t p-4">
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="w-full justify-start gap-2"
          onClick={handleLogout}
        >
          <LogOut className="h-4 w-4" />
          退出登录
        </Button>
        <p className="text-xs text-muted-foreground">内部系统 · v0.1.0</p>
      </div>

      <ProductCreateDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={handleProductCreated}
      />
    </aside>
  );
}
