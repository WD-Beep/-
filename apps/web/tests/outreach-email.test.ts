import "./register-path-aliases.ts";
import assert from "node:assert/strict";
import test from "node:test";

import { influencerFilterQueryParams } from "../src/lib/api.ts";
import {
  canSendOutreachEmail,
  outreachRecipientIssue,
  outreachSendConfirmMessage,
  resolveInfluencerEmail,
} from "../src/lib/outreach-email-helpers.ts";

test("emailStatus maps to email_status query param", () => {
  const params = influencerFilterQueryParams({ emailStatus: "sent" });
  assert.equal(params.email_status, "sent");
});

test("resolveInfluencerEmail matches backend priority", () => {
  assert.equal(
    resolveInfluencerEmail({
      final_email: "final@example.com",
      business_email: "biz@example.com",
      public_email: "pub@example.com",
      email: "legacy@example.com",
    }),
    "final@example.com",
  );
  assert.equal(
    resolveInfluencerEmail({
      final_email: null,
      business_email: "biz@example.com",
      public_email: "pub@example.com",
      email: "legacy@example.com",
    }),
    "biz@example.com",
  );
  assert.equal(
    resolveInfluencerEmail({
      final_email: null,
      business_email: null,
      public_email: "pub@example.com",
      email: "legacy@example.com",
    }),
    "pub@example.com",
  );
  assert.equal(
    resolveInfluencerEmail({
      final_email: null,
      business_email: null,
      public_email: null,
      email: "legacy@example.com",
    }),
    "legacy@example.com",
  );
});

test("canSendOutreachEmail requires recipient subject and body", () => {
  assert.equal(
    canSendOutreachEmail({ recipient: "a@b.com", subject: "Hi", body: "Hello" }),
    true,
  );
  assert.equal(canSendOutreachEmail({ recipient: "", subject: "Hi", body: "Hello" }), false);
  assert.equal(canSendOutreachEmail({ recipient: "a@b.com", subject: "", body: "Hello" }), false);
  assert.equal(canSendOutreachEmail({ recipient: "a@b.com", subject: "Hi", body: "  " }), false);
});

test("canSendOutreachEmail rejects recipient same as sender", () => {
  assert.equal(
    canSendOutreachEmail({
      recipient: "sender@company.com",
      subject: "Hi",
      body: "Hello",
      senderEmail: "sender@company.com",
    }),
    false,
  );
});

test("outreachRecipientIssue flags sender recipient", () => {
  assert.match(
    outreachRecipientIssue("sender@company.com", "sender@company.com") || "",
    /发件邮箱相同/,
  );
});

test("outreachSendConfirmMessage includes recipient", () => {
  const msg = outreachSendConfirmMessage("creator@example.com");
  assert.match(msg, /creator@example.com/);
  assert.match(msg, /确认发送/);
});
