import "./register-path-aliases.ts";
import assert from "node:assert/strict";
import test from "node:test";

import {
  buildInfluencerExportUrl,
  influencerFilterQueryParams,
} from "../src/lib/api.ts";

test("valueTier maps to value_tier query param", () => {
  const params = influencerFilterQueryParams({ valueTier: "direct_contact" });
  assert.equal(params.value_tier, "direct_contact");
});

test("highValue still maps to high_value query param", () => {
  const params = influencerFilterQueryParams({ highValue: true });
  assert.equal(params.high_value, true);
});

test("emailStatus maps to email_status query param", () => {
  const params = influencerFilterQueryParams({ emailStatus: "sent" });
  assert.equal(params.email_status, "sent");
});

test("export URL includes value_tier and high_value filters", () => {
  const url = buildInfluencerExportUrl({
    valueTier: "manual_research",
    highValue: true,
    collectionTaskId: 52,
    platform: "tiktok",
    search: "travel",
  });

  assert.equal(url.includes("value_tier=manual_research"), true);
  assert.equal(url.includes("high_value=true"), true);
  assert.equal(url.includes("collection_task_id=52"), true);
  assert.equal(url.includes("platform=tiktok"), true);
  assert.equal(url.includes("keyword=travel"), true);
});

test("export URL includes skip tier filter", () => {
  const url = buildInfluencerExportUrl({ valueTier: "skip" });
  assert.equal(url.includes("value_tier=skip"), true);
});

test("export URL includes email status filter", () => {
  const url = buildInfluencerExportUrl({ emailStatus: "unsent" });
  assert.equal(url.includes("email_status=unsent"), true);
});
