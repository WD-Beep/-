"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Inbox, Loader2, RefreshCw, Trash2 } from "lucide-react";

import { AdminShell } from "@/components/layout/admin-shell";
import { useActiveProductId } from "@/components/providers/product-provider";
import { EmptyState, ErrorAlert, SuccessAlert } from "@/components/shared/page-states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  deleteEmailReplies,
  fetchEmailReplies,
  fetchInfluencers,
  fetchOutreachCampaigns,
  pollImapInbox,
  sendEmailReplyResponse,
  updateEmailReply,
  type EmailReply,
  type Influencer,
  type OutreachCampaign,
} from "@/lib/api";
import {
  filterEmailRepliesForCenter,
  getSelectableReplyIds,
  getEmailReplyIntentLabel,
  getEmailReplyInfluencerDisplay,
  getEmailReplyMatchCandidates,
  buildEmailReplyResponseDraft,
  getEmailReplyProcessingLabel,
  type EmailReplyCenterView,
} from "@/lib/email-reply-helpers";
import { ALL_PRODUCTS_ID } from "@/lib/product-context";

const PAGE_SIZE = 100;

const VIEW_TABS: Array<{ key: EmailReplyCenterView; label: string }> = [
  { key: "all", label: "全部回复" },
  { key: "unprocessed", label: "未处理" },
  { key: "interested", label: "有意向" },
  { key: "follow_up", label: "需跟进" },
  { key: "unmatched", label: "未匹配" },
  { key: "processed", label: "已处理" },
];

function formatDate(value: string | null | undefined): string {
  if (!value) return "-";
  return new Date(value).toLocaleString("zh-CN");
}

function truncate(text: string | null | undefined, max = 90): string {
  const value = text?.trim() ?? "";
  if (!value) return "-";
  return value.length > max ? `${value.slice(0, max)}...` : value;
}

function influencerLabel(influencer: Influencer): string {
  return `${influencer.display_name || influencer.username || influencer.id} · ${influencer.final_email || influencer.business_email || influencer.public_email || influencer.email || "无邮箱"}`;
}

function candidateLabel(candidate: { display_name?: string | null; username?: string | null; email?: string | null }): string {
  const name = candidate.display_name || candidate.username || "疑似红人";
  return candidate.email ? `${name} · ${candidate.email}` : name;
}

function isGenericReplyAddress(value: string | null | undefined): boolean {
  const email = (value || "").toLowerCase().trim();
  const local = email.split("@", 1)[0];
  return ["support", "contact", "hello", "info", "service", "noreply", "no-reply"].includes(local);
}

export function EmailRepliesPanel() {
  const productId = useActiveProductId();
  const requiresProduct = productId === ALL_PRODUCTS_ID;
  const searchParams = useSearchParams();
  const initialCampaignId = Number(searchParams.get("campaign_id"));
  const [replies, setReplies] = useState<EmailReply[]>([]);
  const [influencers, setInfluencers] = useState<Influencer[]>([]);
  const [campaigns, setCampaigns] = useState<OutreachCampaign[]>([]);
  const [activeView, setActiveView] = useState<EmailReplyCenterView>("unprocessed");
  const [campaignFilter, setCampaignFilter] = useState<number | null>(
    Number.isFinite(initialCampaignId) && initialCampaignId > 0 ? initialCampaignId : null,
  );
  const [expanded, setExpanded] = useState<EmailReply | null>(null);
  const [selectedInfluencerId, setSelectedInfluencerId] = useState("");
  const [selectedCampaignId, setSelectedCampaignId] = useState("");
  const [responseBody, setResponseBody] = useState("");
  const [responseDraftGenerated, setResponseDraftGenerated] = useState(false);
  const [loading, setLoading] = useState(true);
  const [actionId, setActionId] = useState<number | null>(null);
  const [sendingResponse, setSendingResponse] = useState(false);
  const [polling, setPolling] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [selectedReplyIds, setSelectedReplyIds] = useState<Set<number>>(() => new Set());
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [replyData, influencerData, campaignData] = await Promise.all([
        fetchEmailReplies({ page: 1, pageSize: PAGE_SIZE }),
        fetchInfluencers(1, 100, { hasEmail: true }),
        fetchOutreachCampaigns(),
      ]);
      setReplies(replyData.items);
      setInfluencers(influencerData.items);
      setCampaigns(campaignData);
      setSelectedReplyIds(new Set());
    } catch (err) {
      setError(err instanceof Error ? err.message : "鍥炲鍒楄〃鍔犺浇澶辫触");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    queueMicrotask(() => {
      void load();
    });
  }, [load, productId]);

  const visibleReplies = useMemo(
    () => filterEmailRepliesForCenter(replies, { view: activeView, campaignId: campaignFilter }),
    [activeView, campaignFilter, replies],
  );

  const counts = useMemo(() => {
    const map = new Map<EmailReplyCenterView, number>();
    for (const tab of VIEW_TABS) {
      map.set(tab.key, filterEmailRepliesForCenter(replies, { view: tab.key, campaignId: campaignFilter }).length);
    }
    return map;
  }, [campaignFilter, replies]);

  const influencerMap = useMemo(() => new Map(influencers.map((item) => [item.id, item])), [influencers]);
  const campaignMap = useMemo(() => new Map(campaigns.map((item) => [item.id, item])), [campaigns]);
  const visibleReplyIds = useMemo(() => getSelectableReplyIds(visibleReplies), [visibleReplies]);
  const selectedVisibleIds = useMemo(
    () => visibleReplyIds.filter((id) => selectedReplyIds.has(id)),
    [selectedReplyIds, visibleReplyIds],
  );
  const allVisibleSelected =
    visibleReplyIds.length > 0 && selectedVisibleIds.length === visibleReplyIds.length;

  async function handlePoll() {
    if (requiresProduct) {
      setError("请先选择具体产品后再收取红人回复");
      return;
    }
    setPolling(true);
    setError(null);
    setNotice(null);
    try {
      const result = await pollImapInbox(true);
      if (result.processed === 0) {
        setNotice("没有新的未读回复");
      } else {
        setNotice(`已拉取 ${result.processed} 封邮件，入库 ${result.ingested} 封`);
      }
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "收取邮箱回复失败");
    } finally {
      setPolling(false);
    }
  }

  async function patchReply(reply: EmailReply, payload: Parameters<typeof updateEmailReply>[1]) {
    setActionId(reply.id);
    setError(null);
    try {
      await updateEmailReply(reply.id, payload);
      await load();
      const fresh = replies.find((item) => item.id === reply.id);
      if (expanded?.id === reply.id && fresh) setExpanded(fresh);
    } catch (err) {
      setError(err instanceof Error ? err.message : "更新回复状态失败");
    } finally {
      setActionId(null);
    }
  }

  async function markReplyViewed(reply: EmailReply): Promise<EmailReply> {
    if (reply.viewed_at || requiresProduct) return reply;
    const updated = await updateEmailReply(reply.id, { mark_viewed: true });
    setReplies((current) => current.map((item) => (item.id === updated.id ? updated : item)));
    window.dispatchEvent(new Event("email-replies:work-count-changed"));
    return updated;
  }

  async function handleManualLink(reply: EmailReply) {
    const influencerId = Number(selectedInfluencerId);
    const campaignId = selectedCampaignId ? Number(selectedCampaignId) : undefined;
    if (!Number.isFinite(influencerId) || influencerId <= 0) {
      setError("请先选择要关联的红人");
      return;
    }
    await patchReply(reply, {
      product_influencer_id: influencerId,
      campaign_id: campaignId,
      intent_status: reply.intent_status === "unmatched" ? "unprocessed" : reply.intent_status,
    });
  }

  async function openReplyDetail(reply: EmailReply) {
    const target = await markReplyViewed(reply);
    setExpanded(target);
    setResponseBody("");
    setResponseDraftGenerated(false);
  }

  async function openReplyComposer(reply: EmailReply) {
    const target = await markReplyViewed(reply);
    setExpanded(target);
    const influencer = target.product_influencer_id ? influencerMap.get(target.product_influencer_id) : null;
    setResponseBody(
      buildEmailReplyResponseDraft({
        influencerName: influencer?.display_name || influencer?.username || null,
        intentStatus: target.intent_status,
      }),
    );
    setResponseDraftGenerated(true);
  }

  function handleGenerateResponseDraft(reply: EmailReply) {
    const influencer = reply.product_influencer_id ? influencerMap.get(reply.product_influencer_id) : null;
    setResponseBody(
      buildEmailReplyResponseDraft({
        influencerName: influencer?.display_name || influencer?.username || null,
        intentStatus: reply.intent_status,
      }),
    );
    setResponseDraftGenerated(true);
  }

  async function handleSendResponse(reply: EmailReply) {
    if (!responseBody.trim()) {
      setError("请先填写回复正文");
      return;
    }
    setSendingResponse(true);
    setError(null);
    setNotice(null);
    try {
      const result = await sendEmailReplyResponse(reply.id, {
        body: responseBody,
        use_ai_draft: responseDraftGenerated,
        mark_processed: true,
      });
      if (!result.sent) {
        setError(result.error || "发送回复失败");
        return;
      }
      setNotice("回复已发送，邮箱服务已接受发送");
      await load();
      setExpanded(null);
      setResponseBody("");
      setResponseDraftGenerated(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "发送回复失败");
    } finally {
      setSendingResponse(false);
    }
  }

  function toggleReplySelection(replyId: number, checked: boolean) {
    setSelectedReplyIds((current) => {
      const next = new Set(current);
      if (checked) {
        next.add(replyId);
      } else {
        next.delete(replyId);
      }
      return next;
    });
  }

  function toggleAllVisible(checked: boolean) {
    setSelectedReplyIds((current) => {
      const next = new Set(current);
      for (const replyId of visibleReplyIds) {
        if (checked) {
          next.add(replyId);
        } else {
          next.delete(replyId);
        }
      }
      return next;
    });
  }

  async function handleBulkDelete() {
    if (requiresProduct) {
      setError("请先选择具体产品后再删除回复");
      return;
    }
    const ids = selectedVisibleIds;
    if (ids.length === 0) {
      setError("请先勾选要删除的回复");
      return;
    }
    const confirmed = window.confirm(
      `确定删除已勾选的 ${ids.length} 封回复吗？删除后不会再出现在回复中心。`,
    );
    if (!confirmed) return;
    setDeleting(true);
    setError(null);
    setNotice(null);
    try {
      const result = await deleteEmailReplies(ids);
      setNotice(`已删除 ${result.deleted_count} 封回复`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "鍒犻櫎鍥炲澶辫触锛岃绋嶅悗鍐嶈瘯");
    } finally {
      setDeleting(false);
    }
  }

  return (
    <AdminShell
      title="红人回复"
      description="集中查看红人邮件回复，处理未读线索和未匹配邮件。"
      actions={
        <>
          <Button variant="outline" onClick={() => void load()} disabled={loading}>
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            刷新
          </Button>
          <Button onClick={() => void handlePoll()} disabled={requiresProduct || polling}>
            {polling ? <Loader2 className="h-4 w-4 animate-spin" /> : <Inbox className="h-4 w-4" />}
            收取未读回复
          </Button>
        </>
      }
    >
      <div className="flex h-full min-h-0 flex-col gap-4">
        {error ? <ErrorAlert message={error} onRetry={() => void load()} /> : null}
        {notice ? <SuccessAlert message={notice} /> : null}
        {requiresProduct ? (
          <ErrorAlert message="总盘模式可以查看全部回复；收取、回复或删除前请先选择具体产品。" />
        ) : null}

        <section className="ops-panel shrink-0 p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap gap-2">
              {VIEW_TABS.map((tab) => (
                <Button
                  key={tab.key}
                  size="sm"
                  variant={activeView === tab.key ? "default" : "outline"}
                  onClick={() => setActiveView(tab.key)}
                >
                  {tab.label} {counts.get(tab.key) ?? 0}
                </Button>
              ))}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                size="sm"
                variant="destructive"
                onClick={() => void handleBulkDelete()}
                disabled={requiresProduct || deleting || selectedVisibleIds.length === 0}
              >
                {deleting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
                删除已选{selectedVisibleIds.length > 0 ? ` ${selectedVisibleIds.length}` : ""}
              </Button>
              <select
                className="h-9 rounded-md border bg-background px-3 text-sm"
                value={campaignFilter ?? ""}
                onChange={(event) => setCampaignFilter(event.target.value ? Number(event.target.value) : null)}
              >
                <option value="">全部活动</option>
                {campaigns.map((campaign) => (
                  <option key={campaign.id} value={campaign.id}>
                    {campaign.name}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </section>

        <section className="ops-panel flex min-h-0 flex-1 flex-col overflow-hidden">
          {loading ? (
            <div className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" /> 正在加载回复...
            </div>
          ) : visibleReplies.length === 0 ? (
            <EmptyState title="暂无符合条件的回复" description="可以切换筛选，或在具体产品下收取未读回复。" />
          ) : (
            <div className="min-h-0 flex-1 overflow-auto overscroll-contain">
              <table className="w-full min-w-[1080px] text-sm">
                <thead className="sticky top-0 z-10 bg-[hsl(210_30%_99%)]">
                  <tr className="border-b text-left text-muted-foreground shadow-[0_1px_0_hsl(214_24%_88%)]">
                    <th className="w-12 px-4 py-3">
                      <input
                        type="checkbox"
                        aria-label="全选当前回复"
                        checked={allVisibleSelected}
                        onChange={(event) => toggleAllVisible(event.target.checked)}
                      />
                    </th>
                    <th className="px-4 py-3">红人 / 邮箱</th>
                    <th className="px-4 py-3">主题 / 摘要</th>
                    <th className="px-4 py-3">活动</th>
                    <th className="px-4 py-3">状态</th>
                    <th className="px-4 py-3">回复时间</th>
                    <th className="px-4 py-3">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleReplies.map((reply) => {
                    const influencer = reply.product_influencer_id ? influencerMap.get(reply.product_influencer_id) : null;
                    const campaign = reply.campaign_id ? campaignMap.get(reply.campaign_id) : null;
                    const matchCandidates = getEmailReplyMatchCandidates(reply);
                    return (
                      <tr
                        key={reply.id}
                        className={`border-b align-top last:border-0 ${reply.viewed_at ? "" : "bg-rose-50/45"}`}
                      >
                        <td className="px-4 py-3">
                          <input
                            type="checkbox"
                            aria-label={`选择回复 ${reply.id}`}
                            checked={selectedReplyIds.has(reply.id)}
                            onChange={(event) => toggleReplySelection(reply.id, event.target.checked)}
                          />
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2 font-medium">
                            {!reply.viewed_at ? (
                              <span
                                className="h-2.5 w-2.5 shrink-0 rounded-full bg-rose-500 shadow-[0_0_0_3px_rgba(244,63,94,0.12)]"
                                title="业务员还未查看这封回复"
                              />
                            ) : null}
                            {influencer ? (
                              <Link className="hover:underline" href={`/influencers/${influencer.id}`}>
                                {getEmailReplyInfluencerDisplay(reply, influencer)}
                              </Link>
                            ) : matchCandidates.length > 0 ? (
                              <span className="text-amber-700">疑似匹配：{candidateLabel(matchCandidates[0])}</span>
                            ) : (
                              <span className="text-amber-700">未自动关联</span>
                            )}
                          </div>
                          <div className="mt-1 break-all text-xs text-muted-foreground">{reply.from_address}</div>
                          {!influencer && matchCandidates.length > 0 ? (
                            <div className="mt-2 flex flex-wrap gap-1.5">
                              {matchCandidates.slice(0, 3).map((candidate) => (
                                <Button
                                  key={candidate.product_influencer_id}
                                  size="sm"
                                  variant="outline"
                                  disabled={actionId === reply.id}
                                  onClick={() =>
                                    void patchReply(reply, {
                                      product_influencer_id: candidate.product_influencer_id,
                                      campaign_id: candidate.campaign_id ?? undefined,
                                      intent_status: reply.intent_status === "unmatched" ? "unprocessed" : reply.intent_status,
                                    })
                                  }
                                >
                                  确认关联
                                </Button>
                              ))}
                            </div>
                          ) : null}
                        </td>
                        <td className="max-w-[320px] px-4 py-3">
                          <div className="font-medium">{truncate(reply.subject || "(无标题)", 90)}</div>
                          <div className="mt-1 text-xs text-muted-foreground">{truncate(reply.snippet || reply.body, 120)}</div>
                        </td>
                        <td className="px-4 py-3">
                          {campaign ? (
                            <Link className="hover:underline" href={`/outreach-campaigns/${campaign.id}?tab=replied`}>
                              {campaign.name}
                            </Link>
                          ) : (
                            <span className="text-muted-foreground">未关联活动</span>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex flex-wrap gap-1.5">
                            <Badge variant={reply.processing_status === "processed" ? "secondary" : "warning"}>
                              {getEmailReplyProcessingLabel(reply.processing_status)}
                            </Badge>
                            <Badge variant={reply.intent_status === "interested" ? "success" : "outline"}>
                              {getEmailReplyIntentLabel(reply.intent_status)}
                            </Badge>
                          </div>
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-xs text-muted-foreground">
                          {formatDate(reply.received_at)}
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex flex-wrap gap-1.5">
                            <Button size="sm" variant={reply.viewed_at ? "outline" : "default"} onClick={() => void openReplyDetail(reply)}>
                              查看
                            </Button>
                            <Button size="sm" variant="outline" onClick={() => void openReplyComposer(reply)}>
                              回复
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              disabled={actionId === reply.id}
                              onClick={() => void patchReply(reply, { intent_status: "interested" })}
                            >
                              有意向
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              disabled={actionId === reply.id}
                              onClick={() => void patchReply(reply, { intent_status: "follow_up" })}
                            >
                              需跟进
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              disabled={actionId === reply.id}
                              onClick={() => void patchReply(reply, { intent_status: "not_interested", processing_status: "processed" })}
                            >
                              无意向
                            </Button>
                            <Button
                              size="sm"
                              variant="outline"
                              disabled={actionId === reply.id}
                              onClick={() => void patchReply(reply, { processing_status: "processed", intent_status: reply.intent_status === "unmatched" ? "processed" : reply.intent_status })}
                            >
                              已处理
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
        </section>
      </div>

      {expanded ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="flex max-h-[88vh] w-full max-w-4xl flex-col overflow-hidden rounded-lg border bg-background shadow-xl">
            <div className="flex shrink-0 flex-wrap items-start justify-between gap-3 border-b px-6 py-4">
              <div>
                <h2 className="text-lg font-semibold">{expanded.subject || "(无标题)"}</h2>
                <p className="mt-1 break-all text-sm text-muted-foreground">
                  {expanded.from_address} → {expanded.to_address} · {formatDate(expanded.received_at)}
                </p>
              </div>
              <Button variant="outline" onClick={() => setExpanded(null)}>
                关闭
              </Button>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
              <pre className="max-h-[52vh] overflow-auto whitespace-pre-wrap break-words rounded-md border bg-muted/20 p-4 text-sm leading-6">
                {expanded.body || expanded.snippet || "没有正文内容"}
              </pre>
              <div className="mt-4 space-y-3 rounded-md border bg-muted/10 p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <h3 className="text-sm font-semibold">回复红人</h3>
                    <p className="mt-1 break-all text-xs text-muted-foreground">
                      {expanded.product_influencer_id
                        ? getEmailReplyInfluencerDisplay(expanded, influencerMap.get(expanded.product_influencer_id))
                        : "当前未自动关联红人，建议先关联后发送。"}
                      {" · "}
                      {expanded.from_address}
                      {expanded.campaign_id && campaignMap.get(expanded.campaign_id)
                        ? ` · ${campaignMap.get(expanded.campaign_id)?.name}`
                        : ""}
                    </p>
                  </div>
                  {isGenericReplyAddress(expanded.from_address) ? (
                    <Badge variant="warning">这是通用邮箱，请确认对方身份</Badge>
                  ) : null}
                </div>
                {!expanded.product_influencer_id ? (
                  <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                    当前未自动关联红人，建议先关联后发送。
                  </div>
                ) : null}
                <textarea
                  className="min-h-36 w-full resize-y rounded-md border bg-background p-3 text-sm leading-6"
                  value={responseBody}
                  onChange={(event) => {
                    setResponseBody(event.target.value);
                    setResponseDraftGenerated(false);
                  }}
                  placeholder="编辑要发送给红人的回复内容"
                />
                <div className="flex flex-wrap justify-end gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => handleGenerateResponseDraft(expanded)}
                    disabled={sendingResponse}
                  >
                    生成回复话术
                  </Button>
                  <Button
                    type="button"
                    onClick={() => void handleSendResponse(expanded)}
                    disabled={sendingResponse || !responseBody.trim()}
                  >
                    {sendingResponse ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                    发送回复
                  </Button>
                </div>
              </div>
            </div>

            <div className="shrink-0 border-t bg-background px-6 py-4">
              <div className="grid min-w-0 gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] md:items-end">
                <label className="space-y-1 text-sm">
                  <span className="font-medium">手动关联红人</span>
                  <select
                    className="h-9 w-full rounded-md border bg-background px-3"
                    value={selectedInfluencerId}
                    onChange={(event) => setSelectedInfluencerId(event.target.value)}
                  >
                    <option value="">选择红人</option>
                    {influencers.map((item) => (
                      <option key={item.id} value={item.id}>
                        {influencerLabel(item)}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="space-y-1 text-sm">
                  <span className="font-medium">手动关联活动</span>
                  <select
                    className="h-9 w-full rounded-md border bg-background px-3"
                    value={selectedCampaignId}
                    onChange={(event) => setSelectedCampaignId(event.target.value)}
                  >
                    <option value="">不关联活动</option>
                    {campaigns.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name}
                      </option>
                    ))}
                  </select>
                </label>
                <Button
                  className="h-9 whitespace-nowrap"
                  onClick={() => void handleManualLink(expanded)}
                  disabled={actionId === expanded.id}
                >
                  保存关联
                </Button>
              </div>
            </div>
          </div>
        </div>
      ) : null}
    </AdminShell>
  );
}
