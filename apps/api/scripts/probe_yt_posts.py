import asyncio
import json

from app.services.api_direct_client import ad_get, reset_request_budget


async def main() -> None:
    reset_request_budget()
    response = await ad_get(
        "/v1/youtube/posts",
        params={"query": "The Sommer Home", "pages": 1},
        platform="youtube",
    )
    with open("tmp_posts.json", "w", encoding="utf-8") as handle:
        json.dump(response, handle, ensure_ascii=False, indent=2)
    posts = response.get("posts") or []
    print("count", len(posts))
    if posts:
        print("post keys", sorted(posts[0].keys()))
        for post in posts[:3]:
            for key, value in post.items():
                lower = key.lower()
                if isinstance(value, (dict, list)) or any(token in lower for token in ("link", "url", "channel", "author")):
                    print("---", key, json.dumps(value, ensure_ascii=False)[:2000])


if __name__ == "__main__":
    asyncio.run(main())
