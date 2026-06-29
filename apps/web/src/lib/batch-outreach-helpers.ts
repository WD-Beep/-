import type { OutreachBatchPreviewResponse, OutreachPreviewItem } from "@/lib/api";

export function countSendablePreviewItems(items: OutreachPreviewItem[]): number {
  return items.filter((item) => item.can_send).length;
}

export function previewItemsHaveDistinctContent(items: OutreachPreviewItem[]): boolean {
  const withContent = items.filter((item) => item.subject && item.body);
  if (withContent.length < 2) return true;
  const signatures = new Set(withContent.map((item) => `${item.subject}::${item.body}`));
  return signatures.size === withContent.length;
}

export function realSendButtonLabel(confirmSend: boolean, sendableCount: number): string {
  if (confirmSend) {
    return `确认真实发送 ${sendableCount} 封`;
  }
  return `真实发送 (${sendableCount})`;
}

export function shouldProceedRealSend(confirmSend: boolean): boolean {
  return confirmSend;
}

export function buildDryRunSuccessMessage(
  summary: (OutreachBatchPreviewResponse["summary"] & { pending?: number }) | { generated: number; pending?: number },
): string {
  const pending = typeof summary.pending === "number" ? summary.pending : summary.generated;
  return `测试生成完成：${pending} 条待发送记录已写入邮件日志（未真实 SMTP 发送）。`;
}

export function buildRealSendSuccessMessage(summary: {
  sent: number;
  failed: number;
  skipped_missing_email: number;
}): string {
  return `发送完成：成功 ${summary.sent}，失败 ${summary.failed}，跳过 ${summary.skipped_missing_email}。`;
}
