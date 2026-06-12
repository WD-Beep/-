"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ArrowRight, Link2, Loader2, Play, Plus, RefreshCw, Trash2 } from "lucide-react";

import { AdminShell } from "@/components/layout/admin-shell";
import { useActiveProductId } from "@/components/providers/product-provider";
import { EmptyState, ErrorAlert, LoadingState, SuccessAlert } from "@/components/shared/page-states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  createLinkImportBatch,
  deleteLinkImportBatch,
  fetchLinkImportBatch,
  fetchLinkImportBatches,
  runLinkImportBatch,
  type LinkImportBatch,
  type LinkImportRunResult,
} from "@/lib/api";

const PLATFORM_LABELS: Record<string, string> = {
  instagram: "Instagram",
};

function statusLabel(status: string): string {
  switch (status) {
    case "pending":
      return "待导入";
    case "running":
      return "导入中";
    case "completed":
      return "已完成";
    case "failed":
      return "失败";
    default:
      return status;
  }
}

function formatDate(value: string | null): string {
  if (!value) return "-";
  return new Date(value).toLocaleString("zh-CN");
}

export function LinkImportPanel() {
  const productId = useActiveProductId();
  const [batchName, setBatchName] = useState("");
  const [rawUrls, setRawUrls] = useState("");
  const [currentBatch, setCurrentBatch] = useState<LinkImportBatch | null>(null);
  const [runResult, setRunResult] = useState<LinkImportRunResult | null>(null);
  const [history, setHistory] = useState<LinkImportBatch[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [creating, setCreating] = useState(false);
  const [running, setRunning] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  const loadHistory = useCallback(async () => {
    setLoadingHistory(true);
    try {
      const data = await fetchLinkImportBatches(1, 20);
      setHistory(data.items);
    } catch {
      // 历史列表失败不阻塞主流程
    } finally {
      setLoadingHistory(false);
    }
  }, []);

  useEffect(() => {
    if (productId === null) {
      setLoadingHistory(false);
      return;
    }
    queueMicrotask(() => {
      void loadHistory();
    });
  }, [loadHistory, productId]);

  async function handleCreateBatch() {
    setError(null);
    setMessage(null);
    setRunResult(null);

    if (!batchName.trim()) {
      setError("请填写批次名称");
      return;
    }
    if (!rawUrls.trim()) {
      setError("请粘贴至少一行红人主页链接");
      return;
    }

    setCreating(true);
    try {
      const batch = await createLinkImportBatch({
        name: batchName.trim(),
        raw_urls: rawUrls,
      });
      setCurrentBatch(batch);
      setMessage(
        `批次已创建：共 ${batch.total_count} 条链接，有效 ${batch.valid_urls.length} 条，无效 ${batch.invalid_urls.length} 条`,
      );
      await loadHistory();
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建批次失败");
    } finally {
      setCreating(false);
    }
  }

  async function handleRunImport() {
    if (!currentBatch) {
      setError("请先创建导入批次");
      return;
    }

    setRunning(true);
    setError(null);
    setMessage(null);
    try {
      const result = await runLinkImportBatch(currentBatch.id);
      setRunResult(result);
      setCurrentBatch(await fetchLinkImportBatch(currentBatch.id));
      setMessage("导入完成");
      await loadHistory();
    } catch (err) {
      setError(err instanceof Error ? err.message : "运行导入失败");
      await loadHistory();
    } finally {
      setRunning(false);
    }
  }

  async function handleDeleteBatch(batchId: number) {
    if (!confirm("确定要删除这个导入批次吗？此操作不可撤销。")) return;

    setDeletingId(batchId);
    try {
      await deleteLinkImportBatch(batchId);
      setHistory((prev) => prev.filter((b) => b.id !== batchId));
      if (currentBatch?.id === batchId) {
        setCurrentBatch(null);
        setRunResult(null);
      }
      setMessage("批次已删除");
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除失败");
    } finally {
      setDeletingId(null);
    }
  }

  const displayBatch = currentBatch;
  const invalidUrls = runResult?.invalid_urls ?? displayBatch?.invalid_urls ?? [];
  const importDone =
    displayBatch?.status === "completed" || runResult?.status === "completed";

  return (
    <AdminShell title="Instagram 链接导入" description="粘贴 Instagram 红人主页链接批量采集">
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Link2 className="h-5 w-5" />
              新建导入批次
            </CardTitle>
            <CardDescription>
              每行一个 Instagram 红人主页链接，系统会采集公开资料并生成 AI 画像。
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="batch_name">批次名称</Label>
              <Input
                id="batch_name"
                value={batchName}
                onChange={(e) => setBatchName(e.target.value)}
                placeholder="例如：3月 Instagram 健身红人链接包"
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="raw_urls">主页链接</Label>
              <Textarea
                id="raw_urls"
                value={rawUrls}
                onChange={(e) => setRawUrls(e.target.value)}
                placeholder={
                  "https://instagram.com/creator1\nhttps://www.instagram.com/creator2/"
                }
                rows={10}
                className="font-mono text-xs"
              />
              <p className="text-xs text-muted-foreground">
                当前仅支持 Instagram 主页链接。
              </p>
            </div>

            <div className="flex flex-wrap gap-3">
              <Button onClick={handleCreateBatch} disabled={creating || running}>
                {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
                创建导入批次
              </Button>
              <Button
                variant="secondary"
                onClick={handleRunImport}
                disabled={!currentBatch || running || creating || currentBatch.status === "running"}
              >
                {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                运行导入
              </Button>
            </div>
          </CardContent>
        </Card>

        <div className="space-y-6">
          {message ? <SuccessAlert message={message} /> : null}
          {error ? <ErrorAlert message={error} /> : null}

          {displayBatch ? (
            <Card>
              <CardHeader>
                <CardTitle>当前批次：{displayBatch.name}</CardTitle>
                <CardDescription>
                  状态：<Badge variant="outline">{statusLabel(displayBatch.status)}</Badge>
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {displayBatch.valid_urls.length > 0 ? (
                  <div className="space-y-2">
                    <p className="text-xs font-medium text-muted-foreground">已识别链接</p>
                    <ul className="max-h-40 space-y-1 overflow-y-auto text-xs">
                      {displayBatch.valid_urls.map((item) => (
                        <li key={item.url} className="flex items-start gap-2">
                          <Badge variant="secondary" className="shrink-0">
                            {PLATFORM_LABELS[item.platform] ?? item.platform}
                          </Badge>
                          <span className="break-all text-muted-foreground">{item.url}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                {(runResult || displayBatch.status === "completed") && (
                  <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                    <StatBox label="总链接数" value={runResult?.total_count ?? displayBatch.total_count} />
                    <StatBox label="成功数" value={runResult?.success_count ?? displayBatch.success_count} />
                    <StatBox label="失败数" value={runResult?.failed_count ?? displayBatch.failed_count} />
                    <StatBox label="新增数" value={runResult?.new_count ?? displayBatch.new_count} />
                    <StatBox label="更新数" value={runResult?.updated_count ?? displayBatch.updated_count} />
                    <StatBox label="无效链接" value={invalidUrls.length} />
                  </div>
                )}

                {invalidUrls.length > 0 ? (
                  <div className="space-y-2">
                    <p className="text-xs font-medium text-destructive">无效链接</p>
                    <ul className="max-h-32 space-y-1 overflow-y-auto rounded-md border border-destructive/20 bg-destructive/5 p-3 text-xs">
                      {invalidUrls.map((url) => (
                        <li key={url} className="break-all text-destructive">
                          {url}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                {importDone ? (
                  <Button asChild>
                    <Link href="/influencers">
                      查看红人库
                      <ArrowRight className="h-4 w-4" />
                    </Link>
                  </Button>
                ) : null}
              </CardContent>
            </Card>
          ) : (
            <Card>
              <CardContent className="py-8">
                <EmptyState
                  title="尚未创建批次"
                  description="填写批次名称并粘贴链接后，点击「创建导入批次」，再点击「运行导入」。"
                />
              </CardContent>
            </Card>
          )}
        </div>
      </div>

      <Card className="mt-6">
        <CardHeader className="flex flex-row items-center justify-between">
          <div>
            <CardTitle>历史批次</CardTitle>
            <CardDescription>最近导入记录</CardDescription>
          </div>
          <Button variant="outline" size="sm" onClick={loadHistory} disabled={loadingHistory}>
            {loadingHistory ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
            刷新
          </Button>
        </CardHeader>
        <CardContent>
          {loadingHistory ? (
            <LoadingState label="加载历史批次..." />
          ) : history.length === 0 ? (
            <p className="text-sm text-muted-foreground">暂无历史记录</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[800px] text-sm">
                <thead>
                  <tr className="border-b text-left text-muted-foreground">
                    <th className="pb-3 pr-4 font-medium">批次名称</th>
                    <th className="pb-3 pr-4 font-medium">状态</th>
                    <th className="pb-3 pr-4 font-medium">总链接</th>
                    <th className="pb-3 pr-4 font-medium">成功</th>
                    <th className="pb-3 pr-4 font-medium">新增</th>
                    <th className="pb-3 pr-4 font-medium">更新</th>
                    <th className="pb-3 pr-4 font-medium">创建时间</th>
                    <th className="pb-3 font-medium">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {history.map((batch) => (
                    <tr
                      key={batch.id}
                      className="cursor-pointer border-b last:border-0 hover:bg-muted/40"
                      onClick={() => {
                        setCurrentBatch(batch);
                        setRunResult(
                          batch.status === "completed"
                            ? {
                                batch_id: batch.id,
                                status: batch.status,
                                total_count: batch.total_count,
                                success_count: batch.success_count,
                                failed_count: batch.failed_count,
                                new_count: batch.new_count,
                                updated_count: batch.updated_count,
                                invalid_urls: batch.invalid_urls,
                              }
                            : null,
                        );
                      }}
                    >
                      <td className="py-3 pr-4 font-medium">{batch.name}</td>
                      <td className="py-3 pr-4">
                        <Badge variant="outline">{statusLabel(batch.status)}</Badge>
                      </td>
                      <td className="py-3 pr-4">{batch.total_count}</td>
                      <td className="py-3 pr-4">{batch.success_count}</td>
                      <td className="py-3 pr-4">{batch.new_count}</td>
                      <td className="py-3 pr-4">{batch.updated_count}</td>
                      <td className="py-3 pr-4 whitespace-nowrap">{formatDate(batch.created_at)}</td>
                      <td className="py-3">
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 w-7 p-0 text-destructive hover:bg-destructive/10 hover:text-destructive"
                          disabled={deletingId === batch.id || batch.status === "running"}
                          onClick={(e) => {
                            e.stopPropagation();
                            handleDeleteBatch(batch.id);
                          }}
                          title="删除批次"
                        >
                          {deletingId === batch.id ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                          ) : (
                            <Trash2 className="h-4 w-4" />
                          )}
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </AdminShell>
  );
}

function StatBox({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border bg-muted/30 p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-xl font-semibold">{value}</p>
    </div>
  );
}
