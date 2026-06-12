"use client";

import { useState } from "react";
import { Loader2, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { MessageTemplate, MessageTemplatePayload } from "@/lib/api";
import {
  MESSAGE_TEMPLATE_LANGUAGE_OPTIONS,
  MESSAGE_TEMPLATE_PLATFORM_OPTIONS,
  MESSAGE_TEMPLATE_SCENARIO_OPTIONS,
} from "@/lib/labels";

type FormState = {
  title: string;
  scenario: string;
  platform: string;
  language: string;
  tags: string;
  content: string;
  note: string;
};

const PLACEHOLDER_HINT =
  "支持变量占位符：{name} 达人名、{username} 账号名、{brand} 品牌名、{product} 产品名、{platform} 平台、{price} 报价、{contact} 联系方式";

function emptyForm(): FormState {
  return {
    title: "",
    scenario: "first_contact",
    platform: "",
    language: "",
    tags: "",
    content: "",
    note: "",
  };
}

function templateToForm(template: MessageTemplate): FormState {
  return {
    title: template.title,
    scenario: template.scenario,
    platform: template.platform ?? "",
    language: template.language ?? "",
    tags: template.tags.join(", "),
    content: template.content,
    note: template.note ?? "",
  };
}

function formToPayload(form: FormState): MessageTemplatePayload {
  const tags = form.tags
    .split(/[,，]/)
    .map((tag) => tag.trim())
    .filter(Boolean);
  return {
    title: form.title.trim(),
    scenario: form.scenario,
    platform: form.platform || null,
    language: form.language || null,
    tags,
    content: form.content.trim(),
    note: form.note.trim() || null,
  };
}

function validateForm(form: FormState): string | null {
  if (!form.title.trim()) return "请填写标题";
  if (!form.scenario) return "请选择场景";
  if (!form.content.trim()) return "请填写话术正文";
  return null;
}

type MessageTemplateFormDialogProps = {
  open: boolean;
  mode: "create" | "edit";
  initialTemplate?: MessageTemplate | null;
  submitting?: boolean;
  onClose: () => void;
  onSubmit: (payload: MessageTemplatePayload) => Promise<void>;
};

function MessageTemplateFormBody({
  mode,
  initialTemplate,
  submitting,
  onClose,
  onSubmit,
}: Omit<MessageTemplateFormDialogProps, "open">) {
  const [form, setForm] = useState<FormState>(() =>
    mode === "edit" && initialTemplate ? templateToForm(initialTemplate) : emptyForm(),
  );
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const validationError = validateForm(form);
    if (validationError) {
      setError(validationError);
      return;
    }
    try {
      await onSubmit(formToPayload(form));
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败");
    }
  }

  return (
    <>
      <div className="flex items-center justify-between border-b px-6 py-4">
        <div>
          <h2 className="text-lg font-semibold">{mode === "create" ? "新增话术" : "编辑话术"}</h2>
          <p className="text-sm text-muted-foreground">保存后可搜索、复制并复用</p>
        </div>
        <Button variant="ghost" size="icon" onClick={onClose} disabled={submitting}>
          <X className="h-4 w-4" />
        </Button>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4 px-6 py-4">
        {error ? (
          <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
            {error}
          </div>
        ) : null}

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-2 sm:col-span-2">
            <Label htmlFor="mt-title">标题 *</Label>
            <Input
              id="mt-title"
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
              placeholder="例如：首次联系 - 健身类达人"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="mt-scenario">场景 *</Label>
            <select
              id="mt-scenario"
              value={form.scenario}
              onChange={(e) => setForm({ ...form, scenario: e.target.value })}
              className="flex h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
            >
              {MESSAGE_TEMPLATE_SCENARIO_OPTIONS.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="mt-platform">平台</Label>
            <select
              id="mt-platform"
              value={form.platform}
              onChange={(e) => setForm({ ...form, platform: e.target.value })}
              className="flex h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
            >
              {MESSAGE_TEMPLATE_PLATFORM_OPTIONS.map((item) => (
                <option key={item.value || "any"} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="mt-language">语言</Label>
            <select
              id="mt-language"
              value={form.language}
              onChange={(e) => setForm({ ...form, language: e.target.value })}
              className="flex h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
            >
              <option value="">不限</option>
              {MESSAGE_TEMPLATE_LANGUAGE_OPTIONS.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </div>

          <div className="space-y-2">
            <Label htmlFor="mt-tags">标签</Label>
            <Input
              id="mt-tags"
              value={form.tags}
              onChange={(e) => setForm({ ...form, tags: e.target.value })}
              placeholder="多个标签用逗号分隔"
            />
          </div>

          <div className="space-y-2 sm:col-span-2">
            <Label htmlFor="mt-content">话术正文 *</Label>
            <Textarea
              id="mt-content"
              value={form.content}
              onChange={(e) => setForm({ ...form, content: e.target.value })}
              rows={8}
              placeholder="Hi {name}, we love your content on {platform}..."
            />
            <p className="text-xs text-muted-foreground">{PLACEHOLDER_HINT}</p>
          </div>

          <div className="space-y-2 sm:col-span-2">
            <Label htmlFor="mt-note">备注</Label>
            <Textarea
              id="mt-note"
              value={form.note}
              onChange={(e) => setForm({ ...form, note: e.target.value })}
              rows={2}
              placeholder="可选，内部说明"
            />
          </div>
        </div>

        <div className="flex justify-end gap-2 border-t pt-4">
          <Button type="button" variant="outline" onClick={onClose} disabled={submitting}>
            取消
          </Button>
          <Button type="submit" disabled={submitting}>
            {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            保存
          </Button>
        </div>
      </form>
    </>
  );
}

export function MessageTemplateFormDialog({
  open,
  mode,
  initialTemplate,
  submitting = false,
  onClose,
  onSubmit,
}: MessageTemplateFormDialogProps) {
  if (!open) return null;

  const formKey = mode === "edit" && initialTemplate ? `edit-${initialTemplate.id}` : "create";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-xl border bg-background shadow-lg">
        <MessageTemplateFormBody
          key={formKey}
          mode={mode}
          initialTemplate={initialTemplate}
          submitting={submitting}
          onClose={onClose}
          onSubmit={onSubmit}
        />
      </div>
    </div>
  );
}
