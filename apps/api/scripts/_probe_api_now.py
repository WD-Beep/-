"""快速探测 API Direct 各端点当前可用性。"""
from __future__ import annotations

import asyncio

from app.services.api_direct_client import ApiDirectError, ad_get, reset_request_budget


async def probe(label: str, path: str, params: dict, platform: str) -> bool:
    try:
        data = await ad_get(path, params=params, platform=platform)
        if "videos" in data:
            print(f"[OK] {label} videos={len(data.get('videos') or [])}")
        elif "channels" in data:
            print(f"[OK] {label} channels={len(data.get('channels') or [])}")
        elif "user" in data:
            user = data["user"] or {}
            print(f"[OK] {label} user={user.get('username')} followers={user.get('follower_count')}")
        else:
            print(f"[OK] {label} keys={list(data.keys())}")
        return True
    except ApiDirectError as exc:
        print(f"[FAIL] {label} status={exc.status_code} {exc}")
        return False


async def main() -> int:
    reset_request_budget()
    youtube_ok = await probe(
        "youtube channels",
        "/v1/youtube/channels",
        {"query": "amazon finds creator", "pages": 1},
        "youtube",
    )
    reset_request_budget()
    tiktok_ok = await probe(
        "tiktok videos",
        "/v1/tiktok/videos",
        {"query": "amazon finds", "pages": 1},
        "tiktok",
    )

    ig_names = ["instagram", "nike", "travel", "baduser_xyz_12345"]
    ig_ok = ig_fail = 0
    for name in ig_names:
        reset_request_budget()
        try:
            await ad_get("/v1/instagram/user", params={"username": name}, platform="instagram")
            ig_ok += 1
        except Exception as exc:
            ig_fail += 1
            print(f"[FAIL] instagram user {name}: {exc}")

    print(f"instagram sample: ok={ig_ok} fail={ig_fail}")
    print(f"summary: youtube={youtube_ok} tiktok={tiktok_ok}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
