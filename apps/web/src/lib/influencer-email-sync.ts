// 文件说明：前端公共工具和业务辅助函数；当前文件：influencer email sync
export const INFLUENCER_EMAIL_SENT_EVENT = "influencer-email-sent";

export function notifyInfluencerEmailSent(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(INFLUENCER_EMAIL_SENT_EVENT));
}
