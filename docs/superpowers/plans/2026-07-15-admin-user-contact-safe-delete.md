# Admin User Contact and Safe Delete Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow arbitrary salesperson contact text, safely delete salesperson accounts while preserving business history, and deploy the public long-running AI proxy fix.

**Architecture:** Keep the existing `email` transport field for compatibility but validate it as optional bounded text. Replace delete blocking with one backend transaction that cancels active sends, nulls historical ownership, records an audit row, deletes account-owned memberships, and returns a structured result. Public AI/link generation uses the dedicated long-running Next.js proxy and aligned Nginx timeouts.

**Tech Stack:** Next.js App Router, React, TypeScript, FastAPI, Pydantic, SQLAlchemy async, PostgreSQL, Alembic, Node test runner, pytest, Docker Compose, Nginx.

---

### Task 1: Add failing contact and UI regression tests

**Files:**
- Modify: `apps/api/tests/test_admin_api.py`
- Modify: `apps/web/tests/admin-backbone.test.ts`

- [ ] Add backend tests proving `sales1@local`, phone, WeChat and plain text are accepted while blank usernames and non-admin writes remain rejected.
- [ ] Add frontend source tests proving all admin salesperson forms use a text contact field and do not run strict email validation.
- [ ] Run the focused tests and confirm they fail for the missing behavior.

### Task 2: Relax salesperson contact validation

**Files:**
- Modify: `apps/api/app/api/routes/admin.py`
- Modify: `apps/web/src/components/admin/admin-user-dialogs.tsx`
- Modify: `apps/web/src/components/admin/admin-products-management.tsx`

- [ ] Replace `EmailStr` with optional `str` fields limited to 255 characters.
- [ ] Trim contact text on create/update while preserving empty-as-null behavior.
- [ ] Remove frontend regex, native email input validation and contact-dropping logic.
- [ ] Rename labels and descriptions to “邮箱 / 手机 / 联系方式”.
- [ ] Run focused contact tests and confirm they pass.

### Task 3: Add failing safe-delete backend tests

**Files:**
- Modify: `apps/api/tests/test_admin_api.py`

- [ ] Create a salesperson with product membership, collection task, email/reply history, campaign and queue records.
- [ ] Assert admin deletion succeeds, memberships are removed, owner fields are null, active sends are cancelled, history rows remain and audit data is written.
- [ ] Assert non-admin and current-admin deletion are rejected.
- [ ] Inject a failure before commit and assert the user and relationships remain intact.
- [ ] Run focused tests and confirm they fail against the current blocking endpoint.

### Task 4: Implement transactional safe deletion

**Files:**
- Create: `apps/api/app/models/admin_audit_log.py`
- Create: `apps/api/alembic/versions/056_admin_user_safe_delete.py`
- Modify: `apps/api/app/models/__init__.py`
- Modify: `apps/api/app/models/outreach_email_campaign.py`
- Modify: `apps/api/app/models/outreach_send_queue.py`
- Modify: `apps/api/app/schemas/outreach_campaign.py`
- Modify: `apps/api/app/schemas/outreach_email.py`
- Modify: `apps/api/app/api/routes/admin.py`

- [ ] Add nullable `SET NULL` ownership constraints and the audit table migration.
- [ ] Add structured delete response fields for released products/tasks, cancelled sends and preserved history.
- [ ] Implement one commit with rollback on any exception.
- [ ] Keep current-admin and administrator permission checks.
- [ ] Run focused backend tests and confirm they pass.

### Task 5: Replace complex frontend delete flow

**Files:**
- Modify: `apps/web/src/lib/api.ts`
- Modify: `apps/web/src/components/admin/admin-products-management.tsx`
- Modify: `apps/web/src/components/admin/admin-products-panel.tsx`
- Modify: `apps/web/src/components/admin/admin-users-panel.tsx`
- Modify: `apps/web/tests/admin-backbone.test.ts`

- [ ] Type the structured delete result and nullable historical campaign/queue owners.
- [ ] Replace migration/disable choices with cancel and confirm-delete buttons.
- [ ] Display username, product/task counts and other preserved history counts.
- [ ] Add delete to the main admin users list and refresh after success.
- [ ] Run focused frontend tests and confirm they pass.

### Task 6: Harden and verify public long-running generation

**Files:**
- Modify: `apps/web/src/app/api-long/[...path]/route.ts`
- Modify: `apps/web/tests/admin-backbone.test.ts`
- Existing modified: `apps/web/src/lib/api.ts`
- Existing modified: `apps/web/Dockerfile`
- Existing modified: `docker-compose.yml`

- [ ] Add a regression test for link refresh/generate/regenerate using `LONG_RUNNING_API_URL` and structured upstream timeout errors.
- [ ] Return clear JSON for long-proxy timeout and backend connection failures.
- [ ] Run the focused proxy tests and production Web build.

### Task 7: Full verification and deployment

**Files:**
- Server configuration: `/etc/nginx/sites-enabled/influencer-intel`
- Deployment directory: `/opt/influencer-intel`

- [ ] Run `npm.cmd run lint`, focused Node tests and `npm.cmd run build` in `apps/web`.
- [ ] Run focused pytest tests and Alembic migration checks in `apps/api`.
- [ ] Copy only changed project files without overwriting server secrets.
- [ ] Run `docker compose build api web`, `docker compose run --rm api alembic upgrade head`, and `docker compose up -d`.
- [ ] Back up Nginx config, set read/send timeout to 900 seconds, run `nginx -t`, then reload.
- [ ] Verify public `/api-proxy/health`, `/api-long/health`, container health, migration head and generation logs.

No Git commit or force operation is included.
