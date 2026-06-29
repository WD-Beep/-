# Outreach Campaign Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enhance the existing outreach campaign module into an AI-personalized batch outreach workflow where sales users can inspect per-influencer drafts, safely queue valid drafts, and track replies inside each campaign.

**Architecture:** Keep the current campaign, recipient, send queue, email log, and email reply models. Add only narrow schemas, service queries, route endpoints, frontend API bindings, helpers, and UI sections needed for phase 1. Do not create a second campaign or reply system.

**Tech Stack:** FastAPI, SQLAlchemy async, Pydantic, pytest, Next.js/React, TypeScript, node:test.

---

### Task 1: Backend Campaign Statistics

**Files:**
- Modify: `apps/api/app/schemas/outreach_campaign.py`
- Modify: `apps/api/app/services/outreach_campaign_service.py`
- Test: `apps/api/tests/test_outreach_campaigns.py`

- [ ] Add failing tests that list campaigns after preview, queue, and mock replies, expecting real `draft_count`, `can_queue_count`, `reply_count`, `interested_count`, `unreplied_count`, and `latest_reply_at` fields.
- [ ] Implement the minimal schema fields and query aggregation against existing campaign recipients and email replies.
- [ ] Re-run the targeted backend test and keep existing campaign tests passing.

### Task 2: Backend Campaign Reply Board

**Files:**
- Modify: `apps/api/app/schemas/outreach_campaign.py`
- Modify: `apps/api/app/services/outreach_campaign_service.py`
- Modify: `apps/api/app/api/routes/outreach_campaigns.py`
- Test: `apps/api/tests/test_outreach_campaigns.py`

- [ ] Add failing tests for `list_campaign_replies`, covering replied, unreplied, interested, sent-without-reply, failed, and skipped rows using existing DB records.
- [ ] Implement a campaign reply board response sourced from `OutreachCampaignRecipient`, `OutreachSendQueueItem`, `EmailLog`, `EmailReply`, and `ProductInfluencer`.
- [ ] Add a route under the existing outreach campaign router. Do not add a new reply system.
- [ ] Re-run the targeted backend test.

### Task 3: Backend Queue Safety Visibility

**Files:**
- Modify: `apps/api/app/services/outreach_campaign_service.py`
- Test: `apps/api/tests/test_outreach_campaigns.py`

- [ ] Add failing tests that queueing rejects or skips rows with empty recipient, changed influencer email, sender-email recipient, empty subject/body, invalid status, or `can_queue=false`.
- [ ] Implement minimal queue-time validation updates that persist `skip_reason` on campaign recipients.
- [ ] Re-run targeted queue tests.

### Task 4: Frontend Labels, Statuses, and Helpers

**Files:**
- Modify: `apps/web/src/lib/outreach-campaign-helpers.ts`
- Test: `apps/web/tests/outreach-campaign.test.ts`

- [ ] Add failing tests for clear page copy, button labels, phase labels, statistics formatting, filter labels, and skip reason summary.
- [ ] Implement helper constants and pure functions only.
- [ ] Re-run the frontend helper test.

### Task 5: Frontend API Bindings

**Files:**
- Modify: `apps/web/src/lib/api.ts`
- Test: `apps/web/tests/outreach-campaign.test.ts`

- [ ] Add failing type/helper usage tests where practical for the new reply board shape.
- [ ] Add TypeScript types and fetch function for the existing-router campaign reply board endpoint.
- [ ] Re-run frontend tests.

### Task 6: Outreach Campaign Page UI

**Files:**
- Modify: `apps/web/src/components/outreach-campaigns/outreach-campaigns-panel.tsx`

- [ ] Update the existing page only: top explanation, four-step guide, current batch highlight, history distinction, filters, campaign statistics, draft detail section, skip summary, and reply board section.
- [ ] Ensure all draft/reply/stat fields render only from API state.
- [ ] Avoid unrelated page edits and avoid frontend fake data.

### Task 7: Verification and Local Flow

**Files:**
- No source edits unless a failing verification reveals a scoped bug.

- [ ] Run targeted backend pytest for outreach campaign and inbound reply behavior.
- [ ] Run targeted frontend tests.
- [ ] Start backend and frontend locally if dependencies and environment allow.
- [ ] Open `/outreach-campaigns`, walk the draft, queue, and reply board flow using fixture/mock data, and confirm no browser console errors and no Network 500s.
- [ ] If local app startup is blocked by environment or missing services, report the exact blocker and the automated verification that did run.
