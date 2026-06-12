"use client";

import { useEffect, useState } from "react";
import { Loader2, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { CollectionMode, CollectionTask, CollectionTaskPayload, PlatformCapability, PlatformCapabilitiesResponse } from "@/lib/api";
import { fetchPlatformCapabilities } from "@/lib/api";
import { COLLECTION_MODE_OPTIONS, PLATFORM_CAPABILITY_STATUS_LABELS, PLATFORM_LABELS } from "@/lib/labels";
import { formatCollectionSourceSummary, formatPlatformCapabilityHint } from "@/lib/collection-sources";
import { cn } from "@/lib/utils";

const DEFAULT_PLATFORMS = ["youtube"];

export type TaskFormValues = {
  name: string;
  collection_mode: CollectionMode;
  platform: string;
  platforms: string[];
  keywordsText: string;
  inputUrlsText: string;
  country: string;
  category: string;
  discovery_limit: string;
  min_engagement_rate: string;
  min_followers_count: string;
  max_followers_count: string;
  filterIncludeKeywordsText: string;
  filterExcludeKeywordsText: string;
  schedule_enabled: boolean;
  schedule_cron: string;
  email_enabled: boolean;
  email_recipientsText: string;
  outreach_enabled: boolean;
  outreach_provider: string;
  outreach_dry_run: boolean;
  micro_subject: string;
  micro_body: string;
  mid_subject: string;
  mid_body: string;
  macro_subject: string;
  macro_body: string;
  comment_discovery_enabled: boolean;
  competitorInputText: string;
  competitorBrandText: string;
  competitorWebsiteText: string;
};

const emptyForm: TaskFormValues = {
  name: "",
  collection_mode: "discovery",
  platform: "youtube",
  platforms: [...DEFAULT_PLATFORMS],
  keywordsText: "amazon finds creator\namazon home finds",
  inputUrlsText: "",
  country: "",
  category: "",
  discovery_limit: "5",
  min_engagement_rate: "0.5",
  min_followers_count: "10000",
  max_followers_count: "",
  filterIncludeKeywordsText: "",
  filterExcludeKeywordsText: "wholesale\nofficial store\nfan page",
  schedule_enabled: false,
  schedule_cron: "",
  email_enabled: false,
  email_recipientsText: "",
  outreach_enabled: false,
  outreach_provider: "mailchimp",
  outreach_dry_run: true,
  micro_subject: "",
  micro_body: "",
  mid_subject: "",
  mid_body: "",
  macro_subject: "",
  macro_body: "",
  comment_discovery_enabled: false,
  competitorInputText: "",
  competitorBrandText: "",
  competitorWebsiteText: "",
};

function templatesToForm(templates: Record<string, string> = {}): Pick<
  TaskFormValues,
  "micro_subject" | "micro_body" | "mid_subject" | "mid_body" | "macro_subject" | "macro_body"
> {
  return {
    micro_subject: templates.micro_subject ?? "",
    micro_body: templates.micro_body ?? "",
    mid_subject: templates.mid_subject ?? "",
    mid_body: templates.mid_body ?? "",
    macro_subject: templates.macro_subject ?? "",
    macro_body: templates.macro_body ?? "",
  };
}

function formToTemplates(values: TaskFormValues): Record<string, string> {
  const templates: Record<string, string> = {};
  const pairs: [string, string][] = [
    ["micro_subject", values.micro_subject],
    ["micro_body", values.micro_body],
    ["mid_subject", values.mid_subject],
    ["mid_body", values.mid_body],
    ["macro_subject", values.macro_subject],
    ["macro_body", values.macro_body],
  ];
  for (const [key, value] of pairs) {
    if (value.trim()) templates[key] = value.trim();
  }
  return templates;
}

function splitLines(text: string): string[] {
  return text
    .split(/[\n,，]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function isAmazonOrHttpUrl(text: string): boolean {
  return /amazon\.[a-z.]+/i.test(text) || /^https?:\/\//i.test(text);
}

function parseCompetitorFormInput(text: string): { keywords: string[]; input_urls: string[] } {
  const keywords: string[] = [];
  const input_urls: string[] = [];
  for (const line of splitLines(text)) {
    if (isAmazonOrHttpUrl(line)) {
      input_urls.push(line);
    } else {
      keywords.push(line);
    }
  }
  return { keywords, input_urls };
}

function validateForm(values: TaskFormValues, platformCapabilities: PlatformCapability[]): string | null {
  const keywords = splitLines(values.keywordsText);
  const urls = splitLines(values.inputUrlsText);

  if (!values.name.trim()) return "请填写任务名";
  if (!values.platforms.length) return "请至少选择一个采集平台";
  for (const platform of values.platforms) {
    const cap = platformCapabilities.find((item) => item.platform === platform);
    if (cap && (cap.status === "not_configured" || cap.status === "not_available")) {
      return cap.message || `${platform} 当前不可采集，请检查 Apify / API Direct 配置`;
    }
  }
  const mode =
    values.collection_mode === "comment_authors" ? "urls" : values.collection_mode;
  if ((mode === "keyword" || mode === "discovery") && keywords.length === 0) {
    return "关键词采集至少填写一个关键词";
  }
  if (mode === "category_discovery") {
    if (!values.category.trim()) return "类目采集必须填写类目";
  }
  if ((mode === "urls" || mode === "clustering") && urls.length === 0) {
    return "请至少填写一个平台主页/帖子/Reel 链接或用户名";
  }
  if (values.collection_mode === "mixed" && keywords.length === 0 && urls.length === 0) {
    return "混合模式需填写关键词或链接至少一项";
  }
  if (values.collection_mode === "competitor_product") {
    const competitor = parseCompetitorFormInput(values.competitorInputText);
    if (
      competitor.keywords.length === 0 &&
      competitor.input_urls.length === 0 &&
      !values.competitorBrandText.trim()
    ) {
      return "竞品商品发现需填写 Amazon 链接、ASIN 或商品关键词";
    }
  }
  if (values.email_enabled && splitLines(values.email_recipientsText).length === 0) {
    return "启用邮件发送时请填写收件人邮箱";
  }
  const discoveryLimit = Number(values.discovery_limit);
  if (!Number.isFinite(discoveryLimit) || discoveryLimit < 1 || discoveryLimit > 500) {
    return "采集数量上限需在 1-500 之间";
  }
  const minEngagement = Number(values.min_engagement_rate);
  if (!Number.isFinite(minEngagement) || minEngagement < 0 || minEngagement > 100) {
    return "最低互动率需在 0-100 之间";
  }
  const minFollowers = values.min_followers_count.trim();
  const maxFollowers = values.max_followers_count.trim();
  if (minFollowers) {
    const n = Number(minFollowers);
    if (!Number.isFinite(n) || n < 0 || !Number.isInteger(n)) {
      return "最低粉丝数需为非负整数";
    }
  }
  if (maxFollowers) {
    const n = Number(maxFollowers);
    if (!Number.isFinite(n) || n < 0 || !Number.isInteger(n)) {
      return "最高粉丝数需为非负整数";
    }
  }
  if (minFollowers && maxFollowers && Number(minFollowers) > Number(maxFollowers)) {
    return "最低粉丝数不能大于最高粉丝数";
  }
  return null;
}

function parseOptionalInt(text: string): number | null {
  const trimmed = text.trim();
  if (!trimmed) return null;
  return Number(trimmed);
}

export function formValuesToPayload(values: TaskFormValues): CollectionTaskPayload {
  if (values.collection_mode === "competitor_product") {
    const competitor = parseCompetitorFormInput(values.competitorInputText);
    const keywords = [...competitor.keywords];
    const input_urls = [...competitor.input_urls];
    const brand = values.competitorBrandText.trim();
    if (brand) keywords.unshift(`brand:${brand}`);
    const website = values.competitorWebsiteText.trim();
    if (website) input_urls.push(website);
    return {
      name: values.name.trim(),
      collection_mode: values.collection_mode,
      platform: values.platforms.length === 1 ? values.platforms[0] : "multi",
      platforms: values.platforms,
      keywords,
      input_urls,
      country: values.country.trim() || null,
      category: values.category.trim() || null,
      discovery_limit: Number(values.discovery_limit),
      min_engagement_rate: Number(values.min_engagement_rate),
      min_followers_count: parseOptionalInt(values.min_followers_count),
      max_followers_count: parseOptionalInt(values.max_followers_count),
      filter_include_keywords: splitLines(values.filterIncludeKeywordsText),
      filter_exclude_keywords: splitLines(values.filterExcludeKeywordsText),
      schedule_enabled: values.schedule_enabled,
      schedule_cron: values.schedule_enabled ? values.schedule_cron.trim() || null : null,
      email_enabled: values.email_enabled,
      email_recipients: values.email_enabled ? splitLines(values.email_recipientsText) : [],
      outreach_enabled: values.outreach_enabled,
      outreach_provider: values.outreach_provider,
      outreach_dry_run: values.outreach_dry_run,
      outreach_templates: formToTemplates(values),
      comment_discovery_enabled: false,
    };
  }

  return {
    name: values.name.trim(),
    collection_mode: values.collection_mode,
    platform: values.platforms.length === 1 ? values.platforms[0] : "multi",
    platforms: values.platforms,
    keywords: splitLines(values.keywordsText),
    input_urls: splitLines(values.inputUrlsText),
    country: values.country.trim() || null,
    category: values.category.trim() || null,
    discovery_limit: Number(values.discovery_limit),
    min_engagement_rate: Number(values.min_engagement_rate),
    min_followers_count: parseOptionalInt(values.min_followers_count),
    max_followers_count: parseOptionalInt(values.max_followers_count),
    filter_include_keywords: splitLines(values.filterIncludeKeywordsText),
    filter_exclude_keywords: splitLines(values.filterExcludeKeywordsText),
    schedule_enabled: values.schedule_enabled,
    schedule_cron: values.schedule_enabled ? values.schedule_cron.trim() || null : null,
    email_enabled: values.email_enabled,
    email_recipients: values.email_enabled ? splitLines(values.email_recipientsText) : [],
    outreach_enabled: values.outreach_enabled,
    outreach_provider: values.outreach_provider,
    outreach_dry_run: values.outreach_dry_run,
    outreach_templates: formToTemplates(values),
    comment_discovery_enabled: values.comment_discovery_enabled,
  };
}

export function taskToFormValues(task: CollectionTask): TaskFormValues {
  let competitorInputText = "";
  let competitorBrandText = "";
  let competitorWebsiteText = "";
  if (task.collection_mode === "competitor_product") {
    const rawKeywords = [...(task.keywords ?? [])];
    const rawUrls = [...(task.input_urls ?? [])];
    const productKeywords: string[] = [];
    for (const kw of rawKeywords) {
      if (kw.toLowerCase().startsWith("brand:")) {
        competitorBrandText = kw.split(":").slice(1).join(":").trim();
      } else {
        productKeywords.push(kw);
      }
    }
    const amazonUrls: string[] = [];
    for (const url of rawUrls) {
      if (/amazon\.[a-z.]+/i.test(url)) {
        amazonUrls.push(url);
      } else {
        competitorWebsiteText = url;
      }
    }
    competitorInputText = [...amazonUrls, ...productKeywords].join("\n");
  }

  return {
    name: task.name,
    collection_mode:
      task.collection_mode === "comment_authors" ? "urls" : (task.collection_mode ?? "discovery"),
    comment_discovery_enabled: task.comment_discovery_enabled ?? true,
    platform: task.platform,
    platforms: task.platforms?.length ? task.platforms : [task.platform || "instagram"],
    keywordsText: (task.keywords ?? []).join("\n"),
    inputUrlsText: (task.input_urls ?? []).join("\n"),
    country: task.country ?? "",
    category: task.category ?? "",
    discovery_limit: String(task.discovery_limit ?? 100),
    min_engagement_rate: String(task.min_engagement_rate ?? 1),
    min_followers_count: task.min_followers_count != null ? String(task.min_followers_count) : "",
    max_followers_count: task.max_followers_count != null ? String(task.max_followers_count) : "",
    filterIncludeKeywordsText: (task.filter_include_keywords ?? []).join("\n"),
    filterExcludeKeywordsText: (task.filter_exclude_keywords ?? []).join("\n"),
    schedule_enabled: task.schedule_enabled,
    schedule_cron: task.schedule_cron ?? "",
    email_enabled: task.email_enabled,
    email_recipientsText: (task.email_recipients ?? []).join(", "),
    outreach_enabled: task.outreach_enabled ?? false,
    outreach_provider: task.outreach_provider ?? "mailchimp",
    outreach_dry_run: task.outreach_dry_run ?? true,
    ...templatesToForm(task.outreach_templates ?? {}),
    competitorInputText,
    competitorBrandText,
    competitorWebsiteText,
  };
}

function getInitialForm(open: boolean, initialTask?: CollectionTask | null): TaskFormValues {
  if (!open) return emptyForm;
  return initialTask ? taskToFormValues(initialTask) : emptyForm;
}

type TaskFormDialogProps = {
  open: boolean;
  mode: "create" | "edit";
  initialTask?: CollectionTask | null;
  submitting: boolean;
  onClose: () => void;
  onSubmit: (payload: CollectionTaskPayload) => Promise<void>;
};

export function TaskFormDialog({
  open,
  mode,
  initialTask,
  submitting,
  onClose,
  onSubmit,
}: TaskFormDialogProps) {
  const [form, setForm] = useState<TaskFormValues>(emptyForm);
  const [error, setError] = useState<string | null>(null);
  const [platformCapabilities, setPlatformCapabilities] = useState<PlatformCapability[]>([]);
  const [platformMeta, setPlatformMeta] = useState<PlatformCapabilitiesResponse | null>(null);
  const [platformCapabilitiesLoaded, setPlatformCapabilitiesLoaded] = useState(false);
  const [platformCapabilitiesError, setPlatformCapabilitiesError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    queueMicrotask(() => {
      setError(null);
      setForm(getInitialForm(open, initialTask));
      setPlatformCapabilitiesLoaded(false);
      setPlatformCapabilitiesError(null);
      setPlatformMeta(null);
    });
    void fetchPlatformCapabilities()
      .then((data) => {
        if (cancelled) return;
        setPlatformCapabilities(data.items);
        setPlatformMeta(data);
        setPlatformCapabilitiesError(null);
      })
      .catch(() => {
        if (cancelled) return;
        setPlatformCapabilities([]);
        setPlatformCapabilitiesError("配置状态加载失败");
      })
      .finally(() => {
        if (cancelled) return;
        setPlatformCapabilitiesLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [open, initialTask]);

  if (!open) return null;

  const collectionMode =
    form.collection_mode === "comment_authors" ? "urls" : form.collection_mode;
  const showKeywords =
    collectionMode === "keyword" ||
    collectionMode === "mixed" ||
    collectionMode === "discovery" ||
    collectionMode === "category_discovery";
  const isCategoryMode = collectionMode === "category_discovery";
  const isKeywordPrimaryMode = collectionMode === "keyword" || collectionMode === "discovery";
  const showUrls =
    collectionMode === "urls" || collectionMode === "mixed" || collectionMode === "clustering";
  const showCompetitorProduct = collectionMode === "competitor_product";

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);

    const validationError = validateForm(form, platformCapabilities);
    if (validationError) {
      setError(validationError);
      return;
    }

    try {
      await onSubmit(formValuesToPayload(form));
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败");
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-xl border bg-background shadow-lg">
        <div className="flex items-center justify-between border-b px-6 py-4">
          <div>
            <h2 className="text-lg font-semibold">
              {mode === "create" ? "创建采集任务" : "编辑采集任务"}
            </h2>
            <p className="text-sm text-muted-foreground">配置采集模式、平台、关键词/链接与邮件通知</p>
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
              <Label htmlFor="name">任务名</Label>
              <Input
                id="name"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                placeholder="例如：美国健身类 Instagram 红人"
              />
            </div>

            <div className="space-y-2 sm:col-span-2">
              <Label htmlFor="collection_mode">采集模式</Label>
              <select
                id="collection_mode"
                value={collectionMode}
                onChange={(e) => {
                  const nextMode = e.target.value as CollectionMode;
                  setForm((prev) => ({
                    ...prev,
                    collection_mode: nextMode,
                    comment_discovery_enabled:
                      nextMode === "competitor_product" ? false : prev.comment_discovery_enabled,
                    min_followers_count:
                      prev.platforms.includes("instagram") && !prev.min_followers_count.trim()
                        ? "30000"
                        : prev.min_followers_count,
                  }));
                }}
                className={cn(
                  "flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                )}
              >
                {COLLECTION_MODE_OPTIONS.map((m) => (
                  <option key={m.value} value={m.value}>
                    {m.label}
                  </option>
                ))}
              </select>
              <p className="text-xs text-muted-foreground">
                {COLLECTION_MODE_OPTIONS.find((m) => m.value === collectionMode)?.hint}
              </p>
            </div>

            {!showCompetitorProduct ? (
              <div className="space-y-2 sm:col-span-2 rounded-lg border bg-muted/30 px-4 py-3">
                <label className="flex cursor-pointer items-start gap-3">
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={form.comment_discovery_enabled}
                    onChange={(e) =>
                      setForm({ ...form, comment_discovery_enabled: e.target.checked })
                    }
                  />
                  <span>
                    <span className="text-sm font-medium">自动抓取帖子/Reels 评论区用户</span>
                    <span className="mt-1 block text-xs text-muted-foreground">
                      系统在关键词、hashtag、主页链接、帖子/Reel 链接采集时自动尝试抓取评论区用户，用于扩大候选红人池。评论 API
                      失败不会导致整任务失败。
                    </span>
                  </span>
                </label>
              </div>
            ) : (
              <div className="space-y-2 sm:col-span-2 rounded-lg border border-dashed bg-muted/20 px-4 py-3 text-xs text-muted-foreground">
                竞品商品发现模式默认不抓取评论区用户，仅根据 hashtag 搜索到的帖子 caption 匹配疑似推广账号。
              </div>
            )}

            <div className="space-y-2 sm:col-span-2">
              <Label>采集平台（可多选）</Label>
              <div className="grid gap-2 sm:grid-cols-2">
                {Object.entries(PLATFORM_LABELS)
                  .filter(([value]) => value !== "multi")
                  .map(([value, label]) => {
                    const cap = platformCapabilities.find((item) => item.platform === value);
                    const checked = form.platforms.includes(value);
                    const statusLabel = !platformCapabilitiesLoaded
                      ? "加载中…"
                      : platformCapabilitiesError ??
                        formatPlatformCapabilityHint(
                          cap,
                          PLATFORM_CAPABILITY_STATUS_LABELS[cap?.status ?? ""] ?? "配置状态加载失败",
                        );
                    return (
                      <label
                        key={value}
                        className={cn(
                          "flex cursor-pointer items-start gap-3 rounded-lg border px-3 py-2",
                          checked ? "border-primary bg-primary/5" : "bg-background",
                        )}
                      >
                        <input
                          type="checkbox"
                          className="mt-1"
                          checked={checked}
                          onChange={(e) => {
                            setForm((prev) => {
                              const next = e.target.checked
                                ? [...prev.platforms, value]
                                : prev.platforms.filter((p) => p !== value);
                              return {
                                ...prev,
                                platforms: next,
                                platform: next.length === 1 ? next[0] : "multi",
                              };
                            });
                          }}
                        />
                        <span>
                          <span className="text-sm font-medium">{label}</span>
                          <span className="mt-1 block text-xs text-muted-foreground">
                            {statusLabel}
                          </span>
                        </span>
                      </label>
                    );
                  })}
              </div>
              <p className="text-xs text-muted-foreground">
                {platformMeta
                  ? `${formatCollectionSourceSummary(platformMeta)}；Pinterest / LTK / ShopMy 支持 URL 导入。`
                  : "Instagram / YouTube / TikTok / Facebook 默认 Apify；Pinterest / LTK / ShopMy 支持 URL 导入。"}
                {form.platforms.includes("youtube") ? (
                  <span className="mt-1 block">
                    YouTube：默认走 Apify YouTube Scraper（关键词搜索 + 频道外链）；About 缺失时仍会公开页补采。
                    遇限流会自动降速重试。采集上限表示目标合格入库数量。
                  </span>
                ) : null}
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="country">国家</Label>
              <Input
                id="country"
                value={form.country}
                onChange={(e) => setForm({ ...form, country: e.target.value })}
                placeholder="US / UK / JP"
              />
            </div>

            <div className="space-y-2 sm:col-span-2">
              <Label htmlFor="category">
                类目
                {isCategoryMode ? <span className="text-destructive"> *</span> : null}
              </Label>
              <Input
                id="category"
                value={form.category}
                onChange={(e) => setForm({ ...form, category: e.target.value })}
                placeholder={isCategoryMode ? "美妆 / 科技 / 旅行（必填）" : "美妆 / 科技 / 旅行（可选，用于评分偏好）"}
              />
              {isCategoryMode ? (
                <p className="text-xs text-muted-foreground">
                  系统将按所选平台自动扩展类目关键词与链接种子，再进入发现与入库流程。
                </p>
              ) : null}
            </div>

            <div className="space-y-2">
              <Label htmlFor="discovery_limit">采集数量上限</Label>
              <Input
                id="discovery_limit"
                type="number"
                min={1}
                max={500}
                value={form.discovery_limit}
                onChange={(e) => setForm({ ...form, discovery_limit: e.target.value })}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="min_engagement_rate">最低互动率 (%)</Label>
              <Input
                id="min_engagement_rate"
                type="number"
                min={0}
                max={100}
                step="0.1"
                value={form.min_engagement_rate}
                onChange={(e) => setForm({ ...form, min_engagement_rate: e.target.value })}
              />
            </div>

            <div className="space-y-2 sm:col-span-2">
              <p className="text-sm font-medium">筛选与评分说明</p>
              <p className="text-xs text-muted-foreground">
                {form.platforms.includes("instagram")
                  ? "Instagram 最低粉丝硬门槛为 3 万（填更低仍按 3 万执行，可填更高如 5 万）。"
                  : "YouTube / TikTok 按你填的「最低粉丝数」硬过滤（建议 1 万～5 万，关键词用 amazon finds creator 这类精准词更容易出大号）。"}
                最高粉丝数、最低互动率、偏好包含关键词为软偏好，用于排序与评分。
                「排除关键词」会直接丢弃账号（匹配简介、昵称、近期标题等文本）。
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="min_followers_count">最低粉丝数</Label>
              <Input
                id="min_followers_count"
                type="number"
                min={0}
                step={1}
                value={form.min_followers_count}
                onChange={(e) => setForm({ ...form, min_followers_count: e.target.value })}
                placeholder={
                  form.platforms.includes("instagram")
                    ? "至少 30000，可填更高如 50000"
                    : "建议 10000～50000"
                }
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="max_followers_count">最高粉丝数</Label>
              <Input
                id="max_followers_count"
                type="number"
                min={0}
                step={1}
                value={form.max_followers_count}
                onChange={(e) => setForm({ ...form, max_followers_count: e.target.value })}
                placeholder="例如 500000，留空不限制"
              />
            </div>

            <div className="space-y-2 sm:col-span-2">
              <Label htmlFor="filter_include_keywords">偏好包含关键词（每行一个，用于评分，不阻止入库）</Label>
              <Textarea
                id="filter_include_keywords"
                value={form.filterIncludeKeywordsText}
                onChange={(e) => setForm({ ...form, filterIncludeKeywordsText: e.target.value })}
                placeholder={"brand deal\ncollab\namazon"}
                rows={3}
              />
            </div>

            <div className="space-y-2 sm:col-span-2">
              <Label htmlFor="filter_exclude_keywords">排除关键词（每行一个，命中任一即丢弃）</Label>
              <Textarea
                id="filter_exclude_keywords"
                value={form.filterExcludeKeywordsText}
                onChange={(e) => setForm({ ...form, filterExcludeKeywordsText: e.target.value })}
                placeholder={"giveaway\nfan page\nmeme"}
                rows={3}
              />
            </div>

            {showCompetitorProduct ? (
              <>
                <div className="space-y-2 sm:col-span-2">
                  <Label htmlFor="competitor_input">商品链接 / ASIN / 关键词</Label>
                  <Textarea
                    id="competitor_input"
                    value={form.competitorInputText}
                    onChange={(e) => setForm({ ...form, competitorInputText: e.target.value })}
                    placeholder={
                      "https://www.amazon.com/dp/B0XXXXXXX/\nB0XXXXXXX\nwireless earbuds\nportable fan"
                    }
                    rows={4}
                  />
                  <p className="text-xs text-muted-foreground">
                    支持 Amazon 商品链接、ASIN、商品关键词；系统会自动扩展 amazonfinds 等 hashtag，并在 caption 中匹配品牌/关键词/ASIN/Amazon 相关词。
                  </p>
                </div>
                <div className="space-y-2">
                  <Label htmlFor="competitor_brand">品牌名（可选）</Label>
                  <Input
                    id="competitor_brand"
                    value={form.competitorBrandText}
                    onChange={(e) => setForm({ ...form, competitorBrandText: e.target.value })}
                    placeholder="Anker"
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="competitor_website">竞品官网/落地页（可选）</Label>
                  <Input
                    id="competitor_website"
                    value={form.competitorWebsiteText}
                    onChange={(e) => setForm({ ...form, competitorWebsiteText: e.target.value })}
                    placeholder="https://www.example.com/product"
                  />
                </div>
              </>
            ) : null}

            {showKeywords ? (
              <div className="space-y-2 sm:col-span-2">
                <Label htmlFor="keywords">
                  {isCategoryMode
                    ? "补充关键词（可选，每行一个）"
                    : isKeywordPrimaryMode && form.collection_mode === "discovery"
                      ? "Hashtag 标签（每行一个）"
                      : "关键词（每行一个，或用逗号分隔）"}
                  {isKeywordPrimaryMode ? <span className="text-destructive"> *</span> : null}
                </Label>
                <Textarea
                  id="keywords"
                  value={form.keywordsText}
                  onChange={(e) => setForm({ ...form, keywordsText: e.target.value })}
                  placeholder={
                    isCategoryMode
                      ? "可持续补充偏好词，例如：amazon storefront\naffiliate"
                      : form.collection_mode === "discovery"
                        ? "amazon finds creator\namazon home finds"
                        : "amazon finds creator\namazon home finds"
                  }
                  rows={4}
                />
              </div>
            ) : null}

            {showUrls ? (
              <div className="space-y-2 sm:col-span-2">
                <Label htmlFor="input_urls">Instagram 链接或用户名（每行一个）</Label>
                <Textarea
                  id="input_urls"
                  value={form.inputUrlsText}
                  onChange={(e) => setForm({ ...form, inputUrlsText: e.target.value })}
                  placeholder={
                    "https://www.instagram.com/creator/\nhttps://www.instagram.com/p/ABC123/\nhttps://www.instagram.com/reel/XYZ/\n@username"
                  }
                  rows={4}
                />
                <p className="text-xs text-muted-foreground">
                  自动识别主页、帖子、Reel；主页会先取近期帖子再扫评论。粉丝 &lt; 3 万不入库。
                </p>
              </div>
            ) : null}
          </div>

          <div className="space-y-4 rounded-lg border p-4">
            <label className="flex items-center gap-2 text-sm font-medium">
              <input
                type="checkbox"
                checked={form.schedule_enabled}
                onChange={(e) => setForm({ ...form, schedule_enabled: e.target.checked })}
              />
              启用定时任务
            </label>
            {form.schedule_enabled ? (
              <div className="space-y-2">
                <Label htmlFor="schedule_cron">定时规则（Cron 表达式）</Label>
                <Input
                  id="schedule_cron"
                  value={form.schedule_cron}
                  onChange={(e) => setForm({ ...form, schedule_cron: e.target.value })}
                  placeholder="0 9 * * 1"
                />
              </div>
            ) : null}
          </div>

          <div className="space-y-4 rounded-lg border p-4">
            <label className="flex items-center gap-2 text-sm font-medium">
              <input
                type="checkbox"
                checked={form.email_enabled}
                onChange={(e) => setForm({ ...form, email_enabled: e.target.checked })}
              />
              采集完成后发送邮件
            </label>
            {form.email_enabled ? (
              <div className="space-y-2">
                <Label htmlFor="email_recipients">收件人邮箱（逗号分隔）</Label>
                <Input
                  id="email_recipients"
                  value={form.email_recipientsText}
                  onChange={(e) => setForm({ ...form, email_recipientsText: e.target.value })}
                  placeholder="ops@example.com, marketing@example.com"
                />
              </div>
            ) : null}
          </div>

          <div className="space-y-4 rounded-lg border p-4">
            <label className="flex items-center gap-2 text-sm font-medium">
              <input
                type="checkbox"
                checked={form.outreach_enabled}
                onChange={(e) => setForm({ ...form, outreach_enabled: e.target.checked })}
              />
              启用外联同步
            </label>
            {form.outreach_enabled ? (
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="outreach_provider">外联渠道</Label>
                  <select
                    id="outreach_provider"
                    value={form.outreach_provider}
                    onChange={(e) => setForm({ ...form, outreach_provider: e.target.value })}
                    className={cn(
                      "flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    )}
                  >
                    <option value="mailchimp">Mailchimp 受众同步</option>
                    <option value="smtp">SMTP 直发邮件</option>
                  </select>
                </div>
                <div className="flex items-end">
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={form.outreach_dry_run}
                      onChange={(e) => setForm({ ...form, outreach_dry_run: e.target.checked })}
                    />
                    试跑模式（仅记录，不同步）
                  </label>
                </div>
                <p className="sm:col-span-2 text-xs text-muted-foreground">
                  Mailchimp 同步使用公开邮箱；新联系人默认待确认（需对方同意），已退订的会跳过。
                </p>
                <div className="space-y-2 sm:col-span-2">
                  <Label>邮件模板 · 小微红人（&lt;1万粉）</Label>
                  <Input
                    value={form.micro_subject}
                    onChange={(e) => setForm({ ...form, micro_subject: e.target.value })}
                    placeholder="邮件主题"
                  />
                  <Textarea
                    value={form.micro_body}
                    onChange={(e) => setForm({ ...form, micro_body: e.target.value })}
                    placeholder="邮件正文，可用 {name} {username} {platform} {followers}"
                    rows={2}
                  />
                </div>
                <div className="space-y-2 sm:col-span-2">
                  <Label>邮件模板 · 中型红人（1万-10万粉）</Label>
                  <Input
                    value={form.mid_subject}
                    onChange={(e) => setForm({ ...form, mid_subject: e.target.value })}
                    placeholder="邮件主题"
                  />
                  <Textarea
                    value={form.mid_body}
                    onChange={(e) => setForm({ ...form, mid_body: e.target.value })}
                    placeholder="邮件正文"
                    rows={2}
                  />
                </div>
                <div className="space-y-2 sm:col-span-2">
                  <Label>邮件模板 · 头部红人（≥10万粉）</Label>
                  <Input
                    value={form.macro_subject}
                    onChange={(e) => setForm({ ...form, macro_subject: e.target.value })}
                    placeholder="邮件主题"
                  />
                  <Textarea
                    value={form.macro_body}
                    onChange={(e) => setForm({ ...form, macro_body: e.target.value })}
                    placeholder="邮件正文"
                    rows={2}
                  />
                </div>
              </div>
            ) : null}
          </div>

          <div className="flex justify-end gap-3 border-t pt-4">
            <Button type="button" variant="outline" onClick={onClose} disabled={submitting}>
              取消
            </Button>
            <Button type="submit" disabled={submitting}>
              {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              {mode === "create" ? "创建任务" : "保存修改"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
