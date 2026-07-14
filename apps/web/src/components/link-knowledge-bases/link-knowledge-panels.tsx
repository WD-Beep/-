"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Copy,
  Download,
  Eye,
  Loader2,
  Pencil,
  Plus,
  RefreshCw,
  Save,
  Sparkles,
  Trash2,
} from "lucide-react";

import { AdminShell } from "@/components/layout/admin-shell";
import { useActiveProductId } from "@/components/providers/product-provider";
import { EmptyState, ErrorAlert, LoadingState } from "@/components/shared/page-states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  archiveLinkKnowledgeBase,
  createLinkKnowledgeBase,
  exportLinkScriptJob,
  fetchInfluencers,
  fetchLinkKnowledgeBase,
  fetchLinkKnowledgeBases,
  fetchLinkScriptJob,
  fetchLinkScriptJobs,
  fetchLinkScriptResults,
  generateLinkScripts,
  regenerateLinkScript,
  refreshLinkKnowledgeBase,
  updateLinkKnowledgeBase,
  updateLinkScriptResult,
  type Influencer,
  type LinkKnowledgeBase,
  type LinkScriptJob,
  type LinkScriptResult,
} from "@/lib/api";
import { translateErrorMessage } from "@/lib/labels";
import { ALL_PRODUCTS_ID } from "@/lib/product-context";

const SCRIPT_TYPES = [
  "email_subjects",
  "email_first_touch",
  "instagram_dm",
  "tiktok_dm",
  "youtube_pitch",
  "follow_up_1",
  "follow_up_2",
  "negotiation_reply",
  "comment_script",
];

const STATUS_VARIANT: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  parsed: "default",
  completed: "default",
  pending: "secondary",
  fetching: "outline",
  running: "outline",
  generating: "outline",
  failed: "destructive",
  partial_failed: "destructive",
  archived: "secondary",
};
const FULL_LINK_SCRIPT_MIN_WORDS = 90;

function formatDate(value: string | null | undefined): string {
  if (!value) return "-";
  return new Date(value).toLocaleString("zh-CN");
}

function stringifyJson(value: unknown): string {
  return JSON.stringify(value ?? {}, null, 2);
}

function parseJsonObject(text: string): Record<string, unknown> {
  const parsed = JSON.parse(text);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("JSON must be an object");
  }
  return parsed as Record<string, unknown>;
}

function tagsText(tags: string[] | null | undefined): string {
  return (tags ?? []).join(", ");
}

function parseTags(text: string): string[] {
  return text
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function firstString(value: unknown): string {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.map((item) => String(item)).join("\n");
  if (value == null) return "";
  return JSON.stringify(value, null, 2);
}

function getPlatformScriptKeys(platform: string | null | undefined): string[] {
  const normalized = (platform ?? "").toLowerCase();
  if (normalized.includes("tiktok")) return ["email_first_touch", "youtube_pitch", "tiktok_dm", "instagram_dm"];
  if (normalized.includes("instagram")) return ["email_first_touch", "youtube_pitch", "instagram_dm", "tiktok_dm"];
  if (normalized.includes("youtube")) return ["youtube_pitch", "email_first_touch", "instagram_dm"];
  return ["email_first_touch", "youtube_pitch", "instagram_dm", "tiktok_dm"];
}

function hasTextValue(value: unknown): boolean {
  return firstString(value).trim().length > 0;
}

function getPrimaryLinkScriptKey(result: LinkScriptResult, content: Record<string, unknown>): string {
  if (hasTextValue(content.primary_script)) return "primary_script";
  const candidates = [
    ...getPlatformScriptKeys(result.platform),
    "email_first_touch",
    "instagram_dm",
    "tiktok_dm",
    "youtube_pitch",
    "follow_up_1",
    "comment_script",
  ];
  return candidates.find((key) => hasTextValue(content[key])) ?? "primary_script";
}

function getPrimaryLinkScriptText(result: LinkScriptResult, content: Record<string, unknown>): string {
  const key = getPrimaryLinkScriptKey(result, content);
  return buildCompleteLinkScript(result, content, firstString(content[key]).trim());
}

function wordCount(text: string): number {
  return text.trim().split(/\s+/).filter(Boolean).length;
}

function buildCompleteLinkScript(
  result: LinkScriptResult,
  content: Record<string, unknown>,
  baseText: string,
): string {
  const trimmed = baseText.trim();
  if (wordCount(trimmed) >= FULL_LINK_SCRIPT_MIN_WORDS) return trimmed;

  const influencerName = result.influencer_name || result.influencer_handle || "there";
  const parts = trimmed
    ? [trimmed]
    : [`Hi ${influencerName},\n\nI came across your content and thought this could be a relevant fit for your audience.`];
  const matchReason = firstString(content.match_reason).trim();
  if (matchReason && !trimmed.toLowerCase().includes(matchReason.toLowerCase().slice(0, 40))) {
    parts.push(`Why I thought of you: ${matchReason}`);
  } else {
    parts.push("Why I thought of you: your content style feels practical, relatable, and close to the kind of audience this product is trying to reach.");
  }

  const followUp = firstString(content.follow_up_1).trim();
  parts.push(
    "Collaboration idea: we can share product details, gifting terms, and a simple content direction, then keep the brief lightweight so it fits your normal style instead of feeling like a scripted ad.",
  );
  parts.push(
    "Would you be open to taking a quick look? If it feels aligned, I can send the product info and a clear outline so you can decide whether it works for your content.",
  );
  if (followUp && wordCount(parts.join(" ")) < FULL_LINK_SCRIPT_MIN_WORDS + 20) {
    parts.push(followUp);
  }

  const signatureName = result.influencer_name || result.influencer_handle ? "[Your Name]" : "";
  return `${parts.join("\n\n")}${signatureName ? `\n\nBest,\n${signatureName}` : ""}`;
}

export function LinkKnowledgeBasesPanel() {
  const productId = useActiveProductId();
  const requiresProduct = productId === ALL_PRODUCTS_ID;
  const [items, setItems] = useState<LinkKnowledgeBase[]>([]);
  const [keyword, setKeyword] = useState("");
  const [loading, setLoading] = useState(true);
  const [actionId, setActionId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (requiresProduct) {
      setItems([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const data = await fetchLinkKnowledgeBases({ page: 1, pageSize: 50, keyword: keyword || undefined });
      setItems(data.items);
    } catch (err) {
      setError(translateErrorMessage(err instanceof Error ? err.message : "加载链接库失败"));
    } finally {
      setLoading(false);
    }
  }, [keyword, requiresProduct]);

  useEffect(() => {
    queueMicrotask(() => {
      void load();
    });
  }, [load, productId]);

  async function handleRefresh(id: number) {
    setActionId(id);
    try {
      await refreshLinkKnowledgeBase(id);
      await load();
    } catch (err) {
      setError(translateErrorMessage(err instanceof Error ? err.message : "重新解析失败"));
    } finally {
      setActionId(null);
    }
  }

  async function handleDelete(id: number) {
    if (!window.confirm("确定删除这个链接吗？删除后列表中不再显示。")) return;
    setActionId(id);
    try {
      await archiveLinkKnowledgeBase(id);
      await load();
    } catch (err) {
      setError(translateErrorMessage(err instanceof Error ? err.message : "删除失败"));
    } finally {
      setActionId(null);
    }
  }

  return (
    <AdminShell title="链接库" description="从官网、商品页和电商链接提取长期品牌知识，并生成红人外联话术">
      {requiresProduct ? (
        <div className="ops-page">
          <div className="ops-toolbar shrink-0">
            <div className="flex min-w-[300px] flex-1 items-center gap-2">
              <Input placeholder="搜索名称、URL、品牌或摘要" disabled />
              <Button variant="outline" disabled>
                <RefreshCw className="h-4 w-4" />
                刷新
              </Button>
            </div>
            <Button disabled>
              <Plus className="h-4 w-4" />
              新增链接
            </Button>
          </div>

          <div className="asset-summary shrink-0">
            <div className="asset-summary-item">
              <div className="asset-summary-label">链接总数</div>
              <div className="asset-summary-value">0</div>
            </div>
            <div className="asset-summary-item">
              <div className="asset-summary-label">可用链接</div>
              <div className="asset-summary-value">0</div>
            </div>
            <div className="asset-summary-item">
              <div className="asset-summary-label">解析中</div>
              <div className="asset-summary-value">0</div>
            </div>
            <div className="asset-summary-item">
              <div className="asset-summary-label">最近更新</div>
              <div className="mt-2 text-sm font-medium text-slate-500">待选择</div>
            </div>
          </div>

          <Card className="flex min-h-0 flex-1 flex-col overflow-hidden">
            <CardHeader className="shrink-0 border-b px-4 py-3">
              <CardTitle>链接列表</CardTitle>
              <CardDescription>选择具体产品/品牌后，可添加官网、商品页或电商链接沉淀品牌知识。</CardDescription>
            </CardHeader>
            <CardContent className="flex min-h-0 flex-1 flex-col p-0">
              <div className="asset-empty">
                <EmptyState
                  title="请选择具体产品/品牌"
                  description="链接库按当前产品隔离，请先在左侧切换到具体产品后再新增和解析链接。"
                />
              </div>
            </CardContent>
          </Card>
        </div>
      ) : (
        <div className="ops-page">
          <div className="ops-toolbar shrink-0">
            <div className="flex min-w-[300px] flex-1 items-center gap-2">
              <Input
                value={keyword}
                onChange={(event) => setKeyword(event.target.value)}
                placeholder="搜索名称、URL、品牌或摘要"
                onKeyDown={(event) => {
                  if (event.key === "Enter") void load();
                }}
              />
              {keyword ? (
                <Button variant="ghost" size="sm" onClick={() => setKeyword("")}>
                  清空
                </Button>
              ) : null}
              <Button variant="outline" onClick={() => void load()} disabled={loading}>
                {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                刷新
              </Button>
            </div>
            <Button asChild>
              <Link href="/link-knowledge-bases/new">
                <Plus className="h-4 w-4" />
                新增链接
              </Link>
            </Button>
          </div>

          <div className="asset-summary shrink-0">
            <div className="asset-summary-item">
              <div className="asset-summary-label">链接总数</div>
              <div className="asset-summary-value">{items.length}</div>
            </div>
            <div className="asset-summary-item">
              <div className="asset-summary-label">可用链接</div>
              <div className="asset-summary-value">{items.filter((item) => ["parsed", "completed"].includes(item.status)).length}</div>
            </div>
            <div className="asset-summary-item">
              <div className="asset-summary-label">解析中</div>
              <div className="asset-summary-value">{items.filter((item) => ["pending", "fetching", "running"].includes(item.status)).length}</div>
            </div>
            <div className="asset-summary-item">
              <div className="asset-summary-label">最近更新</div>
              <div className="mt-2 truncate text-sm font-medium text-slate-700">{formatDate(items[0]?.updated_at)}</div>
            </div>
          </div>

          {error ? <ErrorAlert message={error} onRetry={() => void load()} /> : null}

          <Card className="flex min-h-0 flex-1 flex-col overflow-hidden">
            <CardHeader className="shrink-0 border-b px-4 py-3">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <CardTitle>链接列表</CardTitle>
                  <CardDescription>品牌官网、商品页、Amazon 或 Shopify 链接会在这里沉淀为品牌知识。</CardDescription>
                </div>
                <Button asChild variant="outline" size="sm">
                  <Link href="/link-knowledge-bases/new">
                    <Plus className="h-4 w-4" />
                    新增链接
                  </Link>
                </Button>
              </div>
            </CardHeader>
            <CardContent className="flex min-h-0 flex-1 flex-col p-0">
              {loading ? (
                <LoadingState label="加载链接库..." />
              ) : items.length === 0 ? (
                <div className="asset-empty">
                  <EmptyState
                    title="暂无链接"
                    description="添加品牌官网、商品页或电商链接后，系统会抓取正文并提取品牌知识，后续可用于外联话术生成。"
                    action={
                      <Button asChild>
                        <Link href="/link-knowledge-bases/new">
                          <Plus className="h-4 w-4" />
                          新增链接
                        </Link>
                      </Button>
                    }
                    secondaryAction={<Button variant="outline">查看导入示例</Button>}
                  />
                </div>
              ) : (
                <div className="ops-table-wrap">
                  <table className="ops-table min-w-[960px]">
                    <thead>
                      <tr>
                        <th>名称</th>
                        <th>域名</th>
                        <th>品牌/产品</th>
                        <th>状态</th>
                        <th>更新</th>
                        <th className="text-right">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {items.map((item) => {
                        const knowledge = item.extracted_knowledge ?? {};
                        const busy = actionId === item.id;
                        return (
                          <tr key={item.id}>
                            <td>
                              <p className="truncate font-medium">{item.name}</p>
                              <p className="max-w-sm truncate text-xs text-muted-foreground">{item.url}</p>
                            </td>
                            <td className="text-slate-600">{item.domain ?? "-"}</td>
                            <td>
                              <p className="truncate">{firstString(knowledge.brand_name) || "-"}</p>
                              <p className="truncate text-xs text-muted-foreground">{firstString(knowledge.product_name)}</p>
                            </td>
                            <td>
                              <Badge variant={STATUS_VARIANT[item.status] ?? "secondary"}>{item.status}</Badge>
                            </td>
                            <td className="text-muted-foreground">{formatDate(item.updated_at)}</td>
                            <td>
                              <div className="flex justify-end gap-1">
                                <Button asChild size="icon" variant="ghost" className="ops-icon-button" title="查看">
                                  <Link href={`/link-knowledge-bases/${item.id}`}>
                                    <Eye className="h-4 w-4" />
                                  </Link>
                                </Button>
                                <Button asChild size="icon" variant="ghost" className="ops-icon-button" title="编辑">
                                  <Link href={`/link-knowledge-bases/${item.id}/edit`}>
                                    <Pencil className="h-4 w-4" />
                                  </Link>
                                </Button>
                                <Button size="icon" variant="ghost" className="ops-icon-button" disabled={busy} onClick={() => void handleRefresh(item.id)} title="重新解析">
                                  {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                                </Button>
                                <Button size="icon" variant="ghost" className="ops-icon-button" disabled={busy} onClick={() => void handleDelete(item.id)} title="删除">
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
        </div>
      )}
    </AdminShell>
  );
}

export function NewLinkKnowledgeBasePanel() {
  const router = useRouter();
  const productId = useActiveProductId();
  const requiresProduct = productId === ALL_PRODUCTS_ID;
  const [url, setUrl] = useState("");
  const [name, setName] = useState("");
  const [tags, setTags] = useState("");
  const [parseImmediately, setParseImmediately] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const created = await createLinkKnowledgeBase({
        url,
        name: name || null,
        tags: parseTags(tags),
        parse_immediately: parseImmediately,
      });
      router.push(`/link-knowledge-bases/${created.id}`);
    } catch (err) {
      setError(translateErrorMessage(err instanceof Error ? err.message : "创建链接库失败"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AdminShell title="新增链接库" description="添加品牌官网、商品页或电商链接，生成长期品牌知识">
      {requiresProduct ? (
        <Card>
          <CardContent className="py-10">
            <EmptyState title="请选择具体产品/品牌" description="请先在左侧切换到具体产品后再新增链接库。" />
          </CardContent>
        </Card>
      ) : (
        <Card className="max-w-3xl">
          <CardHeader>
            <CardTitle>链接信息</CardTitle>
            <CardDescription>立即解析会同步抓取网页并调用 AI 或本地降级规则提取知识。</CardDescription>
          </CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={(event) => void handleSubmit(event)}>
              {error ? <ErrorAlert message={error} /> : null}
              <div className="space-y-2">
                <label className="text-sm font-medium" htmlFor="link-url">URL</label>
                <Input id="link-url" required value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://brand.com/products/item" />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium" htmlFor="link-name">名称</label>
                <Input id="link-name" value={name} onChange={(event) => setName(event.target.value)} placeholder="可选，默认从 URL 推断" />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium" htmlFor="link-tags">标签</label>
                <Input id="link-tags" value={tags} onChange={(event) => setTags(event.target.value)} placeholder="skincare, amazon, serum" />
              </div>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={parseImmediately}
                  onChange={(event) => setParseImmediately(event.target.checked)}
                />
                立即解析
              </label>
              <div className="flex gap-2">
                <Button type="submit" disabled={submitting}>
                  {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                  创建
                </Button>
                <Button type="button" variant="outline" onClick={() => router.push("/link-knowledge-bases")}>
                  返回
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      )}
    </AdminShell>
  );
}

export function EditLinkKnowledgeBasePanel({ baseId }: { baseId: number }) {
  const router = useRouter();
  const productId = useActiveProductId();
  const requiresProduct = productId === ALL_PRODUCTS_ID;
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [url, setUrl] = useState("");
  const [name, setName] = useState("");
  const [tags, setTags] = useState("");
  const [summary, setSummary] = useState("");
  const [reparse, setReparse] = useState(false);

  const load = useCallback(async () => {
    if (requiresProduct) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const data = await fetchLinkKnowledgeBase(baseId);
      setUrl(data.url);
      setName(data.name);
      setTags(tagsText(data.tags));
      setSummary(data.summary ?? "");
    } catch (err) {
      setError(translateErrorMessage(err instanceof Error ? err.message : "加载链接失败"));
    } finally {
      setLoading(false);
    }
  }, [baseId, requiresProduct]);

  useEffect(() => {
    queueMicrotask(() => {
      void load();
    });
  }, [load, productId]);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await updateLinkKnowledgeBase(baseId, {
        url,
        name: name || null,
        tags: parseTags(tags),
        summary: summary || null,
        reparse,
      });
      router.push(`/link-knowledge-bases/${baseId}`);
    } catch (err) {
      setError(translateErrorMessage(err instanceof Error ? err.message : "保存失败"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AdminShell title="编辑链接" description="修改链接名称、URL、标签等信息，保存后可继续生成外联话术">
      {requiresProduct ? (
        <Card>
          <CardContent className="py-10">
            <EmptyState title="请选择具体产品/品牌" description="请先在左侧切换到具体产品后再编辑链接。" />
          </CardContent>
        </Card>
      ) : loading ? (
        <LoadingState label="加载链接..." />
      ) : (
        <Card className="max-w-3xl">
          <CardHeader>
            <CardTitle>链接信息</CardTitle>
            <CardDescription>修改 URL 或勾选重新解析时，会重新抓取页面并更新提取知识。</CardDescription>
          </CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={(event) => void handleSubmit(event)}>
              {error ? <ErrorAlert message={error} /> : null}
              <div className="space-y-2">
                <label className="text-sm font-medium" htmlFor="edit-link-url">URL</label>
                <Input id="edit-link-url" required value={url} onChange={(event) => setUrl(event.target.value)} />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium" htmlFor="edit-link-name">名称</label>
                <Input id="edit-link-name" value={name} onChange={(event) => setName(event.target.value)} />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium" htmlFor="edit-link-tags">标签</label>
                <Input id="edit-link-tags" value={tags} onChange={(event) => setTags(event.target.value)} placeholder="skincare, amazon, serum" />
              </div>
              <div className="space-y-2">
                <label className="text-sm font-medium" htmlFor="edit-link-summary">摘要</label>
                <Textarea id="edit-link-summary" value={summary} onChange={(event) => setSummary(event.target.value)} rows={4} />
              </div>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={reparse}
                  onChange={(event) => setReparse(event.target.checked)}
                />
                保存时重新解析网页
              </label>
              <div className="flex gap-2">
                <Button type="submit" disabled={submitting}>
                  {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                  保存
                </Button>
                <Button type="button" variant="outline" onClick={() => router.push(`/link-knowledge-bases/${baseId}`)}>
                  取消
                </Button>
                <Button type="button" variant="ghost" onClick={() => router.push("/link-knowledge-bases")}>
                  返回列表
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      )}
    </AdminShell>
  );
}

export function LinkKnowledgeBaseDetailPanel({ baseId }: { baseId: number }) {
  const router = useRouter();
  const productId = useActiveProductId();
  const [base, setBase] = useState<LinkKnowledgeBase | null>(null);
  const [jobs, setJobs] = useState<LinkScriptJob[]>([]);
  const [influencers, setInfluencers] = useState<Influencer[]>([]);
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [knowledgeText, setKnowledgeText] = useState("{}");
  const [summary, setSummary] = useState("");
  const [tags, setTags] = useState("");
  const [tone, setTone] = useState("friendly");
  const [collaborationType, setCollaborationType] = useState("gifted_collab");
  const [extraInstruction, setExtraInstruction] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [baseData, influencerData] = await Promise.all([
        fetchLinkKnowledgeBase(baseId),
        fetchInfluencers(1, 50),
      ]);
      setBase(baseData);
      setKnowledgeText(stringifyJson(baseData.extracted_knowledge));
      setSummary(baseData.summary ?? "");
      setTags(tagsText(baseData.tags));
      setInfluencers(influencerData.items);
      const jobData = await fetchLinkScriptJobs({ linkKnowledgeBaseId: baseId, pageSize: 20 });
      setJobs(jobData.items);
    } catch (err) {
      setError(translateErrorMessage(err instanceof Error ? err.message : "加载链接库详情失败"));
    } finally {
      setLoading(false);
    }
  }, [baseId]);

  useEffect(() => {
    queueMicrotask(() => {
      void load();
    });
  }, [load, productId]);

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      const extracted = parseJsonObject(knowledgeText);
      const updated = await updateLinkKnowledgeBase(baseId, {
        name: base?.name ?? null,
        summary,
        tags: parseTags(tags),
        extracted_knowledge: extracted,
      });
      setBase(updated);
      setKnowledgeText(stringifyJson(updated.extracted_knowledge));
      setSummary(updated.summary ?? "");
      setTags(tagsText(updated.tags));
    } catch (err) {
      setError(translateErrorMessage(err instanceof Error ? err.message : "保存失败"));
    } finally {
      setSaving(false);
    }
  }

  async function handleRefresh() {
    setSaving(true);
    setError(null);
    try {
      const refreshed = await refreshLinkKnowledgeBase(baseId);
      setBase(refreshed);
      setKnowledgeText(stringifyJson(refreshed.extracted_knowledge));
      setSummary(refreshed.summary ?? "");
      setTags(tagsText(refreshed.tags));
    } catch (err) {
      setError(translateErrorMessage(err instanceof Error ? err.message : "重新解析失败"));
    } finally {
      setSaving(false);
    }
  }

  async function handleGenerate() {
    if (selectedIds.length === 0) {
      setError("请至少选择一个红人");
      return;
    }
    setGenerating(true);
    setError(null);
    try {
      let extracted: Record<string, unknown> = {};
      try {
        extracted = parseJsonObject(knowledgeText);
      } catch {
        setError("结构化知识 JSON 格式不正确，请先修正并保存后再生成话术");
        return;
      }
      const hasManualKnowledge =
        Boolean(summary.trim()) ||
        Object.keys(extracted).some((key) => {
          const value = extracted[key];
          if (value == null) return false;
          if (typeof value === "string") return value.trim().length > 0;
          if (Array.isArray(value)) return value.length > 0;
          if (typeof value === "object") return Object.keys(value as object).length > 0;
          return true;
        });
      if ((base?.status === "failed" || base?.status === "pending") && !hasManualKnowledge) {
        setError(
          "当前链接尚未解析出品牌知识（常见于 Amazon 限流）。请先手动填写摘要或结构化知识并点保存，或换链接后重新解析，再生成话术。",
        );
        return;
      }
      const updated = await updateLinkKnowledgeBase(baseId, {
        name: base?.name ?? null,
        summary: summary || null,
        tags: parseTags(tags),
        extracted_knowledge: extracted,
      });
      setBase(updated);
      setKnowledgeText(stringifyJson(updated.extracted_knowledge));
      setSummary(updated.summary ?? "");
      setTags(tagsText(updated.tags));

      const job = await generateLinkScripts(baseId, {
        influencer_ids: selectedIds,
        tone,
        collaboration_type: collaborationType,
        language: "en",
        script_types: SCRIPT_TYPES,
        extra_instruction: extraInstruction || null,
      });
      router.push(`/link-script-jobs/${job.id}`);
    } catch (err) {
      setError(translateErrorMessage(err instanceof Error ? err.message : "生成话术失败"));
    } finally {
      setGenerating(false);
    }
  }

  const knowledge = base?.extracted_knowledge ?? {};

  return (
    <AdminShell title="链接库详情" description="查看、编辑链接知识，并选择红人生成外联话术">
      {loading ? (
        <LoadingState label="加载链接库详情..." />
      ) : error && !base ? (
        <ErrorAlert message={error} onRetry={() => void load()} />
      ) : base ? (
        <div className="space-y-6">
          {error ? <ErrorAlert message={error} /> : null}
          <Card>
            <CardHeader className="flex flex-row items-start justify-between gap-4">
              <div>
                <CardTitle>{base.name}</CardTitle>
                <CardDescription>{base.url}</CardDescription>
              </div>
              <div className="flex items-center gap-2">
                <Badge variant={STATUS_VARIANT[base.status] ?? "secondary"}>{base.status}</Badge>
                <Button asChild size="sm" variant="outline">
                  <Link href={`/link-knowledge-bases/${base.id}/edit`}>
                    <Pencil className="h-4 w-4" />
                    编辑
                  </Link>
                </Button>
              </div>
            </CardHeader>
            <CardContent className="grid gap-3 text-sm md:grid-cols-3">
              <div><span className="text-muted-foreground">域名：</span>{base.domain ?? "-"}</div>
              <div><span className="text-muted-foreground">来源：</span>{base.source_type}</div>
              <div><span className="text-muted-foreground">最近解析：</span>{formatDate(base.last_fetched_at)}</div>
              {base.error_message ? (
                <div className="md:col-span-3 text-red-600">{translateErrorMessage(base.error_message)}</div>
              ) : null}
            </CardContent>
          </Card>

          <div className="grid gap-6 xl:grid-cols-[minmax(0,1.2fr)_minmax(360px,0.8fr)]">
            <Card>
              <CardHeader>
                <CardTitle>提取知识</CardTitle>
                <CardDescription>
                  品牌：{firstString(knowledge.brand_name) || "-"}；产品：{firstString(knowledge.product_name) || "-"}
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <label className="text-sm font-medium">摘要</label>
                  <Textarea value={summary} onChange={(event) => setSummary(event.target.value)} rows={4} />
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-medium">标签</label>
                  <Input value={tags} onChange={(event) => setTags(event.target.value)} />
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-medium">结构化知识 JSON</label>
                  <Textarea
                    value={knowledgeText}
                    onChange={(event) => setKnowledgeText(event.target.value)}
                    className="min-h-[360px] font-mono text-xs"
                  />
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button disabled={saving} onClick={() => void handleSave()}>
                    {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                    保存
                  </Button>
                  <Button variant="outline" disabled={saving} onClick={() => void handleRefresh()}>
                    <RefreshCw className="h-4 w-4" />
                    重新解析
                  </Button>
                </div>
              </CardContent>
            </Card>

            <div className="space-y-6">
              <Card>
                <CardHeader>
                  <CardTitle>选择红人生成话术</CardTitle>
                  <CardDescription>当前加载前 50 个红人，支持多选。</CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="max-h-72 space-y-2 overflow-y-auto rounded-md border p-2">
                    {influencers.length === 0 ? (
                      <p className="p-3 text-sm text-muted-foreground">暂无红人数据</p>
                    ) : (
                      influencers.map((item) => (
                        <label key={item.id} className="flex items-start gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-muted">
                          <input
                            type="checkbox"
                            checked={selectedIds.includes(item.id)}
                            onChange={(event) => {
                              setSelectedIds((current) =>
                                event.target.checked
                                  ? [...current, item.id]
                                  : current.filter((id) => id !== item.id),
                              );
                            }}
                          />
                          <span>
                            <span className="font-medium">{item.display_name || item.username}</span>
                            <span className="block text-xs text-muted-foreground">
                              {item.platform} · {item.followers_count ?? "-"} followers
                            </span>
                          </span>
                        </label>
                      ))
                    )}
                  </div>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <div className="space-y-1">
                      <label className="text-sm font-medium">语气</label>
                      <select className="h-9 w-full rounded-md border bg-background px-3 text-sm" value={tone} onChange={(event) => setTone(event.target.value)}>
                        {["friendly", "professional", "casual", "warm", "direct"].map((item) => <option key={item}>{item}</option>)}
                      </select>
                    </div>
                    <div className="space-y-1">
                      <label className="text-sm font-medium">合作方式</label>
                      <select className="h-9 w-full rounded-md border bg-background px-3 text-sm" value={collaborationType} onChange={(event) => setCollaborationType(event.target.value)}>
                        {["gifted_collab", "paid_collab", "affiliate", "ambassador", "ugc", "review"].map((item) => <option key={item}>{item}</option>)}
                      </select>
                    </div>
                  </div>
                  <Textarea value={extraInstruction} onChange={(event) => setExtraInstruction(event.target.value)} placeholder="额外要求，可选" />
                  <Button className="w-full" disabled={generating} onClick={() => void handleGenerate()}>
                    {generating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                    生成话术
                  </Button>
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle>历史任务</CardTitle>
                </CardHeader>
                <CardContent>
                  {jobs.length === 0 ? (
                    <EmptyState title="暂无任务" description="生成话术后会出现在这里。" />
                  ) : (
                    <div className="space-y-2">
                      {jobs.map((job) => (
                        <Link key={job.id} href={`/link-script-jobs/${job.id}`} className="block rounded-md border px-3 py-2 text-sm hover:bg-muted">
                          <span className="font-medium">{job.name}</span>
                          <span className="ml-2 text-muted-foreground">{job.status} · {job.success_count}/{job.total_count}</span>
                        </Link>
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>
          </div>

        </div>
      ) : null}
    </AdminShell>
  );
}

export function LinkScriptJobDetailPanel({ jobId }: { jobId: number }) {
  const productId = useActiveProductId();
  const [job, setJob] = useState<LinkScriptJob | null>(null);
  const [results, setResults] = useState<LinkScriptResult[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState<{ resultId: number | null; text: string }>({ resultId: null, text: "" });
  const [loading, setLoading] = useState(true);
  const [actionId, setActionId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const selected = useMemo(
    () => results.find((item) => item.id === selectedId) ?? null,
    [results, selectedId],
  );

  const load = useCallback(async () => {
    if (productId === ALL_PRODUCTS_ID) {
      setJob(null);
      setResults([]);
      setError("请先在左侧选择具体产品/品牌，再查看话术结果。");
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const [jobData, resultData] = await Promise.all([
        fetchLinkScriptJob(jobId),
        fetchLinkScriptResults(jobId, { pageSize: 200 }),
      ]);
      setJob(jobData);
      setResults(resultData.items);
      setSelectedId((current) => {
        if (current == null) return current;
        return resultData.items.some((item) => item.id === current) ? current : null;
      });
    } catch (err) {
      setError(translateErrorMessage(err instanceof Error ? err.message : "加载话术任务失败"));
    } finally {
      setLoading(false);
    }
  }, [jobId, productId]);

  useEffect(() => {
    queueMicrotask(() => {
      void load();
    });
  }, [load]);

  const selectedContent = useMemo(
    () => selected?.used_content ?? selected?.edited_content ?? selected?.generated_content ?? {},
    [selected],
  );
  const selectedScriptKey = useMemo(
    () => (selected ? getPrimaryLinkScriptKey(selected, selectedContent) : "primary_script"),
    [selected, selectedContent],
  );
  const selectedScriptText = useMemo(
    () => (selected ? getPrimaryLinkScriptText(selected, selectedContent) : ""),
    [selected, selectedContent],
  );
  const editText = selected && editDraft.resultId === selected.id ? editDraft.text : selectedScriptText;

  async function handleSaveResult() {
    if (!selected) return;
    setActionId(selected.id);
    setError(null);
    try {
      const scriptText = editText.trim();
      const baseContent = selected.edited_content ?? selected.generated_content ?? {};
      const edited = {
        ...baseContent,
        [selectedScriptKey]: scriptText,
        primary_script: scriptText,
      };
      const updated = await updateLinkScriptResult(selected.id, { edited_content: edited });
      setResults((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
      setSelectedId(updated.id);
      const nextContent = updated.edited_content ?? updated.generated_content ?? {};
      setEditDraft({ resultId: updated.id, text: getPrimaryLinkScriptText(updated, nextContent) });
    } catch (err) {
      setError(translateErrorMessage(err instanceof Error ? err.message : "保存话术失败"));
    } finally {
      setActionId(null);
    }
  }

  async function handleRegenerate(resultId: number) {
    setActionId(resultId);
    setError(null);
    try {
      const updated = await regenerateLinkScript(resultId);
      setResults((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
      setSelectedId(updated.id);
      const nextContent = updated.edited_content ?? updated.generated_content ?? {};
      setEditDraft({ resultId: updated.id, text: getPrimaryLinkScriptText(updated, nextContent) });
    } catch (err) {
      setError(translateErrorMessage(err instanceof Error ? err.message : "重新生成失败"));
    } finally {
      setActionId(null);
    }
  }

  async function handleCopy() {
    await navigator.clipboard.writeText(editText.trim() || selectedScriptText);
  }

  return (
    <AdminShell title="话术结果" description="查看、编辑、复制或重新生成链接库话术结果">
      {loading ? (
        <LoadingState label="加载话术结果..." />
      ) : error && !job ? (
        <ErrorAlert message={error} onRetry={() => void load()} />
      ) : job ? (
        <div className="space-y-6">
          {error ? <ErrorAlert message={error} /> : null}
          <Card>
            <CardHeader className="flex flex-row items-start justify-between gap-4">
              <div>
                <CardTitle>{job.name}</CardTitle>
                <CardDescription>
                  {job.status} · 成功 {job.success_count} / 总数 {job.total_count} · {formatDate(job.completed_at)}
                </CardDescription>
              </div>
              <Button variant="outline" onClick={() => void exportLinkScriptJob(job.id)}>
                <Download className="h-4 w-4" />
                导出 Excel
              </Button>
            </CardHeader>
          </Card>

          <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(420px,0.9fr)]">
            <Card>
              <CardHeader>
                <CardTitle>结果列表</CardTitle>
                <CardDescription>{results.length} 条结果</CardDescription>
              </CardHeader>
              <CardContent>
                {results.length === 0 ? (
                  <EmptyState title="暂无结果" />
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b text-left text-muted-foreground">
                          <th className="pb-3 pr-4 font-medium">红人</th>
                          <th className="pb-3 pr-4 font-medium">平台</th>
                          <th className="pb-3 pr-4 font-medium">状态</th>
                          <th className="pb-3 font-medium">操作</th>
                        </tr>
                      </thead>
                      <tbody>
                        {results.map((result) => {
                          const busy = actionId === result.id;
                          return (
                            <tr key={result.id} className="border-b last:border-0">
                              <td className="py-3 pr-4">
                                <p className="font-medium">{result.influencer_name || result.influencer_handle || result.influencer_id}</p>
                                <p className="text-xs text-muted-foreground">{result.profile_url}</p>
                              </td>
                              <td className="py-3 pr-4">{result.platform ?? "-"}</td>
                              <td className="py-3 pr-4">
                                <Badge variant={STATUS_VARIANT[result.status] ?? "secondary"}>{result.status}</Badge>
                              </td>
                              <td className="py-3">
                                <div className="flex flex-wrap gap-1">
                                  <Button
                                    size="sm"
                                    variant="outline"
                                    onClick={() => setSelectedId(result.id)}
                                  >
                                    查看
                                  </Button>
                                  <Button size="sm" variant="outline" disabled={busy} onClick={() => void handleRegenerate(result.id)}>
                                    {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
                                    重生
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

            <Card>
              <CardHeader>
                <CardTitle>推荐话术</CardTitle>
                <CardDescription>{selected ? selected.influencer_handle || selected.influencer_name : "请选择一条结果"}</CardDescription>
              </CardHeader>
              <CardContent>
                {!selected ? (
                  <EmptyState title="未选择结果" description="从左侧列表选择一条结果查看和编辑。" />
                ) : (
                  <div className="space-y-4">
                    <div className="rounded-md border bg-muted/30 p-3 text-sm">
                      <p className="font-medium">匹配理由</p>
                      <p className="mt-1 whitespace-pre-wrap text-muted-foreground">{firstString(selectedContent.match_reason) || "-"}</p>
                    </div>
                    <Textarea
                      value={editText}
                      onChange={(event) => setEditDraft({ resultId: selected.id, text: event.target.value })}
                      className="min-h-[280px] text-sm leading-6"
                      placeholder="这里显示一份可直接发送给红人的完整话术。"
                    />
                    <div className="flex flex-wrap gap-2">
                      <Button disabled={actionId === selected.id} onClick={() => void handleSaveResult()}>
                        <Save className="h-4 w-4" />
                        保存编辑
                      </Button>
                      <Button variant="outline" onClick={() => void handleCopy()}>
                        <Copy className="h-4 w-4" />
                        复制话术
                      </Button>
                      <Button variant="outline" disabled={actionId === selected.id} onClick={() => void handleRegenerate(selected.id)}>
                        <RefreshCw className="h-4 w-4" />
                        重新生成
                      </Button>
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      ) : null}
    </AdminShell>
  );
}
