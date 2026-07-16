# Paused Task Inserted Candidates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist already-inserted collection candidates during task execution so a paused task immediately shows its saved red-person records.

**Architecture:** Add a focused runner helper that builds the current candidate rows using existing outcome builders, filters them to `inserted`, and replaces the task candidate snapshot at persistence batch boundaries. Keep the existing terminal finalization unchanged so completed tasks still receive the full candidate diagnostics.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, pytest, Next.js client polling.

---

### Task 1: Reproduce paused candidate loss

**Files:**
- Modify: `apps/api/tests/test_collection_task_pause.py`
- Inspect: `apps/api/app/services/collection_runner.py`

- [ ] Add a failing test proving a persistence batch with inserted outcomes writes candidate rows before terminal completion.
- [ ] Add a failing test proving paused finalization preserves the previously written inserted snapshot.
- [ ] Run `pytest apps/api/tests/test_collection_task_pause.py -q` and confirm the new assertions fail for missing incremental persistence.

### Task 2: Persist the inserted snapshot

**Files:**
- Modify: `apps/api/app/services/collection_runner.py`

- [ ] Extract a helper that builds current Instagram and multi-platform candidate rows from `outcomes` and `platform_outcomes`.
- [ ] Filter the batch snapshot to `CandidateStatus.INSERTED.value`.
- [ ] Replace the task candidate rows and synchronize inserted statistics inside each persistence batch commit.
- [ ] Pass the current inserted snapshot into pause finalization so the final pause checkpoint cannot lose it.

### Task 3: Verify both completion modes

**Files:**
- Test: `apps/api/tests/test_collection_task_pause.py`
- Test: existing collection runner and candidate tests

- [ ] Run the focused pause tests and confirm they pass.
- [ ] Run candidate and collection runner regression tests.
- [ ] Run API lint/type checks available in the repository.
- [ ] Confirm the normal terminal path still replaces the snapshot with full candidate diagnostics.

### Task 4: Deploy and verify

**Files:**
- Deploy modified API files to `/opt/influencer-intel`.

- [ ] Rebuild and restart the API container without changing database volumes.
- [ ] Verify `/api-proxy/health` returns OK.
- [ ] Pause a running task or exercise the pause regression against the deployed API and confirm inserted candidates are returned.
