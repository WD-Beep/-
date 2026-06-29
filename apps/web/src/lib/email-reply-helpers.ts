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
};

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
