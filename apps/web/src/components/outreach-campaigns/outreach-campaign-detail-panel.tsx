"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ArrowLeft, ChevronLeft, ChevronRight, Loader2, RefreshCw } from "lucide-react";

import { AdminShell } from "@/components/layout/admin-shell";
import { EmptyState, ErrorAlert } from "@/components/shared/page-states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  fetchOutreachCampaignRecipients,
  fetchOutreachCampaignReplyBoard,
  fetchOutreachCampaigns,
  openOutreachCampaignDraft,
  approveOutreachCampaignDraft,
  skipOutreachCampaignDraft,
  regenerateOutreachCampaignDraft,
  updateOutreachCampaignDraft,
  type OutreachCampaign,
  type OutreachCampaignPreviewItem,
  type OutreachCampaignReplyBoard,
  type OutreachCampaignReplyBoardItem,
} from "@/lib/api";
import {
  CAMPAIGN_STATUS_LABELS,
  buildCampaignBusinessSummary,
  buildCampaignStatsLine,
  buildSkipReasonSummary,
  getCampaignPhaseLabel,
  getOutreachDraftStatusLabel,
  getReplyStatusLabel,
  isCampaignFullySkipped,
} from "@/lib/outreach-campaign-helpers";
import {
  CAMPAIGN_DETAIL_TABS,
  type CampaignDetailTabKey,
  filterCampaignDetailRows,
  paginateCampaignDetailRows,
} from "@/lib/outreach-campaign-detail-helpers";
import { translateErrorMessage } from "@/lib/labels";

type DetailRow = {
  influencer_id: number;
  username: string;
  display_name: string | null;
  recipient: string | null;
  subject: string | null;
  body: string;
  reason: string;
  template_title: string;
  matched_knowledge: OutreachCampaignPreviewItem["matched_knowledge"];
  can_queue: boolean;
  skip_reason: string | null;
  draft_status: string;
  is_high_value: boolean;
  opened_at: string | null;
  approval_block_reason: string | null;
  send_status: string;
  reply_status: string;
  reply_time: string | null;
  reply_snippet: string | null;
  match_method: string | null;
};

function truncate(text: string, max = 90): string {
  if (text.length <= max) return text;
  return `${text.slice(0, max)}...`;
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  return new Date(value).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function sendStatusLabel(status: string): string {
  if (status === "sent") return "已发送";
  if (status === "failed") return "发送失败";
  if (status === "skipped") return "自动跳过";
  if (status === "pending") return "待发送";
  if (status === "queued") return "待发送";
  if (status === "not_queued") return "未发送";
  return status;
}

function mergeRows(
  recipients: OutreachCampaignPreviewItem[],
  replyBoard: OutreachCampaignReplyBoard | null,
): DetailRow[] {
  const replyByInfluencer = new Map<number, OutreachCampaignReplyBoardItem>();
  for (const item of replyBoard?.items ?? []) {
    replyByInfluencer.set(item.influencer_id, item);
  }
  return recipients.map((item) => {
    const reply = replyByInfluencer.get(item.influencer_id);
    return {
      influencer_id: item.influencer_id,
      username: item.username,
      display_name: item.display_name,
      recipient: item.recipient,
      subject: item.subject || reply?.subject || null,
      body: item.body,
      reason: item.reason,
      template_title: item.template_title,
      matched_knowledge: item.matched_knowledge,
      can_queue: item.can_queue,
      skip_reason: item.skip_reason ?? reply?.skip_reason ?? null,
      draft_status: item.draft_status,
      is_high_value: item.is_high_value,
      opened_at: item.opened_at,
      approval_block_reason: item.approval_block_reason,
      send_status: reply?.send_status ?? (item.skip_reason ? "skipped" : item.can_queue ? "not_queued" : "skipped"),
      reply_status: reply?.reply_status ?? (item.skip_reason ? "skipped" : "unreplied"),
      reply_time: reply?.reply_time ?? null,
      reply_snippet: reply?.reply_snippet ?? null,
      match_method: reply?.match_method ?? null,
    };
  });
}

export function OutreachCampaignDetailPanel({ campaignId }: { campaignId: number }) {
  const searchParams = useSearchParams();
  const initialTab = (searchParams.get("tab") || "all") as CampaignDetailTabKey;
  const [campaign, setCampaign] = useState<OutreachCampaign | null>(null);
  const [recipients, setRecipients] = useState<OutreachCampaignPreviewItem[]>([]);
  const [replyBoard, setReplyBoard] = useState<OutreachCampaignReplyBoard | null>(null);
  const [activeTab, setActiveTab] = useState<CampaignDetailTabKey>(
    CAMPAIGN_DETAIL_TABS.some((tab) => tab.key === initialTab) ? initialTab : "all",
  );
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [busyInfluencerId, setBusyInfluencerId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [campaigns, recipientData, replies] = await Promise.all([
        fetchOutreachCampaigns(),
        fetchOutreachCampaignRecipients(campaignId),
        fetchOutreachCampaignReplyBoard(campaignId),
      ]);
      setCampaign(campaigns.find((item) => item.id === campaignId) ?? null);
      setRecipients(recipientData.items);
      setReplyBoard(replies);
    } catch (err) {
      setError(translateErrorMessage(err instanceof Error ? err.message : "加载批次明细失败"));
    } finally {
      setLoading(false);
    }
  }, [campaignId]);

  const runDraftAction = useCallback(
    async (influencerId: number, action: "open" | "approve" | "skip" | "regenerate" | "edit") => {
      setBusyInfluencerId(influencerId);
      setError(null);
      try {
        if (action === "open") {
          await openOutreachCampaignDraft(campaignId, influencerId);
          setExpandedId(influencerId);
        } else if (action === "approve") {
          await approveOutreachCampaignDraft(campaignId, influencerId);
        } else if (action === "skip") {
          await skipOutreachCampaignDraft(campaignId, influencerId);
        } else if (action === "regenerate") {
          await regenerateOutreachCampaignDraft(campaignId, influencerId);
        } else {
          const current = recipients.find((row) => row.influencer_id === influencerId);
          const subject = window.prompt("编辑邮件标题", current?.subject || "");
          if (subject === null) return;
          const body = window.prompt("编辑邮件正文", current?.body || "");
          if (body === null) return;
          await updateOutreachCampaignDraft(campaignId, influencerId, { subject, body });
        }
        await load();
      } catch (err) {
        setError(translateErrorMessage(err instanceof Error ? err.message : "草稿操作失败"));
      } finally {
        setBusyInfluencerId(null);
      }
    },
    [campaignId, load, recipients],
  );

  useEffect(() => {
    queueMicrotask(() => {
      void load();
    });
  }, [load]);

  const rows = useMemo(() => mergeRows(recipients, replyBoard), [recipients, replyBoard]);
  const filteredRows = useMemo(() => filterCampaignDetailRows(rows, activeTab), [rows, activeTab]);
  const paged = useMemo(
    () => paginateCampaignDetailRows(filteredRows, { page, pageSize }),
    [filteredRows, page, pageSize],
  );
  const expanded = rows.find((row) => row.influencer_id === expandedId) ?? null;

  useEffect(() => {
    queueMicrotask(() => {
      setPage(1);
    });
  }, [activeTab, pageSize]);

  const tabCounts = useMemo(() => {
    const map = new Map<CampaignDetailTabKey, number>();
    for (const tab of CAMPAIGN_DETAIL_TABS) {
      map.set(tab.key, filterCampaignDetailRows(rows, tab.key).length);
    }
    return map;
  }, [rows]);

  return (
    <AdminShell title="批次发送明细" description="查看这一批红人谁发了、谁跳过、谁失败、谁回复。">
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Button variant="outline" asChild>
          <Link href="/outreach-campaigns">
            <ArrowLeft className="h-4 w-4" />
            返回 AI批量发邮件
          </Link>
        </Button>
        <Button variant="outline" onClick={() => void load()} disabled={loading}>
          <RefreshCw className="h-4 w-4" />
          刷新
        </Button>
        <Button variant="outline" asChild>
          <Link href={`/email-replies?campaign_id=${campaignId}`}>查看全部回复</Link>
        </Button>
      </div>

      {error ? <ErrorAlert message={error} className="mb-4" onRetry={() => void load()} /> : null}

      {loading ? (
        <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> 加载批次明细...
        </div>
      ) : !campaign ? (
        <EmptyState title="没有找到这个批次" description="请返回 AI批量发邮件页面重新选择批次。" />
      ) : (
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <div className="flex flex-wrap items-center gap-2">
                <CardTitle>{campaign.name}</CardTitle>
                <Badge variant="secondary">{CAMPAIGN_STATUS_LABELS[campaign.status] ?? campaign.status}</Badge>
              </div>
              <CardDescription>{getCampaignPhaseLabel(campaign)}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="grid gap-3 md:grid-cols-4">
                <div className="rounded-md border p-3">
                  <p className="text-xs text-muted-foreground">本批红人</p>
                  <p className="mt-1 text-xl font-semibold">{campaign.total_count}</p>
                </div>
                <div className="rounded-md border p-3">
                  <p className="text-xs text-muted-foreground">已发送</p>
                  <p className="mt-1 text-xl font-semibold">{campaign.sent_count}</p>
                </div>
                <div className="rounded-md border p-3">
                  <p className="text-xs text-muted-foreground">自动跳过</p>
                  <p className="mt-1 text-xl font-semibold">{campaign.skipped_count}</p>
                </div>
                <div className="rounded-md border p-3">
                  <p className="text-xs text-muted-foreground">已回复</p>
                  <p className="mt-1 text-xl font-semibold">{campaign.reply_count}</p>
                </div>
              </div>
              <div className="space-y-1 text-sm">
                {buildCampaignBusinessSummary(campaign).map((line) => (
                  <p key={line}>{line}</p>
                ))}
              </div>
              <p className="text-xs text-muted-foreground">{buildCampaignStatsLine(campaign)}</p>
              {isCampaignFullySkipped(campaign) ? (
                <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                  这批没有真正发出邮件。系统检查了 {campaign.total_count} 位红人，但全部被自动跳过。
                  {buildSkipReasonSummary(recipients).length ? (
                    <span className="ml-1">
                      跳过原因：
                      {buildSkipReasonSummary(recipients)
                        .map((item) => `${item.reason} ${item.count}`)
                        .join("；")}
                    </span>
                  ) : null}
                </div>
              ) : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>红人发送明细</CardTitle>
              <CardDescription>这里是当前批次的数据，不会重新生成话术，也不会发送邮件。</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="mb-4 flex flex-wrap gap-2">
                {CAMPAIGN_DETAIL_TABS.map((tab) => (
                  <Button
                    key={tab.key}
                    size="sm"
                    variant={activeTab === tab.key ? "default" : "outline"}
                    onClick={() => setActiveTab(tab.key)}
                  >
                    {tab.label} {tabCounts.get(tab.key) ?? 0}
                  </Button>
                ))}
              </div>

              {paged.items.length === 0 ? (
                <EmptyState title="当前分类没有记录" description="可以切换上方分类查看其它状态。" />
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[980px] text-sm">
                    <thead>
                      <tr className="border-b text-left text-muted-foreground">
                        <th className="pb-2 pr-3">红人</th>
                        <th className="pb-2 pr-3">邮箱</th>
                        <th className="pb-2 pr-3">状态</th>
                        <th className="pb-2 pr-3">邮件标题</th>
                        <th className="pb-2 pr-3">跳过/失败原因</th>
                        <th className="pb-2 pr-3">回复摘要</th>
                        <th className="pb-2">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {paged.items.map((row) => (
                        <tr key={row.influencer_id} className="border-b align-top last:border-0">
                          <td className="py-2 pr-3">
                            <div className="font-medium">{row.display_name || row.username || row.influencer_id}</div>
                            <div className="text-xs text-muted-foreground">@{row.username}</div>
                          </td>
                          <td className="py-2 pr-3">{row.recipient || "-"}</td>
                          <td className="py-2 pr-3">
                            <div>{getOutreachDraftStatusLabel(row.draft_status)}</div>
                            <div className="text-xs text-muted-foreground">
                              {sendStatusLabel(row.send_status)} / {getReplyStatusLabel(row.reply_status)}
                            </div>
                            {row.is_high_value && row.approval_block_reason ? (
                              <div className="mt-1 text-xs text-amber-700">高价值，需打开确认</div>
                            ) : null}
                          </td>
                          <td className="max-w-[220px] py-2 pr-3">{truncate(row.subject || "-", 80)}</td>
                          <td className="max-w-[220px] py-2 pr-3 text-xs text-muted-foreground">
                            {truncate(row.skip_reason || row.match_method || "-", 90)}
                          </td>
                          <td className="max-w-[220px] py-2 pr-3 text-xs">
                            {row.reply_snippet ? (
                              <>
                                <div>{truncate(row.reply_snippet, 80)}</div>
                                <div className="text-muted-foreground">{formatDateTime(row.reply_time)}</div>
                              </>
                            ) : (
                              "-"
                            )}
                          </td>
                          <td className="py-2">
                            <div className="flex flex-wrap gap-2">
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => void runDraftAction(row.influencer_id, "open")}
                                disabled={busyInfluencerId === row.influencer_id}
                              >
                                打开
                              </Button>
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => void runDraftAction(row.influencer_id, "edit")}
                                disabled={busyInfluencerId === row.influencer_id || row.draft_status === "queued" || row.draft_status === "sent"}
                              >
                                编辑
                              </Button>
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => void runDraftAction(row.influencer_id, "regenerate")}
                                disabled={busyInfluencerId === row.influencer_id || row.draft_status === "queued" || row.draft_status === "sent"}
                              >
                                重生成
                              </Button>
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => void runDraftAction(row.influencer_id, "skip")}
                                disabled={busyInfluencerId === row.influencer_id || row.draft_status === "queued" || row.draft_status === "sent"}
                              >
                                跳过
                              </Button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-sm">
                <div className="text-muted-foreground">
                  共 {paged.total} 条，第 {paged.page} / {paged.totalPages} 页
                </div>
                <div className="flex items-center gap-2">
                  <select
                    className="h-8 rounded-md border bg-background px-2 text-sm"
                    value={pageSize}
                    onChange={(event) => setPageSize(Number(event.target.value))}
                  >
                    <option value={20}>每页 20 条</option>
                    <option value={50}>每页 50 条</option>
                  </select>
                  <Button size="sm" variant="outline" disabled={paged.page <= 1} onClick={() => setPage((v) => v - 1)}>
                    <ChevronLeft className="h-4 w-4" />
                    上一页
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={paged.page >= paged.totalPages}
                    onClick={() => setPage((v) => v + 1)}
                  >
                    下一页
                    <ChevronRight className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {expanded ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <Card className="max-h-[86vh] w-full max-w-3xl overflow-y-auto">
            <CardHeader>
              <CardTitle>{expanded.display_name || expanded.username}</CardTitle>
              <CardDescription>{expanded.recipient || "无邮箱"}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <p className="text-xs font-medium text-muted-foreground">邮件标题</p>
                <p className="mt-1 text-sm">{expanded.subject || "-"}</p>
              </div>
              <div>
                <p className="text-xs font-medium text-muted-foreground">邮件正文</p>
                <p className="mt-1 whitespace-pre-wrap rounded-md border bg-muted/20 p-3 text-sm leading-6">
                  {expanded.body || "-"}
                </p>
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                <div>
                  <p className="text-xs font-medium text-muted-foreground">AI 生成理由</p>
                  <p className="mt-1 text-sm">{expanded.reason || "-"}</p>
                </div>
                <div>
                  <p className="text-xs font-medium text-muted-foreground">使用话术</p>
                  <p className="mt-1 text-sm">{expanded.template_title || "-"}</p>
                </div>
              </div>
              <div>
                <p className="text-xs font-medium text-muted-foreground">匹配知识库</p>
                <p className="mt-1 text-sm">
                  {expanded.matched_knowledge.length
                    ? expanded.matched_knowledge
                        .map((item) => `${item.document}${item.summary ? `：${item.summary}` : ""}`)
                        .join("；")
                    : "未引用知识库"}
                </p>
              </div>
              <div className="flex justify-end">
                <Button variant="outline" onClick={() => setExpandedId(null)}>
                  关闭
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      ) : null}
    </AdminShell>
  );
}
