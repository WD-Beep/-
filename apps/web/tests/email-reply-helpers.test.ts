import "./register-path-aliases.ts";
import assert from "node:assert/strict";
import test from "node:test";

import {
  countUnhandledReplies,
  filterEmailRepliesForCenter,
  getSelectableReplyIds,
  getEmailReplyIntentLabel,
  getEmailReplyInfluencerDisplay,
  getEmailReplyMatchCandidates,
  buildEmailReplyResponseDraft,
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
test("reply center displays matched influencer name and email", () => {
  const label = getEmailReplyInfluencerDisplay(
    { ...baseReply, product_influencer_id: 101 },
    {
      id: 101,
      username: "kayla",
      display_name: "Kayla",
      final_email: "kayla@example.com",
      business_email: null,
      public_email: null,
      email: null,
    },
  );

  assert.equal(label, "Kayla · kayla@example.com");
});

test("reply center uses clearer unmatched copy when no influencer is linked", () => {
  const label = getEmailReplyInfluencerDisplay({ ...baseReply, product_influencer_id: null }, null);

  assert.equal(label, "未自动关联");
});

test("reply center exposes low-confidence candidates from reply diagnostics", () => {
  const candidates = getEmailReplyMatchCandidates({
    ...baseReply,
    product_influencer_id: null,
    raw_headers: {
      reply_match: {
        status: "candidate",
        candidates: [
          { product_influencer_id: 201, campaign_id: 33, display_name: "Kayla", email: "kayla@example.com" },
        ],
      },
    },
  });

  assert.deepEqual(candidates, [
    { product_influencer_id: 201, campaign_id: 33, display_name: "Kayla", email: "kayla@example.com" },
  ]);
});

test("reply panel offers candidate confirmation through the update API and refreshes", async () => {
  const source = await import("node:fs/promises").then((fs) =>
    fs.readFile(new URL("../src/components/email-replies/email-replies-panel.tsx", import.meta.url), "utf8"),
  );

  assert.match(source, /getEmailReplyMatchCandidates/);
  assert.match(source, /product_influencer_id:\s*candidate\.product_influencer_id/);
  assert.doesNotMatch(source, /campaign_id:\s*candidate\.campaign_id\s*\?\?\s*undefined/);
  assert.match(source, /await load\(\)/);
});

test("reply panel keeps unmatched label but removes campaign clutter from the list", async () => {
  const source = await import("node:fs/promises").then((fs) =>
    fs.readFile(new URL("../src/components/email-replies/email-replies-panel.tsx", import.meta.url), "utf8"),
  );

  assert.match(source, /未自动关联/);
  assert.doesNotMatch(source, />\s*活动\s*<\/th>/);
  assert.doesNotMatch(source, /全部活动/);
  assert.doesNotMatch(source, /未关联活动/);
});

test("reply response draft changes by intent status", () => {
  const interested = buildEmailReplyResponseDraft({
    influencerName: "Kayla",
    intentStatus: "interested",
  });
  const followUp = buildEmailReplyResponseDraft({
    influencerName: "Kayla",
    intentStatus: "follow_up",
  });

  assert.match(interested, /Hi Kayla/);
  assert.match(interested, /share more details/);
  assert.match(followUp, /following up/i);
});

test("reply panel exposes response composer, send API, warning, and refresh behavior", async () => {
  const source = await import("node:fs/promises").then((fs) =>
    fs.readFile(new URL("../src/components/email-replies/email-replies-panel.tsx", import.meta.url), "utf8"),
  );
  const apiSource = await import("node:fs/promises").then((fs) =>
    fs.readFile(new URL("../src/lib/api.ts", import.meta.url), "utf8"),
  );

  assert.match(source, /textarea/);
  assert.match(source, /buildEmailReplyResponseDraft/);
  assert.match(source, /sendEmailReplyResponse/);
  assert.match(source, /当前未自动关联红人/);
  assert.match(source, /这是通用邮箱，请确认对方身份/);
  assert.match(source, /await load\(\)/);
  assert.match(apiSource, /email-replies\/\$\{replyId\}\/send-response/);
});

test("reply panel exposes direct row reply action for sales users", async () => {
  const source = await import("node:fs/promises").then((fs) =>
    fs.readFile(new URL("../src/components/email-replies/email-replies-panel.tsx", import.meta.url), "utf8"),
  );

  assert.match(source, /openReplyComposer/);
  assert.match(source, />\s*回复\s*</);
  assert.match(source, /onClick=\{\(\) => void openReplyComposer\(reply\)\}/);
});

test("reply panel lets sales edit follow up notes from the row", async () => {
  const source = await import("node:fs/promises").then((fs) =>
    fs.readFile(new URL("../src/components/email-replies/email-replies-panel.tsx", import.meta.url), "utf8"),
  );
  const apiSource = await import("node:fs/promises").then((fs) =>
    fs.readFile(new URL("../src/lib/api.ts", import.meta.url), "utf8"),
  );

  assert.match(source, /openNoteEditor/);
  assert.match(source, /saveReplyNote/);
  assert.match(source, /manual_note/);
  assert.match(source, />\s*备注\s*</);
  assert.match(apiSource, /manual_note\?:\s*string \| null/);
});

test("reply panel marks a reply viewed before clearing the navigation badge", async () => {
  const source = await import("node:fs/promises").then((fs) =>
    fs.readFile(new URL("../src/components/email-replies/email-replies-panel.tsx", import.meta.url), "utf8"),
  );
  const sidebarSource = await import("node:fs/promises").then((fs) =>
    fs.readFile(new URL("../src/components/layout/sidebar.tsx", import.meta.url), "utf8"),
  );
  const apiSource = await import("node:fs/promises").then((fs) =>
    fs.readFile(new URL("../src/lib/api.ts", import.meta.url), "utf8"),
  );

  assert.match(source, /markReplyViewed/);
  assert.match(source, /mark_viewed:\s*true/);
  assert.match(source, /email-replies:work-count-changed/);
  assert.match(source, /reply\.viewed_at/);
  assert.match(sidebarSource, /summary\.unviewed_count/);
  assert.match(apiSource, /viewed_at:\s*string \| null/);
});

test("reply panel keeps first paint fast by lazy loading optional influencer lookup", async () => {
  const source = await import("node:fs/promises").then((fs) =>
    fs.readFile(new URL("../src/components/email-replies/email-replies-panel.tsx", import.meta.url), "utf8"),
  );

  assert.match(source, /const replyData = await fetchEmailReplies/);
  assert.match(source, /setReplies\(replyData\.items\)/);
  assert.doesNotMatch(source, /const influencerData = await fetchInfluencers/);
  assert.match(source, /ensureInfluencers/);
  assert.match(source, /fetchInfluencers\(1,\s*100,\s*\{\s*hasEmail:\s*true\s*\}\)/);
});

test("reply panel exposes linked influencer detail and social profile actions", async () => {
  const source = await import("node:fs/promises").then((fs) =>
    fs.readFile(new URL("../src/components/email-replies/email-replies-panel.tsx", import.meta.url), "utf8"),
  );

  assert.match(source, /查看红人信息/);
  assert.match(source, /查看社媒链接/);
  assert.match(source, /href=\{`\/influencers\/\$\{influencer\.id\}`\}/);
  assert.match(source, /influencer\.profile_url/);
});

test("reply panel lets unmatched replies rematch before viewing influencer information", async () => {
  const source = await import("node:fs/promises").then((fs) =>
    fs.readFile(new URL("../src/components/email-replies/email-replies-panel.tsx", import.meta.url), "utf8"),
  );
  const apiSource = await import("node:fs/promises").then((fs) =>
    fs.readFile(new URL("../src/lib/api.ts", import.meta.url), "utf8"),
  );

  assert.match(source, /rematchEmailReply/);
  assert.match(source, /openInfluencerInfo/);
  assert.match(source, /openSocialLink/);
  assert.doesNotMatch(source, /disabled title="当前回复未关联红人"/);
  assert.match(source, /暂未找到对应红人信息/);
  assert.match(apiSource, /email-inbound\/replies\/\$\{replyId\}\/rematch/);
});
