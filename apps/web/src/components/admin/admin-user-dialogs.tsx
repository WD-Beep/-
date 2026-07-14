"use client";

import { useMemo, useState, type FormEvent } from "react";
import { Eye, EyeOff, Loader2, Pencil, Search, ShieldCheck, X } from "lucide-react";

import { AdminConfirmDialog } from "@/components/admin/admin-ui";
import { AdminBrandManagementDrawer } from "@/components/admin/admin-products-management";
import { Button } from "@/components/ui/button";
import {
  createAdminUser,
  resetAdminUserPassword,
  setAdminUserProducts,
  updateAdminUser,
  type AdminProduct,
  type AdminUser,
} from "@/lib/api";

type AccountDialogProps = {
  open: boolean;
  user?: AdminUser | null;
  products: AdminProduct[];
  users: AdminUser[];
  currentUserId?: number | null;
  onClose: () => void;
  onSaved: (user: AdminUser) => void | Promise<void>;
  onProductsChanged: () => void | Promise<void>;
};

const fieldClass =
  "h-10 w-full rounded-md border border-[#D8E2EE] bg-white px-3 text-sm text-[#102033] outline-none focus:border-[#2563EB] focus:ring-2 focus:ring-[#DBEAFE]";

export function AdminUserAccountDialog(props: AccountDialogProps) {
  const { open, user } = props;
  if (!open) return null;
  return <AdminUserAccountDialogContent key={user?.id ?? "new"} {...props} />;
}

function AdminUserAccountDialogContent({
  user,
  products,
  users,
  currentUserId,
  onClose,
  onSaved,
  onProductsChanged,
}: AccountDialogProps) {
  const [username, setUsername] = useState(user?.username ?? "");
  const [displayName, setDisplayName] = useState(user?.display_name ?? "");
  const [email, setEmail] = useState(user?.email ?? "");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [role, setRole] = useState<"admin" | "sales">(user?.role ?? "sales");
  const [isActive, setIsActive] = useState(user?.is_active ?? true);
  const [productIds, setProductIds] = useState<number[]>((user?.bound_products ?? []).map((product) => product.id));
  const [brandSearch, setBrandSearch] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [confirmRemoveOpen, setConfirmRemoveOpen] = useState(false);
  const [pendingSubmit, setPendingSubmit] = useState<(() => Promise<void>) | null>(null);
  const [removedProductNames, setRemovedProductNames] = useState<string[]>([]);
  const [brandManagementOpen, setBrandManagementOpen] = useState(false);
  const usernameLocked = Boolean(user && currentUserId && user.id === currentUserId);

  const initialProductIds = useMemo(
    () => (user?.bound_products ?? []).map((product) => product.id),
    [user],
  );

  const filteredProducts = useMemo(() => {
    const query = brandSearch.trim().toLowerCase();
    if (!query) return products;
    return products.filter(
      (product) =>
        product.name.toLowerCase().includes(query) ||
        product.slug.toLowerCase().includes(query) ||
      String(product.id).includes(query),
    );
  }, [brandSearch, products]);

  const activeProductIds = useMemo(() => {
    const availableIds = new Set(products.map((product) => product.id));
    return productIds.filter((id) => availableIds.has(id));
  }, [productIds, products]);

  function toggleProduct(productId: number) {
    setProductIds((current) =>
      current.includes(productId) ? current.filter((id) => id !== productId) : [...current, productId],
    );
  }

  async function performSave() {
    setSubmitting(true);
    setError(null);
    try {
      let saved: AdminUser;
      if (user) {
        saved = await updateAdminUser(user.id, {
          username: username.trim(),
          display_name: displayName.trim() || null,
          email: email.trim() || null,
          role,
          is_active: isActive,
        });
        if (password.trim().length > 0) {
          await resetAdminUserPassword(user.id, password.trim());
        }
        saved = await setAdminUserProducts(user.id, role === "admin" ? [] : activeProductIds);
      } else {
        saved = await createAdminUser({
          username: username.trim(),
          password,
          display_name: displayName.trim() || null,
          email: email.trim() || null,
          role,
          is_active: isActive,
          product_ids: role === "admin" ? [] : activeProductIds,
        });
      }
      await onSaved(saved);
      setSuccessMessage(user ? "账号与品牌权限已更新。" : "账号创建成功。");
      window.setTimeout(() => onClose(), 600);
    } catch (err) {
      const message = err instanceof Error ? err.message : "保存账号失败";
      if (/exist|duplicate|409|已存在|重复/i.test(message)) {
        setError("登录账号已存在，请更换后再保存。");
      } else {
        setError(message);
      }
    } finally {
      setSubmitting(false);
      setConfirmRemoveOpen(false);
      setPendingSubmit(null);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    const trimmedUsername = username.trim();
    const trimmedEmail = email.trim();
    if (!trimmedUsername) {
      setError("请填写登录账号。");
      return;
    }
    if (!user && !password.trim()) {
      setError("请填写初始密码。");
      return;
    }
    if (!/^[A-Za-z0-9_.-]+$/.test(trimmedUsername)) {
      setError("登录账号只能包含字母、数字、下划线、点和短横线。");
      return;
    }
    if (trimmedEmail && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmedEmail)) {
      setError("邮箱格式不正确，请输入有效的邮箱地址。");
      return;
    }
    const removed = initialProductIds.filter((id) => !activeProductIds.includes(id));
    if (user && role === "sales" && removed.length > 0) {
      const names = products.filter((product) => removed.includes(product.id)).map((product) => product.name);
      setRemovedProductNames(names);
      setPendingSubmit(() => performSave);
      setConfirmRemoveOpen(true);
      return;
    }

    await performSave();
  }

  return (
    <>
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#102033]/55 p-4 backdrop-blur-[2px]">
        <div className="max-h-[92vh] w-full max-w-2xl overflow-auto rounded-xl border border-[#D8E2EE] bg-white shadow-[0_28px_80px_rgba(16,32,51,0.28)]">
          <div className="sticky top-0 z-10 flex items-start justify-between border-b border-[#E5ECF4] bg-white px-6 py-5">
            <div>
              <div className="flex items-center gap-2 text-[#2563EB]">
                <ShieldCheck className="h-4 w-4" />
                <span className="text-xs font-semibold tracking-wider">账号与权限</span>
              </div>
              <h2 className="mt-2 text-xl font-semibold text-[#102033]">
                {user ? "编辑后台账号" : "创建后台账号"}
              </h2>
              <p className="mt-1 text-sm text-[#667085]">
                {user ? "修改账号信息、重置密码，并调整品牌数据权限。" : "设置账号角色、状态，以及业务员可查看和操作的品牌范围。"}
              </p>
            </div>
            <button type="button" onClick={onClose} disabled={submitting} className="rounded-md p-2 text-[#667085] hover:bg-[#F3F6FA]" aria-label="关闭">
              <X className="h-4 w-4" />
            </button>
          </div>
          <form onSubmit={submit} noValidate className="space-y-5 p-6">
            {error ? <div className="rounded-md border border-[#FECDCA] bg-[#FEF3F2] px-4 py-3 text-sm text-[#B42318]">{error}</div> : null}
            {successMessage ? (
              <div className="rounded-md border border-[#BAE6D1] bg-[#ECFDF3] px-4 py-3 text-sm text-[#047857]">{successMessage}</div>
            ) : null}
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="grid gap-1.5 text-sm font-medium text-[#344054]">
                登录账号 *
                <input
                  className={fieldClass}
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  disabled={usernameLocked}
                  placeholder="例如 sales11"
                />
                {usernameLocked ? (
                  <span className="text-xs font-normal text-[#667085]">
                    当前登录管理员账号不可修改登录账号；请使用其他管理员账号操作。
                  </span>
                ) : null}
              </label>
              <label className="grid gap-1.5 text-sm font-medium text-[#344054]">
                {user ? "重置密码" : "初始密码 *"}
                <span className="relative">
                  <input
                    className={`${fieldClass} pr-10`}
                    type={showPassword ? "text" : "password"}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder={user ? "留空则不修改（管理员可设任意密码）" : "管理员可设任意密码"}
                  />
                  <button type="button" onClick={() => setShowPassword((value) => !value)} className="absolute inset-y-0 right-0 px-3 text-[#667085]">
                    {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </span>
              </label>
              <label className="grid gap-1.5 text-sm font-medium text-[#344054]">
                姓名 / 昵称
                <input className={fieldClass} value={displayName} onChange={(e) => setDisplayName(e.target.value)} placeholder="用于后台展示" />
              </label>
              <label className="grid gap-1.5 text-sm font-medium text-[#344054]">
                邮箱
                <input className={fieldClass} type="text" inputMode="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@company.com（选填）" />
              </label>
              <label className="grid gap-1.5 text-sm font-medium text-[#344054]">
                账号角色
                <select className={fieldClass} value={role} onChange={(e) => setRole(e.target.value as "admin" | "sales")}>
                  <option value="sales">业务员 · 仅访问已分配品牌</option>
                  <option value="admin">管理员 · 查看全部数据并管理账号</option>
                </select>
              </label>
              <label className="grid gap-1.5 text-sm font-medium text-[#344054]">
                账号状态
                <select className={fieldClass} value={isActive ? "active" : "disabled"} onChange={(e) => setIsActive(e.target.value === "active")}>
                  <option value="active">启用 · 可以登录</option>
                  <option value="disabled">禁用 · 立即禁止登录</option>
                </select>
              </label>
            </div>

            <section className="rounded-lg border border-[#DDE6F0] bg-[#F8FAFD] p-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h3 className="text-sm font-semibold text-[#102033]">品牌数据权限</h3>
                  <p className="mt-1 text-xs text-[#667085]">业务员只能看到勾选品牌的数据；管理员默认可查看全部品牌。</p>
                </div>
                <div className="flex items-center gap-3">
                  <button
                    type="button"
                    className="inline-flex items-center gap-1 text-xs font-semibold text-[#2563EB]"
                    onClick={() => setBrandManagementOpen(true)}
                  >
                    <Pencil className="h-3.5 w-3.5" />
                    编辑品牌
                  </button>
                  {role === "sales" && products.length ? (
                    <button
                      type="button"
                      onClick={() =>
                        setProductIds(
                          activeProductIds.length === products.length ? [] : products.map((product) => product.id),
                        )
                      }
                      className="text-xs font-semibold text-[#2563EB]"
                    >
                      {activeProductIds.length === products.length ? "取消全选" : "全选"}
                    </button>
                  ) : null}
                </div>
              </div>
              {role === "admin" ? (
                <div className="mt-3 rounded-md border border-[#BFDBFE] bg-[#EFF6FF] px-3 py-2 text-sm text-[#1D4ED8]">
                  管理员拥有全部品牌和业务数据访问权限，无需单独分配。
                </div>
              ) : products.length ? (
                <>
                  <label className="relative mt-3 block">
                    <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#98A2B3]" />
                    <input
                      className={`${fieldClass} pl-9`}
                      value={brandSearch}
                      onChange={(e) => setBrandSearch(e.target.value)}
                      placeholder="搜索品牌名称、slug 或 ID"
                    />
                  </label>
                  <div className="mt-3 grid max-h-52 gap-2 overflow-auto sm:grid-cols-2">
                    {filteredProducts.map((product) => (
                      <label
                        key={product.id}
                        className="flex cursor-pointer items-center gap-2 rounded-md border border-[#DDE6F0] bg-white px-3 py-2 text-sm text-[#344054] hover:border-[#93C5FD]"
                      >
                        <input
                          type="checkbox"
                          checked={productIds.includes(product.id)}
                          onChange={() => toggleProduct(product.id)}
                          className="h-4 w-4 accent-[#2563EB]"
                        />
                        <span className="min-w-0 truncate">{product.name}</span>
                      </label>
                    ))}
                  </div>
                  {!filteredProducts.length ? <p className="mt-3 text-sm text-[#667085]">没有匹配的品牌。</p> : null}
                  <p className="mt-2 text-xs text-[#667085]">已选 {activeProductIds.length} / {products.length} 个品牌</p>
                </>
              ) : (
                <p className="mt-3 text-sm text-[#667085]">暂无可分配品牌，可先到“品牌管理”创建品牌。</p>
              )}
            </section>

            <div className="flex justify-end gap-2 border-t border-[#E5ECF4] pt-5">
              <Button type="button" variant="outline" onClick={onClose} disabled={submitting}>
                取消
              </Button>
              <Button type="submit" disabled={submitting} className="bg-[#2563EB] text-white hover:bg-[#1D4ED8]">
                {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                {user ? "保存设置" : "创建账号"}
              </Button>
            </div>
          </form>
        </div>
      </div>

      <AdminConfirmDialog
        open={confirmRemoveOpen}
        title="确认取消品牌权限？"
        description={`即将取消 ${removedProductNames.length} 个品牌的访问权限：${removedProductNames.slice(0, 5).join("、")}${removedProductNames.length > 5 ? " 等" : ""}。业务员将无法再查看这些品牌的数据。`}
        confirmLabel="确认取消权限"
        danger
        loading={submitting}
        onCancel={() => {
          setConfirmRemoveOpen(false);
          setPendingSubmit(null);
        }}
        onConfirm={() => {
          void pendingSubmit?.();
        }}
      />
      <AdminBrandManagementDrawer
        open={brandManagementOpen}
        products={products}
        users={users}
        selectedProductIds={activeProductIds}
        onSelectedProductIdsChange={setProductIds}
        onClose={() => setBrandManagementOpen(false)}
        onProductsChanged={onProductsChanged}
      />
    </>
  );
}

export function AdminPasswordResetDialog({ user, onClose }: { user: AdminUser | null; onClose: () => void }) {
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  if (!user) return null;
  const userId = user.id;
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!password.trim()) {
      setMessage("请填写新密码。");
      return;
    }
    setSubmitting(true);
    try {
      await resetAdminUserPassword(userId, password);
      setMessage("密码已重置，新密码可以立即登录。");
      setPassword("");
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "重置失败");
    } finally {
      setSubmitting(false);
    }
  }
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-[#102033]/55 p-4">
      <form onSubmit={submit} className="w-full max-w-md rounded-xl bg-white p-6 shadow-2xl">
        <div className="flex justify-between">
          <div>
            <h2 className="text-lg font-semibold text-[#102033]">重置 {user.username} 的密码</h2>
            <p className="mt-1 text-sm text-[#667085]">保存后旧密码立即失效。</p>
          </div>
          <button type="button" onClick={onClose}>
            <X className="h-4 w-4" />
          </button>
        </div>
        {message ? <div className="mt-4 rounded-md bg-[#F3F6FA] px-3 py-2 text-sm text-[#344054]">{message}</div> : null}
        <label className="mt-4 grid gap-1.5 text-sm font-medium text-[#344054]">
          新密码
          <input autoFocus type="password" className={fieldClass} value={password} onChange={(e) => setPassword(e.target.value)} placeholder="管理员可设任意密码" />
        </label>
        <div className="mt-5 flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={onClose}>
            关闭
          </Button>
          <Button type="submit" disabled={submitting} className="bg-[#2563EB] text-white">
            确认重置
          </Button>
        </div>
      </form>
    </div>
  );
}
