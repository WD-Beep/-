export const INFLUENCER_EMAIL_SENT_EVENT = "influencer-email-sent";

export function notifyInfluencerEmailSent(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(INFLUENCER_EMAIL_SENT_EVENT));
}
