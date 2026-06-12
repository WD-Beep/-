import asyncio
import json

from app.services.api_direct_client import ad_get, reset_request_budget


async def main() -> None:
    reset_request_budget()
    base = {"query": "The Sommer Home", "pages": 1}
    extras = [
        {},
        {"include_about": "true"},
        {"include_about": 1},
        {"about": 1},
        {"with_about": 1},
        {"with_links": 1},
        {"links": 1},
        {"expand": "about"},
        {"expand": "links"},
        {"fields": "links,external_links,about"},
        {"part": "about,links"},
    ]
    for extra in extras:
        params = {**base, **extra}
        try:
            response = await ad_get("/v1/youtube/channels", params=params, platform="youtube")
            ch = next((c for c in response.get("channels", []) if "Sommer Home" == c.get("title")), None)
            if not ch:
                continue
            keys = sorted(ch.keys())
            print("params", extra, "keys", keys)
            if len(keys) > 7:
                print(json.dumps(ch, ensure_ascii=True)[:2000])
        except Exception as exc:
            print("ERR", extra, str(exc)[:80])


if __name__ == "__main__":
    asyncio.run(main())
