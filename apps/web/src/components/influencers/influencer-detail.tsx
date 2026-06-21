"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  ArrowLeft,
  Bot,
  ExternalLink,
  Loader2,
  RefreshCw,
  UserRound,
} from "lucide-react";

import { AdminShell } from "@/components/layout/admin-shell";
import { ErrorAlert, SuccessAlert } from "@/components/shared/page-states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  analyzeInfluencer,
  fetchInfluencerFollowups,
  refreshInfluencerContact,
  type Influencer,
  type InfluencerFollowup,
  type InfluencerLeadUpdatePayload,
  updateInfluencerLead,
} from "@/lib/api";
import { copyLinkText, resolveExternalLink } from "@/lib/instagram-url";
import {
  aiModeLabel,
  CONTACT_CHANNEL_LABELS,
  CONTACT_FETCH_STATUS_LABELS,
  contactCredibilityLabel,
  emailSourceLabel,
  FOLLOWUP_ACTION_LABELS,
  leadStatusLabel,
  leadStatusVariant,
  platformLabel,
  followersAudienceLabel,
  SOURCE_DISCOVERY_LABELS,
} from "@/lib/labels";
import { cn } from "@/lib/utils";

const FOLLOW_STATUS_OPTIONS = [
  { value: "new", label: "新线索" },
  { value: "to_contact", label: "待联系" },
  { value: "contacted", label: "已联系" },
  { value: "replied", label: "已回复" },
  { value: "interested", label: "有意向" },
  { value: "quoted", label: "已报价" },
  { value: "cooperating", label: "合作中" },
  { value: "cooperated", label: "已合作" },
  { value: "invalid", label: "无效" },
  { value: "blacklisted", label: "黑名单" },
];

type InfluencerDetailProps = {
  initial: Influencer;
};

function formatNumber(value: number | null | undefined): string {
  if (value == null) return "-";
  return value.toLocaleString("zh-CN");
}

function formatPercent(value: number | null | undefined): string {
  if (value == null) return "-";
  return `${value.toFixed(1)}%`;
}

function formatScore(value: number | null | undefined): string {
  if (value == null) return "-";
  return value.toFixed(1);
}

function formatRoi(value: number | null | undefined): string {
  if (value == null) return "-";
  return `${value.toFixed(1)}x`;
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "-";
  return new Date(value).toLocaleString("zh-CN");
}

function riskBadgeVariant(level: string | null): "success" | "warning" | "destructive" | "secondary" {
  if (level === "low") return "success";
  if (level === "medium") return "warning";
  if (level === "high") return "destructive";
  return "secondary";
}

function riskLabel(level: string | null): string {
  if (level === "low") return "低风险";
  if (level === "medium") return "中风险";
  if (level === "high") return "高风险";
  return level ?? "-";
}

function followStatusLabel(status: string | null): string {
  return leadStatusLabel(status);
}

function resolvePrimaryEmail(influencer: Influencer): string | null {
  return (
    influencer.final_email ||
    influencer.business_email ||
    influencer.public_email ||
    influencer.email
  );
}

function InfoItem({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <p className="text-xs text-muted-foreground">{label}</p>
      <div className="text-sm font-medium break-words">{value ?? "-"}</div>
    </div>
  );
}

function LinkItem({ label, href }: { label: string; href: string | null | undefined }) {
  const [copyHint, setCopyHint] = useState<string | null>(null);

  if (!href) {
    return <InfoItem label={label} value="-" />;
  }

  const link = resolveExternalLink(href);

  if (!link.ok) {
    return (
      <InfoItem
        label={label}
        value={
          <div className="space-y-2">
            <p className="text-sm text-amber-800">{link.reason ?? "链接异常"}</p>
            <p className="break-all text-xs text-muted-foreground">{href}</p>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={async () => {
                const ok = await copyLinkText(href);
                setCopyHint(ok ? "已复制原始链接" : "复制失败");
              }}
            >
              复制链接
            </Button>
            {copyHint ? <p className="text-xs text-muted-foreground">{copyHint}</p> : null}
            <p className="text-xs text-muted-foreground">
              若链接格式正常但仍打不开，可能是 Instagram 需登录或网络限制，并非系统数据错误。
            </p>
          </div>
        }
      />
    );
  }

  return (
    <InfoItem
      label={label}
      value={
        <div className="space-y-1">
          <a
            href={link.href}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-start gap-1 text-primary hover:underline"
          >
            <span className="break-all">{link.href}</span>
            <ExternalLink className="mt-0.5 h-3 w-3 shrink-0" />
          </a>
          {copyHint ? <p className="text-xs text-muted-foreground">{copyHint}</p> : null}
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-xs"
            onClick={async () => {
              const ok = await copyLinkText(link.href);
              setCopyHint(ok ? "已复制链接" : "复制失败");
            }}
          >
            复制链接
          </Button>
        </div>
      }
    />
  );
}

function aiWhyRecommendText(influencer: Influencer): string {
  if (influencer.ai_summary?.trim()) {
    return influencer.ai_summary;
  }
  if (influencer.score_reason?.trim()) {
    return influencer.score_reason;
  }
  return "暂无，可点击「重新 AI 分析」生成";
}

function aiFieldOrHint(
  value: string | null | undefined,
  influencer: Influencer,
  emptyLabel: string,
): string {
  if (value?.trim()) {
    return value;
  }
  if (influencer.score_reason?.includes("AI 分析失败") || influencer.score_reason?.includes("未配置 KIMI")) {
    return influencer.score_reason;
  }
  return emptyLabel;
}

function SectionCard({
  title,
  description,
  children,
  className,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <Card className={className}>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        {description ? <CardDescription>{description}</CardDescription> : null}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}

export function InfluencerDetail({ initial }: InfluencerDetailProps) {
  const router = useRouter();
  const [influencer, setInfluencer] = useState(initial);
  const [followStatus, setFollowStatus] = useState(initial.follow_status ?? "new");
  const [owner, setOwner] = useState(initial.owner ?? "");
  const [note, setNote] = useState(initial.note ?? "");
  const [nextFollowUpAt, setNextFollowUpAt] = useState(
    initial.next_follow_up_at ? initial.next_follow_up_at.slice(0, 10) : "",
  );
  const [invalidReason, setInvalidReason] = useState(initial.invalid_reason ?? "");
  const [blacklistReason, setBlacklistReason] = useState(initial.blacklist_reason ?? "");
  const [operatorName, setOperatorName] = useState("");
  const [followups, setFollowups] = useState<InfluencerFollowup[]>([]);
  const [followupsLoading, setFollowupsLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [refreshingContact, setRefreshingContact] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [aiSource, setAiSource] = useState<string | null>(null);

  const displayName = influencer.display_name || influencer.username;
  const primaryEmail = resolvePrimaryEmail(influencer);
  const otherLinks = influencer.other_social_links ?? [];
  const recentTitles = influencer.recent_post_titles ?? [];
  const recentUrls = influencer.recent_post_urls ?? [];

  useEffect(() => {
    let cancelled = false;
    queueMicrotask(async () => {
      setFollowupsLoading(true);
      try {
        const data = await fetchInfluencerFollowups(influencer.id);
        if (!cancelled) setFollowups(data);
      } catch {
        if (!cancelled) setFollowups([]);
      } finally {
        if (!cancelled) setFollowupsLoading(false);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [influencer.id]);

  async function reloadFollowups() {
    setFollowupsLoading(true);
    try {
      const data = await fetchInfluencerFollowups(influencer.id);
      setFollowups(data);
    } catch {
      setFollowups([]);
    } finally {
      setFollowupsLoading(false);
    }
  }

  async function handleLeadSave(fields: InfluencerLeadUpdatePayload) {
    setSaving(true);
    setError(null);
    setMessage(null);
    try {
      const updated = await updateInfluencerLead(influencer.id, {
        ...fields,
        operator_name: operatorName.trim() || undefined,
      });
      setInfluencer(updated);
      setFollowStatus(updated.follow_status ?? "new");
      setOwner(updated.owner ?? "");
      setNote(updated.note ?? "");
      setNextFollowUpAt(updated.next_follow_up_at ? updated.next_follow_up_at.slice(0, 10) : "");
      setInvalidReason(updated.invalid_reason ?? "");
      setBlacklistReason(updated.blacklist_reason ?? "");
      setMessage("保存成功");
      await reloadFollowups();
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function handleAnalyze() {
    setAnalyzing(true);
    setError(null);
    setMessage(null);
    try {
      const result = await analyzeInfluencer(influencer.id);
      setInfluencer(result.influencer);
      setAiSource(result.analysis.source);
      if (result.analysis.source === "kimi") {
        setMessage(`AI 分析完成（${aiModeLabel(result.analysis.source)}）`);
      } else if (result.analysis.error_message) {
        setMessage(`已保存规则评分（${aiModeLabel(result.analysis.source)}）`);
        setError(`AI 分析失败：${result.analysis.error_message}`);
      } else {
        setMessage(`已使用规则评分（${aiModeLabel(result.analysis.source)}）`);
      }
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "AI 分析失败");
    } finally {
      setAnalyzing(false);
    }
  }

  async function handleRefreshContact() {
    setRefreshingContact(true);
    setError(null);
    setMessage(null);
    try {
      const result = await refreshInfluencerContact(influencer.id);
      setInfluencer(result.influencer);
      setMessage(
        result.final_email
          ? `联系方式已更新：${result.final_email}`
          : result.contact_page
            ? "未找到邮箱，但发现了联系页/外链"
            : "联系方式深挖完成，仍未找到可用邮箱",
      );
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "联系方式深挖失败");
    } finally {
      setRefreshingContact(false);
    }
  }

  return (
    <AdminShell title="红人详情" description={`红人详情 · ${displayName}`}>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Button variant="outline" asChild>
          <Link href="/influencers">
            <ArrowLeft className="h-4 w-4" />
            返回列表
          </Link>
        </Button>
        <Button variant="default" onClick={handleAnalyze} disabled={analyzing || saving || refreshingContact}>
          {analyzing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Bot className="h-4 w-4" />}
          {analyzing ? "分析中..." : "重新 AI 分析"}
        </Button>
        <Button
          variant="secondary"
          onClick={handleRefreshContact}
          disabled={analyzing || saving || refreshingContact}
        >
          {refreshingContact ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <RefreshCw className="h-4 w-4" />
          )}
          {refreshingContact ? "查找中..." : "重新查找联系方式"}
        </Button>
        {aiSource ? (
          <Badge variant="secondary">{aiModeLabel(aiSource)}</Badge>
        ) : null}
      </div>

      {message ? <SuccessAlert message={message} className="mb-4" /> : null}
      {error ? <ErrorAlert message={error} className="mb-4" /> : null}

      <div className="space-y-6">
        {/* 1. 基础信息 */}
        <SectionCard title="基础信息" description="红人账号基本资料">
          <div className="flex flex-col gap-6 lg:flex-row">
            <div className="flex shrink-0 items-start gap-4">
              {influencer.avatar_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={influencer.avatar_url}
                  alt={displayName}
                  className="h-24 w-24 rounded-full border object-cover"
                />
              ) : (
                <div className="flex h-24 w-24 items-center justify-center rounded-full border bg-muted">
                  <UserRound className="h-10 w-10 text-muted-foreground" />
                </div>
              )}
              <div className="min-w-0">
                <h2 className="text-2xl font-semibold">{displayName}</h2>
                <p className="text-sm text-muted-foreground">@{influencer.username}</p>
                <div className="mt-2 flex flex-wrap gap-2">
                  <Badge variant="secondary">{platformLabel(influencer.platform)}</Badge>
                  {influencer.niche ? <Badge variant="outline">{influencer.niche}</Badge> : null}
                </div>
              </div>
            </div>

            <div className="grid flex-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              <InfoItem label="昵称" value={displayName} />
              <InfoItem label="平台" value={platformLabel(influencer.platform)} />
              <InfoItem label="国家" value={influencer.country} />
              <InfoItem label="语言" value={influencer.language} />
              <InfoItem label="类目" value={influencer.category} />
              <InfoItem label="领域" value={influencer.niche} />
              <div className="sm:col-span-2 lg:col-span-3">
                <LinkItem label="个人主页" href={influencer.profile_url} />
              </div>
              {influencer.bio ? (
                <div className="sm:col-span-2 lg:col-span-3">
                  <InfoItem label="简介" value={<span className="font-normal leading-relaxed text-muted-foreground">{influencer.bio}</span>} />
                </div>
              ) : (
                <InfoItem label="简介" value="-" />
              )}
            </div>
          </div>
        </SectionCard>

        {/* 2. 数据指标 */}
        <SectionCard title="数据指标" description="粉丝与互动表现">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <InfoItem label={`${followersAudienceLabel(influencer.platform)}数`} value={formatNumber(influencer.followers_count)} />
            <InfoItem label="平均观看" value={formatNumber(influencer.avg_views)} />
            <InfoItem label="平均点赞" value={formatNumber(influencer.avg_likes)} />
            <InfoItem label="平均评论" value={formatNumber(influencer.avg_comments)} />
            <InfoItem label="互动率" value={formatPercent(influencer.engagement_rate)} />
            <InfoItem label="优先级" value={influencer.final_priority ?? "-"} />
            <InfoItem label="综合评分" value={formatScore(influencer.score)} />
            <InfoItem label="互动分" value={formatScore(influencer.engagement_score)} />
            <InfoItem label="内容匹配" value={formatScore(influencer.content_match_score)} />
            <InfoItem label="可联系分" value={formatScore(influencer.contactability_score)} />
            <InfoItem label="商业信号" value={formatScore(influencer.commercial_signal_score)} />
            <InfoItem label="活跃度" value={formatScore(influencer.activity_score)} />
            <InfoItem label="风险分" value={formatScore(influencer.risk_score)} />
            <InfoItem label="Product Fit" value={formatScore(influencer.product_fit)} />
            <InfoItem label="Travel Fit Score" value={formatScore(influencer.travel_fit_score)} />
            <InfoItem label="购买力评分" value={formatScore(influencer.purchasing_power_score)} />
            <InfoItem label="带货能力评分" value={formatScore(influencer.sales_potential_score)} />
            <InfoItem label="受众匹配度" value={formatScore(influencer.audience_match_score)} />
            <InfoItem label="ROI 预估" value={formatRoi(influencer.roi_forecast)} />
            <InfoItem
              label="风险等级"
              value={
                <Badge variant={riskBadgeVariant(influencer.risk_level)}>
                  {riskLabel(influencer.risk_level)}
                </Badge>
              }
            />
          </div>
        </SectionCard>

        {/* 3. AI 画像与合作建议 */}
        <SectionCard
          title="AI 推荐理由与触达建议"
          description="为什么推荐、适合怎么合作、可以怎么开口"
        >
          <div className="mb-4 rounded-md border border-primary/20 bg-primary/5 p-4 space-y-3">
            <div>
              <p className="text-xs font-medium text-primary mb-1">为什么推荐</p>
              <p className="text-sm leading-relaxed whitespace-pre-wrap">
                {aiWhyRecommendText(influencer)}
              </p>
            </div>
            <div>
              <p className="text-xs font-medium text-primary mb-1">适合怎么合作</p>
              <p className="text-sm leading-relaxed whitespace-pre-wrap">
                {aiFieldOrHint(influencer.ai_collaboration_suggestion, influencer, "-")}
              </p>
            </div>
            <div>
              <p className="text-xs font-medium text-primary mb-1">可以怎么开口</p>
              <p className="text-sm leading-relaxed whitespace-pre-wrap">
                {aiFieldOrHint(influencer.ai_outreach_message, influencer, "-")}
              </p>
            </div>
          </div>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 mb-4">
            <InfoItem label="综合评分" value={formatScore(influencer.score)} />
            <InfoItem label="Product Fit" value={formatScore(influencer.product_fit)} />
            <InfoItem label="ROI 预估" value={formatRoi(influencer.roi_forecast)} />
          </div>
          <div className="space-y-4">
            <div>
              <p className="text-xs text-muted-foreground mb-1">AI 画像</p>
              <p className="text-sm leading-relaxed whitespace-pre-wrap">
                {influencer.ai_summary?.trim() ? influencer.ai_summary : "-"}
              </p>
            </div>
            {influencer.tags?.length ? (
              <div>
                <p className="text-xs text-muted-foreground mb-2">标签</p>
                <div className="flex flex-wrap gap-1.5">
                  {influencer.tags.map((tag) => (
                    <Badge key={tag} variant="outline">
                      {tag}
                    </Badge>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        </SectionCard>

        {(influencer.source_discovery_type ||
          influencer.source_post_url ||
          influencer.source_comment_text ||
          (influencer.source_records?.length ?? 0) > 0) && (
          <SectionCard title="发现来源" description="该红人如何进入系统">
            {(influencer.source_records?.length ?? 0) > 0 ? (
              <div className="space-y-4">
                {influencer.source_records!.map((source) => (
                  <div
                    key={source.id}
                    className="rounded-md border bg-muted/20 p-3 grid gap-3 sm:grid-cols-2"
                  >
                    <LinkItem label="来源作品链接" href={source.source_post_url} />
                    <LinkItem label="来源输入链接" href={source.source_input_url} />
                    <InfoItem label="来源任务" value={source.task_name || (source.task_id ? `#${source.task_id}` : "-")} />
                    <InfoItem
                      label="采集时间"
                      value={
                        source.collected_at
                          ? new Date(source.collected_at).toLocaleString("zh-CN")
                          : "-"
                      }
                    />
                    {source.source_platform ? (
                      <InfoItem label="来源平台" value={source.source_platform} />
                    ) : null}
                  </div>
                ))}
              </div>
            ) : (
              <div className="grid gap-4 sm:grid-cols-2">
                <InfoItem
                  label="发现类型"
                  value={
                    influencer.source_discovery_type
                      ? SOURCE_DISCOVERY_LABELS[influencer.source_discovery_type] ??
                        influencer.source_discovery_type
                      : "-"
                  }
                />
                <LinkItem label="来源帖子" href={influencer.source_post_url} />
                <LinkItem label="来源评论链接" href={influencer.source_comment_url} />
                <InfoItem
                  label="来源评论"
                  value={
                    influencer.source_comment_text ? (
                      <span className="font-normal leading-relaxed text-muted-foreground">
                        {influencer.source_comment_text}
                      </span>
                    ) : (
                      "-"
                    )
                  }
                />
              </div>
            )}
          </SectionCard>
        )}

        {/* 4. 联系方式与商业价值 */}
        <SectionCard title="联系方式" description="深挖 bio、Linktree、官网与联系页中的邮箱和渠道">
          {!primaryEmail &&
          !influencer.whatsapp &&
          !influencer.telegram &&
          !influencer.contact_page &&
          !influencer.linktree_url &&
          !influencer.website ? (
            <p className="mb-4 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
              缺联系方式 — 可点击「重新查找联系方式」，或通过 Instagram DM 触达
            </p>
          ) : null}
          {!primaryEmail && influencer.contact_page ? (
            <p className="mb-4 rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-900">
              暂无邮箱，但存在联系页，建议通过官网表单联系
            </p>
          ) : null}
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <InfoItem label="最终邮箱" value={primaryEmail} />
            <InfoItem label="公开邮箱" value={influencer.public_email} />
            <InfoItem label="商务邮箱" value={influencer.business_email} />
            <InfoItem label="邮箱来源" value={emailSourceLabel(influencer.email_source)} />
            <InfoItem
              label="联系可信度"
              value={contactCredibilityLabel(influencer.contact_credibility_level)}
            />
            <InfoItem label="联系方式评分" value={formatScore(influencer.contact_score)} />
            <InfoItem
              label="深挖状态"
              value={
                influencer.contact_fetch_status
                  ? CONTACT_FETCH_STATUS_LABELS[influencer.contact_fetch_status] ??
                    influencer.contact_fetch_status
                  : "-"
              }
            />
            <InfoItem label="最后深挖" value={formatDate(influencer.contact_discovered_at)} />
            <LinkItem label="官网" href={influencer.website} />
            <LinkItem label="联系页" href={influencer.contact_page} />
            <LinkItem label="链接树" href={influencer.linktree_url} />
            <InfoItem label="WhatsApp" value={influencer.whatsapp} />
            <InfoItem label="Telegram" value={influencer.telegram} />
          </div>

          {influencer.contact_fetch_error ? (
            <p className="mt-4 text-sm text-muted-foreground">
              深挖提示：{influencer.contact_fetch_error}
            </p>
          ) : null}

          {influencer.contact_sources?.length ? (
            <div className="mt-4 space-y-2">
              <p className="text-xs text-muted-foreground">联系方式来源</p>
              <ul className="space-y-2">
                {influencer.contact_sources.map((source, index) => (
                  <li key={`${source.type}-${index}`} className="rounded-md border px-3 py-2 text-sm">
                    <div className="font-medium">
                      {emailSourceLabel(String(source.type ?? "unknown"))}
                      {source.confidence != null ? ` · 置信 ${String(source.confidence)}` : ""}
                    </div>
                    {source.value ? (
                      <p className="mt-1 text-muted-foreground">{String(source.value)}</p>
                    ) : null}
                    {source.url ? (
                      <a
                        href={String(source.url)}
                        target="_blank"
                        rel="noreferrer"
                        className="mt-1 inline-flex items-center gap-1 text-xs text-primary hover:underline"
                      >
                        {String(source.url)}
                        <ExternalLink className="h-3 w-3" />
                      </a>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {otherLinks.length > 0 ? (
            <div className="mt-4 space-y-2">
              <p className="text-xs text-muted-foreground">其他社交链接</p>
              <div className="space-y-2">
                {otherLinks.map((link) => (
                  <a
                    key={`${link.label}-${link.url}`}
                    href={link.url}
                    target="_blank"
                    rel="noreferrer"
                    className="flex items-center gap-2 text-sm text-primary hover:underline"
                  >
                    <span className="font-medium">{link.label}</span>
                    <span className="truncate text-muted-foreground">{link.url}</span>
                    <ExternalLink className="h-3 w-3 shrink-0" />
                  </a>
                ))}
              </div>
            </div>
          ) : (
            <p className="mt-4 text-sm text-muted-foreground">暂无其他社交链接</p>
          )}
        </SectionCard>

        {/* 5. 内容与受众 */}
        <SectionCard title="内容与受众" description="内容主题与受众画像">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <InfoItem
              label="内容主题"
              value={
                influencer.content_topics?.length ? (
                  <div className="flex flex-wrap gap-1.5">
                    {influencer.content_topics.map((topic) => (
                      <Badge key={topic} variant="secondary">
                        {topic}
                      </Badge>
                    ))}
                  </div>
                ) : (
                  "-"
                )
              }
            />
            <InfoItem label="受众国家" value={influencer.audience_country} />
            <InfoItem label="受众语言" value={influencer.audience_language} />
            <InfoItem label="最后发帖时间" value={formatDate(influencer.last_post_at)} />
            <InfoItem label="发帖频率" value={influencer.posting_frequency} />
          </div>

          {recentTitles.length > 0 ? (
            <div className="mt-4 space-y-3">
              <p className="text-xs text-muted-foreground">近期帖子</p>
              <ul className="space-y-2">
                {recentTitles.map((title, index) => {
                  const url = recentUrls[index];
                  return (
                    <li key={`${title}-${index}`} className="rounded-md border px-3 py-2 text-sm">
                      <p className="font-medium">{title}</p>
                      {url ? (
                        <a
                          href={url}
                          target="_blank"
                          rel="noreferrer"
                          className="mt-1 inline-flex items-center gap-1 text-xs text-primary hover:underline"
                        >
                          {url}
                          <ExternalLink className="h-3 w-3" />
                        </a>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            </div>
          ) : (
            <p className="mt-4 text-sm text-muted-foreground">暂无近期内容记录</p>
          )}
        </SectionCard>

        <SectionCard title="线索跟进" description="状态、负责人、下次跟进与历史记录">
          <div className="mb-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <InfoItem
              label="当前状态"
              value={
                <Badge variant={leadStatusVariant(influencer.follow_status)}>
                  {followStatusLabel(influencer.follow_status)}
                </Badge>
              }
            />
            <InfoItem label="负责人" value={influencer.owner} />
            <InfoItem label="最后联系" value={formatDate(influencer.last_contacted_at)} />
            <InfoItem label="最后回复" value={formatDate(influencer.last_reply_at)} />
            <InfoItem label="下次跟进" value={formatDate(influencer.next_follow_up_at)} />
            <InfoItem label="最后采集" value={formatDate(influencer.last_collected_at)} />
          </div>

          <div className="mb-4 max-w-xs space-y-2">
            <Label htmlFor="operator_name">操作人（写入跟进记录）</Label>
            <Input
              id="operator_name"
              value={operatorName}
              onChange={(e) => setOperatorName(e.target.value)}
              placeholder="你的名字"
            />
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="space-y-2">
              <Label htmlFor="follow_status">跟进状态</Label>
              <select
                id="follow_status"
                value={followStatus}
                onChange={(e) => setFollowStatus(e.target.value)}
                className={cn(
                  "flex h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                )}
              >
                {FOLLOW_STATUS_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
              <Button
                size="sm"
                variant="secondary"
                disabled={saving}
                onClick={() =>
                  handleLeadSave({
                    lead_status: followStatus,
                    invalid_reason: followStatus === "invalid" ? invalidReason || null : undefined,
                    blacklist_reason:
                      followStatus === "blacklisted" ? blacklistReason || null : undefined,
                  })
                }
              >
                {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                保存跟进状态
              </Button>
            </div>

            <div className="space-y-2">
              <Label htmlFor="owner">负责人</Label>
              <Input
                id="owner"
                value={owner}
                onChange={(e) => setOwner(e.target.value)}
                placeholder="输入负责人"
              />
              <Button
                size="sm"
                variant="secondary"
                disabled={saving}
                onClick={() => handleLeadSave({ owner_name: owner || null })}
              >
                {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                保存负责人
              </Button>
            </div>

            <div className="space-y-2">
              <Label htmlFor="next_follow_up_at">下次跟进日期</Label>
              <Input
                id="next_follow_up_at"
                type="date"
                value={nextFollowUpAt}
                onChange={(e) => setNextFollowUpAt(e.target.value)}
              />
              <Button
                size="sm"
                variant="secondary"
                disabled={saving}
                onClick={() =>
                  handleLeadSave({
                    next_follow_up_at: nextFollowUpAt
                      ? new Date(`${nextFollowUpAt}T09:00:00`).toISOString()
                      : null,
                  })
                }
              >
                保存跟进时间
              </Button>
            </div>
          </div>

          {(followStatus === "invalid" || influencer.invalid_reason) && (
            <div className="mt-4 space-y-2">
              <Label htmlFor="invalid_reason">无效原因</Label>
              <Textarea
                id="invalid_reason"
                value={invalidReason}
                onChange={(e) => setInvalidReason(e.target.value)}
                rows={2}
              />
            </div>
          )}

          {(followStatus === "blacklisted" || influencer.blacklist_reason) && (
            <div className="mt-4 space-y-2">
              <Label htmlFor="blacklist_reason">黑名单原因</Label>
              <Textarea
                id="blacklist_reason"
                value={blacklistReason}
                onChange={(e) => setBlacklistReason(e.target.value)}
                rows={2}
              />
            </div>
          )}

          <div className="mt-4 space-y-2">
            <Label htmlFor="note">业务备注</Label>
            <Textarea
              id="note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="输入备注信息（会写入跟进记录）"
              rows={4}
            />
            <Button
              size="sm"
              variant="secondary"
              disabled={saving}
              onClick={() => handleLeadSave({ lead_note: note || null })}
            >
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              保存备注
            </Button>
          </div>

          <div className="mt-6 space-y-3">
            <h3 className="text-sm font-medium">跟进历史</h3>
            {followupsLoading ? (
              <p className="text-sm text-muted-foreground">加载跟进记录...</p>
            ) : followups.length === 0 ? (
              <p className="text-sm text-muted-foreground">暂无跟进记录</p>
            ) : (
              <ul className="space-y-2">
                {followups.map((item) => (
                  <li key={item.id} className="rounded-md border px-3 py-2 text-sm">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant="outline">
                        {FOLLOWUP_ACTION_LABELS[item.action_type] ?? item.action_type}
                      </Badge>
                      <span className="text-xs text-muted-foreground">
                        {formatDate(item.created_at)}
                      </span>
                      {item.operator_name ? (
                        <span className="text-xs text-muted-foreground">· {item.operator_name}</span>
                      ) : null}
                      {item.contact_channel ? (
                        <span className="text-xs text-muted-foreground">
                          · {CONTACT_CHANNEL_LABELS[item.contact_channel] ?? item.contact_channel}
                        </span>
                      ) : null}
                    </div>
                    {item.old_status || item.new_status ? (
                      <p className="mt-1 text-xs text-muted-foreground">
                        {item.old_status ? followStatusLabel(item.old_status) : "-"} →{" "}
                        {item.new_status ? followStatusLabel(item.new_status) : "-"}
                      </p>
                    ) : null}
                    {item.content ? (
                      <p className="mt-1 whitespace-pre-wrap text-muted-foreground">{item.content}</p>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </SectionCard>
      </div>
    </AdminShell>
  );
}
