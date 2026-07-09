# Admin Backbone Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first real admin backend skeleton with admin-only navigation, dashboard overview, users page, products page, and minimal admin APIs.

**Architecture:** Keep the sales workspace untouched. Add a separate `components/admin` shell guarded by stored admin session state, and add FastAPI `/api/admin/*` read-only endpoints that aggregate from the existing tenant, product, collection, influencer, email, and reply tables. Use empty states when real rows are absent.

**Tech Stack:** Next.js 16, React 19, Tailwind CSS, Node test runner, FastAPI, SQLAlchemy async, pytest.

---

### Task 1: Tests First

**Files:**
- Create: `apps/web/tests/admin-backbone.test.ts`
- Create: `apps/api/tests/test_admin_api.py`

- [ ] Write frontend tests asserting admin dashboard no longer imports `OperationsHomePanel`, admin shell/sidebar files exist, admin pages exist, and admin UI excludes sales brand controls.
- [ ] Write backend tests asserting admin can read summary/users/products, sales receives `403`, and an admin products response includes a brand created by a sales user through `ProductMember`.
- [ ] Run the new tests and confirm they fail because the feature is missing.

### Task 2: Backend Admin API

**Files:**
- Create: `apps/api/app/api/routes/admin.py`
- Modify: `apps/api/app/api/routes/__init__.py`

- [ ] Add admin-only dependency that checks `UserContext.is_admin`.
- [ ] Add summary, users, and products endpoints using existing tables only.
- [ ] Include the admin router under `/api`.
- [ ] Run backend admin tests and confirm they pass.

### Task 3: Frontend Admin Shell and Pages

**Files:**
- Create: `apps/web/src/components/admin/admin-route-guard.tsx`
- Create: `apps/web/src/components/admin/admin-shell.tsx`
- Create: `apps/web/src/components/admin/admin-sidebar.tsx`
- Create: `apps/web/src/components/admin/admin-header.tsx`
- Create: `apps/web/src/components/admin/admin-dashboard-panel.tsx`
- Create: `apps/web/src/components/admin/admin-users-panel.tsx`
- Create: `apps/web/src/components/admin/admin-products-panel.tsx`
- Create: `apps/web/src/components/admin/admin-placeholder-panel.tsx`
- Modify: `apps/web/src/app/admin/dashboard/page.tsx`
- Create: `apps/web/src/app/admin/users/page.tsx`
- Create: `apps/web/src/app/admin/products/page.tsx`
- Create placeholder admin pages for collection tasks, influencers, emails, and settings.
- Modify: `apps/web/src/lib/api.ts`

- [ ] Add typed admin API client functions.
- [ ] Add admin guard and shell that never imports the sales sidebar or product create dialog.
- [ ] Render dashboard/user/product panels with loading, error, empty, and table states.
- [ ] Run frontend admin tests and confirm they pass.

### Task 4: Verification

- [ ] Run `cd apps/web; node --test tests/*.test.ts`.
- [ ] Run `cd apps/web; npm run lint`.
- [ ] Run `cd apps/web; npm run build`.
- [ ] Run `python -m pytest apps/api/tests/test_product_member_access.py apps/api/tests/test_tenant*.py apps/api/tests/test_collection*.py apps/api/tests/test_email*.py -q`.
- [ ] Run `python -m pytest apps/api/tests/test_admin*.py -q`.
