export type EmailReplyCenterView =
  | "all"
  | "unprocessed"
  | "interested"
  | "follow_up"
  | "unmatched"
  | "processed";

export type EmailReplyCenterItem = {
  id: number;
  product_influencer_id: number | null;
  campaign_id: number | null;
  processing_status: string | null;
  intent_status: string | null;
  raw_headers?: Record<string, unknown> | null;
};

export type EmailReplyInfluencerSummary = {
  id: number;
  username: string | null;
  display_name: string | null;
  final_email?: string | null;
  business_email?: string | null;
  public_email?: string | null;
  email?: string | null;
};

export type EmailReplyMatchCandidate = {
  product_influencer_id: number;
  campaign_id?: number | null;
  display_name?: string | null;
  username?: string | null;
  email?: string | null;
  reason?: string | null;
  matched_text?: string | null;
};

function influencerEmail(influencer: EmailReplyInfluencerSummary | null | undefined): string | null {
  if (!influencer) return null;
  return influencer.final_email || influencer.business_email || influencer.public_email || influencer.email || null;
}

export function getEmailReplyInfluencerDisplay(
  reply: EmailReplyCenterItem,
  influencer: EmailReplyInfluencerSummary | null | undefined,
): string {
  if (!reply.product_influencer_id || !influencer) return "未自动关联";
  const name = influencer.display_name || influencer.username || String(influencer.id);
  const email = influencerEmail(influencer);
  return email ? `${name} · ${email}` : name;
}

export function getEmailReplyMatchCandidates(reply: EmailReplyCenterItem): EmailReplyMatchCandidate[] {
  const replyMatch = reply.raw_headers?.reply_match;
  if (!replyMatch || typeof replyMatch !== "object" || !("candidates" in replyMatch)) return [];
  const candidates = (replyMatch as { candidates?: unknown }).candidates;
  if (!Array.isArray(candidates)) return [];
  return candidates.filter((candidate): candidate is EmailReplyMatchCandidate => {
    if (!candidate || typeof candidate !== "object") return false;
    return typeof (candidate as { product_influencer_id?: unknown }).product_influencer_id === "number";
  });
}

export function buildEmailReplyResponseDraft({
  influencerName,
  intentStatus,
}: {
  influencerName?: string | null;
  intentStatus?: string | null;
}): string {
  const name = influencerName?.trim() || "there";
  if (intentStatus === "follow_up") {
    return `Hi ${name},\n\nThanks for getting back to us. I am following up with a few more details and would be happy to answer any questions about the collaboration.\n\nBest,`;
  }
  if (intentStatus === "interested") {
    return `Hi ${name},\n\nThanks for getting back to us. We'd be happy to share more details about the collaboration, including the brief, timeline, and next steps.\n\nBest,`;
  }
  return `Hi ${name},\n\nThanks for your reply. We'd be happy to continue the conversation and share more details.\n\nBest,`;
}

export function getEmailReplyIntentLabel(status: string | null | undefined): string {
  switch (status) {
    case "interested":
      return "有意向";
    case "follow_up":
      return "需跟进";
    case "not_interested":
      return "无意向";
    case "processed":
      return "已处理";
    case "unmatched":
      return "未匹配";
    case "unprocessed":
      return "未处理";
    default:
      return status || "未处理";
  }
}

export function getEmailReplyProcessingLabel(status: string | null | undefined): string {
  return status === "processed" ? "已处理" : "未处理";
}

export function filterEmailRepliesForCenter<T extends EmailReplyCenterItem>(
  replies: T[],
  filters: { view: EmailReplyCenterView; campaignId?: number | null },
): T[] {
  return replies.filter((reply) => {
    if (filters.campaignId && reply.campaign_id !== filters.campaignId) return false;
    if (filters.view === "all") return true;
    if (filters.view === "unprocessed") return reply.processing_status !== "processed";
    if (filters.view === "unmatched") return reply.product_influencer_id === null || reply.intent_status === "unmatched";
    if (filters.view === "processed") return reply.processing_status === "processed";
    return reply.intent_status === filters.view;
  });
}

export function countUnhandledReplies(replies: EmailReplyCenterItem[]): number {
  return replies.filter((reply) => reply.processing_status !== "processed").length;
}

export function getSelectableReplyIds(replies: EmailReplyCenterItem[]): number[] {
  return replies.map((reply) => reply.id);
}
