"""检查 .env 中的 API_DIRECT_API_KEY 是否可用。"""
from __future__ import annotations

import asyncio
import sys

import httpx

from app.core.config import settings


async def main() -> int:
    key = settings.api_direct_api_key.strip()
    print(f"provider={settings.active_instagram_provider}")
    print(f"configured={settings.is_api_direct_configured}")
    if not key:
        print("error=未配置 API_DIRECT_API_KEY")
        return 1

    base = settings.api_direct_api_base.rstrip("/")
    url = f"{base}/v1/instagram/user"
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            url,
            headers={"X-API-Key": key},
            params={"username": "instagram"},
        )
    print(f"http={response.status_code}")
    if response.status_code == 200:
        data = response.json()
        user = data.get("user") or {}
        print(f"username={user.get('username')}")
        print(f"followers={user.get('follower_count')}")
        return 0
    print(f"body={response.text[:300]}")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
