import "./register-path-aliases.ts";
import assert from "node:assert/strict";
import test from "node:test";

import type { CollectionTask } from "../src/lib/api.ts";
import { buildCollectionTasksQueryString } from "../src/lib/api.ts";
import {
  isTaskTestHistory,
  nextTaskListPageForFilterChange,
  taskManagementTags,
} from "../src/lib/task-effectiveness.ts";

function task(overrides: Partial<CollectionTask> = {}): CollectionTask {
  return {
    id: 1,
    name: "real campaign",
    collection_mode: "link_import",
    platform: "ltk",
    platforms: ["ltk"],
    keywords: [],
    input_urls: [],
    status: "completed_with_results",
    inserted_count: 1,
    result_count: 1,
    success_count: 1,
    run_checkpoint: {},
    ...overrides,
  } as CollectionTask;
}

test("test and history tasks are identified without deleting real tasks", () => {
  const testTask = task({ name: "seed-discovery-tiktok 验收" });
  const historyTask = task({ run_checkpoint: { link_import_source: true } });
  const realTask = task({ name: "Summer creator search", inserted_count: 5, result_count: 5 });

  assert.equal(isTaskTestHistory(testTask), true);
  assert.equal(isTaskTestHistory(historyTask), true);
  assert.equal(isTaskTestHistory(realTask), false);
  assert.ok(taskManagementTags(testTask).some((tag) => tag.label === "测试任务"));
  assert.ok(taskManagementTags(historyTask).some((tag) => tag.label === "历史批次"));
});

test("duplicate tasks are marked but not deleted automatically", () => {
  const row = task({ is_possible_duplicate: true });
  const tags = taskManagementTags(row).map((tag) => tag.label);
  assert.ok(tags.includes("可能重复"));
});

test("filter changes reset task list pagination", () => {
  assert.equal(nextTaskListPageForFilterChange({ currentPage: 4, changed: true }), 1);
  assert.equal(nextTaskListPageForFilterChange({ currentPage: 4, changed: false }), 4);
});

test("collection task list query uses page and page size", () => {
  const query = buildCollectionTasksQueryString(3, 50, {
    task_view: "test_history",
    search: "seed",
  });
  assert.equal(query, "page=3&page_size=50&owner_scope=mine&task_view=test_history&search=seed");
});

test("collection task list query supports admin all-owner scope", () => {
  const query = buildCollectionTasksQueryString(1, 20, {
    owner_scope: "all",
  });
  assert.equal(query, "page=1&page_size=20&owner_scope=all");
});
