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
  }, [requiresProduct, selectedBaseId, productId]);

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
        <Card>
          <CardContent className="py-10">
            <EmptyState
              title="请选择具体产品/品牌"
              description="知识库按产品隔离，请先在左侧切换到具体品牌后再管理文档。"
            />
          </CardContent>
        </Card>
      ) : loading ? (
        <LoadingState label="加载知识库…" />
      ) : error ? (
        <ErrorAlert message={error} onRetry={() => void loadData()} />
      ) : (
        <div className="space-y-6">
          <Card>
            <CardHeader className="flex flex-row items-start justify-between gap-4">
              <div>
                <CardTitle className="flex items-center gap-2">
                  <BookOpen className="h-5 w-5" />
                  品牌知识库
                </CardTitle>
                <CardDescription>
                  上传 PDF / PPTX 品牌资料，系统会分段索引供 AI 推荐话术时检索引用。
                </CardDescription>
              </div>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" onClick={() => void loadData()}>
                  <RefreshCw className="mr-1 h-4 w-4" />
                  刷新
                </Button>
                <Button size="sm" onClick={() => void handleCreateBase()}>
                  <Plus className="mr-1 h-4 w-4" />
                  新建知识库
                </Button>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex flex-wrap items-center gap-3">
                <label className="text-sm text-muted-foreground">当前知识库</label>
                <select
                  value={selectedBaseId ?? ""}
                  onChange={(e) => setSelectedBaseId(Number(e.target.value))}
                  className="h-9 min-w-[200px] rounded-md border border-input bg-background px-3 text-sm"
                >
                  {bases.map((base) => (
                    <option key={base.id} value={base.id}>
                      {base.name}（{base.document_count} 文档 / {base.chunk_count} 片段）
                    </option>
                  ))}
                </select>
                {activeBase ? (
                  <span className="text-xs text-muted-foreground">
                    更新于 {formatDate(activeBase.updated_at)}
                  </span>
                ) : null}
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".pdf,.pptx"
                  multiple
                  className="hidden"
                  onChange={(e) => void handleUpload(e.target.files)}
                />
                <Button
                  size="sm"
                  disabled={uploading || !selectedBaseId}
                  onClick={() => fileInputRef.current?.click()}
                >
                  {uploading ? (
                    <Loader2 className="mr-1 h-4 w-4 animate-spin" />
                  ) : (
                    <Upload className="mr-1 h-4 w-4" />
                  )}
                  上传文档
                </Button>
                <span className="text-xs text-muted-foreground">支持 PDF、PPTX</span>
              </div>

              {importPresets.length > 0 ? (
                <div className="rounded-lg border border-dashed bg-muted/20 px-4 py-3">
                  <p className="text-sm font-medium">ScandiHome 品牌资料导入</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    从服务器已配置路径一键导入视觉手册与视觉升级 PPT（需设置 SCANDIHOME_PDF_PATH / SCANDIHOME_PPTX_PATH）。
                  </p>
                  <div className="mt-3 flex flex-wrap gap-2">
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
                          {busy ? (
                            <Loader2 className="mr-1 h-4 w-4 animate-spin" />
                          ) : (
                            <FileText className="mr-1 h-4 w-4" />
                          )}
                          {preset.label}
                          {!preset.available ? "（文件不可用）" : ""}
                        </Button>
                      );
                    })}
                  </div>
                </div>
              ) : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">搜索知识库</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex gap-2">
                <Input
                  placeholder="搜索品牌定位、视觉风格、产品卖点…"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void handleSearch();
                  }}
                />
                <Button disabled={searching} onClick={() => void handleSearch()}>
                  {searching ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Search className="h-4 w-4" />
                  )}
                </Button>
              </div>
              {searchResults.length > 0 ? (
                <div className="space-y-2">
                  {searchResults.map((item) => (
                    <div key={item.chunk_id} className="rounded-lg border px-3 py-2 text-sm">
                      <p className="font-medium">
                        {item.document_name}
                        {item.section ? ` · ${item.section}` : ""}
                        <span className="ml-2 text-xs text-muted-foreground">相关度 {item.score}</span>
                      </p>
                      {item.title ? <p className="text-xs text-muted-foreground">{item.title}</p> : null}
                      <p className="mt-1 line-clamp-3 text-muted-foreground">{item.content}</p>
                    </div>
                  ))}
                </div>
              ) : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">文档列表</CardTitle>
              <CardDescription>
                {documents.length} 个文档
                {activeBase ? ` · ${activeBase.name}` : ""}
              </CardDescription>
            </CardHeader>
            <CardContent>
              {documents.length === 0 ? (
                <EmptyState
                  title="暂无文档"
                  description="请上传品牌 PDF 或 PPTX 资料，或使用上方 ScandiHome 一键导入（服务器已配置路径时）。"
                />
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b text-left text-muted-foreground">
                        <th className="pb-3 pr-4 font-medium">文件名</th>
                        <th className="pb-3 pr-4 font-medium">类型</th>
                        <th className="pb-3 pr-4 font-medium">状态</th>
                        <th className="pb-3 pr-4 font-medium">片段数</th>
                        <th className="pb-3 pr-4 font-medium">更新时间</th>
                        <th className="pb-3 font-medium">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {documents.map((doc) => {
                        const busy = actionId === doc.id;
                        return (
                          <tr key={doc.id} className="border-b last:border-0">
                            <td className="py-3 pr-4">
                              <div className="flex items-center gap-2">
                                <FileText className="h-4 w-4 text-muted-foreground" />
                                <span className="font-medium">{doc.file_name}</span>
                              </div>
                              {doc.error_message ? (
                                <p className="mt-1 text-xs text-red-600">{doc.error_message}</p>
                              ) : null}
                            </td>
                            <td className="py-3 pr-4 uppercase">{doc.file_type}</td>
                            <td className="py-3 pr-4">
                              <Badge variant={STATUS_VARIANT[doc.status] ?? "secondary"}>
                                {STATUS_LABELS[doc.status] ?? doc.status}
                              </Badge>
                            </td>
                            <td className="py-3 pr-4">{doc.chunk_count}</td>
                            <td className="py-3 pr-4 text-muted-foreground">
                              {formatDate(doc.updated_at)}
                            </td>
                            <td className="py-3">
                              <div className="flex flex-wrap gap-1">
                                <Button
                                  size="sm"
                                  variant="outline"
                                  disabled={busy || doc.status !== "ready"}
                                  onClick={() => void openDetail(doc)}
                                >
                                  <Eye className="mr-1 h-3.5 w-3.5" />
                                  片段
                                </Button>
                                <Button
                                  size="sm"
                                  variant="outline"
                                  disabled={busy}
                                  onClick={() => void handleReprocess(doc)}
                                >
                                  {busy ? (
                                    <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
                                  ) : (
                                    <RefreshCw className="mr-1 h-3.5 w-3.5" />
                                  )}
                                  重解析
                                </Button>
                                <Button
                                  size="sm"
                                  variant="outline"
                                  disabled={busy}
                                  onClick={() => void handleDelete(doc)}
                                >
                                  <Trash2 className="mr-1 h-3.5 w-3.5" />
                                  删除
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

          {detailDoc ? (
            <Card>
              <CardHeader className="flex flex-row items-center justify-between">
                <div>
                  <CardTitle className="text-base">知识片段 · {detailDoc.file_name}</CardTitle>
                  <CardDescription>共 {chunks.length} 个片段</CardDescription>
                </div>
                <Button variant="ghost" size="sm" onClick={() => setDetailDoc(null)}>
                  关闭
                </Button>
              </CardHeader>
              <CardContent>
                {chunksLoading ? (
                  <LoadingState label="加载片段…" />
                ) : chunks.length === 0 ? (
                  <EmptyState title="暂无片段" description="文档可能尚未解析成功。" />
                ) : (
                  <div className="max-h-[480px] space-y-3 overflow-y-auto">
                    {chunks.map((chunk) => (
                      <div key={chunk.id} className="rounded-lg border px-3 py-3 text-sm">
                        <p className="font-medium">
                          #{chunk.chunk_index + 1}
                          {chunk.title ? ` · ${chunk.title}` : ""}
                        </p>
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
