import asyncio
import json

from app.services.api_direct_client import ad_get, reset_request_budget


async def main() -> None:
    reset_request_budget()
    probes = [
        ("/v1/youtube/posts", {"query": "The Sommer Home", "pages": 1, "full_description": 1}),
        ("/v1/youtube/posts", {"query": "The Sommer Home", "pages": 1, "include_description": 1}),
        ("/v1/youtube/posts", {"query": "lnktr.ee TheSommerHomeYT", "pages": 1}),
        ("/v1/youtube/posts", {"query": "https://lnktr.ee/TheSommerHomeYT", "pages": 1}),
        ("/v1/youtube/posts", {"query": "UCjFszKQ1yE9FJhHHqb5HQpg", "pages": 1, "channel_id": "UCjFszKQ1yE9FJhHHqb5HQpg"}),
        ("/v1/youtube/channels", {"query": "The Sommer Home", "pages": 1, "expand_description": 1}),
    ]
    for path, params in probes:
        try:
            data = await ad_get(path, params=params, platform="youtube")
            text = json.dumps(data, ensure_ascii=True)
            print("OK", params, "linkish", "lnktr" in text.lower() or "linktr" in text.lower())
            if "lnktr" in text.lower() or "linktr" in text.lower():
                print(text[:4000])
            posts = data.get("posts") or []
            if posts:
                first = posts[0]
                print("post keys", sorted(first.keys()))
                for key in ("description", "snippet", "full_description", "links", "channel_links"):
                    if first.get(key):
                        print(key, str(first.get(key))[:500])
        except Exception as exc:
            print("ERR", params, str(exc)[:100])


if __name__ == "__main__":
    asyncio.run(main())
