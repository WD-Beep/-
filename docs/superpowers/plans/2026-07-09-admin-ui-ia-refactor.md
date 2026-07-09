# Admin UI IA Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework the admin backend into a daily-use operations workspace with clear hierarchy, metrics, filters, status labels, and action paths.

**Architecture:** Keep the current Next.js admin routes and existing API calls. Add a small shared admin UI layer for page headers, KPI cards, filters, status badges, tables, and panel states, plus helper functions for status localization, derived metrics, and client-side filtering.

**Tech Stack:** Next.js 16, React 19, TypeScript, Tailwind CSS, node:test.

---

### Task 1: Shared Helpers And Tests

**Files:**
- Create: `apps/web/src/components/admin/admin-ui-helpers.ts`
- Test: `apps/web/tests/admin-ui-helpers.test.ts`

- [x] Write tests for Chinese status labels, derived metrics, and filter behavior.
- [x] Run the helper test and verify it fails because the helper module does not exist.
- [ ] Implement helper functions for formatting, filtering, status tone selection, and dashboard summaries.
- [ ] Re-run the helper test until it passes.

### Task 2: Shared Admin Components

**Files:**
- Create: `apps/web/src/components/admin/admin-ui.tsx`
- Modify: `apps/web/src/components/admin/admin-shell.tsx`
- Modify: `apps/web/src/components/admin/admin-sidebar.tsx`
- Modify: `apps/web/src/components/admin/admin-header.tsx`

- [ ] Add reusable page header, KPI card, filter bar, status badge, data table, section panel, and state components.
- [ ] Fix sidebar/header Chinese copy and improve active state while keeping the left nav + top bar structure.
- [ ] Add responsive shell behavior for narrow screens and horizontal table overflow.

### Task 3: Dashboard, Users, And Brands

**Files:**
- Modify: `apps/web/src/components/admin/admin-dashboard-panel.tsx`
- Modify: `apps/web/src/components/admin/admin-users-panel.tsx`
- Modify: `apps/web/src/components/admin/admin-products-panel.tsx`

- [ ] Rebuild the dashboard around KPI cards, rankings, recent tasks, reply trend, exception reminders, and brand progress.
- [ ] Rebuild users as a performance table with filters and action buttons.
- [ ] Rebuild brands as an operations-status table with filters and action buttons.

### Task 4: Tasks, Influencers, Replies, Details, Settings

**Files:**
- Modify: `apps/web/src/components/admin/admin-detail-panels.tsx`

- [ ] Turn collection tasks into a task monitoring center.
- [ ] Turn influencers into a searchable profile library.
- [ ] Turn email/replies into a follow-up workbench.
- [ ] Refresh user and brand detail pages into compact chain views.
- [ ] Refresh system information and add suggested module cards.

### Task 5: Verification

**Files:**
- Test: `apps/web/tests/admin-backbone.test.ts`
- Test: `apps/web/tests/admin-ui-helpers.test.ts`

- [ ] Run targeted admin tests.
- [ ] Run lint/build if dependency state permits.
- [ ] Start the web app and visually inspect admin pages in the browser if the local API/session permits.
