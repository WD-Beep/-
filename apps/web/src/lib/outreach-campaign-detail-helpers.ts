export type CampaignDetailTabKey = "all" | "sent" | "skipped" | "failed" | "replied" | "unreplied";

export const CAMPAIGN_DETAIL_TABS: Array<{ key: CampaignDetailTabKey; label: string }> = [
  { key: "all", label: "全部" },
  { key: "sent", label: "已发送" },
  { key: "skipped", label: "自动跳过" },
  { key: "failed", label: "发送失败" },
  { key: "replied", label: "已回复" },
  { key: "unreplied", label: "未回复" },
];

export type CampaignDetailFilterRow = {
  send_status?: string | null;
  reply_status?: string | null;
};

export function filterCampaignDetailRows<T extends CampaignDetailFilterRow>(
  rows: T[],
  tab: CampaignDetailTabKey,
): T[] {
  if (tab === "sent") return rows.filter((row) => row.send_status === "sent");
  if (tab === "failed") return rows.filter((row) => row.send_status === "failed");
  if (tab === "skipped") return rows.filter((row) => row.send_status === "skipped");
  if (tab === "replied") {
    return rows.filter((row) => row.reply_status === "replied" || row.reply_status === "interested");
  }
  if (tab === "unreplied") return rows.filter((row) => row.reply_status === "unreplied");
  return rows;
}

export function paginateCampaignDetailRows<T>(
  rows: T[],
  input: { page: number; pageSize: number },
): { items: T[]; page: number; pageSize: number; total: number; totalPages: number } {
  const pageSize = Math.max(1, input.pageSize);
  const total = rows.length;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const page = Math.min(Math.max(1, input.page), totalPages);
  const start = (page - 1) * pageSize;
  return {
    items: rows.slice(start, start + pageSize),
    page,
    pageSize,
    total,
    totalPages,
  };
}
