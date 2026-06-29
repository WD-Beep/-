"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, Check, HelpCircle, Loader2, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { CollectionMode, CollectionTask, CollectionTaskPayload, PlatformCapability, TaskSourceMethod } from "@/lib/api";
import { fetchPlatformCapabilities } from "@/lib/api";
import { formatLinkImportPlatformHints, parseLinkImportPreview } from "@/lib/collection-sources";
import { COLLECTION_MODE_OPTIONS, KEYWORD_DISCOVERY_PLATFORMS, KEYWORD_SEED_DISCOVERY_PLATFORMS, LINK_IMPORT_URL_EXAMPLES, LINK_IMPORT_USAGE_LINES, LINK_ONLY_PENDING_KEYWORD_HINT, LINK_ONLY_PLATFORM_CARD_LINES, PLATFORM_LABELS, SEED_DISCOVERY_PLATFORMS, URL_ONLY_PLATFORMS, VERIFIED_KEYWORD_PLATFORM_HINT } from "@/lib/labels";
import {
  advancedFilterSummary,
  applyStableCollectionMode,
  clearStableCollectionMode,
  applyDiscoverySource,
  createEmptyTaskForm,
  discoverySourceFromForm,
  formValuesToPayload,
  getInitialForm,
  hasAdvancedSettings,
  isKeywordDiscoveryPlatform,
  isKeywordPlatformSelectable,
  isLinkImportTaskForm,
  saveFormTemplate,
  suggestTaskName,
  toggleKeywordPlatformSelection,
  toggleSeedPlatformSelection,
  validateForm,
  type DiscoverySource,
  type TaskFormValues,
} from "@/lib/task-form-payload";
import { cn } from "@/lib/utils";

const DISCOVERY_SOURCE_OPTIONS: { value: DiscoverySource; label: string; hint: string }[] = [
  { value: "keyword_hashtag", label: "关键词 / Hashtag", hint: "按关键词或 hashtag 搜索红人" },
  { value: "link_import", label: "链接导入", hint: "粘贴主页、商品或 Pin 链接" },
  { value: "multi_platform_auto", label: "多平台自动发现", hint: "同时在多个平台按 hashtag 发现" },
  {
    value: "shopping_seed_auto",
    label: "导购 seed 自动发现",
    hint: "输入主题 / 品牌 / 商品词 / ASIN / Amazon 线索，先找 LTK / ShopMy / Pinterest seed 链接，再批量采集补全",
  },
];

const FILTER_RULES_HELP = [
  "粉丝数和互动率用于筛选候选红人；开启「仅入库达标」后，未达标账号会进入候选池但不写入红人库。",
  "要求邮箱 / 联系方式会检查邮箱、官网、Linktree、ShopMy、LTK、Amazon 店铺等可联系入口。",
  "联系方式尚未补采完成时会标记为「待补采」，不会因此误判为低价值。",
  "严格模式：不符合条件的账号直接过滤，不会入库。",
  "偏好关键词只影响评分排序；开启仅入库/严格模式后才会阻止入库。",
  "排除关键词命中后会直接丢弃账号。",
];

export type { TaskFormValues } from "@/lib/task-form-payload";

function platformCardMeta(
  platform: string,
  cap: PlatformCapability | undefined,
  loaded: boolean,
  loadError: string | null,
  keywordSelectable: boolean,
): { statusLabel: string; disabled: boolean; hint: string } {
  if (!loaded) {
    return { statusLabel: "加载中", disabled: true, hint: "" };
  }
  if (loadError) {
    return { statusLabel: "未知", disabled: true, hint: "" };
  }
  if ((KEYWORD_SEED_DISCOVERY_PLATFORMS as readonly string[]).includes(platform)) {
    return {
      statusLabel: "seed 自动发现",
      disabled: false,
      hint: cap?.link_import_hint || LINK_ONLY_PENDING_KEYWORD_HINT,
    };
  }
  if (!keywordSelectable) {
    return {
      statusLabel: "链接补全 / 外链发现",
      disabled: true,
      hint: LINK_ONLY_PENDING_KEYWORD_HINT,
    };
  }
  if (!cap) {
    return {
      statusLabel: "未配置",
      disabled: true,
      hint: VERIFIED_KEYWORD_PLATFORM_HINT,
    };
  }
  if (cap.status === "not_configured" || cap.status === "not_available") {
    return {
      statusLabel: cap.status === "not_configured" ? "未配置" : "不可用",
      disabled: true,
      hint: cap.message || VERIFIED_KEYWORD_PLATFORM_HINT,
    };
  }
  return {
    statusLabel: cap.status === "supported" ? "已配置" : "可采集",
    disabled: false,
    hint: VERIFIED_KEYWORD_PLATFORM_HINT,
  };
}

function PlatformSelectionCard({
  platform,
  checked,
  meta,
  onToggle,
}: {
  platform: string;
  checked: boolean;
  meta: { statusLabel: string; disabled: boolean; hint: string };
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      disabled={meta.disabled}
      onClick={onToggle}
      aria-pressed={checked}
      className={cn(
        "relative rounded-md border px-3 py-2 text-left transition-colors",
        checked ? "border-primary bg-primary/10 ring-2 ring-primary/30" : "hover:bg-muted/40",
        meta.disabled && "cursor-not-allowed opacity-60",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <span className="block text-sm font-medium">{PLATFORM_LABELS[platform] ?? platform}</span>
          <span className="mt-0.5 block text-[10px] text-muted-foreground">{meta.hint}</span>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          <span
            className={cn(
              "text-[10px]",
              meta.statusLabel === "已配置" ||
                meta.statusLabel === "可采集" ||
                meta.statusLabel === "seed 自动发现"
                ? "text-emerald-600"
                : "text-muted-foreground",
            )}
          >
            {meta.statusLabel}
          </span>
          {checked ? <Check className="h-3.5 w-3.5 text-primary" aria-hidden /> : null}
        </div>
      </div>
    </button>
  );
}

function PendingPlatformCard({
  platform,
  cap,
}: {
  platform: string;
  cap: PlatformCapability | undefined;
}) {
  return (
    <div
      className="rounded-md border border-dashed bg-muted/20 px-3 py-2"
      aria-disabled="true"
      title={LINK_ONLY_PLATFORM_CARD_LINES.join("；")}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <span className="block text-sm font-medium">{PLATFORM_LABELS[platform] ?? platform}</span>
          <ul className="mt-1.5 space-y-0.5 text-[10px] text-muted-foreground">
            {LINK_ONLY_PLATFORM_CARD_LINES.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </div>
        <span className="shrink-0 rounded bg-amber-100 px-1.5 py-0.5 text-[10px] text-amber-800">
          不可关键词采集
        </span>
      </div>
      {cap?.link_import_hint ? (
        <p className="mt-2 text-[10px] text-muted-foreground">
          能力说明：{cap.link_import_hint}
        </p>
      ) : null}
    </div>
  );
}

type TaskFormDialogProps = {
  open: boolean;
  mode: "create" | "edit";
  initialTask?: CollectionTask | null;
  defaultSourceMethod?: TaskSourceMethod;
  submitting: boolean;
  onClose: () => void;
  onSubmit: (payload: CollectionTaskPayload) => Promise<void>;
};

export function TaskFormDialog({
  open,
  mode,
  initialTask,
  defaultSourceMethod = "keyword_discovery",
  submitting,
  onClose,
  onSubmit,
}: TaskFormDialogProps) {
  const [form, setForm] = useState<TaskFormValues>(createEmptyTaskForm);
  const [error, setError] = useState<string | null>(null);
  const [platformCapabilities, setPlatformCapabilities] = useState<PlatformCapability[]>([]);
  const [platformCapabilitiesLoaded, setPlatformCapabilitiesLoaded] = useState(false);
  const [platformCapabilitiesError, setPlatformCapabilitiesError] = useState<string | null>(null);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [automationOpen, setAutomationOpen] = useState(false);
  const [filterHelpOpen, setFilterHelpOpen] = useState(false);
  const [nameTouched, setNameTouched] = useState(false);
  const dialogRef = useRef<HTMLDivElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const titleId = "task-form-dialog-title";
  const descriptionId = "task-form-dialog-description";

  useEffect(() => {
    if (!open) return;
    previousFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const focusTimer = window.setTimeout(() => {
      dialogRef.current?.focus();
    }, 0);
    return () => {
      window.clearTimeout(focusTimer);
      previousFocusRef.current?.focus();
    };
  }, [open]);

  useEffect(() => {
    if (!open || submitting) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, submitting, onClose]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    queueMicrotask(() => {
      setError(null);
      const initial = getInitialForm(open, initialTask, defaultSourceMethod);
      setForm(initial);
      setNameTouched(Boolean(initialTask?.name));
      setAdvancedOpen(Boolean(initialTask && hasAdvancedSettings(initial)));
      setAutomationOpen(Boolean(initialTask && (initial.schedule_enabled || initial.email_enabled || initial.outreach_enabled)));
      setFilterHelpOpen(false);
      setPlatformCapabilitiesLoaded(false);
      setPlatformCapabilitiesError(null);
    });
    void fetchPlatformCapabilities()
      .then((data) => {
        if (cancelled) return;
        setPlatformCapabilities(data.items);
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
  }, [open, initialTask, defaultSourceMethod]);

  const isLinkImport = isLinkImportTaskForm(form);
  const discoverySource = discoverySourceFromForm(form);
  const linkImportPreview = useMemo(
    () => (isLinkImport && open ? parseLinkImportPreview(form.inputUrlsText) : null),
    [form.inputUrlsText, isLinkImport, open],
  );
  const validationError = useMemo(
    () => validateForm(form, platformCapabilities),
    [form, platformCapabilities],
  );
  const advancedSummary = useMemo(() => advancedFilterSummary(form), [form]);
  const linkImportHintGroups = useMemo(
    () => formatLinkImportPlatformHints(platformCapabilities),
    [platformCapabilities],
  );

  const suggestedName = useMemo(
    () => (nameTouched || form.name.trim() ? "" : suggestTaskName(form)),
    [form, nameTouched],
  );

  if (!open) return null;

  const collectionMode =
    form.collection_mode === "comment_authors" ? "urls" : form.collection_mode;
  const showKeywordsField =
    !isLinkImport &&
    (collectionMode === "keyword" ||
      collectionMode === "mixed" ||
      collectionMode === "discovery" ||
      collectionMode === "category_discovery" ||
      collectionMode === "link_seed_discovery");
  const showSeedDiscovery = !isLinkImport && collectionMode === "link_seed_discovery";
  const showCompetitorProduct = !isLinkImport && collectionMode === "competitor_product";
  const showShoppingSeedProductInput = showCompetitorProduct || showSeedDiscovery;
  const showLegacyUrls =
    !isLinkImport &&
    (collectionMode === "urls" || collectionMode === "mixed" || collectionMode === "clustering");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (validationError) {
      setError(validationError);
      return;
    }
    try {
      await onSubmit(formValuesToPayload(form, platformCapabilities));
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败");
    }
  }

  function handleSaveTemplate() {
    saveFormTemplate(form);
    setError(null);
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-3 sm:p-4">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        tabIndex={-1}
        className="flex max-h-[92vh] w-full max-w-2xl flex-col overflow-hidden rounded-xl border bg-background shadow-lg outline-none"
      >
        <div className="flex shrink-0 items-start justify-between gap-3 border-b px-5 py-4 sm:px-6">
          <div className="min-w-0">
            <h2 id={titleId} className="text-lg font-semibold">
              {mode === "create" ? "创建采集任务" : "编辑采集任务"}
            </h2>
            <p id={descriptionId} className="mt-1 text-sm text-muted-foreground">
              {mode === "create"
                ? "选择平台和关键词，系统会自动发现匹配红人"
                : "修改任务配置后保存"}
            </p>
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="shrink-0"
            onClick={onClose}
            disabled={submitting}
            aria-label="关闭"
          >
            <X className="h-4 w-4" />
          </Button>
        </div>

        <form onSubmit={handleSubmit} className="flex min-h-0 flex-1 flex-col">
          <div className="min-h-0 flex-1 space-y-6 overflow-y-auto px-5 py-5 sm:px-6">
            {error ? (
              <div className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
                {error}
              </div>
            ) : null}

            <section className="space-y-4">
              <div className="flex items-center justify-between gap-2">
                <h3 className="text-sm font-medium">基础配置</h3>
                <span className="text-xs text-muted-foreground">必填</span>
              </div>

              <div className="space-y-2">
                <Label htmlFor="name">任务名</Label>
                <Input
                  id="name"
                  value={form.name}
                  onChange={(e) => {
                    setNameTouched(true);
                    setForm({ ...form, name: e.target.value });
                  }}
                  placeholder={suggestedName || "将根据关键词自动生成"}
                />
                {suggestedName ? (
                  <p className="text-xs text-muted-foreground">未填写时将使用：{suggestedName}</p>
                ) : null}
              </div>

              <div className="space-y-2">
                <Label>发现来源</Label>
                <div className="grid gap-2 sm:grid-cols-3">
                  {DISCOVERY_SOURCE_OPTIONS.map((option) => {
                    const active = discoverySource === option.value;
                    return (
                      <button
                        key={option.value}
                        type="button"
                        disabled={mode === "edit"}
                        onClick={() =>
                          setForm((prev) => applyDiscoverySource(option.value, prev, platformCapabilities))
                        }
                        className={cn(
                          "rounded-md border px-3 py-2 text-left transition-colors",
                          active ? "border-primary bg-primary/5" : "hover:bg-muted/40",
                          mode === "edit" && !active && "opacity-60",
                        )}
                      >
                        <span className="block text-sm font-medium">{option.label}</span>
                        <span className="mt-0.5 block text-xs text-muted-foreground">{option.hint}</span>
                      </button>
                    );
                  })}
                </div>
              </div>

              {!isLinkImport ? (
                <label className="flex items-start gap-3 rounded-md border bg-muted/20 px-3 py-2 text-sm">
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={form.stable_collection_mode}
                    onChange={(e) =>
                      setForm((prev) =>
                        e.target.checked ? applyStableCollectionMode(prev) : clearStableCollectionMode(prev),
                      )
                    }
                  />
                  <span>
                    <span className="font-medium">稳定采集模式</span>
                    <span className="mt-0.5 block text-xs text-muted-foreground">
                      稳定模式会慢一点，但结果更稳定；默认采集 20 个候选，放宽联系方式要求，并优先单平台运行。
                    </span>
                  </span>
                </label>
              ) : null}

              {!isLinkImport ? (
                <div className="space-y-4">
                  {showSeedDiscovery ? (
                    <div className="space-y-2">
                      <Label>导购 seed 来源平台</Label>
                      <p className="text-xs text-muted-foreground">
                        选择要自动发现的导购 seed 平台（LTK / ShopMy / Pinterest）。系统会按主题找 seed 链接，再批量采集并补全到 Instagram / TikTok / YouTube / Facebook 社媒主页。
                      </p>
                      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                        {SEED_DISCOVERY_PLATFORMS.map((value) => {
                          const checked = form.platforms.includes(value);
                          return (
                            <PlatformSelectionCard
                              key={value}
                              platform={value}
                              checked={checked}
                              meta={{
                                statusLabel: "外链发现",
                                disabled: false,
                                hint: "通过社媒搜索发现真实主页链接",
                              }}
                              onToggle={() =>
                                setForm((prev) => toggleSeedPlatformSelection(prev, value))
                              }
                            />
                          );
                        })}
                      </div>
                    </div>
                  ) : (
                    <>
                  <div className="space-y-2">
                    <Label>采集平台</Label>
                    <p className="text-xs text-muted-foreground">
                      请明确选择要采集的平台。多平台同时采集成功率可能较低，建议按需勾选。
                    </p>
                  </div>

                  <div className="space-y-2">
                    <p className="text-xs font-medium text-foreground">主动关键词采集平台</p>
                    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                      {KEYWORD_DISCOVERY_PLATFORMS.map((value) => {
                        const cap = platformCapabilities.find((item) => item.platform === value);
                        const checked = form.platforms.includes(value);
                        const keywordSelectable = isKeywordPlatformSelectable(value, cap);
                        const meta = platformCardMeta(
                          value,
                          cap,
                          platformCapabilitiesLoaded,
                          platformCapabilitiesError,
                          keywordSelectable,
                        );
                        return (
                          <PlatformSelectionCard
                            key={value}
                            platform={value}
                            checked={checked}
                            meta={meta}
                            onToggle={() =>
                              setForm((prev) => toggleKeywordPlatformSelection(prev, value, platformCapabilities))
                            }
                          />
                        );
                      })}
                    </div>
                  </div>

                  <div className="space-y-2">
                    <p className="text-xs font-medium text-foreground">链接补全 / 外链发现平台</p>
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                      {URL_ONLY_PLATFORMS.filter(
                        (value) => !(KEYWORD_DISCOVERY_PLATFORMS as readonly string[]).includes(value),
                      ).map((value) => {
                        const cap = platformCapabilities.find((item) => item.platform === value);
                        const keywordAllowed = isKeywordDiscoveryPlatform(value, cap);
                        if (keywordAllowed) {
                          const checked = form.platforms.includes(value);
                          const meta = platformCardMeta(
                            value,
                            cap,
                            platformCapabilitiesLoaded,
                            platformCapabilitiesError,
                            true,
                          );
                          return (
                            <PlatformSelectionCard
                              key={value}
                              platform={value}
                              checked={checked}
                              meta={meta}
                              onToggle={() =>
                                setForm((prev) => toggleKeywordPlatformSelection(prev, value, platformCapabilities))
                              }
                            />
                          );
                        }
                        return <PendingPlatformCard key={value} platform={value} cap={cap} />;
                      })}
                    </div>
                    <p className="text-xs text-muted-foreground">
                      以下平台不支持完整站内关键词直采；可使用「导购 seed 自动发现」批量发现入口，也可用「链接导入」定向补全资料。
                    </p>
                  </div>
                    </>
                  )}
                </div>
              ) : null}

              {isLinkImport ? (
                <div className="space-y-3">
                  <div className="space-y-2">
                    <Label>支持链接导入的平台</Label>
                    <ul className="list-disc space-y-1 pl-5 text-xs text-muted-foreground">
                      {LINK_IMPORT_USAGE_LINES.map((line) => (
                        <li key={line}>{line}</li>
                      ))}
                    </ul>
                    <div className="rounded-md border border-dashed bg-muted/20 px-3 py-2">
                      <p className="text-xs font-medium text-foreground">链接示例（粘贴对应平台 URL 即可，无需手选平台）</p>
                      <ul className="mt-1.5 space-y-1 text-[11px] text-muted-foreground">
                        {LINK_IMPORT_URL_EXAMPLES.map((item) => (
                          <li key={item.platform}>
                            <span className="font-medium text-foreground/80">{item.platform}：</span>
                            <span className="break-all">{item.url}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                    {linkImportHintGroups.length > 0 ? (
                      <div className="space-y-2 rounded-md bg-muted/30 px-3 py-2">
                        {linkImportHintGroups.map((group) => (
                          <div key={group.title}>
                            <p className="text-xs font-medium text-foreground">{group.title}</p>
                            <ul className="mt-1 space-y-0.5 text-xs text-muted-foreground">
                              {group.items.map((item) => (
                                <li key={item}>{item}</li>
                              ))}
                            </ul>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="text-xs text-muted-foreground">加载平台说明中…</p>
                    )}
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="link_import_urls">粘贴链接</Label>
                    <Textarea
                      id="link_import_urls"
                      value={form.inputUrlsText}
                      onChange={(e) => setForm({ ...form, inputUrlsText: e.target.value })}
                      rows={6}
                      placeholder={"每行一条链接，支持 Instagram / YouTube / TikTok / Facebook / Pinterest / LTK / ShopMy / Amazon"}
                    />
                    {linkImportPreview &&
                    (linkImportPreview.recognizedLines.length > 0 || linkImportPreview.invalidCount > 0) ? (
                      <div className="space-y-1 rounded-md bg-muted/30 px-3 py-2 text-xs">
                        {linkImportPreview.recognizedLines.map((line) => (
                          <p key={line} className="text-foreground/80">
                            {line}
                          </p>
                        ))}
                        {linkImportPreview.invalidLines.map((line) => (
                          <p key={line} className="text-destructive">
                            {line}
                          </p>
                        ))}
                        {linkImportPreview.mixedAmazonAndProfiles ? (
                          <p className="text-destructive">Amazon 商品链接请单独建任务。</p>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                </div>
              ) : showShoppingSeedProductInput ? (
                <div className="space-y-2">
                  <Label htmlFor="competitor_input">主题 / 品牌 / 商品词 / ASIN / Amazon URL</Label>
                  <Textarea
                    id="competitor_input"
                    value={form.competitorInputText}
                    onChange={(e) => setForm({ ...form, competitorInputText: e.target.value })}
                    rows={4}
                    placeholder={"home decor finds\nHOMEHIVE jewelry storage bags\nB0XXXXXXX\nhttps://www.amazon.com/dp/B0XXXXXXX/"}
                  />
                </div>
              ) : showKeywordsField ? (
                <div className="space-y-2">
                  <Label htmlFor="keywords">
                    {collectionMode === "discovery"
                      ? "Hashtag / 关键词"
                      : collectionMode === "link_seed_discovery"
                        ? "关键词（可选，与类目至少填一项）"
                        : "关键词"}
                    {collectionMode !== "link_seed_discovery" ? (
                      <span className="text-destructive"> *</span>
                    ) : null}
                  </Label>
                  <Textarea
                    id="keywords"
                    value={form.keywordsText}
                    onChange={(e) => setForm({ ...form, keywordsText: e.target.value })}
                    rows={4}
                    placeholder={"amazon finds creator\namazon home finds"}
                  />
                </div>
              ) : showLegacyUrls ? (
                <div className="space-y-2">
                  <Label htmlFor="input_urls">主页 / 帖子链接</Label>
                  <Textarea
                    id="input_urls"
                    value={form.inputUrlsText}
                    onChange={(e) => setForm({ ...form, inputUrlsText: e.target.value })}
                    rows={4}
                    placeholder={"https://www.instagram.com/creator/\n@username"}
                  />
                </div>
              ) : null}

              {!isLinkImport ? (
                <div className="space-y-2 sm:max-w-xs">
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
              ) : null}
            </section>

            <section className="border-t pt-4">
                <button
                  type="button"
                  className="flex w-full items-center justify-between gap-3 text-left"
                  onClick={() => setAdvancedOpen((value) => !value)}
                >
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <h3 className="text-sm font-medium">{isLinkImport ? "高价值筛选" : "高级筛选"}</h3>
                      <span className="text-xs text-muted-foreground">可选</span>
                    </div>
                    <p className="mt-1 truncate text-xs text-muted-foreground">{advancedSummary}</p>
                  </div>
                  <ChevronDown
                    className={cn("h-4 w-4 shrink-0 text-muted-foreground transition-transform", advancedOpen && "rotate-180")}
                  />
                </button>

                {advancedOpen ? (
                  <div className="mt-4 space-y-4">
                    <div className="flex items-start gap-2">
                      <button
                        type="button"
                        className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
                        onClick={() => setFilterHelpOpen((value) => !value)}
                      >
                        <HelpCircle className="h-3.5 w-3.5" />
                        筛选规则说明
                      </button>
                    </div>
                    {filterHelpOpen ? (
                      <ul className="list-disc space-y-1 pl-5 text-xs text-muted-foreground">
                        {FILTER_RULES_HELP.map((line) => (
                          <li key={line}>{line}</li>
                        ))}
                      </ul>
                    ) : null}

                    {!isLinkImport ? (
                      <>
                    <div className="space-y-2">
                      <Label htmlFor="collection_mode">发现模式</Label>
                      <select
                        id="collection_mode"
                        value={collectionMode}
                        onChange={(e) => {
                          const nextMode = e.target.value as CollectionMode;
                          setForm((prev) => {
                            const nextSourceMethod: TaskSourceMethod =
                              nextMode === "link_seed_discovery"
                                ? "shopping_seed_auto"
                                : nextMode === "link_import"
                                  ? "link_import"
                                  : prev.sourceMethod === "shopping_seed_auto" || prev.sourceMethod === "link_import"
                                    ? "keyword_discovery"
                                    : prev.sourceMethod;
                            const base = {
                              ...prev,
                              sourceMethod: nextSourceMethod,
                              collection_mode: nextMode,
                              comment_discovery_enabled:
                                nextMode === "competitor_product" || nextMode === "link_seed_discovery"
                                  ? false
                                  : prev.comment_discovery_enabled,
                            };
                            if (nextMode === "link_seed_discovery") {
                              const seedPlatforms = [...SEED_DISCOVERY_PLATFORMS];
                              return {
                                ...base,
                                platforms: seedPlatforms,
                                platform: "multi",
                              };
                            }
                            return base;
                          });
                        }}
                        className={cn(
                          "flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                        )}
                      >
                        {COLLECTION_MODE_OPTIONS.map((item) => (
                          <option key={item.value} value={item.value}>
                            {item.label}
                          </option>
                        ))}
                      </select>
                    </div>

                    <div className="grid gap-4 sm:grid-cols-2">
                      <div className="space-y-2">
                        <Label htmlFor="category">类目</Label>
                        <Input
                          id="category"
                          value={form.category}
                          onChange={(e) => setForm({ ...form, category: e.target.value })}
                          placeholder="美妆 / 科技（可选）"
                        />
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
                    </div>
                      </>
                    ) : null}

                    <div className="grid gap-4 sm:grid-cols-2">
                      <div className="space-y-2">
                        <Label htmlFor="min_followers_count">最低粉丝数</Label>
                        <Input
                          id="min_followers_count"
                          type="number"
                          min={0}
                          step={1}
                          value={form.min_followers_count}
                          onChange={(e) => setForm({ ...form, min_followers_count: e.target.value })}
                          placeholder="留空不限制"
                        />
                        <p className="text-xs text-muted-foreground">只保留粉丝数达到门槛的账号</p>
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="max_followers_count">最高粉丝数（可选）</Label>
                        <Input
                          id="max_followers_count"
                          type="number"
                          min={0}
                          step={1}
                          value={form.max_followers_count}
                          onChange={(e) => setForm({ ...form, max_followers_count: e.target.value })}
                          placeholder="留空不限制"
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
                          placeholder="留空不限制"
                        />
                      </div>
                    </div>

                    <div className="space-y-3 rounded-md border border-dashed p-3">
                      <p className="text-xs font-medium text-foreground">联系方式与入库策略</p>
                      <label className="flex items-start gap-2 text-sm">
                        <input
                          type="checkbox"
                          className="mt-1"
                          checked={form.require_email}
                          onChange={(e) => setForm({ ...form, require_email: e.target.checked })}
                        />
                        <span>
                          <span className="font-medium">要求有邮箱</span>
                          <span className="mt-0.5 block text-xs text-muted-foreground">
                            优先采集已发现明确邮箱的账号
                          </span>
                        </span>
                      </label>
                      <label className="flex items-start gap-2 text-sm">
                        <input
                          type="checkbox"
                          className="mt-1"
                          checked={form.require_contact}
                          onChange={(e) => setForm({ ...form, require_contact: e.target.checked })}
                        />
                        <span>
                          <span className="font-medium">要求有联系方式</span>
                          <span className="mt-0.5 block text-xs text-muted-foreground">
                            邮箱、官网、Linktree、ShopMy、LTK、Amazon 店铺等任一可联系入口
                          </span>
                        </span>
                      </label>
                      <label className="flex items-start gap-2 text-sm">
                        <input
                          type="checkbox"
                          className="mt-1"
                          checked={form.insert_qualified_only}
                          onChange={(e) => setForm({ ...form, insert_qualified_only: e.target.checked })}
                        />
                        <span>
                          <span className="font-medium">只入库符合条件的账号</span>
                          <span className="mt-0.5 block text-xs text-muted-foreground">
                            不符合条件的账号进入候选池，但不入库
                          </span>
                        </span>
                      </label>
                      <label className="flex items-start gap-2 text-sm">
                        <input
                          type="checkbox"
                          className="mt-1"
                          checked={form.strict_quality_filter}
                          onChange={(e) => setForm({ ...form, strict_quality_filter: e.target.checked })}
                        />
                        <span>
                          <span className="font-medium">严格模式</span>
                          <span className="mt-0.5 block text-xs text-muted-foreground">
                            不符合条件直接过滤，不写入红人库
                          </span>
                        </span>
                      </label>
                      <label className="flex items-start gap-2 text-sm">
                        <input
                          type="checkbox"
                          className="mt-1"
                          checked={form.export_qualified_only}
                          onChange={(e) => setForm({ ...form, export_qualified_only: e.target.checked })}
                        />
                        <span>
                          <span className="font-medium">只导出符合条件的账号</span>
                          <span className="mt-0.5 block text-xs text-muted-foreground">
                            候选池导出时默认仅包含高价值账号
                          </span>
                        </span>
                      </label>
                    </div>

                    {!isLinkImport ? (
                      <>
                    <div className="space-y-2">
                      <Label htmlFor="filter_include_keywords">偏好包含关键词</Label>
                      <Textarea
                        id="filter_include_keywords"
                        value={form.filterIncludeKeywordsText}
                        onChange={(e) => setForm({ ...form, filterIncludeKeywordsText: e.target.value })}
                        placeholder={"brand deal\ncollab"}
                        rows={2}
                      />
                    </div>

                    <div className="space-y-2">
                      <Label htmlFor="filter_exclude_keywords">排除关键词</Label>
                      <Textarea
                        id="filter_exclude_keywords"
                        value={form.filterExcludeKeywordsText}
                        onChange={(e) => setForm({ ...form, filterExcludeKeywordsText: e.target.value })}
                        placeholder={"giveaway\nfan page"}
                        rows={2}
                      />
                    </div>

                    {!showCompetitorProduct ? (
                      <label className="flex items-start gap-2 text-sm">
                        <input
                          type="checkbox"
                          className="mt-1"
                          checked={form.comment_discovery_enabled}
                          onChange={(e) =>
                            setForm({ ...form, comment_discovery_enabled: e.target.checked })
                          }
                        />
                        <span>
                          <span className="font-medium">自动抓取帖子 / Reels 评论区用户</span>
                        </span>
                      </label>
                    ) : null}

                    {showCompetitorProduct ? (
                      <div className="grid gap-4 sm:grid-cols-2">
                        <div className="space-y-2 sm:col-span-2">
                          <Label htmlFor="competitor_brand">品牌名（可选）</Label>
                          <Input
                            id="competitor_brand"
                            value={form.competitorBrandText}
                            onChange={(e) => setForm({ ...form, competitorBrandText: e.target.value })}
                            placeholder="Anker"
                          />
                        </div>
                        <div className="space-y-2 sm:col-span-2">
                          <Label htmlFor="competitor_website">竞品官网（可选）</Label>
                          <Input
                            id="competitor_website"
                            value={form.competitorWebsiteText}
                            onChange={(e) => setForm({ ...form, competitorWebsiteText: e.target.value })}
                            placeholder="https://www.example.com/product"
                          />
                        </div>
                      </div>
                    ) : null}
                      </>
                    ) : null}
                  </div>
                ) : null}
              </section>

            <section className="border-t pt-4">
              <button
                type="button"
                className="flex w-full items-center justify-between gap-3 text-left"
                onClick={() => setAutomationOpen((value) => !value)}
              >
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="text-sm font-medium">自动化与通知</h3>
                    <span className="text-xs text-muted-foreground">可选</span>
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {form.schedule_enabled || form.email_enabled || form.outreach_enabled
                      ? "已启用部分自动化选项"
                      : "默认可跳过"}
                  </p>
                </div>
                <ChevronDown
                  className={cn("h-4 w-4 shrink-0 text-muted-foreground transition-transform", automationOpen && "rotate-180")}
                />
              </button>

              {automationOpen ? (
                <div className="mt-4 space-y-4">
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={form.schedule_enabled}
                      onChange={(e) => setForm({ ...form, schedule_enabled: e.target.checked })}
                    />
                    启用定时任务
                  </label>
                  {form.schedule_enabled ? (
                    <div className="space-y-2">
                      <Label htmlFor="schedule_cron">Cron 表达式</Label>
                      <Input
                        id="schedule_cron"
                        value={form.schedule_cron}
                        onChange={(e) => setForm({ ...form, schedule_cron: e.target.value })}
                        placeholder="0 9 * * 1"
                      />
                    </div>
                  ) : null}

                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={form.email_enabled}
                      onChange={(e) => setForm({ ...form, email_enabled: e.target.checked })}
                    />
                    采集完成后发送邮件
                  </label>
                  {form.email_enabled ? (
                    <div className="space-y-2">
                      <Label htmlFor="email_recipients">收件人邮箱</Label>
                      <Input
                        id="email_recipients"
                        value={form.email_recipientsText}
                        onChange={(e) => setForm({ ...form, email_recipientsText: e.target.value })}
                        placeholder="ops@example.com"
                      />
                    </div>
                  ) : null}

                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={form.outreach_enabled}
                      onChange={(e) => setForm({ ...form, outreach_enabled: e.target.checked })}
                    />
                    启用外联同步
                  </label>
                  {form.outreach_enabled ? (
                    <div className="grid gap-3 sm:grid-cols-2">
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
                          <option value="mailchimp">Mailchimp</option>
                          <option value="smtp">SMTP</option>
                        </select>
                      </div>
                      <label className="flex items-end gap-2 pb-2 text-sm">
                        <input
                          type="checkbox"
                          checked={form.outreach_dry_run}
                          onChange={(e) => setForm({ ...form, outreach_dry_run: e.target.checked })}
                        />
                        试跑模式
                      </label>
                    </div>
                  ) : null}
                </div>
              ) : null}
            </section>
          </div>

          <div className="shrink-0 border-t bg-background px-5 py-4 sm:px-6">
            {validationError && mode === "create" ? (
              <p className="mb-3 text-xs text-muted-foreground">{validationError}</p>
            ) : null}
            <div className="flex flex-col-reverse gap-2 sm:flex-row sm:items-center sm:justify-between">
              <Button type="button" variant="outline" onClick={onClose} disabled={submitting} className="w-full sm:w-auto">
                取消
              </Button>
              <div className="flex flex-col gap-2 sm:flex-row">
                {mode === "create" ? (
                  <Button
                    type="button"
                    variant="ghost"
                    className="w-full sm:w-auto"
                    onClick={handleSaveTemplate}
                    disabled={submitting}
                  >
                    保存为模板
                  </Button>
                ) : null}
                <Button
                  type="submit"
                  disabled={submitting || Boolean(validationError)}
                  className="w-full sm:w-auto"
                >
                  {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                  {mode === "create" ? "创建任务" : "保存修改"}
                </Button>
              </div>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}
