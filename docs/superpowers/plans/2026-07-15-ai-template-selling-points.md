# AI Template And Selling Points Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add reusable AI generation templates and human-priority link selling points, then deploy and verify the live DeepSeek workflow.

**Architecture:** Extend the existing `MessageTemplate` and `LinkKnowledgeBase` records instead of adding parallel systems. Keep campaign draft review unchanged; pass the selected template into the existing AI services and validate generated output before drafts become queueable.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy, Alembic, PostgreSQL, Next.js App Router, React 19, TypeScript, node:test, pytest, Docker Compose, Nginx.

---

### Task 1: Persist template rules and selling points

**Files:**
- Create: `apps/api/alembic/versions/057_ai_template_rules_selling_points.py`
- Modify: `apps/api/app/models/message_template.py`
- Modify: `apps/api/app/models/link_knowledge_base.py`
- Modify: `apps/api/app/schemas/message_template.py`
- Modify: `apps/api/app/schemas/link_knowledge_base.py`
- Test: `apps/api/tests/test_message_templates.py`
- Test: `apps/api/tests/test_link_knowledge_bases.py`

- [ ] Write tests asserting template rules/default/source fields and manual selling points survive API CRUD.
- [ ] Run the focused tests and confirm missing-field failures.
- [ ] Add model/schema fields and migration with safe defaults.
- [ ] Implement one-default-per-product normalization in `MessageTemplateService`.
- [ ] Re-run focused tests and confirm pass.

### Task 2: Parse uploaded template files

**Files:**
- Modify: `apps/api/app/api/routes/message_templates.py`
- Modify: `apps/api/app/schemas/message_template.py`
- Test: `apps/api/tests/test_message_templates.py`

- [ ] Write failing API tests for `.txt`, `.md`, `.docx`, unsupported extension, oversized and empty files.
- [ ] Add an authenticated multipart parse endpoint with a 2MB limit.
- [ ] Parse text encodings and DOCX XML in memory without storing files.
- [ ] Re-run focused tests and confirm pass.

### Task 3: Enforce templates in campaign AI generation

**Files:**
- Modify: `apps/api/app/services/speech_recommendation_service.py`
- Modify: `apps/api/app/services/outreach_campaign_service.py`
- Test: `apps/api/tests/test_ai_outreach_email_generation.py`
- Test: `apps/api/tests/test_outreach_campaigns.py`

- [ ] Write failing tests proving selected template rules enter the AI prompt and short/invalid output is retried once.
- [ ] Add pure output validation helpers for length, required content, forbidden content and unresolved placeholders.
- [ ] Include template content/rules in the AI prompt and retry once with validation errors.
- [ ] Make AI preview resolve and require the campaign template while preserving manual/template modes.
- [ ] Re-run focused tests and confirm pass.

### Task 4: Merge human and extracted selling points

**Files:**
- Modify: `apps/api/app/services/link_script_generator.py`
- Modify: `apps/api/app/api/routes/link_knowledge_bases.py`
- Modify: `apps/api/app/schemas/link_knowledge_base.py`
- Test: `apps/api/tests/test_link_knowledge_bases.py`

- [ ] Write failing tests for human-first deduplicated selling points and template-aware link prompts.
- [ ] Add a pure merge helper and include merged points in snapshots and fallbacks.
- [ ] Resolve optional link-generation template IDs within the current product.
- [ ] Pass template content/rules to the generator and require 2–4 matching supplied points.
- [ ] Re-run focused tests and confirm pass.

### Task 5: Add template management to AI workbench

**Files:**
- Modify: `apps/web/src/lib/api.ts`
- Modify: `apps/web/src/components/message-templates/message-template-form-dialog.tsx`
- Modify: `apps/web/src/components/outreach-campaigns/outreach-campaigns-panel.tsx`
- Test: `apps/web/tests/outreach-campaign.test.ts`

- [ ] Write failing source-level tests for AI template selection, CRUD actions, default state and upload.
- [ ] Extend API types/functions for rules, default and file parsing.
- [ ] Extend the reusable template dialog with rule fields and uploaded initial content.
- [ ] Render template management under AI mode and pass selected template ID when creating the campaign.
- [ ] Re-run Web tests and confirm pass.

### Task 6: Replace link summary with selling-point editor

**Files:**
- Modify: `apps/web/src/lib/api.ts`
- Modify: `apps/web/src/components/link-knowledge-bases/link-knowledge-panels.tsx`
- Test: `apps/web/tests/outreach-campaign.test.ts`

- [ ] Write failing source-level tests for manual selling points, extracted points, advanced details and template selection.
- [ ] Add line-based human selling-point editing and save independent from extracted knowledge.
- [ ] Move summary/JSON into an advanced disclosure while preserving edit/refresh behavior.
- [ ] Add template selection to link script generation and pass `message_template_id`.
- [ ] Re-run Web tests and confirm pass.

### Task 7: Verify, deploy, and smoke test

**Files:**
- Modify only files required by failures discovered during verification.

- [ ] Run focused API and Web tests.
- [ ] Run `npm.cmd run lint` in `apps/web`.
- [ ] Run `npm.cmd run build` in `apps/web`.
- [ ] Run the broader relevant pytest suite.
- [ ] Upload only changed runtime files without overwriting server `.env`.
- [ ] Rebuild containers and apply Alembic migration `057`.
- [ ] Verify health, login, template CRUD/upload, real link parsing, real DeepSeek generation, draft review and single-recipient regenerate through the public URL.
- [ ] Remove smoke-test business data and report exact commands/results.
