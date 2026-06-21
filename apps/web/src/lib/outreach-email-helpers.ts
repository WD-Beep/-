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
}): boolean {
  return Boolean(input.recipient.trim() && input.subject.trim() && input.body.trim());
}

export function outreachSendConfirmMessage(recipient: string): string {
  return `将真实发送邮件到 ${recipient}，确认发送？`;
}
