// 文件说明：前端管理员后台组件；当前文件：admin products management
"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Eye, EyeOff, Loader2, Pencil, Plus, Search, Trash2, Upload } from "lucide-react";

import {
  AdminConfirmDialog,
  AdminDrawer,
  AdminFilterField,
  AdminInput,
  AdminSelect,
} from "@/components/admin/admin-ui";
import { UNASSIGNED_SALESPERSON_KEY } from "@/components/admin/admin-ui-helpers";
import { Button } from "@/components/ui/button";
import {
  createAdminUser,
  createTenantProduct,
  deleteAdminUser,
  deleteAdminProduct,
  resetAdminUserPassword,
  setAdminUserProducts,
  updateAdminUser,
  updateTenantProduct,
  type AdminProduct,
  type AdminUser,
} from "@/lib/api";
import { clearCachedTenantProducts } from "@/lib/product-options-cache";
import { slugifyProductName } from "@/lib/product-slug";
import { cn } from "@/lib/utils";

const AVATAR_CACHE_KEY = "admin-progress-avatars-v1";

type AvatarCache = {
  users: Record<string, string>;
  products: Record<string, string>;
};

function readAvatarCache(): AvatarCache {
  if (typeof window === "undefined") return { users: {}, products: {} };
  try {
    const raw = window.localStorage.getItem(AVATAR_CACHE_KEY);
    if (!raw) return { users: {}, products: {} };
    const parsed = JSON.parse(raw) as Partial<AvatarCache>;
    return { users: parsed.users ?? {}, products: parsed.products ?? {} };
  } catch {
    return { users: {}, products: {} };
  }
}

function writeAvatarCache(cache: AvatarCache) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(AVATAR_CACHE_KEY, JSON.stringify(cache));
}

export function useAdminAvatarCache() {
  const [cache, setCache] = useState<AvatarCache>(() => readAvatarCache());

  function setUserAvatar(userId: number, url: string | null) {
    setCache((current) => {
      const next = {
        users: { ...current.users },
        products: { ...current.products },
      };
      const key = String(userId);
      if (url) next.users[key] = url;
      else delete next.users[key];
      writeAvatarCache(next);
      return next;
    });
  }

  function setProductLogo(productId: number, url: string | null) {
    setCache((current) => {
      const next = {
        users: { ...current.users },
        products: { ...current.products },
      };
      const key = String(productId);
      if (url) next.products[key] = url;
      else delete next.products[key];
      writeAvatarCache(next);
      return next;
    });
  }

  return {
    getUserAvatar: (userId: number | null | undefined) => (userId ? cache.users[String(userId)] : undefined),
    getProductLogo: (productId: number | null | undefined) => (productId ? cache.products[String(productId)] : undefined),
    setUserAvatar,
    setProductLogo,
  };
}

const fieldClass =
  "h-10 w-full rounded-md border border-[#D8E2EE] bg-white px-3 text-sm text-[#102033] outline-none focus:border-[#2563EB] focus:ring-2 focus:ring-[#DBEAFE]";

function ImageUploadField({
  label,
  hint,
  previewUrl,
  onChange,
}: {
  label: string;
  hint?: string;
  previewUrl: string | null;
  onChange: (url: string | null) => void;
}) {
  return (
    <label className="grid gap-2 text-sm font-medium text-[#344054]">
      {label}
      <div className="flex items-center gap-3">
        {previewUrl ? (
          <img src={previewUrl} alt="" className="h-14 w-14 rounded-full border border-[#D8E2EE] object-cover" />
        ) : (
          <span className="inline-flex h-14 w-14 items-center justify-center rounded-full border border-dashed border-[#D8E2EE] bg-[#FAFBFC] text-[#98A2B3]">
            <Upload className="h-4 w-4" />
          </span>
        )}
        <div className="flex flex-wrap gap-2">
          <label className="inline-flex cursor-pointer items-center rounded-md border border-[#D8E2EE] bg-white px-3 py-1.5 text-xs font-medium text-[#344054] hover:bg-[#F8FAFD]">
            上传图片
            <input
              type="file"
              accept="image/*"
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (!file) return;
                onChange(URL.createObjectURL(file));
              }}
            />
          </label>
          {previewUrl ? (
            <button type="button" className="text-xs text-[#667085] hover:text-[#B42318]" onClick={() => onChange(null)}>
              移除
            </button>
          ) : null}
        </div>
      </div>
      {hint ? <span className="text-xs font-normal text-[#667085]">{hint}</span> : null}
    </label>
  );
}

export function hasBrandBusinessData(brand: AdminProduct): boolean {
  return (
    brand.collection_task_count > 0 ||
    brand.influencer_count > 0 ||
    brand.email_count > 0 ||
    brand.reply_count > 0
  );
}

export function buildBrandDeleteDescription(brand: AdminProduct): string {
  if (!hasBrandBusinessData(brand)) {
    return "删除后不可恢复，请确认该品牌不再需要。";
  }
  const parts: string[] = [];
  if (brand.collection_task_count > 0) parts.push(`${brand.collection_task_count} 个任务`);
  if (brand.influencer_count > 0) parts.push(`${brand.influencer_count} 个红人`);
  if (brand.email_count > 0) parts.push(`${brand.email_count} 封邮件`);
  if (brand.reply_count > 0) parts.push(`${brand.reply_count} 条回复`);
  return `该品牌已有业务数据（${parts.join("、")}），删除后将一并清除且不可恢复。请确认是否继续删除？`;
}

export function hasSalespersonRelatedData(row: {
  brandCount: number;
  taskCount: number;
  influencerCount: number;
  emailCount: number;
  replyCount: number;
}): boolean {
  return (
    row.brandCount > 0 ||
    row.taskCount > 0 ||
    row.influencerCount > 0 ||
    row.emailCount > 0 ||
    row.replyCount > 0
  );
}

export function hasSalespersonUserRelatedData(user: AdminUser): boolean {
  return (
    (user.bound_products?.length ?? 0) > 0 ||
    user.product_count > 0 ||
    user.collection_task_count > 0 ||
    user.influencer_count > 0 ||
    user.email_count > 0 ||
    user.reply_count > 0
  );
}

export function salespersonHasRelatedData(user: AdminUser, row: Parameters<typeof hasSalespersonRelatedData>[0]): boolean {
  return hasSalespersonRelatedData(row) || hasSalespersonUserRelatedData(user);
}

export async function disableBrand(brandId: number) {
  await updateTenantProduct(brandId, { is_hidden: true });
}

export async function enableBrand(brandId: number) {
  await updateTenantProduct(brandId, { is_hidden: false, is_archived: false });
}

export async function reassignBrandOwner({
  brandId,
  newOwnerUserId,
  users,
}: {
  brandId: number;
  newOwnerUserId: number | null;
  users: AdminUser[];
}) {
  for (const user of users.filter((item) => item.role === "sales")) {
    const currentIds = (user.bound_products ?? []).map((product) => product.id);
    const hasBrand = currentIds.includes(brandId);
    const shouldOwn = newOwnerUserId !== null && user.id === newOwnerUserId;
    if (shouldOwn && !hasBrand) {
      await setAdminUserProducts(user.id, [...currentIds, brandId]);
    } else if (!shouldOwn && hasBrand) {
      await setAdminUserProducts(
        user.id,
        currentIds.filter((id) => id !== brandId),
      );
    }
  }
}

export async function transferBrandsBetweenUsers({
  fromUserId,
  toUserId,
  users,
}: {
  fromUserId: number;
  toUserId: number;
  users: AdminUser[];
}) {
  const fromUser = users.find((user) => user.id === fromUserId);
  const toUser = users.find((user) => user.id === toUserId);
  if (!fromUser || !toUser) return;
  const merged = new Set<number>([
    ...(toUser.bound_products ?? []).map((product) => product.id),
    ...(fromUser.bound_products ?? []).map((product) => product.id),
  ]);
  await setAdminUserProducts(toUserId, Array.from(merged));
  await setAdminUserProducts(fromUserId, []);
}

type SalespersonDrawerProps = {
  open: boolean;
  mode: "create" | "edit";
  user: AdminUser | null;
  products: AdminProduct[];
  users: AdminUser[];
  avatarUrl: string | null;
  onAvatarChange: (url: string | null) => void;
  onClose: () => void;
  onSaved: () => void;
  onProductsChanged: () => void | Promise<void>;
};

export function SalespersonFormDrawer(props: SalespersonDrawerProps) {
  const { open, mode, user } = props;
  if (!open) return null;
  return <SalespersonFormDrawerContent key={`${mode}-${user?.id ?? "new"}`} {...props} />;
}

function SalespersonFormDrawerContent({
  open,
  mode,
  user,
  products,
  users,
  avatarUrl,
  onAvatarChange,
  onClose,
  onSaved,
  onProductsChanged,
}: SalespersonDrawerProps) {
  const [username, setUsername] = useState(user?.username ?? "");
  const [displayName, setDisplayName] = useState(user?.display_name ?? "");
  const [email, setEmail] = useState(user?.email ?? "");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [isActive, setIsActive] = useState(user?.is_active ?? true);
  const [productIds, setProductIds] = useState<number[]>((user?.bound_products ?? []).map((product) => product.id));
  const [brandSearch, setBrandSearch] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [revokeConfirmOpen, setRevokeConfirmOpen] = useState(false);
  const [pendingRevokeNames, setPendingRevokeNames] = useState<string[]>([]);
  const [pendingSave, setPendingSave] = useState<(() => Promise<void>) | null>(null);
  const [brandManagementOpen, setBrandManagementOpen] = useState(false);

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

  async function performSave() {
    setSubmitting(true);
    setError(null);
    const emailPayload = email.trim() || null;
    try {
      if (mode === "create") {
        await createAdminUser({
          username: username.trim(),
          password,
          display_name: displayName.trim() || null,
          email: emailPayload,
          role: "sales",
          is_active: isActive,
          product_ids: activeProductIds,
        });
      } else if (user) {
        await updateAdminUser(user.id, {
          username: username.trim(),
          display_name: displayName.trim() || null,
          email: emailPayload,
          is_active: isActive,
        });
        if (password.trim()) {
          await resetAdminUserPassword(user.id, password.trim());
        }
        await setAdminUserProducts(user.id, activeProductIds);
      }
      onSaved();
      onClose();
    } catch (err) {
      const message = err instanceof Error ? err.message : "保存业务员失败。";
      if (/exist|duplicate|已存在|重复/i.test(message)) {
        setError("用户名已存在，请更换登录账号。");
      } else {
        setError(message);
      }
    } finally {
      setSubmitting(false);
      setRevokeConfirmOpen(false);
      setPendingSave(null);
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    if (mode === "create") {
      if (!username.trim()) {
        setError("请填写登录账号。");
        return;
      }
      if (!password.trim()) {
        setError("请填写初始密码。");
        return;
      }
    } else if (!username.trim()) {
      setError("请填写登录账号。");
      return;
    }

    if (mode === "edit" && user) {
      const removedIds = initialProductIds.filter((id) => !activeProductIds.includes(id));
      const riskyRemoved = products.filter(
        (product) =>
          removedIds.includes(product.id) &&
          (product.collection_task_count > 0 ||
            product.influencer_count > 0 ||
            product.email_count > 0 ||
            product.reply_count > 0),
      );
      if (riskyRemoved.length > 0) {
        setPendingRevokeNames(riskyRemoved.map((product) => product.name));
        setPendingSave(() => performSave);
        setRevokeConfirmOpen(true);
        return;
      }
    }

    await performSave();
  }

  const visibleSelectedCount = filteredProducts.filter((product) => activeProductIds.includes(product.id)).length;

  return (
    <>
      <AdminDrawer
        open={open}
        title={mode === "create" ? "新增业务员" : "编辑业务员"}
        description={
          mode === "create"
            ? "设置业务员基本信息、头像预览和负责品牌范围。"
            : "修改业务员信息、重置密码，并调整负责品牌权限。"
        }
        onClose={onClose}
      >
        <form onSubmit={submit} className="space-y-5">
          {error ? <div className="rounded-md border border-[#FECDCA] bg-[#FEF3F2] px-4 py-3 text-sm text-[#B42318]">{error}</div> : null}
          <ImageUploadField
            label="业务员头像"
            hint="头像仅本地预览，上传接口待后端接入（avatarUrl）。"
            previewUrl={avatarUrl}
            onChange={onAvatarChange}
          />
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="grid gap-1.5 text-sm font-medium text-[#344054]">
              登录账号 *
              <input
                className={fieldClass}
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="例如 sales11"
              />
            </label>
            <label className="grid gap-1.5 text-sm font-medium text-[#344054]">
              {mode === "create" ? "初始密码 *" : "重置密码"}
              <span className="relative">
                <input
                  className={cn(fieldClass, "pr-10")}
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder={mode === "create" ? "管理员手动设置密码" : "留空则不修改密码"}
                />
                <button
                  type="button"
                  className="absolute inset-y-0 right-0 flex items-center px-3 text-[#667085]"
                  onClick={() => setShowPassword((current) => !current)}
                  aria-label={showPassword ? "隐藏密码" : "显示密码"}
                >
                  {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </span>
            </label>
            <label className="grid gap-1.5 text-sm font-medium text-[#344054]">
              业务员姓名
              <input className={fieldClass} value={displayName} onChange={(e) => setDisplayName(e.target.value)} placeholder="后台展示名称" />
            </label>
            <label className="grid gap-1.5 text-sm font-medium text-[#344054]">
              邮箱 / 手机 / 联系方式
              <input className={fieldClass} value={email ?? ""} onChange={(e) => setEmail(e.target.value)} placeholder="邮箱、手机号、微信号或内部账号（选填）" maxLength={255} />
            </label>
            <label className="grid gap-1.5 text-sm font-medium text-[#344054]">
              状态
              <select className={fieldClass} value={isActive ? "active" : "disabled"} onChange={(e) => setIsActive(e.target.value === "active")}>
                <option value="active">启用</option>
                <option value="disabled">停用</option>
              </select>
            </label>
          </div>
          <section className="rounded-lg border border-[#DDE6F0] bg-[#F8FAFD] p-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h3 className="text-sm font-semibold text-[#102033]">负责品牌</h3>
                <p className="mt-1 text-xs text-[#667085]">勾选后该业务员可在工作台查看和处理这些品牌。</p>
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
                {products.length ? (
                  <button
                    type="button"
                    className="text-xs font-semibold text-[#2563EB]"
                    onClick={() => {
                      const visibleIds = filteredProducts.map((product) => product.id);
                      const allVisibleSelected = visibleIds.every((id) => productIds.includes(id));
                      setProductIds((current) =>
                        allVisibleSelected
                          ? current.filter((id) => !visibleIds.includes(id))
                          : Array.from(new Set([...current, ...visibleIds])),
                      );
                    }}
                  >
                    {filteredProducts.length > 0 && visibleSelectedCount === filteredProducts.length ? "取消全选" : "全选"}
                  </button>
                ) : null}
              </div>
            </div>
            {products.length ? (
              <>
                <div className="relative mt-3">
                  <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[#98A2B3]" />
                  <input
                    className={cn(fieldClass, "pl-9")}
                    value={brandSearch}
                    onChange={(e) => setBrandSearch(e.target.value)}
                    placeholder="搜索品牌名称 / slug / ID"
                  />
                </div>
                <div className="mt-3 grid max-h-52 gap-2 overflow-auto sm:grid-cols-2">
                  {filteredProducts.map((product) => (
                    <label key={product.id} className="flex cursor-pointer items-center gap-2 rounded-md border border-[#DDE6F0] bg-white px-3 py-2 text-sm text-[#344054]">
                      <input
                        type="checkbox"
                        checked={productIds.includes(product.id)}
                        onChange={() =>
                          setProductIds((current) =>
                            current.includes(product.id) ? current.filter((id) => id !== product.id) : [...current, product.id],
                          )
                        }
                        className="h-4 w-4 accent-[#2563EB]"
                      />
                      <span className="min-w-0 flex-1 truncate">{product.name}</span>
                      <span className="shrink-0 font-mono text-[10px] text-[#98A2B3]">#{product.id}</span>
                    </label>
                  ))}
                  {!filteredProducts.length ? <p className="col-span-full text-sm text-[#667085]">没有匹配的品牌。</p> : null}
                </div>
              </>
            ) : (
              <p className="mt-3 text-sm text-[#667085]">暂无可分配品牌，创建账号后可再到品牌进度页分配。</p>
            )}
          </section>
          <div className="flex justify-end gap-2 border-t border-[#E5ECF4] pt-4">
            <Button type="button" variant="outline" onClick={onClose} disabled={submitting}>
              取消
            </Button>
            <Button type="submit" disabled={submitting} className="bg-[#2563EB] text-white hover:bg-[#1D4ED8]">
              {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              {mode === "create" ? "创建业务员" : "保存修改"}
            </Button>
          </div>
        </form>
      </AdminDrawer>

      <AdminConfirmDialog
        open={revokeConfirmOpen}
        title="确认取消品牌权限？"
        description={`以下品牌已有任务或跟进数据：${pendingRevokeNames.join("、")}。取消权限后该业务员将无法继续处理这些品牌，是否确认？`}
        confirmLabel="确认取消并保存"
        danger
        loading={submitting}
        onCancel={() => {
          setRevokeConfirmOpen(false);
          setPendingSave(null);
        }}
        onConfirm={() => {
          void pendingSave?.();
        }}
      />
      <AdminBrandManagementDrawer
        open={brandManagementOpen}
        products={products}
        users={users}
        selectedProductIds={activeProductIds}
        onSelectedProductIdsChange={setProductIds}
        defaultOwnerUserId={user?.id ?? null}
        onClose={() => setBrandManagementOpen(false)}
        onProductsChanged={onProductsChanged}
      />
    </>
  );
}

type BrandDrawerProps = {
  open: boolean;
  brand: AdminProduct | null;
  users: AdminUser[];
  logoUrl: string | null;
  onLogoChange: (url: string | null) => void;
  onClose: () => void;
  onSaved: () => void;
};

export function BrandFormDrawer(props: BrandDrawerProps) {
  const { open, brand } = props;
  if (!open || !brand) return null;
  return <BrandFormDrawerContent key={brand.id} {...props} brand={brand} />;
}

function BrandFormDrawerContent({
  open,
  brand,
  users,
  logoUrl,
  onLogoChange,
  onClose,
  onSaved,
}: BrandDrawerProps & { brand: AdminProduct }) {
  const [name, setName] = useState(brand.name);
  const [slug, setSlug] = useState(brand.slug);
  const [slugTouched, setSlugTouched] = useState(false);
  const [description, setDescription] = useState(brand.description ?? "");
  const [ownerUserId, setOwnerUserId] = useState<string>(() => {
    const owner = brand.members.find((member) => member.role === "owner") ?? brand.members[0];
    return owner ? String(owner.user_id) : "";
  });
  const [brandStatus, setBrandStatus] = useState<"active" | "hidden">(
    brand.status === "hidden" || brand.status === "archived" ? "hidden" : "active",
  );
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const salesUsers = useMemo(() => users.filter((user) => user.role === "sales"), [users]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    const trimmedName = name.trim();
    if (!trimmedName) {
      setError("请填写品牌名称。");
      return;
    }
    setSubmitting(true);
    try {
      await updateTenantProduct(brand!.id, {
        name: trimmedName,
        slug: (slug.trim() || slugifyProductName(trimmedName)).slice(0, 100),
        description: description.trim() || null,
        is_hidden: brandStatus === "hidden",
      });
      const nextOwnerId = ownerUserId ? Number(ownerUserId) : null;
      await reassignBrandOwner({ brandId: brand!.id, newOwnerUserId: nextOwnerId, users });
      onSaved();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存品牌失败。");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AdminDrawer
      open={open}
      title={`编辑品牌 · ${brand.name}`}
      description="修改品牌名称、slug、负责人、状态和备注。"
      onClose={onClose}
    >
      <form onSubmit={submit} className="space-y-5">
        {error ? <div className="rounded-md border border-[#FECDCA] bg-[#FEF3F2] px-4 py-3 text-sm text-[#B42318]">{error}</div> : null}
        <ImageUploadField
          label="品牌 Logo"
          hint="Logo 仅本地预览，上传接口待后端接入（logoUrl）。"
          previewUrl={logoUrl}
          onChange={onLogoChange}
        />
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="grid gap-1.5 text-sm font-medium text-[#344054]">
            品牌名称 *
            <input
              className={fieldClass}
              value={name}
              onChange={(e) => {
                const nextName = e.target.value;
                setName(nextName);
                if (!slugTouched) setSlug(slugifyProductName(nextName));
              }}
            />
          </label>
          <label className="grid gap-1.5 text-sm font-medium text-[#344054]">
            slug
            <input
              className={fieldClass}
              value={slug}
              onChange={(e) => {
                setSlug(e.target.value);
                setSlugTouched(true);
              }}
            />
          </label>
          <label className="grid gap-1.5 text-sm font-medium text-[#344054] sm:col-span-2">
            所属业务员 / 负责人
            <select className={fieldClass} value={ownerUserId} onChange={(e) => setOwnerUserId(e.target.value)}>
              <option value="">未分配</option>
              {salesUsers.map((user) => (
                <option key={user.id} value={user.id}>
                  {user.display_name?.trim() || user.username} (#{user.id})
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-1.5 text-sm font-medium text-[#344054]">
            品牌状态
            <select className={fieldClass} value={brandStatus} onChange={(e) => setBrandStatus(e.target.value as "active" | "hidden")}>
              <option value="active">启用</option>
              <option value="hidden">停用</option>
            </select>
          </label>
          <label className="grid gap-1.5 text-sm font-medium text-[#344054] sm:col-span-2">
            备注
            <textarea
              className={cn(fieldClass, "min-h-[80px] py-2")}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </label>
        </div>
        <div className="flex justify-end gap-2 border-t border-[#E5ECF4] pt-4">
          <Button type="button" variant="outline" onClick={onClose} disabled={submitting}>
            取消
          </Button>
          <Button type="submit" disabled={submitting} className="bg-[#2563EB] text-white hover:bg-[#1D4ED8]">
            {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            保存品牌
          </Button>
        </div>
      </form>
    </AdminDrawer>
  );
}

type AssignDrawerProps = {
  open: boolean;
  rowKey: string | null;
  rowName: string;
  user: AdminUser | null;
  products: AdminProduct[];
  onClose: () => void;
  onSaved: () => void;
};

export function AssignBrandsDrawer(props: AssignDrawerProps) {
  const { open, user, rowKey } = props;
  if (!open || !user || rowKey === UNASSIGNED_SALESPERSON_KEY) return null;
  return <AssignBrandsDrawerContent key={`${user.id}-${rowKey}`} {...props} user={user} />;
}

function AssignBrandsDrawerContent({
  open,
  rowKey,
  rowName,
  user,
  products,
  onClose,
  onSaved,
}: AssignDrawerProps & { user: AdminUser }) {
  const [selectedIds, setSelectedIds] = useState<number[]>((user.bound_products ?? []).map((product) => product.id));
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await setAdminUserProducts(user!.id, selectedIds);
      onSaved();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "分配品牌失败。");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AdminDrawer open={open} title={`分配品牌 · ${rowName}`} description="调整该业务员负责的品牌范围。" onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        {error ? <div className="rounded-md border border-[#FECDCA] bg-[#FEF3F2] px-4 py-3 text-sm text-[#B42318]">{error}</div> : null}
        <div className="grid max-h-[420px] gap-2 overflow-auto">
          {products.map((product) => (
            <label key={product.id} className="flex cursor-pointer items-center gap-2 rounded-md border border-[#DDE6F0] bg-[#FAFBFC] px-3 py-2 text-sm">
              <input
                type="checkbox"
                checked={selectedIds.includes(product.id)}
                onChange={() =>
                  setSelectedIds((current) =>
                    current.includes(product.id) ? current.filter((id) => id !== product.id) : [...current, product.id],
                  )
                }
                className="h-4 w-4 accent-[#2563EB]"
              />
              <span className="min-w-0 flex-1 truncate font-medium text-[#344054]">{product.name}</span>
              <span className="shrink-0 font-mono text-[11px] text-[#98A2B3]">#{product.id}</span>
            </label>
          ))}
        </div>
        <div className="flex justify-end gap-2 border-t border-[#E5ECF4] pt-4">
          <Button type="button" variant="outline" onClick={onClose} disabled={submitting}>
            取消
          </Button>
          <Button type="submit" disabled={submitting} className="bg-[#2563EB] text-white hover:bg-[#1D4ED8]">
            {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            保存分配
          </Button>
        </div>
      </form>
    </AdminDrawer>
  );
}

type ReassignDrawerProps = {
  open: boolean;
  brand: AdminProduct | null;
  users: AdminUser[];
  onClose: () => void;
  onSaved: () => void;
};

export function ReassignOwnerDrawer(props: ReassignDrawerProps) {
  const { open, brand } = props;
  if (!open || !brand) return null;
  return <ReassignOwnerDrawerContent key={brand.id} {...props} brand={brand} />;
}

function ReassignOwnerDrawerContent({
  open,
  brand,
  users,
  onClose,
  onSaved,
}: ReassignDrawerProps & { brand: AdminProduct }) {
  const [ownerUserId, setOwnerUserId] = useState(() => {
    const owner = brand.members.find((member) => member.role === "owner") ?? brand.members[0];
    return owner ? String(owner.user_id) : "";
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const salesUsers = useMemo(() => users.filter((user) => user.role === "sales"), [users]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await reassignBrandOwner({
        brandId: brand!.id,
        newOwnerUserId: ownerUserId ? Number(ownerUserId) : null,
        users,
      });
      onSaved();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "更换负责人失败。");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AdminDrawer open={open} title={`更换负责人 · ${brand.name}`} description="将品牌分配给指定业务员，或设为未分配。" onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        {error ? <div className="rounded-md border border-[#FECDCA] bg-[#FEF3F2] px-4 py-3 text-sm text-[#B42318]">{error}</div> : null}
        <AdminFilterField label="负责人">
          <AdminSelect value={ownerUserId} onChange={(event) => setOwnerUserId(event.target.value)}>
            <option value="">未分配</option>
            {salesUsers.map((user) => (
              <option key={user.id} value={user.id}>
                {user.display_name?.trim() || user.username} · {user.username}
              </option>
            ))}
          </AdminSelect>
        </AdminFilterField>
        <div className="flex justify-end gap-2 border-t border-[#E5ECF4] pt-4">
          <Button type="button" variant="outline" onClick={onClose} disabled={submitting}>
            取消
          </Button>
          <Button type="submit" disabled={submitting} className="bg-[#2563EB] text-white hover:bg-[#1D4ED8]">
            {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            确认更换
          </Button>
        </div>
      </form>
    </AdminDrawer>
  );
}

type TransferDrawerProps = {
  open: boolean;
  user: AdminUser | null;
  users: AdminUser[];
  onClose: () => void;
  onTransferred: () => void;
};

export function TransferBrandsDrawer({ open, user, users, onClose, onTransferred }: TransferDrawerProps) {
  const [targetUserId, setTargetUserId] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const options = users.filter((item) => item.role === "sales" && item.id !== user?.id);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!user || !targetUserId) {
      setError("请选择接收业务员。");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await transferBrandsBetweenUsers({ fromUserId: user.id, toUserId: Number(targetUserId), users });
      onTransferred();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "转移品牌失败。");
    } finally {
      setSubmitting(false);
    }
  }

  if (!open || !user) return null;

  return (
    <AdminDrawer open={open} title={`转移品牌 · ${user.username}`} description="将该业务员负责的品牌转移给其他人后再停用或删除。" onClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        {error ? <div className="rounded-md border border-[#FECDCA] bg-[#FEF3F2] px-4 py-3 text-sm text-[#B42318]">{error}</div> : null}
        <p className="text-sm text-[#667085]">
          当前负责 {user.bound_products?.length ?? user.product_count} 个品牌，请选择接收业务员。
        </p>
        {options.length === 0 ? (
          <div className="rounded-md border border-[#FEDF89] bg-[#FFFAEB] px-3 py-2 text-sm text-[#B54708]">
            暂无其他业务员可接收。请先创建业务员账号，再转移品牌后删除。
          </div>
        ) : null}
        <AdminFilterField label="接收业务员">
          <AdminSelect value={targetUserId} onChange={(event) => setTargetUserId(event.target.value)} disabled={options.length === 0}>
            <option value="">请选择</option>
            {options.map((item) => (
              <option key={item.id} value={item.id}>
                {item.display_name?.trim() || item.username}
              </option>
            ))}
          </AdminSelect>
        </AdminFilterField>
        <div className="flex justify-end gap-2 border-t border-[#E5ECF4] pt-4">
          <Button type="button" variant="outline" onClick={onClose} disabled={submitting}>
            取消
          </Button>
          <Button type="submit" disabled={submitting} className="bg-[#2563EB] text-white hover:bg-[#1D4ED8]">
            {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            确认转移
          </Button>
        </div>
      </form>
    </AdminDrawer>
  );
}

export function AdminDeleteConfirmDialog({
  open,
  title,
  description,
  loading,
  confirmDisabled,
  confirmLabel = "确认删除",
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  description: string;
  loading?: boolean;
  confirmDisabled?: boolean;
  confirmLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <AdminConfirmDialog
      open={open}
      title={title}
      description={description}
      confirmLabel={confirmLabel}
      danger
      loading={loading}
      confirmDisabled={confirmDisabled}
      onConfirm={onConfirm}
      onCancel={onCancel}
    />
  );
}

export function SalespersonDeleteDialog({
  open,
  userName,
  username,
  productCount,
  taskCount,
  influencerCount,
  emailCount,
  replyCount,
  error,
  loading,
  onCancel,
  onDelete,
}: {
  open: boolean;
  userName: string;
  username: string;
  productCount: number;
  taskCount: number;
  influencerCount: number;
  emailCount: number;
  replyCount: number;
  error?: string | null;
  loading?: boolean;
  onCancel: () => void;
  onDelete: () => void;
}) {
  if (!open) return null;

  const hasOtherHistory = influencerCount > 0 || emailCount > 0 || replyCount > 0;

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-[#102033]/50 p-4 backdrop-blur-[1px]">
      <div className="w-full max-w-md rounded-xl border border-[#D8E2EE] bg-white p-5 shadow-[0_24px_64px_rgba(16,32,51,0.18)]">
        <h3 className="text-base font-semibold text-[#102033]">删除业务员 · {userName}</h3>
        <p className="mt-2 text-sm leading-6 text-[#667085]">
          删除后账号无法恢复；品牌和任务将变为未分配，邮件、红人、回复和发送历史会保留。
        </p>
        <dl className="mt-4 grid grid-cols-2 gap-3 rounded-lg border border-[#E5ECF4] bg-[#F8FAFD] p-4 text-sm">
          <div>
            <dt className="text-[#667085]">登录账号</dt>
            <dd className="mt-1 font-medium text-[#102033]">{username}</dd>
          </div>
          <div>
            <dt className="text-[#667085]">关联品牌</dt>
            <dd className="mt-1 font-medium text-[#102033]">{productCount}</dd>
          </div>
          <div>
            <dt className="text-[#667085]">关联任务</dt>
            <dd className="mt-1 font-medium text-[#102033]">{taskCount}</dd>
          </div>
          <div>
            <dt className="text-[#667085]">其他历史数据</dt>
            <dd className="mt-1 font-medium text-[#102033]">{hasOtherHistory ? "存在，将保留" : "无"}</dd>
          </div>
        </dl>
        {hasOtherHistory ? (
          <p className="mt-3 text-xs text-[#667085]">
            红人 {influencerCount}、邮件 {emailCount}、回复 {replyCount}
          </p>
        ) : null}
        {error ? (
          <div className="mt-3 rounded-md border border-[#FECDCA] bg-[#FEF3F2] px-3 py-2 text-sm text-[#B42318]">
            {error}
          </div>
        ) : null}
        <div className="mt-5 flex justify-end gap-2">
          <Button type="button" variant="outline" disabled={loading} onClick={onCancel}>
            取消
          </Button>
          <Button
            type="button"
            disabled={loading}
            onClick={onDelete}
            className="bg-[#B42318] text-white hover:bg-[#912018] disabled:opacity-50"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            确认删除
          </Button>
        </div>
      </div>
    </div>
  );
}

export async function disableSalesperson(userId: number) {
  await updateAdminUser(userId, { is_active: false });
}

export async function deleteSalespersonSafely(userId: number) {
  return deleteAdminUser(userId);
}

export async function deleteBrandSafely(brand: AdminProduct) {
  await deleteAdminProduct(brand.id);
}

type AdminBrandManagementDrawerProps = {
  open: boolean;
  products: AdminProduct[];
  users: AdminUser[];
  selectedProductIds?: number[];
  defaultOwnerUserId?: number | null;
  onSelectedProductIdsChange?: (productIds: number[]) => void;
  onClose: () => void;
  onProductsChanged: () => void | Promise<void>;
};

export function AdminBrandManagementDrawer({
  open,
  products,
  users,
  selectedProductIds = [],
  defaultOwnerUserId = null,
  onSelectedProductIdsChange,
  onClose,
  onProductsChanged,
}: AdminBrandManagementDrawerProps) {
  const [query, setQuery] = useState("");
  const [editingBrand, setEditingBrand] = useState<AdminProduct | null>(null);
  const [creatingBrand, setCreatingBrand] = useState(false);
  const [deletingBrand, setDeletingBrand] = useState<AdminProduct | null>(null);
  const [deleteLoading, setDeleteLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectedSet = useMemo(() => new Set(selectedProductIds), [selectedProductIds]);
  const filteredProducts = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) return products;
    return products.filter(
      (product) =>
        product.name.toLowerCase().includes(normalized) ||
        product.slug.toLowerCase().includes(normalized) ||
        String(product.id).includes(normalized),
    );
  }, [products, query]);

  useEffect(() => {
    if (!onSelectedProductIdsChange) return;
    const availableIds = new Set(products.map((product) => product.id));
    const nextSelectedIds = selectedProductIds.filter((id) => availableIds.has(id));
    if (nextSelectedIds.length !== selectedProductIds.length) {
      onSelectedProductIdsChange(nextSelectedIds);
    }
  }, [onSelectedProductIdsChange, products, selectedProductIds]);

  if (!open) return null;

  async function refreshProducts() {
    clearCachedTenantProducts();
    await onProductsChanged();
  }

  function toggleSelected(productId: number) {
    if (!onSelectedProductIdsChange) return;
    onSelectedProductIdsChange(
      selectedSet.has(productId)
        ? selectedProductIds.filter((id) => id !== productId)
        : [...selectedProductIds, productId],
    );
  }

  async function handleBrandSaved() {
    setError(null);
    await refreshProducts();
  }

  async function confirmDelete() {
    if (!deletingBrand) return;
    setDeleteLoading(true);
    setError(null);
    try {
      const deletedId = deletingBrand.id;
      await deleteBrandSafely(deletingBrand);
      if (onSelectedProductIdsChange) {
        onSelectedProductIdsChange(selectedProductIds.filter((id) => id !== deletedId));
      }
      setDeletingBrand(null);
      await refreshProducts();
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除品牌失败。");
    } finally {
      setDeleteLoading(false);
    }
  }

  return (
    <>
      <AdminDrawer
        open={open}
        title="编辑品牌"
        description="新增、修改、删除品牌后，账号权限和业务员负责品牌列表会立即刷新。"
        onClose={onClose}
      >
        <div className="space-y-4">
          {error ? <div className="rounded-md border border-[#FECDCA] bg-[#FEF3F2] px-4 py-3 text-sm text-[#B42318]">{error}</div> : null}
          <div className="flex flex-wrap items-center gap-2">
            <label className="relative min-w-[220px] flex-1">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[#98A2B3]" />
              <AdminInput
                className="pl-9"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="搜索品牌名称 / slug / ID"
              />
            </label>
            <Button type="button" className="bg-[#2563EB] text-white hover:bg-[#1D4ED8]" onClick={() => setCreatingBrand(true)}>
              <Plus className="h-4 w-4" />
              新增品牌
            </Button>
          </div>

          <div className="grid max-h-[58vh] gap-2 overflow-auto">
            {filteredProducts.map((product) => (
              <div key={product.id} className="flex items-center gap-3 rounded-md border border-[#DDE6F0] bg-white px-3 py-2 text-sm">
                {onSelectedProductIdsChange ? (
                  <input
                    type="checkbox"
                    checked={selectedSet.has(product.id)}
                    onChange={() => toggleSelected(product.id)}
                    className="h-4 w-4 accent-[#2563EB]"
                    aria-label={`选择 ${product.name}`}
                  />
                ) : null}
                <div className="min-w-0 flex-1">
                  <div className="truncate font-medium text-[#102033]">{product.name}</div>
                  <div className="truncate font-mono text-[11px] text-[#98A2B3]">
                    #{product.id} / {product.slug}
                  </div>
                </div>
                <button
                  type="button"
                  className="rounded-md p-2 text-[#475467] hover:bg-[#F3F6FA] hover:text-[#2563EB]"
                  onClick={() => setEditingBrand(product)}
                  aria-label={`编辑 ${product.name}`}
                >
                  <Pencil className="h-4 w-4" />
                </button>
                <button
                  type="button"
                  className="rounded-md p-2 text-[#B42318] hover:bg-[#FEF3F2]"
                  onClick={() => setDeletingBrand(product)}
                  aria-label={`删除 ${product.name}`}
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
            ))}
            {!filteredProducts.length ? (
              <div className="rounded-md border border-dashed border-[#DDE6F0] bg-[#FAFBFC] px-4 py-6 text-center text-sm text-[#667085]">
                没有匹配的品牌。
              </div>
            ) : null}
          </div>
        </div>
      </AdminDrawer>

      <WorkbenchBrandDrawer
        open={creatingBrand}
        mode="create"
        brand={null}
        users={users}
        defaultOwnerUserId={defaultOwnerUserId}
        onClose={() => setCreatingBrand(false)}
        onSaved={() => void handleBrandSaved()}
      />
      <WorkbenchBrandDrawer
        open={Boolean(editingBrand)}
        mode="edit"
        brand={editingBrand}
        users={users}
        onClose={() => setEditingBrand(null)}
        onSaved={() => void handleBrandSaved()}
      />
      <AdminDeleteConfirmDialog
        open={Boolean(deletingBrand)}
        title="确认删除品牌？"
        description={deletingBrand ? buildBrandDeleteDescription(deletingBrand) : ""}
        loading={deleteLoading}
        onCancel={() => setDeletingBrand(null)}
        onConfirm={() => void confirmDelete()}
      />
    </>
  );
}

type WorkbenchBrandDrawerProps = {
  open: boolean;
  mode: "create" | "edit";
  brand: AdminProduct | null;
  users: AdminUser[];
  defaultOwnerUserId?: number | null;
  onClose: () => void;
  onSaved: () => void;
};

export function WorkbenchBrandDrawer(props: WorkbenchBrandDrawerProps) {
  const { open, mode, brand, defaultOwnerUserId } = props;
  if (!open) return null;
  const formKey = mode === "edit" && brand ? `edit-${brand.id}` : `create-${defaultOwnerUserId ?? "new"}`;
  return <WorkbenchBrandDrawerContent key={formKey} {...props} />;
}

function WorkbenchBrandDrawerContent({
  open,
  mode,
  brand,
  users,
  defaultOwnerUserId,
  onClose,
  onSaved,
}: WorkbenchBrandDrawerProps) {
  const [name, setName] = useState(mode === "edit" && brand ? brand.name : "");
  const [slug, setSlug] = useState(mode === "edit" && brand ? brand.slug : "");
  const [slugTouched, setSlugTouched] = useState(false);
  const [platform, setPlatform] = useState("");
  const [description, setDescription] = useState(mode === "edit" && brand ? (brand.description ?? "") : "");
  const [ownerUserId, setOwnerUserId] = useState(() => {
    if (mode === "edit" && brand) {
      const owner = brand.members.find((member) => member.role === "owner") ?? brand.members[0];
      return owner ? String(owner.user_id) : "";
    }
    return defaultOwnerUserId ? String(defaultOwnerUserId) : "";
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const salesUsers = useMemo(() => users.filter((user) => user.role === "sales"), [users]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const trimmedName = name.trim();
    if (!trimmedName) {
      setError("请填写品牌名称。");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const noteParts = [platform ? `所属平台: ${platform}` : null, description.trim()].filter(Boolean);
      const payloadDescription = noteParts.join("\n") || null;
      const nextSlug = (slug.trim() || slugifyProductName(trimmedName)).slice(0, 100);

      if (mode === "create") {
        const created = await createTenantProduct({
          name: trimmedName,
          slug: nextSlug,
          description: payloadDescription,
        });
        if (ownerUserId) {
          const owner = users.find((user) => user.id === Number(ownerUserId));
          const currentIds = (owner?.bound_products ?? []).map((product) => product.id);
          await setAdminUserProducts(Number(ownerUserId), [...currentIds, created.id]);
        }
      } else if (brand) {
        await updateTenantProduct(brand.id, {
          name: trimmedName,
          slug: nextSlug,
          description: payloadDescription,
        });
        await reassignBrandOwner({
          brandId: brand.id,
          newOwnerUserId: ownerUserId ? Number(ownerUserId) : null,
          users,
        });
      }
      onSaved();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存品牌失败。");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AdminDrawer
      open={open}
      title={mode === "create" ? "新增品牌" : `编辑品牌 · ${brand?.name ?? ""}`}
      description="设置品牌基础信息、负责人和平台备注。"
      onClose={onClose}
    >
      <form onSubmit={submit} className="space-y-4">
        {error ? <div className="rounded-md border border-[#FECDCA] bg-[#FEF3F2] px-4 py-3 text-sm text-[#B42318]">{error}</div> : null}
        <label className="grid gap-1.5 text-sm font-medium text-[#344054]">
          品牌名称 *
          <AdminInput
            value={name}
            onChange={(event) => {
              const nextName = event.target.value;
              setName(nextName);
              if (!slugTouched) setSlug(slugifyProductName(nextName));
            }}
          />
        </label>
        <label className="grid gap-1.5 text-sm font-medium text-[#344054]">
          slug
          <AdminInput
            value={slug}
            onChange={(event) => {
              setSlug(event.target.value);
              setSlugTouched(true);
            }}
          />
        </label>
        <AdminFilterField label="所属平台">
          <AdminSelect value={platform} onChange={(event) => setPlatform(event.target.value)}>
            <option value="">请选择</option>
            <option value="instagram">Instagram</option>
            <option value="youtube">YouTube</option>
            <option value="tiktok">TikTok</option>
            <option value="facebook">Facebook</option>
            <option value="amazon">Amazon</option>
          </AdminSelect>
        </AdminFilterField>
        <AdminFilterField label="负责人 / 业务员">
          <AdminSelect value={ownerUserId} onChange={(event) => setOwnerUserId(event.target.value)}>
            <option value="">未分配</option>
            {salesUsers.map((user) => (
              <option key={user.id} value={user.id}>
                {user.display_name?.trim() || user.username} / {user.username}
              </option>
            ))}
          </AdminSelect>
        </AdminFilterField>
        <label className="grid gap-1.5 text-sm font-medium text-[#344054]">
          备注
          <textarea
            className={cn(fieldClass, "min-h-[80px] py-2")}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
        </label>
        <div className="flex justify-end gap-2 border-t border-[#E5ECF4] pt-4">
          <Button type="button" variant="outline" onClick={onClose} disabled={submitting}>
            取消
          </Button>
          <Button type="submit" disabled={submitting} className="bg-[#2563EB] text-white hover:bg-[#1D4ED8]">
            {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            {mode === "create" ? "创建品牌" : "保存品牌"}
          </Button>
        </div>
      </form>
    </AdminDrawer>
  );
}

type WorkbenchSalespersonDrawerProps = {
  open: boolean;
  user: AdminUser | null;
  onClose: () => void;
  onSaved: () => void;
};

export function WorkbenchSalespersonDrawer(props: WorkbenchSalespersonDrawerProps) {
  const { open, user } = props;
  if (!open || !user) return null;
  return <WorkbenchSalespersonDrawerContent key={user.id} {...props} user={user} />;
}

function WorkbenchSalespersonDrawerContent({
  open,
  user,
  onClose,
  onSaved,
}: WorkbenchSalespersonDrawerProps & { user: AdminUser }) {
  const [username, setUsername] = useState(user.username);
  const [displayName, setDisplayName] = useState(user.display_name ?? "");
  const [email, setEmail] = useState(user.email ?? "");
  const [isActive, setIsActive] = useState(user.is_active);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const trimmedUsername = username.trim();
    if (!trimmedUsername) {
      setError("请填写登录账号。");
      return;
    }
    if (!/^[A-Za-z0-9_.-]+$/.test(trimmedUsername)) {
      setError("登录账号只能包含字母、数字、下划线、点和短横线。");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await updateAdminUser(user!.id, {
        username: trimmedUsername,
        display_name: displayName.trim() || null,
        email: email.trim() || null,
        is_active: isActive,
      });
      onSaved();
      onClose();
    } catch (err) {
      const message = err instanceof Error ? err.message : "保存业务员失败。";
      setError(/exist|duplicate|409|已存在|重复/i.test(message) ? "登录账号已存在，请更换后再保存。" : message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AdminDrawer
      open={open}
      title={`编辑业务员 · ${user.username}`}
      description="修改登录账号、显示名称、联系方式和账号状态。"
      onClose={onClose}
    >
      <form onSubmit={submit} className="space-y-4">
        {error ? <div className="rounded-md border border-[#FECDCA] bg-[#FEF3F2] px-4 py-3 text-sm text-[#B42318]">{error}</div> : null}
        <label className="grid gap-1.5 text-sm font-medium text-[#344054]">
          登录账号
          <AdminInput value={username} onChange={(event) => setUsername(event.target.value)} />
        </label>
        <label className="grid gap-1.5 text-sm font-medium text-[#344054]">
          业务员姓名 / 昵称
          <AdminInput value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="例如 张三" />
        </label>
        <label className="grid gap-1.5 text-sm font-medium text-[#344054]">
          邮箱 / 手机 / 联系方式
          <AdminInput value={email ?? ""} onChange={(event) => setEmail(event.target.value)} maxLength={255} />
        </label>
        <AdminFilterField label="状态">
          <AdminSelect value={isActive ? "active" : "disabled"} onChange={(event) => setIsActive(event.target.value === "active")}>
            <option value="active">启用</option>
            <option value="disabled">停用</option>
          </AdminSelect>
        </AdminFilterField>
        <div className="flex justify-end gap-2 border-t border-[#E5ECF4] pt-4">
          <Button type="button" variant="outline" onClick={onClose} disabled={submitting}>
            取消
          </Button>
          <Button type="submit" disabled={submitting} className="bg-[#2563EB] text-white hover:bg-[#1D4ED8]">
            {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            保存
          </Button>
        </div>
      </form>
    </AdminDrawer>
  );
}
