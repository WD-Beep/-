import "./register-path-aliases.ts";
import assert from "node:assert/strict";
import test from "node:test";

import type { CollectionTask } from "../src/lib/api.ts";
import {
  buildTaskDeleteConfirmCopy,
  isTaskRowIneffective,
  matchesEffectivenessFilter,
  taskEffectivenessCategory,
  taskHasRetentionData,
} from "../src/lib/task-effectiveness.ts";

function task(overrides: Partial<CollectionTask> = {}): CollectionTask {
  return {
    id: 1,
    name: "demo",
    collection_mode: "link_import",
    platform: "ltk",
    platforms: ["ltk"],
    keywords: [],
    input_urls: [],
    status: "completed_with_results",
    inserted_count: 1,
    result_count: 1,
    success_count: 1,
    ...overrides,
  } as CollectionTask;
}

test("taskHasRetentionData follows backend has_retention_traces flag", () => {
  assert.equal(taskHasRetentionData(task({ has_retention_traces: true })), true);
  assert.equal(taskHasRetentionData(task({ has_retention_traces: false })), false);
});

test("empty ltk insert is low_value_result not effective", () => {
  const row = task({
    effectiveness_category: "low_value_result",
    inserted_count: 1,
  });
  assert.equal(taskEffectivenessCategory(row), "low_value_result");
  assert.equal(isTaskRowIneffective(row), true);
  assert.equal(matchesEffectivenessFilter("effective", row), false);
  assert.equal(matchesEffectivenessFilter("low_value_result", row), true);
  assert.equal(matchesEffectivenessFilter("ineffective", row), true);
});

test("task with valuable data is effective", () => {
  const row = task({
    platform: "shopmy",
    effectiveness_category: "effective",
  });
  assert.equal(matchesEffectivenessFilter("effective", row), true);
  assert.equal(matchesEffectivenessFilter("low_value_result", row), false);
  assert.equal(isTaskRowIneffective(row), false);
});

test("partial failed task with large funnel is high value", () => {
  const row = task({
    status: "partial_failed",
    inserted_count: 21,
    result_count: 21,
    discovered_count: 574,
    profile_fetched_count: 481,
    filtered_out_count: 109,
    effectiveness_category: "high_value",
  });
  assert.equal(taskEffectivenessCategory(row), "high_value");
  assert.equal(matchesEffectivenessFilter("high_value", row), true);
  assert.equal(matchesEffectivenessFilter("low_value_result", row), false);
  assert.equal(isTaskRowIneffective(row), false);
});

test("single link import is low value and remains cleanup candidate", () => {
  const row = task({
    inserted_count: 1,
    result_count: 1,
    discovered_count: 1,
    profile_fetched_count: 1,
    effectiveness_category: "low_value_result",
  });
  assert.equal(taskEffectivenessCategory(row), "low_value_result");
  assert.equal(matchesEffectivenessFilter("low_value_result", row), true);
  assert.equal(isTaskRowIneffective(row), true);
});

test("zero insert is no_result", () => {
  const row = task({
    inserted_count: 0,
    result_count: 0,
    success_count: 0,
    effectiveness_category: "no_result",
    status: "completed_no_results",
  });
  assert.equal(matchesEffectivenessFilter("no_result", row), true);
  assert.equal(matchesEffectivenessFilter("effective", row), false);
});

test("delete confirm copy matches archive vs delete behavior", () => {
  const archive = buildTaskDeleteConfirmCopy({
    count: 1,
    hasRetentionData: true,
    taskName: "link import",
  });
  assert.match(archive.body, /不会删除红人库数据和来源作品关系/);
  assert.match(archive.body, /无结果或无价值结果/);
  assert.equal(archive.confirmLabel, "归档任务");
});
