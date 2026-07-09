import "./register-path-aliases.ts";

import assert from "node:assert/strict";
import test from "node:test";

const LINK_IMPORT_STAT_PLATFORMS = ["pinterest", "ltk", "shopmy"] as const;
const URL_ONLY_PLATFORM_STAT_HINT = "主要通过链接导入或外链发现，站内关键词搜索暂未接入";

type PlatformStatItem = {
  platform: string;
  total: number;
};

function stat(platform: string, total: number): PlatformStatItem {
  return { platform, total };
}

function linkImportCardKeys(items: PlatformStatItem[]): string[] {
  const byKey = new Map(items.map((item) => [item.platform, item]));
  const keys: string[] = [];
  for (const key of LINK_IMPORT_STAT_PLATFORMS) {
    const stats = byKey.get(key);
    if (!stats || stats.total <= 0) continue;
    keys.push(key);
  }
  return keys;
}

test("link-import platform cards omitted without inserted stats", () => {
  const keys = linkImportCardKeys([
    stat("tiktok", 3),
    stat("youtube", 0),
    stat("instagram", 0),
    stat("facebook", 0),
  ]);
  for (const platform of LINK_IMPORT_STAT_PLATFORMS) {
    assert.equal(keys.includes(platform), false);
  }
});

test("link-import platform cards shown with real stats", () => {
  const keys = linkImportCardKeys([
    stat("tiktok", 0),
    stat("pinterest", 2),
  ]);
  assert.deepEqual(keys, ["pinterest"]);
  assert.equal(URL_ONLY_PLATFORM_STAT_HINT, "主要通过链接导入或外链发现，站内关键词搜索暂未接入");
});

test("all platform copy is scoped to the current brand", async () => {
  const { buildPlatformCards, platformListTitle } = await import("../src/lib/platform-organizer.ts");
  const cards = buildPlatformCards([
    {
      platform: "instagram",
      total: 1,
      has_email: 0,
      direct_contact: 0,
      missing_contact: 1,
      high_value: 0,
    },
  ]);

  assert.equal(cards[0]?.label, "当前品牌全部平台");
  assert.equal(platformListTitle("all"), "当前品牌线索列表");
});
