// 文件说明：前端公共工具和业务辅助函数；当前文件：outreach email helpers
export function resolveInfluencerEmail(item: {
  final_email: string | null;
  business_email: string | null;
  public_email: string | null;
  email: string | null;
}): string | null {
  return item.final_email || item.business_email || item.public_email || item.email;
}

export function canSendOutreachEmail(input: {
  recipient: string;
  subject: string;
  body: string;
  senderEmail?: string | null;
}): boolean {
  const recipient = input.recipient.trim().toLowerCase();
  if (!recipient || !input.subject.trim() || !input.body.trim()) {
    return false;
  }
  const sender = (input.senderEmail || "").trim().toLowerCase();
  if (sender && recipient === sender) {
    return false;
  }
  return true;
}

export function outreachRecipientIssue(
  recipient: string | null | undefined,
  senderEmail?: string | null,
): string | null {
  const normalized = (recipient || "").trim().toLowerCase();
  if (!normalized) return "缺少邮箱";
  const sender = (senderEmail || "").trim().toLowerCase();
  if (sender && normalized === sender) {
    return "收件人与发件邮箱相同，无法发送红人外联邮件";
  }
  return null;
}

export function outreachSendConfirmMessage(recipient: string): string {
  return `将真实发送邮件到 ${recipient}，确认发送？`;
}
