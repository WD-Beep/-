"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  BarChart3,
  BookOpen,
  ChevronDown,
  Clock,
  FileDown,
  HelpCircle,
  Inbox,
  LayoutDashboard,
  Link2,
  LogOut,
  Mail,
  MessageSquareText,
  Megaphone,
  Plus,
  Search,
  Send,
  Settings,
  Sparkles,
  Upload,
  Users,
} from "lucide-react";

import { ProductCreateDialog } from "@/components/layout/product-create-dialog";
import { fetchEmailReplyWorkCount, fetchTenantProducts, type TenantProduct } from "@/lib/api";
import { clearAuthSession } from "@/lib/auth";
import { formatTenantProductLabel } from "@/lib/brand-products";
import {
  readCachedTenantProducts,
  writeCachedTenantProducts,
} from "@/lib/product-options-cache";
import { ALL_PRODUCTS_ID } from "@/lib/product-context";
import {
  prepareTenantProductOptions,
  resolveStoredProductId,
} from "@/lib/product-visibility";
import { useActiveProductId, useProductActions } from "@/components/providers/product-provider";
import { cn } from "@/lib/utils";

const navGroups = [
  {
    title: "核心数据",
    items: [
      { href: "/", label: "数据概览", icon: LayoutDashboard },
      { href: "/influencers", label: "红人库", icon: Users },
      { href: "/collection-tasks", label: "采集任务", icon: Search },
      { href: "/collection-guide", label: "采集说明", icon: HelpCircle },
      { href: "/link-import", label: "链接导入", icon: Link2 },
    ],
  },
  {
    title: "触达运营",
    items: [
      { href: "/outreach-campaigns", label: "AI批量发邮件", icon: Megaphone },
      { href: "/outreach-send-queue", label: "发送队列", icon: Clock },
      { href: "/email-replies", label: "红人回复", icon: Inbox },
      { href: "/outreach-records", label: "发送记录", icon: Send },
      { href: "/email-logs", label: "邮件日志", icon: Mail },
    ],
  },
  {
    title: "内容资产",
    items: [
      { href: "/message-templates", label: "话术库", icon: MessageSquareText },
      { href: "/knowledge-bases", label: "知识库", icon: BookOpen },
      { href: "/link-knowledge-bases", label: "链接库", icon: Link2 },
    ],
  },
  {
    title: "系统",
    items: [{ href: "/settings", label: "系统设置", icon: Settings }],
  },
];

const quickLinks = [
  { href: "/link-import", label: "数据导入", icon: Upload },
  { href: "/email-logs", label: "邮件中心", icon: Mail },
  { href: "/", label: "月度报告", icon: BarChart3 },
  { href: "/collection-tasks", label: "文件下载", icon: FileDown },
];

const miniItems = [
  { href: "/", label: "数据概览", icon: LayoutDashboard },
  { href: "/influencers", label: "红人库", icon: Users },
  { href: "/collection-tasks", label: "采集任务", icon: Search },
  { href: "/collection-guide", label: "采集说明", icon: HelpCircle },
  { href: "/email-replies", label: "红人回复", icon: Inbox },
  { href: "/email-logs", label: "邮件中心", icon: Mail },
  { href: "/settings", label: "系统设置", icon: Settings },
];

function isNavActive(pathname: string, href: string) {
  return href === "/" ? pathname === "/" : pathname.startsWith(href);
}

const PRODUCT_LOAD_RETRY_DELAY_MS = 420;

function wait(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function fetchTenantProductsWithRetry() {
  try {
    return await fetchTenantProducts();
  } catch (error) {
    await wait(PRODUCT_LOAD_RETRY_DELAY_MS);
    try {
      return await fetchTenantProducts();
    } catch {
      throw error;
    }
  }
}

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const productId = useActiveProductId();
  const { setProductId: setActiveProductId } = useProductActions();
  const [products, setProducts] = useState<TenantProduct[]>(() => readCachedTenantProducts());
  const [productsLoading, setProductsLoading] = useState(true);
  const [productLoadError, setProductLoadError] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [productMenuOpen, setProductMenuOpen] = useState(false);
  const [unprocessedReplyCount, setUnprocessedReplyCount] = useState(0);
  const collapseTimer = useRef<number | null>(null);
  const productMenuRef = useRef<HTMLDivElement | null>(null);

  const activeMiniItem = useMemo(
    () => miniItems.find((item) => isNavActive(pathname, item.href)) ?? miniItems[0],
    [pathname],
  );
  const ActiveMiniIcon = activeMiniItem.icon;
  const activeProductLabel = useMemo(() => {
    if (productId === ALL_PRODUCTS_ID) return "全部产品（汇总）";
    const activeProduct = products.find((product) => product.id === productId);
    return activeProduct
      ? formatTenantProductLabel(activeProduct.name, activeProduct.brand)
      : "选择产品 / 品牌";
  }, [productId, products]);

  const loadProducts = useCallback(async () => {
    const cachedItems = prepareTenantProductOptions(readCachedTenantProducts());
    if (cachedItems.length > 0) {
      setProducts(cachedItems);
    }
    setProductsLoading(true);
    try {
      const items = prepareTenantProductOptions(await fetchTenantProductsWithRetry());
      setProducts(items);
      writeCachedTenantProducts(items);
      setProductLoadError(null);
      return items;
    } catch {
      setProductLoadError("产品/品牌列表加载失败，已保留上次成功的列表");
      if (cachedItems.length > 0) {
        setProducts(cachedItems);
        return cachedItems;
      }
      setProducts([]);
      return cachedItems;
    } finally {
      setProductsLoading(false);
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

  useEffect(() => {
    return () => {
      if (collapseTimer.current) window.clearTimeout(collapseTimer.current);
    };
  }, []);

  useEffect(() => {
    function handlePointerDown(event: PointerEvent) {
      if (!productMenuRef.current?.contains(event.target as Node)) {
        setProductMenuOpen(false);
      }
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setProductMenuOpen(false);
    }
    window.addEventListener("pointerdown", handlePointerDown);
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("pointerdown", handlePointerDown);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    if (productId === null || productId === ALL_PRODUCTS_ID) {
      queueMicrotask(() => {
        if (!cancelled) setUnprocessedReplyCount(0);
      });
      return () => {
        cancelled = true;
      };
    }
    queueMicrotask(() => {
      void fetchEmailReplyWorkCount()
        .then((summary) => {
          if (!cancelled) setUnprocessedReplyCount(summary.unprocessed_count);
        })
        .catch(() => {
          if (!cancelled) setUnprocessedReplyCount(0);
        });
    });
    return () => {
      cancelled = true;
    };
  }, [productId]);

  function openSidebar() {
    if (collapseTimer.current) {
      window.clearTimeout(collapseTimer.current);
      collapseTimer.current = null;
    }
    setExpanded(true);
  }

  function scheduleCollapse() {
    if (collapseTimer.current) window.clearTimeout(collapseTimer.current);
    collapseTimer.current = window.setTimeout(() => {
      setExpanded(false);
      collapseTimer.current = null;
    }, 280);
  }

  function showToast(message: string) {
    setToast(message);
    window.setTimeout(() => setToast(null), 3000);
  }

  function handleLogout() {
    clearAuthSession();
    router.replace("/login");
    router.refresh();
  }

  function selectProduct(next: number) {
    if (!Number.isFinite(next) || next < 0) return;
    setActiveProductId(next);
    setProductMenuOpen(false);
    router.refresh();
  }

  async function handleProductCreated(product: TenantProduct) {
    await loadProducts();
    setActiveProductId(product.id);
    router.refresh();
    showToast("已创建并切换到新产品/品牌");
  }

  return (
    <>
      {toast ? (
        <div className="fixed bottom-6 right-6 z-[80] rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800 shadow-lg">
          {toast}
        </div>
      ) : null}

      <aside
        className="relative z-50 flex h-screen w-16 shrink-0 flex-col items-center overflow-hidden border-r border-[#1D2742] bg-[#0A1020] text-slate-100 shadow-[8px_0_24px_rgba(15,23,42,0.12)]"
        onMouseEnter={openSidebar}
        onMouseLeave={scheduleCollapse}
      >
        <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(180deg,#0A1020_0%,#111A31_58%,#141B32_100%)]" />
        <div className="relative z-10 flex h-full w-full flex-col items-center">
          <button
            type="button"
            className="mt-4 flex h-10 w-10 items-center justify-center rounded-lg bg-white/[0.07] text-white ring-1 ring-white/10 transition hover:bg-white/[0.11]"
            aria-label="展开导航"
            onFocus={openSidebar}
          >
            <Sparkles className="h-5 w-5" />
          </button>

          <div className="mt-7 flex flex-1 flex-col items-center gap-1.5">
            {miniItems.map((item) => {
              const Icon = item.icon;
              const active = isNavActive(pathname, item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  title={item.label}
                  aria-label={item.label}
                  className={cn(
                    "group relative flex h-10 w-10 items-center justify-center rounded-lg transition-all",
                    active
                      ? "bg-[#2563EB] text-white shadow-sm shadow-blue-950/20 ring-1 ring-white/10"
                      : "text-[#9AA7C7] hover:bg-white/[0.08] hover:text-white",
                  )}
                >
                  <Icon className="h-[19px] w-[19px]" />
                  {item.href === "/email-replies" && unprocessedReplyCount > 0 ? (
                    <span className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-rose-500 px-1 text-[10px] font-semibold text-white">
                      {unprocessedReplyCount > 99 ? "99+" : unprocessedReplyCount}
                    </span>
                  ) : null}
                  <span className="pointer-events-none absolute left-[52px] top-1/2 z-[90] hidden -translate-y-1/2 whitespace-nowrap rounded-md bg-[#10162D] px-2 py-1 text-xs text-white shadow-lg group-hover:block">
                    {item.label}
                  </span>
                </Link>
              );
            })}
          </div>

          <div className="mb-5 flex flex-col items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-full bg-slate-200 text-xs font-bold text-[#101632] ring-1 ring-white/20">
              13
            </div>
            <ActiveMiniIcon className="h-4 w-4 text-[#7EA6FF]" />
          </div>
        </div>
      </aside>

      <div
        className={cn(
          "fixed left-0 top-0 z-[70] h-screen w-[264px] overflow-hidden border-r border-white/10 bg-[#0A1020] text-slate-100 shadow-[18px_0_52px_rgba(15,23,42,0.24)] transition-transform duration-300 ease-out",
          expanded ? "translate-x-0" : "-translate-x-[268px]",
        )}
        onMouseEnter={openSidebar}
        onMouseLeave={scheduleCollapse}
      >
        <div className="pointer-events-none absolute inset-0 bg-[linear-gradient(155deg,#0A1020_0%,#111A31_58%,#141B32_100%)]" />
        <div className="pointer-events-none absolute right-0 top-0 h-full w-px bg-gradient-to-b from-white/20 via-white/8 to-transparent" />

        <div className="relative z-10 flex h-full flex-col">
          <div className="flex min-h-[76px] items-center gap-3 px-5 pb-3 pt-5">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-white/[0.07] ring-1 ring-white/10">
              <Sparkles className="h-5 w-5 text-white" />
            </div>
            <div className="min-w-0">
              <p className="text-base font-semibold tracking-normal text-white">红人智采</p>
              <p className="mt-0.5 text-xs text-slate-400">海外红人数据平台</p>
            </div>
          </div>

          <div className="px-4 pb-3">
            <div className="space-y-2 border-y border-white/8 py-3">
              <div className="mb-2 flex items-center justify-between gap-2">
                <label
                  htmlFor="product-selector"
                  className="text-[11px] font-semibold tracking-normal text-slate-500"
                >
                  当前产品 / 品牌
                </label>
                <button
                  type="button"
                  className="inline-flex h-7 items-center gap-1 rounded-md px-2 text-xs font-medium text-slate-300 transition hover:bg-white/[0.08] hover:text-white"
                  onClick={() => setCreateOpen(true)}
                >
                  <Plus className="h-3.5 w-3.5" />
                  新增
                </button>
              </div>
              <div className="relative" ref={productMenuRef}>
                <button
                  id="product-selector"
                  type="button"
                  disabled={productsLoading && products.length === 0}
                  aria-haspopup="listbox"
                  aria-expanded={productMenuOpen}
                  onClick={() => setProductMenuOpen((open) => !open)}
                  className="flex h-9 w-full items-center justify-between gap-2 rounded-md border border-[#33405D] bg-[#151D33] px-3 text-left text-[13px] font-medium text-slate-100 outline-none transition hover:border-[#4B5D82] hover:bg-[#1A243D] focus:border-[#7EA6FF]/80 focus:ring-2 focus:ring-[#2563EB]/25 disabled:cursor-wait disabled:text-slate-500"
                >
                  <span className="min-w-0 flex-1 truncate">{activeProductLabel}</span>
                  <ChevronDown
                    className={cn(
                      "h-4 w-4 shrink-0 text-slate-400 transition-transform",
                      productMenuOpen ? "rotate-180 text-[#9DBBFF]" : "",
                    )}
                  />
                </button>
                {productMenuOpen ? (
                  <div
                    role="listbox"
                    aria-labelledby="product-selector"
                    className="absolute left-0 right-0 top-[42px] z-[95] max-h-[360px] overflow-y-auto rounded-md border border-[#3B4A68] bg-[#111A2F] py-1 text-[13px] shadow-[0_18px_42px_rgba(0,0,0,0.42)] ring-1 ring-white/8 [scrollbar-color:rgba(157,187,255,0.42)_transparent] [scrollbar-width:thin]"
                  >
                    <button
                      type="button"
                      role="option"
                      aria-selected={productId === ALL_PRODUCTS_ID}
                      className={cn(
                        "flex min-h-9 w-full items-center px-3 text-left text-slate-200 transition hover:bg-[#1D2942] hover:text-white",
                        productId === ALL_PRODUCTS_ID ? "bg-[#263A66] text-white" : "",
                      )}
                      onClick={() => selectProduct(ALL_PRODUCTS_ID)}
                    >
                      <span className="truncate">全部产品（汇总）</span>
                    </button>
                    {products.map((product) => {
                      const selected = product.id === productId;
                      return (
                        <button
                          key={product.id}
                          type="button"
                          role="option"
                          aria-selected={selected}
                          className={cn(
                            "flex min-h-9 w-full items-center px-3 text-left text-slate-200 transition hover:bg-[#1D2942] hover:text-white",
                            selected ? "bg-[#263A66] text-white" : "",
                          )}
                          onClick={() => selectProduct(product.id)}
                        >
                          <span className="truncate">
                            {formatTenantProductLabel(product.name, product.brand)}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                ) : null}
              </div>
              {productsLoading && products.length === 0 ? (
                <p className="mt-2 text-[11px] text-slate-400">正在加载产品/品牌...</p>
              ) : null}
              {!productsLoading && products.length === 0 ? (
                <p className="mt-2 text-[11px] text-slate-400">暂无正式产品，请新增产品/品牌</p>
              ) : null}
              {productLoadError && products.length > 0 ? (
                <p className="mt-2 text-[11px] leading-relaxed text-amber-300/90">
                  {productLoadError}
                </p>
              ) : null}
              {!productsLoading && products.length === 0 ? (
                <button
                  type="button"
                  className="mt-2 inline-flex h-8 w-full items-center justify-center gap-1.5 rounded-md bg-white/[0.06] text-xs font-medium text-slate-200 transition hover:bg-white/[0.12]"
                  onClick={() => setCreateOpen(true)}
                >
                  <Plus className="h-3.5 w-3.5" />
                  新增产品/品牌
                </button>
              ) : null}
              <p className="mt-2 text-[11px] leading-relaxed text-slate-500">
                {productId === ALL_PRODUCTS_ID
                  ? "汇总显示所有产品的任务与红人数据"
                  : "仅显示当前产品下的任务与红人数据"}
              </p>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-1 px-4 pb-3">
            {quickLinks.map((item) => {
              const Icon = item.icon;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className="inline-flex h-8 items-center gap-1.5 rounded-md px-2 text-xs font-medium text-slate-400 transition hover:bg-white/[0.08] hover:text-white"
                >
                  <Icon className="h-3.5 w-3.5 text-slate-500" />
                  {item.label}
                </Link>
              );
            })}
          </div>

          <nav className="min-h-0 flex-1 overflow-y-auto px-3 pb-3 [scrollbar-color:rgba(170,182,216,0.35)_transparent] [scrollbar-width:thin]">
            <div className="space-y-4">
              {navGroups.map((group) => (
                <div key={group.title} className="space-y-1.5">
                  <p className="px-3 text-[11px] font-semibold tracking-normal text-slate-500">
                    {group.title}
                  </p>
                  <div className="space-y-0.5">
                    {group.items.map((item) => {
                      const Icon = item.icon;
                      const active = isNavActive(pathname, item.href);

                      return (
                        <Link
                          key={item.href}
                          href={item.href}
                          className={cn(
                            "group relative flex h-9 items-center gap-2.5 whitespace-nowrap rounded-md px-3 text-[13px] font-medium transition-all",
                            active
                              ? "bg-white/[0.1] text-white"
                              : "text-[#AAB6D8] hover:bg-white/[0.08] hover:text-white",
                          )}
                        >
                          <Icon
                            className={cn(
                              "h-[17px] w-[17px] shrink-0 transition-colors",
                              active ? "text-[#7EA6FF]" : "text-[#9AA7C7] group-hover:text-white",
                            )}
                          />
                          <span>{item.label}</span>
                          {item.href === "/email-replies" && unprocessedReplyCount > 0 ? (
                            <span className="ml-auto rounded-full bg-rose-500 px-1.5 py-0.5 text-[10px] font-semibold text-white">
                              {unprocessedReplyCount > 99 ? "99+" : unprocessedReplyCount}
                            </span>
                          ) : null}
                        </Link>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          </nav>

          <div className="border-t border-white/8 px-4 py-3">
            <div className="flex items-center gap-2.5">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-200 text-xs font-bold text-[#101632] ring-1 ring-white/20">
                13
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-[13px] font-semibold text-white">131845839...</p>
                <p className="text-[11px] text-slate-500">内部系统 · v0.1.0</p>
              </div>
              <button
                type="button"
                className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-slate-400 transition hover:bg-white/[0.09] hover:text-white"
                onClick={handleLogout}
                aria-label="退出登录"
              >
                <LogOut className="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>
      </div>

      <ProductCreateDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={handleProductCreated}
      />
    </>
  );
}
