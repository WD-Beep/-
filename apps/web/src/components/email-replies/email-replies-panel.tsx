"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
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
  pollImapInbox,
  rematchEmailReply,
  sendEmailReplyResponse,
  updateEmailReply,
  type EmailReply,
  type Influencer,
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
  return `${influencer.display_name || influencer.username || influencer.id} \u00b7 ${influencer.final_email || influencer.business_email || influencer.public_email || influencer.email || "\u65e0\u90ae\u7bb1"}`;
}

function candidateLabel(candidate: { display_name?: string | null; username?: string | null; email?: string | null }): string {
  const name = candidate.display_name || candidate.username || "疑似红人";
  return candidate.email ? `${name} \u00b7 ${candidate.email}` : name;
}

function isGenericReplyAddress(value: string | null | undefined): boolean {
  const email = (value || "").toLowerCase().trim();
  const local = email.split("@", 1)[0];
  return ["support", "contact", "hello", "info", "service", "noreply", "no-reply"].includes(local);
}

export function EmailRepliesPanel() {
  const productId = useActiveProductId();
  const requiresProduct = productId === ALL_PRODUCTS_ID;
  const [replies, setReplies] = useState<EmailReply[]>([]);
  const [influencers, setInfluencers] = useState<Influencer[]>([]);
  const [influencersLoading, setInfluencersLoading] = useState(false);
  const [influencersLoaded, setInfluencersLoaded] = useState(false);
  const influencersPromiseRef = useRef<Promise<Influencer[]> | null>(null);
  const [activeView, setActiveView] = useState<EmailReplyCenterView>("unprocessed");
  const [expanded, setExpanded] = useState<EmailReply | null>(null);
  const [noteEditingReply, setNoteEditingReply] = useState<EmailReply | null>(null);
  const [noteDraft, setNoteDraft] = useState("");
  const [selectedInfluencerId, setSelectedInfluencerId] = useState("");
  const [responseBody, setResponseBody] = useState("");
  const [responseDraftGenerated, setResponseDraftGenerated] = useState(false);
  const [loading, setLoading] = useState(true);
  const [actionId, setActionId] = useState<number | null>(null);
  const [sendingResponse, setSendingResponse] = useState(false);
  const [savingNote, setSavingNote] = useState(false);
  const [polling, setPolling] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [selectedReplyIds, setSelectedReplyIds] = useState<Set<number>>(() => new Set());
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const replyData = await fetchEmailReplies({ page: 1, pageSize: PAGE_SIZE });
      setReplies(replyData.items);
      setSelectedReplyIds(new Set());
    } catch (err) {
      setError(err instanceof Error ? err.message : "回复列表加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    queueMicrotask(() => {
      void load();
    });
  }, [load, productId]);

  const ensureInfluencers = useCallback(async (): Promise<Influencer[]> => {
    if (influencersLoaded) return influencers;
    if (influencersPromiseRef.current) return influencersPromiseRef.current;
    setInfluencersLoading(true);
    const promise = fetchInfluencers(1, 100, { hasEmail: true })
      .then((data) => {
        setInfluencers(data.items);
        setInfluencersLoaded(true);
        return data.items;
      })
      .catch(() => [])
      .finally(() => {
        setInfluencersLoading(false);
        influencersPromiseRef.current = null;
      });
    influencersPromiseRef.current = promise;
    return promise;
  }, [influencers, influencersLoaded]);

  const visibleReplies = useMemo(
    () => filterEmailRepliesForCenter(replies, { view: activeView }),
    [activeView, replies],
  );

  const counts = useMemo(() => {
    const map = new Map<EmailReplyCenterView, number>();
    for (const tab of VIEW_TABS) {
      map.set(tab.key, filterEmailRepliesForCenter(replies, { view: tab.key }).length);
    }
    return map;
  }, [replies]);

  const influencerMap = useMemo(() => new Map(influencers.map((item) => [item.id, item])), [influencers]);
  const visibleReplyIds = useMemo(() => getSelectableReplyIds(visibleReplies), [visibleReplies]);
  const selectedVisibleIds = useMemo(
    () => visibleReplyIds.filter((id) => selectedReplyIds.has(id)),
    [selectedReplyIds, visibleReplyIds],
  );
  const allVisibleSelected =
    visibleReplyIds.length > 0 && selectedVisibleIds.length === visibleReplyIds.length;

  async function handlePoll() {
    if (requiresProduct) {
      setError("\u8bf7\u5148\u9009\u62e9\u5177\u4f53\u4ea7\u54c1\u540e\u518d\u6536\u53d6\u7ea2\u4eba\u56de\u590d");
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
        setNotice(`\u5df2\u62c9\u53d6 ${result.processed} \u5c01\u90ae\u4ef6\uff0c\u5165\u5e93 ${result.ingested} \u5c01`);
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
    if (!Number.isFinite(influencerId) || influencerId <= 0) {
      setError("\u8bf7\u5148\u9009\u62e9\u8981\u5173\u8054\u7684\u7ea2\u4eba");
      return;
    }
    await patchReply(reply, {
      product_influencer_id: influencerId,
      intent_status: reply.intent_status === "unmatched" ? "unprocessed" : reply.intent_status,
    });
  }

  async function openReplyDetail(reply: EmailReply) {
    const target = await markReplyViewed(reply);
    setExpanded(target);
    setResponseBody("");
    setResponseDraftGenerated(false);
    void ensureInfluencers();
  }

  async function openReplyComposer(reply: EmailReply) {
    const target = await markReplyViewed(reply);
    setExpanded(target);
    let influencer = target.product_influencer_id ? influencerMap.get(target.product_influencer_id) : null;
    if (target.product_influencer_id && !influencer) {
      const loaded = await ensureInfluencers();
      influencer = loaded.find((item) => item.id === target.product_influencer_id) ?? null;
    }
    setResponseBody(
      buildEmailReplyResponseDraft({
        influencerName: influencer?.display_name || influencer?.username || null,
        intentStatus: target.intent_status,
      }),
    );
    setResponseDraftGenerated(true);
  }

  async function rematchReplyForAction(reply: EmailReply): Promise<EmailReply> {
    if (reply.product_influencer_id || requiresProduct) return reply;
    setActionId(reply.id);
    setError(null);
    setNotice(null);
    try {
      const updated = await rematchEmailReply(reply.id);
      setReplies((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      if (expanded?.id === updated.id) setExpanded(updated);
      return updated;
    } finally {
      setActionId(null);
    }
  }

  async function openInfluencerInfo(reply: EmailReply) {
    try {
      const target = await rematchReplyForAction(reply);
      if (target.product_influencer_id) {
        window.location.href = `/influencers/${target.product_influencer_id}`;
        return;
      }
      setNotice("暂未找到对应红人信息，可稍后刷新或检查原发送记录。");
    } catch (err) {
      setError(err instanceof Error ? err.message : "暂未找到对应红人信息");
    }
  }

  async function openSocialLink(reply: EmailReply) {
    try {
      const target = await rematchReplyForAction(reply);
      let influencer = target.product_influencer_id ? influencerMap.get(target.product_influencer_id) : null;
      if (target.product_influencer_id && !influencer) {
        const loaded = await ensureInfluencers();
        influencer = loaded.find((item) => item.id === target.product_influencer_id) ?? null;
      }
      if (influencer?.profile_url) {
        window.open(influencer.profile_url, "_blank", "noopener,noreferrer");
        return;
      }
      setNotice("暂未找到对应红人信息或社媒链接，可稍后刷新或检查原发送记录。");
    } catch (err) {
      setError(err instanceof Error ? err.message : "暂未找到对应红人信息");
    }
  }

  function openNoteEditor(reply: EmailReply) {
    setNoteEditingReply(reply);
    setNoteDraft(reply.manual_note ?? "");
    setError(null);
    setNotice(null);
  }

  async function saveReplyNote() {
    if (!noteEditingReply) return;
    setSavingNote(true);
    setError(null);
    setNotice(null);
    try {
      const updated = await updateEmailReply(noteEditingReply.id, {
        manual_note: noteDraft.trim() || null,
      });
      setReplies((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      if (expanded?.id === updated.id) setExpanded(updated);
      setNoteEditingReply(null);
      setNoteDraft("");
      setNotice("跟进备注已保存");
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存跟进备注失败");
    } finally {
      setSavingNote(false);
    }
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
      setNotice("回复已发送，并已标记为已处理");
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
      setError(err instanceof Error ? err.message : "删除回复失败，请稍后再试");
    } finally {
      setDeleting(false);
    }
  }

  return (
    <AdminShell
      title="红人回复"
      description={"\u96c6\u4e2d\u67e5\u770b\u7ea2\u4eba\u90ae\u4ef6\u56de\u590d\uff0c\u4f18\u5148\u5904\u7406\u672a\u67e5\u770b\u3001\u672a\u5339\u914d\u90ae\u4ef6\u3002"}
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
          <ErrorAlert message={"\u5168\u90e8\u4ea7\u54c1\u6a21\u5f0f\u4e0b\u53ef\u4ee5\u67e5\u770b\u5168\u90e8\u56de\u590d\uff1b\u6536\u53d6\u65b0\u56de\u590d\u6216\u5220\u9664\u524d\uff0c\u8bf7\u5148\u9009\u62e9\u5177\u4f53\u4ea7\u54c1\u3002"} />
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
            </div>
          </div>
        </section>

        <section className="ops-panel flex min-h-0 flex-1 flex-col overflow-hidden">
          {loading ? (
            <div className="flex items-center gap-2 p-6 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" /> 正在加载回复...
            </div>
          ) : visibleReplies.length === 0 ? (
            <EmptyState title={"\u6682\u65e0\u7b26\u5408\u6761\u4ef6\u7684\u56de\u590d"} description={"\u53ef\u4ee5\u5207\u6362\u7b5b\u9009\uff0c\u6216\u5728\u5177\u4f53\u4ea7\u54c1\u4e0b\u6536\u53d6\u672a\u8bfb\u56de\u590d\u3002"} />
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
                    <th className="px-4 py-3">状态</th>
                    <th className="px-4 py-3">回复时间</th>
                    <th className="px-4 py-3">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleReplies.map((reply) => {
                    const influencer = reply.product_influencer_id ? influencerMap.get(reply.product_influencer_id) : null;
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
                              <span className="text-amber-700">{"\u7591\u4f3c\u5339\u914d\uff1a"}{candidateLabel(matchCandidates[0])}</span>
                            ) : (
                              <span className="text-amber-700">{"\u672a\u5173\u8054\u7ea2\u4eba"}</span>
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
                                      intent_status: reply.intent_status === "unmatched" ? "unprocessed" : reply.intent_status,
                                    })
                                  }
                                >
                                  {"\u786e\u8ba4\u5173\u8054"}
                                </Button>
                              ))}
                            </div>
                          ) : null}
                        </td>
                        <td className="max-w-[320px] px-4 py-3">
                          <div className="font-medium">{truncate(reply.subject || "(无标题)", 90)}</div>
                          <div className="mt-1 text-xs text-muted-foreground">{truncate(reply.snippet || reply.body, 120)}</div>
                          {reply.manual_note ? (
                            <div className="mt-2 rounded-md border border-amber-200 bg-amber-50 px-2 py-1 text-xs text-amber-800">
                              备注：{truncate(reply.manual_note, 80)}
                            </div>
                          ) : null}
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
                            {influencer ? (
                              <Button size="sm" variant="outline" asChild>
                                <Link href={`/influencers/${influencer.id}`}>查看红人信息</Link>
                              </Button>
                            ) : (
                              <Button size="sm" variant="outline" disabled={actionId === reply.id} onClick={() => void openInfluencerInfo(reply)}>
                                查看红人信息
                              </Button>
                            )}
                            {influencer?.profile_url ? (
                              <Button size="sm" variant="outline" asChild>
                                <a href={influencer.profile_url} target="_blank" rel="noreferrer">
                                  查看社媒链接
                                </a>
                              </Button>
                            ) : (
                              <Button size="sm" variant="outline" disabled={actionId === reply.id} onClick={() => void openSocialLink(reply)}>
                                查看社媒链接
                              </Button>
                            )}
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
                            {activeView === "follow_up" || reply.intent_status === "follow_up" ? (
                              <Button
                                size="sm"
                                variant={reply.manual_note ? "default" : "outline"}
                                onClick={() => openNoteEditor(reply)}
                              >
                                备注
                              </Button>
                            ) : null}
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
                  {expanded.from_address}{" \u2192 "}{expanded.to_address}{" \u00b7 "}{formatDate(expanded.received_at)}
                </p>
              </div>
              <Button variant="outline" onClick={() => setExpanded(null)}>
                {"\u5173\u95ed"}
              </Button>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
              <pre className="max-h-[52vh] overflow-auto whitespace-pre-wrap break-words rounded-md border bg-muted/20 p-4 text-sm leading-6">
                {expanded.body || expanded.snippet || "没有邮件正文"}
              </pre>
              <div className="mt-4 space-y-3 rounded-md border bg-muted/10 p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <h3 className="text-sm font-semibold">回复处理</h3>
                    <p className="mt-1 break-all text-xs text-muted-foreground">
                      {expanded.product_influencer_id
                        ? getEmailReplyInfluencerDisplay(expanded, influencerMap.get(expanded.product_influencer_id))
                        : "\u5f53\u524d\u672a\u5173\u8054\u7ea2\u4eba\uff0c\u5efa\u8bae\u5148\u5173\u8054\u540e\u53d1\u9001\u3002"}
                      {" \u00b7 "}
                      {expanded.from_address}
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    {expanded.product_influencer_id && influencerMap.get(expanded.product_influencer_id) ? (
                      <>
                        <Button size="sm" variant="outline" asChild>
                          <Link href={`/influencers/${influencerMap.get(expanded.product_influencer_id)!.id}`}>
                            查看红人信息
                          </Link>
                        </Button>
                        {influencerMap.get(expanded.product_influencer_id)!.profile_url ? (
                          <Button size="sm" variant="outline" asChild>
                            <a
                              href={influencerMap.get(expanded.product_influencer_id)!.profile_url}
                              target="_blank"
                              rel="noreferrer"
                            >
                              查看社媒链接
                            </a>
                          </Button>
                        ) : null}
                      </>
                    ) : null}
                    {isGenericReplyAddress(expanded.from_address) ? (
                      <Badge variant="warning">这是通用邮箱，请确认对方身份</Badge>
                    ) : null}
                  </div>
                </div>
                {!expanded.product_influencer_id ? (
                  <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                    {"\u5f53\u524d\u672a\u5173\u8054\u7ea2\u4eba\uff0c\u5efa\u8bae\u5148\u5173\u8054\u540e\u53d1\u9001\u3002"}
                  </div>
                ) : null}
                <textarea
                  className="min-h-36 w-full resize-y rounded-md border bg-background p-3 text-sm leading-6"
                  value={responseBody}
                  onChange={(event) => {
                    setResponseBody(event.target.value);
                    setResponseDraftGenerated(false);
                  }}
                  placeholder={"\u7f16\u8f91\u8981\u53d1\u9001\u7ed9\u7ea2\u4eba\u7684\u56de\u590d\u5185\u5bb9"}
                />
                <div className="flex flex-wrap justify-end gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => handleGenerateResponseDraft(expanded)}
                    disabled={sendingResponse}
                  >
                    生成回复草稿
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
              <div className="grid min-w-0 gap-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-end">
                <label className="space-y-1 text-sm">
                  <span className="font-medium">{"\u624b\u52a8\u5173\u8054\u7ea2\u4eba"}</span>
                  <select
                    className="h-9 w-full rounded-md border bg-background px-3"
                    value={selectedInfluencerId}
                    onFocus={() => void ensureInfluencers()}
                    onChange={(event) => setSelectedInfluencerId(event.target.value)}
                  >
                    <option value="">{influencersLoading ? "正在加载红人..." : "选择红人"}</option>
                    {influencers.map((item) => (
                      <option key={item.id} value={item.id}>
                        {influencerLabel(item)}
                      </option>
                    ))}
                  </select>
                </label>
                <Button
                  className="h-9 whitespace-nowrap"
                  onClick={() => void handleManualLink(expanded)}
                  disabled={actionId === expanded.id}
                >
                  {"\u5173\u8054\u7ea2\u4eba"}
                </Button>
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {noteEditingReply ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-xl rounded-lg border bg-background shadow-xl">
            <div className="border-b px-6 py-4">
              <h2 className="text-lg font-semibold">编辑跟进备注</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                给业务同事记录下一步动作、对方反馈或需要注意的点。
              </p>
            </div>
            <div className="px-6 py-4">
              <textarea
                className="min-h-40 w-full resize-y rounded-md border bg-background p-3 text-sm leading-6"
                value={noteDraft}
                onChange={(event) => setNoteDraft(event.target.value)}
                maxLength={2000}
                placeholder="例如：对方想看报价，需要明天上午确认寄样地址。"
              />
              <div className="mt-2 text-right text-xs text-muted-foreground">{noteDraft.length}/2000</div>
            </div>
            <div className="flex justify-end gap-2 border-t px-6 py-4">
              <Button
                type="button"
                variant="outline"
                disabled={savingNote}
                onClick={() => {
                  setNoteEditingReply(null);
                  setNoteDraft("");
                }}
              >
                取消
              </Button>
              <Button type="button" disabled={savingNote} onClick={() => void saveReplyNote()}>
                {savingNote ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                保存备注
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </AdminShell>
  );
}
