# Outreach Draft Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn AI outreach generation into a reviewed draft workflow where only approved drafts enter the send queue.

**Architecture:** Reuse the existing outreach campaign, campaign recipient, send queue, link knowledge base, email log, and reply models. Add draft state fields and focused campaign recipient actions instead of creating a parallel outreach system. The UI becomes a draft review workbench: generate preview, inspect/edit/regenerate/approve/skip, then queue only approved drafts with explicit count confirmation.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, pytest, Next.js, React, TypeScript, node:test.

---

### Task 1: Recipient Draft State

**Files:**
- Modify: `apps/api/app/models/outreach_campaign_recipient.py`
- Modify: `apps/api/app/schemas/outreach_campaign.py`
- Create: `apps/api/alembic/versions/046_outreach_draft_review.py`
- Test: `apps/api/tests/test_outreach_campaign_draft_review.py`

- [ ] Add failing tests for preview saving each recipient as `pending_review`, skipped rows as `skipped`, and high-value rows as requiring manual open.
- [ ] Add model columns: `draft_status`, `is_high_value`, `opened_at`, `approved_at`, `skipped_at`, `approval_block_reason`.
- [ ] Return draft status fields in recipient preview/list schemas.
- [ ] Re-run the targeted backend test.

### Task 2: Draft Review Actions

**Files:**
- Modify: `apps/api/app/services/outreach_campaign_service.py`
- Modify: `apps/api/app/api/routes/outreach_campaigns.py`
- Modify: `apps/api/app/schemas/outreach_campaign.py`
- Test: `apps/api/tests/test_outreach_campaign_draft_review.py`

- [ ] Add failing tests for opening a high-value draft, editing subject/body, single regenerate, single approve, single skip, and bulk approve excluding unopened high-value rows.
- [ ] Implement PATCH/POST service methods that mutate only one recipient draft at a time.
- [ ] Add routes under the existing campaign router.
- [ ] Re-run targeted backend tests.

### Task 3: Queue Only Approved Drafts

**Files:**
- Modify: `apps/api/app/services/outreach_campaign_service.py`
- Test: `apps/api/tests/test_outreach_campaign_draft_review.py`

- [ ] Add failing tests that queue rejects unapproved drafts and marks approved drafts as `queued`.
- [ ] Update queue validation to require `draft_status == "approved"` and keep all existing skip checks for sent, replied, blacklisted, invalid, invalid email, and missing email.
- [ ] Re-run targeted backend tests.

### Task 4: Frontend API Types And Helpers

**Files:**
- Modify: `apps/web/src/lib/api.ts`
- Modify: `apps/web/src/lib/outreach-campaign-helpers.ts`
- Test: `apps/web/tests/outreach-campaign.test.ts`

- [ ] Add failing tests for draft labels, approve eligibility, send confirmation copy, and skip reason display.
- [ ] Add API bindings for draft edit, open, regenerate, approve, skip, and bulk approve.
- [ ] Re-run targeted frontend tests.

### Task 5: Draft Review UI

**Files:**
- Modify: `apps/web/src/components/outreach-campaigns/outreach-campaigns-panel.tsx`
- Modify: `apps/web/src/components/outreach-campaigns/outreach-campaign-detail-panel.tsx`

- [ ] Replace direct-send emphasis with preview and review-first copy.
- [ ] Render draft rows with status, skip reason, subject/body preview, edit controls, regenerate, approve, skip, and high-value manual confirmation guard.
- [ ] Send action must confirm the approved count and queue only approved drafts.
- [ ] Re-run frontend tests and, if local services allow, browser-check `/outreach-campaigns`.

### Task 6: Verification

**Files:**
- No source edits unless verification exposes a scoped bug.

- [ ] Run targeted backend pytest for draft review and existing outreach campaign tests.
- [ ] Run targeted frontend tests.
- [ ] Report any environment blockers plainly.
