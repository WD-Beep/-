import "./register-path-aliases.ts";
import assert from "node:assert/strict";
import test from "node:test";

import type { OutreachPreviewItem } from "../src/lib/api.ts";
import {
  buildDryRunSuccessMessage,
  buildRealSendSuccessMessage,
  countSendablePreviewItems,
  previewItemsHaveDistinctContent,
  realSendButtonLabel,
  shouldProceedRealSend,
} from "../src/lib/batch-outreach-helpers.ts";

function previewItem(partial: Partial<OutreachPreviewItem> & Pick<OutreachPreviewItem, "influencer_id">): OutreachPreviewItem {
  return {
    influencer_id: partial.influencer_id,
    username: partial.username ?? `user_${partial.influencer_id}`,
    display_name: partial.display_name ?? null,
    recipient: partial.recipient ?? "creator@example.com",
    subject: partial.subject ?? "",
    body: partial.body ?? "",
    reason: partial.reason ?? "",
    matched_knowledge: partial.matched_knowledge ?? [],
    risk_notes: partial.risk_notes ?? [],
    tone: partial.tone ?? "professional",
    can_send: partial.can_send ?? true,
    generated_by_ai: partial.generated_by_ai ?? true,
    provider: partial.provider ?? "openai",
    error_message: partial.error_message ?? null,
  };
}

test("countSendablePreviewItems counts only can_send rows", () => {
  const items = [
    previewItem({ influencer_id: 1, can_send: true }),
    previewItem({ influencer_id: 2, can_send: false }),
    previewItem({ influencer_id: 3, can_send: true }),
  ];
  assert.equal(countSendablePreviewItems(items), 2);
});

test("previewItemsHaveDistinctContent detects different subject/body per influencer", () => {
  const distinct = [
    previewItem({ influencer_id: 1, subject: "A", body: "Body A" }),
    previewItem({ influencer_id: 2, subject: "B", body: "Body B" }),
  ];
  const duplicate = [
    previewItem({ influencer_id: 1, subject: "Same", body: "Same body" }),
    previewItem({ influencer_id: 2, subject: "Same", body: "Same body" }),
  ];
  assert.equal(previewItemsHaveDistinctContent(distinct), true);
  assert.equal(previewItemsHaveDistinctContent(duplicate), false);
});

test("realSendButtonLabel requires confirmation before actual send", () => {
  assert.equal(realSendButtonLabel(false, 3), "真实发送 (3)");
  assert.equal(realSendButtonLabel(true, 3), "确认真实发送 3 封");
  assert.equal(shouldProceedRealSend(false), false);
  assert.equal(shouldProceedRealSend(true), true);
});

test("dry_run and real send success messages include counts", () => {
  assert.match(
    buildDryRunSuccessMessage({ total: 3, generated: 3, missing_email: 0, failed: 0, pending: 3 }),
    /3 条待发送记录/,
  );
  assert.match(
    buildRealSendSuccessMessage({ sent: 2, failed: 1, skipped_missing_email: 0 }),
    /成功 2.*失败 1/,
  );
});
