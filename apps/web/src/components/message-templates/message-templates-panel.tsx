// 文件说明：前端话术模板组件；当前文件：message templates panel
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
import { canDeleteMessageTemplate, canEditMessageTemplate } from "@/lib/message-template-helpers";

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

  const scenarioCounts = MESSAGE_TEMPLATE_SCENARIO_OPTIONS.map((option) => ({
    ...option,
    count: items.filter((item) => item.scenario === option.value).length,
  }));
  const defaultCount = items.filter((item) => item.is_system_default).length;
  const totalUses = items.reduce((sum, item) => sum + item.usage_count, 0);
  const lastUpdated = items
    .map((item) => item.updated_at)
    .filter(Boolean)
    .sort()
    .at(-1) ?? null;
  const hasActiveFilters = Boolean(search || scenarioFilter || platformFilter || languageFilter || tagFilter);

  function clearFilters() {
    setSearch("");
    setScenarioFilter("");
    setPlatformFilter("");
    setLanguageFilter("");
    setTagFilter("");
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

      <div className="ops-page">
        <div className="ops-toolbar shrink-0">
          <div className="relative min-w-[280px] flex-1">
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
            className="h-9 rounded-md border border-slate-200 bg-white px-3 text-sm outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
          >
            <option value="">全部场景</option>
            {MESSAGE_TEMPLATE_SCENARIO_OPTIONS.map((item) => (
              <option key={item.value} value={item.value}>{item.label}</option>
            ))}
          </select>
          <select
            value={platformFilter}
            onChange={(e) => setPlatformFilter(e.target.value)}
            disabled={requiresProduct}
            className="h-9 rounded-md border border-slate-200 bg-white px-3 text-sm outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
          >
            <option value="">全部平台</option>
            {MESSAGE_TEMPLATE_PLATFORM_OPTIONS.filter((item) => item.value).map((item) => (
              <option key={item.value} value={item.value}>{item.label}</option>
            ))}
          </select>
          <select
            value={languageFilter}
            onChange={(e) => setLanguageFilter(e.target.value)}
            disabled={requiresProduct}
            className="h-9 rounded-md border border-slate-200 bg-white px-3 text-sm outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
          >
            <option value="">全部语言</option>
            {MESSAGE_TEMPLATE_LANGUAGE_OPTIONS.map((item) => (
              <option key={item.value} value={item.value}>{item.label}</option>
            ))}
          </select>
          <Input
            value={tagFilter}
            onChange={(e) => setTagFilter(e.target.value)}
            placeholder="标签"
            className="w-[160px]"
            disabled={requiresProduct}
          />
          {hasActiveFilters ? (
            <Button variant="ghost" size="sm" onClick={clearFilters}>清除</Button>
          ) : null}
          <Button variant="outline" onClick={() => void loadData()} disabled={loading || requiresProduct}>
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            刷新
          </Button>
          <Button onClick={openCreateDialog} disabled={requiresProduct}>
            <Plus className="h-4 w-4" />
            新增话术
          </Button>
        </div>

        <div className="asset-summary shrink-0">
          <div className="asset-summary-item">
            <div className="asset-summary-label">话术总数</div>
            <div className="asset-summary-value">{total}</div>
          </div>
          <div className="asset-summary-item">
            <div className="asset-summary-label">系统默认</div>
            <div className="asset-summary-value">{defaultCount}</div>
          </div>
          <div className="asset-summary-item">
            <div className="asset-summary-label">累计使用</div>
            <div className="asset-summary-value">{totalUses}</div>
          </div>
          <div className="asset-summary-item">
            <div className="asset-summary-label">最近更新</div>
            <div className="mt-2 truncate text-sm font-medium text-slate-700">{formatDate(lastUpdated)}</div>
          </div>
        </div>

        {error ? <ErrorAlert message={error} /> : null}

        <Card className="flex min-h-0 flex-1 flex-col overflow-hidden">
          <CardHeader className="shrink-0 border-b px-4 py-3">
            <CardTitle>话术列表</CardTitle>
            <CardDescription>按场景、平台、语言和标签管理可复用外联素材。</CardDescription>
          </CardHeader>
          <CardContent className="flex min-h-0 flex-1 flex-col p-0">
            {loading ? (
              <LoadingState label="加载话术..." />
            ) : requiresProduct ? (
              <div className="asset-empty">
                <EmptyState
                  title="请选择具体产品"
                  description="在左侧切换到某个产品/品牌后，即可查看和管理该产品下的话术。"
                />
              </div>
            ) : items.length === 0 ? (
              <div className="asset-empty">
                <EmptyState
                  title="暂无话术"
                  description="新增外联开场白、邮件模板或 FAQ 话术后，团队可在触达流程中快速复用。"
                  action={<Button onClick={openCreateDialog}><Plus className="h-4 w-4" />新增话术</Button>}
                  secondaryAction={<Button variant="outline">查看模板示例</Button>}
                />
              </div>
            ) : (
              <div className="asset-two-pane">
                <aside className="border-r bg-slate-50/70 p-3">
                  <button
                    type="button"
                    onClick={() => setScenarioFilter("")}
                    className={`mb-1 flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-sm ${scenarioFilter === "" ? "bg-white font-medium text-blue-700 shadow-sm ring-1 ring-slate-200" : "text-slate-600 hover:bg-white"}`}
                  >
                    <span>全部场景</span>
                    <span className="text-xs tabular-nums text-slate-400">{items.length}</span>
                  </button>
                  {scenarioCounts.map((scenario) => (
                    <button
                      key={scenario.value}
                      type="button"
                      onClick={() => setScenarioFilter(scenario.value)}
                      className={`mb-1 flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-sm ${scenarioFilter === scenario.value ? "bg-white font-medium text-blue-700 shadow-sm ring-1 ring-slate-200" : "text-slate-600 hover:bg-white"}`}
                    >
                      <span className="truncate">{scenario.label}</span>
                      <span className="text-xs tabular-nums text-slate-400">{scenario.count}</span>
                    </button>
                  ))}
                </aside>
                <div className="ops-table-wrap">
                  <table className="ops-table min-w-[980px]">
                    <thead>
                      <tr>
                        <th>标题</th>
                        <th>场景</th>
                        <th>平台/语言</th>
                        <th>使用</th>
                        <th>更新时间</th>
                        <th className="text-right">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {items.map((template) => {
                        const busy = actionId === template.id;
                        const platformLabel = template.platform ? PLATFORM_LABELS[template.platform] ?? template.platform : "不限";
                        return (
                          <tr key={template.id}>
                            <td>
                              <div className="min-w-0">
                                <div className="flex min-w-0 items-center gap-2">
                                  <p className="truncate font-medium">{template.title}</p>
                                  {template.is_system_default ? <Badge variant="outline" className="shrink-0 text-xs">系统默认</Badge> : null}
                                </div>
                                <p className="mt-1 line-clamp-1 text-xs text-muted-foreground">{previewContent(template.content, 96)}</p>
                                {template.tags.length > 0 ? (
                                  <div className="mt-1 flex flex-wrap gap-1">
                                    {template.tags.slice(0, 3).map((tag) => (
                                      <Badge key={tag} variant="outline" className="text-xs">{tag}</Badge>
                                    ))}
                                  </div>
                                ) : null}
                              </div>
                            </td>
                            <td><Badge variant="secondary">{messageTemplateScenarioLabel(template.scenario)}</Badge></td>
                            <td>
                              <p className="text-sm">{platformLabel}</p>
                              <p className="text-xs text-muted-foreground">{messageTemplateLanguageLabel(template.language)}</p>
                            </td>
                            <td className="tabular-nums">
                              <p>{template.usage_count} 次</p>
                              <p className="text-xs text-muted-foreground">{formatDate(template.last_used_at)}</p>
                            </td>
                            <td className="text-muted-foreground">{formatDate(template.updated_at)}</td>
                            <td>
                              <div className="flex justify-end gap-1">
                                <Button variant="ghost" size="icon" className="ops-icon-button" onClick={() => void handleCopy(template)} disabled={busy} title="复制">
                                  <Copy className="h-4 w-4" />
                                </Button>
                                <Button variant="ghost" size="icon" className="ops-icon-button" onClick={() => void handleUse(template)} disabled={busy} title="复制并记录使用">
                                  {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Zap className="h-4 w-4" />}
                                </Button>
                                <Button variant="ghost" size="icon" className="ops-icon-button" onClick={() => void handleDuplicate(template)} disabled={busy} title="复制为新话术">
                                  <CopyPlus className="h-4 w-4" />
                                </Button>
                                {canEditMessageTemplate(template) ? (
                                  <Button variant="ghost" size="icon" className="ops-icon-button" onClick={() => openEditDialog(template)} title="编辑">
                                    <Pencil className="h-4 w-4" />
                                  </Button>
                                ) : null}
                                {canDeleteMessageTemplate(template) ? (
                                  <Button variant="ghost" size="icon" className="ops-icon-button text-red-600 hover:bg-red-50 hover:text-red-700" onClick={() => void handleDelete(template)} disabled={busy} title="删除">
                                    <Trash2 className="h-4 w-4" />
                                  </Button>
                                ) : null}
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

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
