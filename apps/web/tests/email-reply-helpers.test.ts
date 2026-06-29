import "./register-path-aliases.ts";
import assert from "node:assert/strict";
import test from "node:test";

import {
  countUnhandledReplies,
  filterEmailRepliesForCenter,
  getSelectableReplyIds,
  getEmailReplyIntentLabel,
  type EmailReplyCenterItem,
} from "../src/lib/email-reply-helpers.ts";

const baseReply: EmailReplyCenterItem = {
  id: 1,
  product_influencer_id: 101,
  campaign_id: 9,
  processing_status: "unprocessed",
  intent_status: "unprocessed",
};

test("reply center filters replies by workflow status and campaign", () => {
  const replies: EmailReplyCenterItem[] = [
    { ...baseReply, id: 1, processing_status: "unprocessed", intent_status: "unprocessed" },
    { ...baseReply, id: 2, processing_status: "processed", intent_status: "interested" },
    { ...baseReply, id: 3, processing_status: "unprocessed", intent_status: "follow_up", campaign_id: 10 },
    { ...baseReply, id: 4, product_influencer_id: null, intent_status: "unmatched", campaign_id: null },
  ];

  assert.deepEqual(filterEmailRepliesForCenter(replies, { view: "unprocessed" }).map((reply) => reply.id), [1, 3, 4]);
  assert.deepEqual(filterEmailRepliesForCenter(replies, { view: "interested" }).map((reply) => reply.id), [2]);
  assert.deepEqual(filterEmailRepliesForCenter(replies, { view: "follow_up" }).map((reply) => reply.id), [3]);
  assert.deepEqual(filterEmailRepliesForCenter(replies, { view: "unmatched" }).map((reply) => reply.id), [4]);
  assert.deepEqual(filterEmailRepliesForCenter(replies, { view: "all", campaignId: 9 }).map((reply) => reply.id), [1, 2]);
});

test("reply center counts unprocessed replies for navigation badge", () => {
  const replies: EmailReplyCenterItem[] = [
    { ...baseReply, id: 1, processing_status: "unprocessed" },
    { ...baseReply, id: 2, processing_status: "processed" },
    { ...baseReply, id: 3, processing_status: "unprocessed", intent_status: "unmatched" },
  ];

  assert.equal(countUnhandledReplies(replies), 2);
});

test("reply center exposes visible ids for bulk selection", () => {
  const replies: EmailReplyCenterItem[] = [
    { ...baseReply, id: 1 },
    { ...baseReply, id: 2, campaign_id: 10 },
    { ...baseReply, id: 3, processing_status: "processed" },
  ];

  const visible = filterEmailRepliesForCenter(replies, { view: "unprocessed" });

  assert.deepEqual(getSelectableReplyIds(visible), [1, 2]);
});

test("reply center status labels use sales-friendly wording", () => {
  assert.equal(getEmailReplyIntentLabel("interested"), "有意向");
  assert.equal(getEmailReplyIntentLabel("follow_up"), "需跟进");
  assert.equal(getEmailReplyIntentLabel("not_interested"), "无意向");
  assert.equal(getEmailReplyIntentLabel("processed"), "已处理");
  assert.equal(getEmailReplyIntentLabel("unmatched"), "未匹配");
});
