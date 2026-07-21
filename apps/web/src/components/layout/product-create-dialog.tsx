// 文件说明：前端页面组件；当前文件：product create dialog
"use client";

import { useState } from "react";
import { Loader2, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { createTenantProduct, type TenantProduct, type TenantProductPayload } from "@/lib/api";
import { slugifyProductName } from "@/lib/product-slug";

type ProductCreateDialogProps = {
  open: boolean;
  submitting?: boolean;
  onClose: () => void;
  onCreated: (product: TenantProduct) => void;
};

type FormState = {
  name: string;
  slug: string;
  slugTouched: boolean;
  isDefault: boolean;
  note: string;
};

function emptyForm(): FormState {
  return {
    name: "",
    slug: "",
    slugTouched: false,
    isDefault: false,
    note: "",
  };
}

export function ProductCreateDialog({
  open,
  submitting = false,
  onClose,
  onCreated,
}: ProductCreateDialogProps) {
  const [form, setForm] = useState<FormState>(emptyForm);
  const [error, setError] = useState<string | null>(null);
  const [localSubmitting, setLocalSubmitting] = useState(false);

  if (!open) return null;

  const busy = submitting || localSubmitting;

  function handleNameChange(name: string) {
    setForm((prev) => ({
      ...prev,
      name,
      slug: prev.slugTouched ? prev.slug : slugifyProductName(name),
    }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const name = form.name.trim();
    if (!name) {
      setError("请填写产品/品牌名称");
      return;
    }
    const slug = (form.slug.trim() || slugifyProductName(name)).slice(0, 100);
    if (!slug) {
      setError("请填写 slug");
      return;
    }

    const payload: TenantProductPayload = {
      name,
      slug,
      description: form.note.trim() || null,
      is_default: form.isDefault,
    };

    setLocalSubmitting(true);
    try {
      const created = await createTenantProduct(payload);
      onCreated(created);
      setForm(emptyForm());
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建失败");
    } finally {
      setLocalSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-md rounded-xl border bg-background shadow-lg">
        <div className="flex items-center justify-between border-b px-5 py-4">
          <div>
            <h2 className="text-lg font-semibold">新增产品/品牌</h2>
            <p className="text-sm text-muted-foreground">创建后可立即切换并录入数据</p>
          </div>
          <Button variant="ghost" size="icon" onClick={onClose} disabled={busy}>
            <X className="h-4 w-4" />
          </Button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4 px-5 py-4">
          {error ? (
            <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
              {error}
            </div>
          ) : null}

          <div className="space-y-2">
            <Label htmlFor="product-name">产品/品牌名称 *</Label>
            <Input
              id="product-name"
              value={form.name}
              onChange={(e) => handleNameChange(e.target.value)}
              placeholder="例如：Summer Travel Bag"
              autoFocus
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="product-slug">slug</Label>
            <Input
              id="product-slug"
              value={form.slug}
              onChange={(e) =>
                setForm((prev) => ({
                  ...prev,
                  slug: e.target.value,
                  slugTouched: true,
                }))
              }
              placeholder="自动生成，可编辑"
            />
          </div>

          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={form.isDefault}
              onChange={(e) => setForm((prev) => ({ ...prev, isDefault: e.target.checked }))}
              className="h-4 w-4 rounded border-input"
            />
            设为默认产品
          </label>

          <div className="space-y-2">
            <Label htmlFor="product-note">备注</Label>
            <Textarea
              id="product-note"
              value={form.note}
              onChange={(e) => setForm((prev) => ({ ...prev, note: e.target.value }))}
              rows={2}
              placeholder="可选，内部说明"
            />
          </div>

          <div className="flex justify-end gap-2 border-t pt-4">
            <Button type="button" variant="outline" onClick={onClose} disabled={busy}>
              取消
            </Button>
            <Button type="submit" disabled={busy}>
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              创建
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
