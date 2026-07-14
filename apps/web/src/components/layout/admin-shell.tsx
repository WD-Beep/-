"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";

import { ProductCreateDialog } from "@/components/layout/product-create-dialog";
import { type TenantProduct } from "@/lib/api";
import { getStoredAuthSession, setAuthSession, type AuthSession } from "@/lib/auth";
import { writeCachedTenantProducts } from "@/lib/product-options-cache";
import { hasNoAccessibleProducts } from "@/lib/product-visibility";
import { useProductActions } from "@/components/providers/product-provider";

type AdminShellProps = {
  children: React.ReactNode;
  title: string;
  description?: string;
  actions?: React.ReactNode;
};

export function AdminShell({ children, title, description, actions }: AdminShellProps) {
  const router = useRouter();
  const { setProductId } = useProductActions();
  const [session, setSession] = useState<AuthSession | null>(() => getStoredAuthSession());
  const [createOpen, setCreateOpen] = useState(false);
  const noAssignedProducts = hasNoAccessibleProducts(session);

  function handleProductCreated(product: TenantProduct) {
    const currentSession = getStoredAuthSession() ?? session;
    if (currentSession) {
      const accessibleProducts = [
        ...currentSession.accessibleProducts.filter((item) => item.id !== product.id),
        product,
      ];
      const nextSession = { ...currentSession, accessibleProducts };
      setAuthSession(nextSession);
      writeCachedTenantProducts(accessibleProducts, nextSession.userId);
      setSession(nextSession);
    }
    setProductId(product.id);
    router.refresh();
  }

  return (
    <>
      <section className="flex h-full min-h-0 flex-col overflow-hidden">
        <header className="admin-page-header shrink-0 px-6 py-3 lg:px-8">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-0">
              <h1 className="text-[22px] font-semibold tracking-normal text-slate-950">{title}</h1>
              {description ? (
                <p className="mt-0.5 max-w-3xl text-[13px] leading-5 text-slate-600">{description}</p>
              ) : null}
            </div>
            {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
          </div>
        </header>
        <div className="min-h-0 flex-1 overflow-auto px-6 py-4 lg:px-8">
          {noAssignedProducts ? (
            <div className="flex h-full items-center justify-center">
              <div className="max-w-md rounded-lg border border-slate-200 bg-white px-6 py-5 text-center shadow-sm">
                <h2 className="text-base font-semibold text-slate-950">还没有品牌</h2>
                <p className="mt-2 text-sm leading-6 text-slate-600">
                  新增一个自己的品牌后，就可以开始采集、入库和跟进邮件。管理员后台会自动看到这个品牌的数据。
                </p>
                <button
                  type="button"
                  className="mt-4 inline-flex h-9 items-center justify-center gap-2 rounded-md bg-[#2563EB] px-4 text-sm font-medium text-white transition hover:bg-[#1D4ED8]"
                  onClick={() => setCreateOpen(true)}
                >
                  <Plus className="h-4 w-4" />
                  新增品牌
                </button>
              </div>
            </div>
          ) : (
            children
          )}
        </div>
      </section>
      <ProductCreateDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={handleProductCreated}
      />
    </>
  );
}
