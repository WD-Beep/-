"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Copy,
  CopyPlus,
  Loader2,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  Zap,
} from "lucide-react";

import { MessageTemplateFormDialog } from "@/components/message-templates/message-template-form-dialog";
import { AdminShell } from "@/components/layout/admin-shell";
import { useActiveProductId } from "@/components/providers/product-provider";
import { EmptyState, ErrorAlert, LoadingState } from "@/components/shared/page-states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  createMessageTemplate,
  deleteMessageTemplate,
  duplicateMessageTemplate,
  fetchMessageTemplates,
  updateMessageTemplate,
  recordMessageTemplateUse,
  type MessageTemplate,
  type MessageTemplatePayload,
} from "@/lib/api";
import { ALL_PRODUCTS_ID } from "@/lib/product-context";
import {
  MESSAGE_TEMPLATE_LANGUAGE_OPTIONS,
  MESSAGE_TEMPLATE_PLATFORM_OPTIONS,
  MESSAGE_TEMPLATE_SCENARIO_OPTIONS,
  PLATFORM_LABELS,
  messageTemplateLanguageLabel,
  messageTemplateScenarioLabel,
  translateErrorMessage,
} from "@/lib/labels";

function formatDate(value: string | null): string {
  if (!value) return "-";
  return new Date(value).toLocaleString("zh-CN");
}

function previewContent(content: string, maxLength = 120): string {
  const normalized = content.replace(/\s+/g, " ").trim();
  if (normalized.length <= maxLength) return normalized;
  return `${normalized.slice(0, maxLength)}…`;
}

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

export function MessageTemplatesPanel() {
  const productId = useActiveProductId();
  const requiresProduct = productId === ALL_PRODUCTS_ID;

  const [items, setItems] = useState<MessageTemplate[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<{ message: string; tone: "success" | "error" } | null>(null);

  const [search, setSearch] = useState("");
  const [scenarioFilter, setScenarioFilter] = useState("");
  const [platformFilter, setPlatformFilter] = useState("");
  const [languageFilter, setLanguageFilter] = useState("");
  const [tagFilter, setTagFilter] = useState("");

  const [formOpen, setFormOpen] = useState(false);
  const [formMode, setFormMode] = useState<"create" | "edit">("create");
  const [editingTemplate, setEditingTemplate] = useState<MessageTemplate | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [actionId, setActionId] = useState<number | null>(null);

  const showToast = useCallback((message: string, tone: "success" | "error" = "success") => {
    setToast({ message, tone });
    window.setTimeout(() => setToast(null), 3000);
  }, []);

  const loadData = useCallback(async () => {
    if (requiresProduct) {
      setLoading(false);
      setItems([]);
      setTotal(0);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const data = await fetchMessageTemplates({
        page: 1,
        pageSize: 100,
        search,
        scenario: scenarioFilter || undefined,
        platform: platformFilter || undefined,
        language: languageFilter || undefined,
        tag: tagFilter || undefined,
      });
      setItems(data.items);
      setTotal(data.total);
    } catch (err) {
      setError(translateErrorMessage(err instanceof Error ? err.message : "加载话术失败"));
    } finally {
      setLoading(false);
    }
  }, [requiresProduct, search, scenarioFilter, platformFilter, languageFilter, tagFilter]);

  useEffect(() => {
    if (productId === null) {
      queueMicrotask(() => setLoading(false));
      return;
    }
    queueMicrotask(() => {
      void loadData();
    });
  }, [loadData, productId]);

  function openCreateDialog() {
    setFormMode("create");
    setEditingTemplate(null);
    setFormOpen(true);
  }

  function openEditDialog(template: MessageTemplate) {
    setFormMode("edit");
    setEditingTemplate(template);
    setFormOpen(true);
  }

  async function handleFormSubmit(payload: MessageTemplatePayload) {
    setSubmitting(true);
    try {
      if (formMode === "create") {
        await createMessageTemplate(payload);
        showToast("话术已保存");
      } else if (editingTemplate) {
        await updateMessageTemplate(editingTemplate.id, payload);
        showToast("话术已更新");
      }
      await loadData();
    } finally {
      setSubmitting(false);
    }
  }

  async function handleCopy(template: MessageTemplate) {
    const ok = await copyText(template.content);
    showToast(ok ? "已复制话术" : "复制失败，请检查浏览器权限", ok ? "success" : "error");
  }

  async function handleUse(template: MessageTemplate) {
    setActionId(template.id);
    try {
      const ok = await copyText(template.content);
      if (!ok) {
        showToast("复制失败，请检查浏览器权限", "error");
        return;
      }
      const updated = await recordMessageTemplateUse(template.id);
      setItems((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
      showToast("已复制话术");
    } catch (err) {
      showToast(translateErrorMessage(err instanceof Error ? err.message : "记录使用失败"), "error");
    } finally {
      setActionId(null);
    }
  }

  async function handleDuplicate(template: MessageTemplate) {
    setActionId(template.id);
    try {
      await duplicateMessageTemplate(template.id);
      showToast("已复制为新话术");
      await loadData();
    } catch (err) {
      showToast(translateErrorMessage(err instanceof Error ? err.message : "复制失败"), "error");
    } finally {
      setActionId(null);
    }
  }

  async function handleDelete(template: MessageTemplate) {
    if (!window.confirm(`确定删除「${template.title}」吗？`)) return;
    setActionId(template.id);
    try {
      await deleteMessageTemplate(template.id);
      showToast("话术已删除");
      await loadData();
    } catch (err) {
      showToast(translateErrorMessage(err instanceof Error ? err.message : "删除失败"), "error");
    } finally {
      setActionId(null);
    }
  }

  return (
    <AdminShell title="话术库" description="保存和复用达人沟通话术">
      {requiresProduct ? (
        <ErrorAlert
          message="请先在左侧选择具体产品/品牌。话术库按产品隔离，不支持「全部产品（汇总）」视图。"
          className="mb-4"
        />
      ) : null}

      {toast ? (
        <div
          className={`fixed bottom-6 right-6 z-50 rounded-lg border px-4 py-3 text-sm shadow-lg ${
            toast.tone === "error"
              ? "border-destructive/30 bg-destructive/10 text-destructive"
              : "border-emerald-200 bg-emerald-50 text-emerald-800"
          }`}
        >
          {toast.message}
        </div>
      ) : null}

      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Button onClick={openCreateDialog} disabled={requiresProduct}>
          <Plus className="h-4 w-4" />
          新增话术
        </Button>
        <Button variant="outline" onClick={() => void loadData()} disabled={loading || requiresProduct}>
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          刷新列表
        </Button>
      </div>

      <Card className="mb-4">
        <CardHeader className="pb-3">
          <CardTitle className="text-base">筛选</CardTitle>
          <CardDescription>按关键词、场景、平台、语言或标签查找历史话术</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
            <div className="relative xl:col-span-2">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="搜索标题或正文"
                className="pl-9"
                disabled={requiresProduct}
              />
            </div>
            <select
              value={scenarioFilter}
              onChange={(e) => setScenarioFilter(e.target.value)}
              disabled={requiresProduct}
              className="flex h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
            >
              <option value="">全部场景</option>
              {MESSAGE_TEMPLATE_SCENARIO_OPTIONS.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
            <select
              value={platformFilter}
              onChange={(e) => setPlatformFilter(e.target.value)}
              disabled={requiresProduct}
              className="flex h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
            >
              <option value="">全部平台</option>
              {MESSAGE_TEMPLATE_PLATFORM_OPTIONS.filter((item) => item.value).map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
            <select
              value={languageFilter}
              onChange={(e) => setLanguageFilter(e.target.value)}
              disabled={requiresProduct}
              className="flex h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
            >
              <option value="">全部语言</option>
              {MESSAGE_TEMPLATE_LANGUAGE_OPTIONS.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Input
              value={tagFilter}
              onChange={(e) => setTagFilter(e.target.value)}
              placeholder="按标签筛选"
              className="max-w-xs"
              disabled={requiresProduct}
            />
            <Button
              variant="secondary"
              size="sm"
              onClick={() => void loadData()}
              disabled={loading || requiresProduct}
            >
              应用筛选
            </Button>
          </div>
        </CardContent>
      </Card>

      {error ? <ErrorAlert message={error} className="mb-4" /> : null}

      <Card>
        <CardHeader>
          <CardTitle>话术列表</CardTitle>
          <CardDescription>共 {total} 条话术</CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <LoadingState label="加载话术..." />
          ) : requiresProduct ? (
            <EmptyState
              title="请选择具体产品"
              description="在左侧切换到某个产品/品牌后，即可查看和管理该产品下的话术。"
            />
          ) : items.length === 0 ? (
            <EmptyState
              title="暂无话术"
              description="首次打开将自动加载系统默认英文外联模板；也可点击「新增话术」保存自定义模板。"
            />
          ) : (
            <div className="space-y-4">
              {items.map((template) => {
                const busy = actionId === template.id;
                const platformLabel = template.platform
                  ? PLATFORM_LABELS[template.platform] ?? template.platform
                  : "不限";
                return (
                  <div
                    key={template.id}
                    className="rounded-lg border p-4 transition-colors hover:bg-muted/30"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0 flex-1 space-y-2">
                        <div className="flex flex-wrap items-center gap-2">
                          <h3 className="font-medium">{template.title}</h3>
                          {template.is_system_default ? (
                            <Badge variant="outline" className="text-xs">
                              系统默认
                            </Badge>
                          ) : null}
                          <Badge variant="secondary">
                            {messageTemplateScenarioLabel(template.scenario)}
                          </Badge>
                          <Badge variant="outline">{platformLabel}</Badge>
                          <Badge variant="outline">
                            {messageTemplateLanguageLabel(template.language)}
                          </Badge>
                        </div>
                        {template.tags.length > 0 ? (
                          <div className="flex flex-wrap gap-1">
                            {template.tags.map((tag) => (
                              <Badge key={tag} variant="outline" className="text-xs">
                                {tag}
                              </Badge>
                            ))}
                          </div>
                        ) : null}
                        <p className="text-sm text-muted-foreground">{previewContent(template.content)}</p>
                        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                          <span>更新：{formatDate(template.updated_at)}</span>
                          <span>创建：{formatDate(template.created_at)}</span>
                          <span>最近使用：{formatDate(template.last_used_at)}</span>
                          <span>使用 {template.usage_count} 次</span>
                        </div>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => void handleCopy(template)}
                          disabled={busy}
                        >
                          <Copy className="h-3.5 w-3.5" />
                          复制
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => void handleUse(template)}
                          disabled={busy}
                        >
                          {busy ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          ) : (
                            <Zap className="h-3.5 w-3.5" />
                          )}
                          使用
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => void handleDuplicate(template)}
                          disabled={busy}
                        >
                          <CopyPlus className="h-3.5 w-3.5" />
                          复制为新话术
                        </Button>
                        <Button variant="outline" size="sm" onClick={() => openEditDialog(template)}>
                          <Pencil className="h-3.5 w-3.5" />
                          编辑
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => void handleDelete(template)}
                          disabled={busy}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                          删除
                        </Button>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>

      <MessageTemplateFormDialog
        open={formOpen}
        mode={formMode}
        initialTemplate={editingTemplate}
        submitting={submitting}
        onClose={() => setFormOpen(false)}
        onSubmit={handleFormSubmit}
      />
    </AdminShell>
  );
}
