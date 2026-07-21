// 文件说明：前端页面组件；当前文件：knowledge bases panel
"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  BookOpen,
  Eye,
  FileText,
  Loader2,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  Upload,
} from "lucide-react";

import { AdminShell } from "@/components/layout/admin-shell";
import { useActiveProductId } from "@/components/providers/product-provider";
import { EmptyState, ErrorAlert, LoadingState } from "@/components/shared/page-states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  createKnowledgeBase,
  deleteKnowledgeDocument,
  fetchKnowledgeBases,
  fetchKnowledgeDocumentChunks,
  fetchKnowledgeDocuments,
  fetchKnowledgeImportPresets,
  importKnowledgeDocument,
  reprocessKnowledgeDocument,
  searchKnowledge,
  uploadKnowledgeDocument,
  type KnowledgeBase,
  type KnowledgeChunk,
  type KnowledgeDocument,
  type KnowledgeImportPreset,
  type KnowledgeSearchResult,
} from "@/lib/api";
import { ALL_PRODUCTS_ID } from "@/lib/product-context";
import { translateErrorMessage } from "@/lib/labels";

const STATUS_LABELS: Record<string, string> = {
  pending: "待处理",
  processing: "解析中",
  ready: "就绪",
  failed: "失败",
};

const STATUS_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  pending: "secondary",
  processing: "outline",
  ready: "default",
  failed: "destructive",
};

function formatDate(value: string | null): string {
  if (!value) return "-";
  return new Date(value).toLocaleString("zh-CN");
}

export function KnowledgeBasesPanel() {
  const productId = useActiveProductId();
  const requiresProduct = productId === ALL_PRODUCTS_ID;
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [bases, setBases] = useState<KnowledgeBase[]>([]);
  const [selectedBaseId, setSelectedBaseId] = useState<number | null>(null);
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<{ message: string; tone: "success" | "error" } | null>(null);
  const [actionId, setActionId] = useState<number | null>(null);
  const [uploading, setUploading] = useState(false);
  const [importingPresetId, setImportingPresetId] = useState<string | null>(null);
  const [importPresets, setImportPresets] = useState<KnowledgeImportPreset[]>([]);

  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<KnowledgeSearchResult[]>([]);
  const [searching, setSearching] = useState(false);

  const [detailDoc, setDetailDoc] = useState<KnowledgeDocument | null>(null);
  const [chunks, setChunks] = useState<KnowledgeChunk[]>([]);
  const [chunksLoading, setChunksLoading] = useState(false);

  const showToast = useCallback((message: string, tone: "success" | "error" = "success") => {
    setToast({ message, tone });
    window.setTimeout(() => setToast(null), 3000);
  }, []);

  const loadImportPresets = useCallback(async () => {
    try {
      const presets = await fetchKnowledgeImportPresets();
      setImportPresets(presets);
    } catch {
      setImportPresets([]);
    }
  }, []);

  const loadData = useCallback(async () => {
    if (requiresProduct) {
      setLoading(false);
      setBases([]);
      setDocuments([]);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const baseItems = await fetchKnowledgeBases();
      setBases(baseItems);
      const activeBaseId = selectedBaseId ?? baseItems[0]?.id ?? null;
      if (selectedBaseId === null && activeBaseId) {
        setSelectedBaseId(activeBaseId);
      }
      const docData = await fetchKnowledgeDocuments({
        page: 1,
        pageSize: 100,
        knowledgeBaseId: activeBaseId ?? undefined,
      });
      setDocuments(docData.items);
    } catch (err) {
      setError(translateErrorMessage(err instanceof Error ? err.message : "加载知识库失败"));
    } finally {
      setLoading(false);
    }
  }, [requiresProduct, selectedBaseId]);

  useEffect(() => {
    if (requiresProduct) {
      queueMicrotask(() => {
        setLoading(false);
        setBases([]);
        setDocuments([]);
      });
      return;
    }
    queueMicrotask(() => {
      void loadData();
      void loadImportPresets();
    });
  }, [loadData, loadImportPresets, requiresProduct, productId]);

  async function handleCreateBase() {
    const name = window.prompt("知识库名称", "品牌知识库");
    if (!name?.trim()) return;
    try {
      const created = await createKnowledgeBase({ name: name.trim() });
      setSelectedBaseId(created.id);
      showToast("知识库已创建");
      await loadData();
    } catch (err) {
      showToast(translateErrorMessage(err instanceof Error ? err.message : "创建失败"), "error");
    }
  }

  async function handleUpload(files: FileList | null) {
    if (!files?.length) return;
    setUploading(true);
    try {
      for (const file of Array.from(files)) {
        await uploadKnowledgeDocument(file, selectedBaseId ?? undefined);
      }
      showToast("文档上传并解析完成");
      await loadData();
    } catch (err) {
      showToast(translateErrorMessage(err instanceof Error ? err.message : "上传失败"), "error");
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  async function handleImportPreset(preset: KnowledgeImportPreset) {
    if (!preset.available) {
      showToast("服务器上未找到该文件，请配置 SCANDIHOME_PDF_PATH / SCANDIHOME_PPTX_PATH", "error");
      return;
    }
    setImportingPresetId(preset.id);
    try {
      await importKnowledgeDocument({
        file_path: preset.file_path,
        knowledge_base_id: selectedBaseId ?? undefined,
      });
      showToast(`${preset.label} 已导入并解析`);
      await loadData();
    } catch (err) {
      showToast(translateErrorMessage(err instanceof Error ? err.message : "导入失败"), "error");
    } finally {
      setImportingPresetId(null);
    }
  }

  async function handleReprocess(doc: KnowledgeDocument) {
    setActionId(doc.id);
    try {
      await reprocessKnowledgeDocument(doc.id);
      showToast("文档已重新解析");
      await loadData();
    } catch (err) {
      showToast(translateErrorMessage(err instanceof Error ? err.message : "重新解析失败"), "error");
    } finally {
      setActionId(null);
    }
  }

  async function handleDelete(doc: KnowledgeDocument) {
    if (!window.confirm(`确定删除文档「${doc.file_name}」？`)) return;
    setActionId(doc.id);
    try {
      await deleteKnowledgeDocument(doc.id);
      if (detailDoc?.id === doc.id) {
        setDetailDoc(null);
        setChunks([]);
      }
      showToast("文档已删除");
      await loadData();
    } catch (err) {
      showToast(translateErrorMessage(err instanceof Error ? err.message : "删除失败"), "error");
    } finally {
      setActionId(null);
    }
  }

  async function handleSearch() {
    if (!searchQuery.trim()) return;
    setSearching(true);
    try {
      const results = await searchKnowledge(searchQuery.trim(), {
        knowledgeBaseId: selectedBaseId ?? undefined,
        limit: 12,
      });
      setSearchResults(results);
    } catch (err) {
      showToast(translateErrorMessage(err instanceof Error ? err.message : "搜索失败"), "error");
    } finally {
      setSearching(false);
    }
  }

  async function openDetail(doc: KnowledgeDocument) {
    setDetailDoc(doc);
    setChunksLoading(true);
    try {
      const data = await fetchKnowledgeDocumentChunks(doc.id, { page: 1, pageSize: 100 });
      setChunks(data.items);
    } catch (err) {
      showToast(translateErrorMessage(err instanceof Error ? err.message : "加载片段失败"), "error");
      setChunks([]);
    } finally {
      setChunksLoading(false);
    }
  }

  const activeBase = bases.find((b) => b.id === selectedBaseId) ?? bases[0];

  return (
    <AdminShell title="知识库" description="按产品/品牌管理品牌资料，供 AI 话术推荐使用">
      {toast ? (
        <div
          className={`fixed bottom-6 right-6 z-50 rounded-lg border px-4 py-3 text-sm shadow-lg ${
            toast.tone === "success"
              ? "border-emerald-200 bg-emerald-50 text-emerald-800"
              : "border-red-200 bg-red-50 text-red-800"
          }`}
        >
          {toast.message}
        </div>
      ) : null}

      {requiresProduct ? (
        <div className="ops-page">
          <div className="ops-toolbar shrink-0">
            <div className="flex min-w-[260px] items-center gap-2">
              <BookOpen className="h-4 w-4 text-slate-500" />
              <span className="text-sm font-medium text-slate-700">当前库</span>
              <span className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-500">
                待选择产品/品牌
              </span>
            </div>
            <div className="flex min-w-[300px] flex-1 items-center gap-2">
              <Input placeholder="搜索品牌定位、视觉风格、产品卖点..." disabled />
              <Button disabled>
                <Search className="h-4 w-4" />
                搜索
              </Button>
            </div>
            <div className="flex flex-wrap items-center justify-end gap-2">
              <Button disabled>
                <Upload className="h-4 w-4" />
                上传文档
              </Button>
              <Button variant="outline" disabled>
                <Plus className="h-4 w-4" />
                新建知识库
              </Button>
            </div>
          </div>

          <div className="asset-summary shrink-0">
            <div className="asset-summary-item">
              <div className="asset-summary-label">文档数</div>
              <div className="asset-summary-value">0</div>
            </div>
            <div className="asset-summary-item">
              <div className="asset-summary-label">片段数</div>
              <div className="asset-summary-value">0</div>
            </div>
            <div className="asset-summary-item">
              <div className="asset-summary-label">可用文档</div>
              <div className="asset-summary-value">0</div>
            </div>
            <div className="asset-summary-item">
              <div className="asset-summary-label">索引状态</div>
              <div className="mt-2 text-sm font-medium text-slate-500">待选择</div>
            </div>
          </div>

          <Card className="asset-table-panel flex min-h-0 flex-1 flex-col overflow-hidden">
            <CardHeader className="asset-card-header shrink-0">
              <CardTitle>文档列表</CardTitle>
              <CardDescription>选择具体产品/品牌后，可在这里管理品牌资料、索引片段和检索结果。</CardDescription>
            </CardHeader>
            <CardContent className="flex min-h-0 flex-1 flex-col p-0">
              <div className="asset-empty">
                <EmptyState
                  title="请选择具体产品/品牌"
                  description="知识库按产品隔离，请先在左侧切换到具体品牌后再上传和管理文档。"
                />
              </div>
            </CardContent>
          </Card>
        </div>
      ) : loading ? (
        <LoadingState label="加载知识库…" />
      ) : error ? (
        <ErrorAlert message={error} onRetry={() => void loadData()} />
      ) : (
        <div className="ops-page">
          <div className="ops-toolbar shrink-0">
            <div className="flex min-w-[260px] flex-wrap items-center gap-2">
              <BookOpen className="h-4 w-4 text-slate-500" />
              <span className="text-sm font-medium text-slate-700">当前库</span>
              <select
                value={selectedBaseId ?? ""}
                onChange={(e) => setSelectedBaseId(Number(e.target.value))}
                className="h-9 min-w-[240px] rounded-md border border-slate-200 bg-white px-3 text-sm outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
              >
                {bases.map((base) => (
                  <option key={base.id} value={base.id}>
                    {base.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex min-w-[300px] flex-1 items-center gap-2">
              <Input
                placeholder="搜索品牌定位、视觉风格、产品卖点..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void handleSearch();
                }}
              />
              {searchQuery ? (
                <Button variant="ghost" size="sm" onClick={() => {
                  setSearchQuery("");
                  setSearchResults([]);
                }}>
                  清空
                </Button>
              ) : null}
              <Button disabled={searching || !searchQuery.trim()} onClick={() => void handleSearch()}>
                {searching ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
                搜索
              </Button>
            </div>
            <div className="flex flex-wrap items-center justify-end gap-2">
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf,.pptx"
                multiple
                className="hidden"
                onChange={(e) => void handleUpload(e.target.files)}
              />
              <Button disabled={uploading || !selectedBaseId} onClick={() => fileInputRef.current?.click()}>
                {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
                上传文档
              </Button>
              <Button variant="outline" onClick={() => void handleCreateBase()}>
                <Plus className="h-4 w-4" />
                新建知识库
              </Button>
              <Button variant="outline" size="icon" onClick={() => void loadData()} title="刷新">
                <RefreshCw className="h-4 w-4" />
              </Button>
            </div>
          </div>

          <div className="asset-summary shrink-0">
            <div className="asset-summary-item">
              <div className="asset-summary-label">文档数</div>
              <div className="asset-summary-value">{activeBase?.document_count ?? documents.length}</div>
            </div>
            <div className="asset-summary-item">
              <div className="asset-summary-label">片段数</div>
              <div className="asset-summary-value">{activeBase?.chunk_count ?? 0}</div>
            </div>
            <div className="asset-summary-item">
              <div className="asset-summary-label">可用文档</div>
              <div className="asset-summary-value">{documents.filter((doc) => doc.status === "ready").length}</div>
            </div>
            <div className="asset-summary-item">
              <div className="asset-summary-label">最近更新</div>
              <div className="mt-2 truncate text-sm font-medium text-slate-700">{formatDate(activeBase?.updated_at ?? null)}</div>
            </div>
          </div>

          {importPresets.length > 0 ? (
            <div className="ops-panel asset-import-panel shrink-0 px-4 py-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="text-sm font-medium text-slate-950">快捷导入</p>
                  <p className="text-xs text-muted-foreground">从服务器预设路径导入 ScandiHome 品牌资料。</p>
                </div>
                <div className="flex flex-wrap gap-2">
                  {importPresets.map((preset) => {
                    const busy = importingPresetId === preset.id;
                    return (
                      <Button
                        key={preset.id}
                        size="sm"
                        variant="outline"
                        disabled={busy || uploading || !selectedBaseId || !preset.available}
                        onClick={() => void handleImportPreset(preset)}
                      >
                        {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileText className="h-4 w-4" />}
                        {preset.label}
                      </Button>
                    );
                  })}
                </div>
              </div>
            </div>
          ) : null}

          <Card className="asset-table-panel flex min-h-0 flex-1 flex-col overflow-hidden">
            <CardHeader className="asset-card-header shrink-0">
              <CardTitle>文档列表</CardTitle>
              <CardDescription>
                {documents.length} 个文档{activeBase ? `，${activeBase.name}` : ""}，支持 PDF、PPTX 分段索引
              </CardDescription>
            </CardHeader>
            <CardContent className="flex min-h-0 flex-1 flex-col p-0">
              {documents.length === 0 ? (
                <div className="asset-empty">
                  <EmptyState
                    title="还没有品牌资料"
                    description="上传品牌 PDF、PPTX 或使用快捷导入后，系统会分段索引内容，供 AI 外联话术检索引用。"
                    action={<Button onClick={() => fileInputRef.current?.click()}><Upload className="h-4 w-4" />上传文档</Button>}
                    secondaryAction={<Button variant="outline" onClick={() => void handleCreateBase()}>新建知识库</Button>}
                  />
                </div>
              ) : (
                <div className="ops-table-wrap">
                  <table className="ops-table min-w-[900px]">
                    <thead>
                      <tr>
                        <th>文件名</th>
                        <th>类型</th>
                        <th>状态</th>
                        <th>片段数</th>
                        <th>更新时间</th>
                        <th className="text-right">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {documents.map((doc) => {
                        const busy = actionId === doc.id;
                        return (
                          <tr key={doc.id}>
                            <td>
                              <div className="flex min-w-0 items-center gap-2">
                                <FileText className="h-4 w-4 shrink-0 text-slate-400" />
                                <div className="min-w-0">
                                  <p className="truncate font-medium">{doc.file_name}</p>
                                  {doc.error_message ? <p className="mt-1 line-clamp-1 text-xs text-red-600">{doc.error_message}</p> : null}
                                </div>
                              </div>
                            </td>
                            <td className="uppercase text-slate-600">{doc.file_type}</td>
                            <td>
                              <Badge variant={STATUS_VARIANT[doc.status] ?? "secondary"}>
                                {STATUS_LABELS[doc.status] ?? doc.status}
                              </Badge>
                            </td>
                            <td className="tabular-nums">{doc.chunk_count}</td>
                            <td className="text-muted-foreground">{formatDate(doc.updated_at)}</td>
                            <td>
                              <div className="flex justify-end gap-1">
                                <Button size="icon" variant="ghost" className="ops-icon-button" disabled={busy || doc.status !== "ready"} onClick={() => void openDetail(doc)} title="查看片段">
                                  <Eye className="h-4 w-4" />
                                </Button>
                                <Button size="icon" variant="ghost" className="ops-icon-button" disabled={busy} onClick={() => void handleReprocess(doc)} title="重新解析">
                                  {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                                </Button>
                                <Button size="icon" variant="ghost" className="ops-icon-button text-red-600 hover:bg-red-50 hover:text-red-700" disabled={busy} onClick={() => void handleDelete(doc)} title="删除">
                                  <Trash2 className="h-4 w-4" />
                                </Button>
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>

          {searchResults.length > 0 ? (
            <Card className="asset-search-panel shrink-0">
              <CardHeader className="asset-card-header">
                <CardTitle>搜索结果</CardTitle>
                <CardDescription>找到 {searchResults.length} 个相关片段</CardDescription>
              </CardHeader>
              <CardContent className="grid gap-2 p-3 md:grid-cols-2">
                {searchResults.map((item) => (
                  <div key={item.chunk_id} className="asset-result-item rounded-md px-3 py-2 text-sm">
                    <p className="truncate font-medium">
                      {item.document_name}{item.section ? ` · ${item.section}` : ""}
                    </p>
                    {item.title ? <p className="truncate text-xs text-muted-foreground">{item.title}</p> : null}
                    <p className="mt-1 line-clamp-2 text-muted-foreground">{item.content}</p>
                  </div>
                ))}
              </CardContent>
            </Card>
          ) : null}

          {detailDoc ? (
            <Card className="asset-detail-panel shrink-0">
              <CardHeader className="asset-card-header flex flex-row items-center justify-between">
                <div>
                  <CardTitle>知识片段 · {detailDoc.file_name}</CardTitle>
                  <CardDescription>共 {chunks.length} 个片段</CardDescription>
                </div>
                <Button variant="ghost" size="sm" onClick={() => setDetailDoc(null)}>
                  关闭
                </Button>
              </CardHeader>
              <CardContent className="p-3">
                {chunksLoading ? (
                  <LoadingState label="加载片段…" />
                ) : chunks.length === 0 ? (
                  <EmptyState title="暂无片段" description="文档可能尚未解析成功。" />
                ) : (
                  <div className="max-h-[360px] space-y-2 overflow-y-auto">
                    {chunks.map((chunk) => (
                      <div key={chunk.id} className="asset-result-item rounded-md px-3 py-2 text-sm">
                        <p className="font-medium">#{chunk.chunk_index + 1}{chunk.title ? ` · ${chunk.title}` : ""}</p>
                        <p className="mt-2 whitespace-pre-wrap text-muted-foreground">{chunk.content}</p>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          ) : null}
        </div>
      )}
    </AdminShell>
  );
}
