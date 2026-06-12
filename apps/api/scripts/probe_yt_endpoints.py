import asyncio
import json

from app.services.api_direct_client import ad_get, reset_request_budget


async def main() -> None:
    reset_request_budget()
    cid = "UCjFszKQ1yE9FJhHHqb5HQpg"
    url = f"https://www.youtube.com/channel/{cid}"
    candidates = [
        ("/v1/youtube/channel", {"url": url}),
        ("/v1/youtube/channel", {"query": url}),
        ("/v1/youtube/channels", {"query": url, "pages": 1}),
        ("/v1/youtube/channels", {"url": url, "query": "The Sommer Home"}),
        ("/v1/youtube/channels/info", {"channel_id": cid}),
        ("/v1/youtube/channels/info", {"query": cid}),
        ("/v1/youtube/channels/details", {"channel_id": cid}),
        ("/v1/youtube/channels/details", {"query": cid}),
    ]
    for path, params in candidates:
        try:
            response = await ad_get(path, params=params, platform="youtube")
            text = json.dumps(response, ensure_ascii=True)
            print("OK", path, params, "keys", list(response.keys())[:8], "linkish", "link" in text.lower())
            if "lnktr" in text.lower() or "linktr" in text.lower() or "external" in text.lower():
                print(text[:3000])
        except Exception as exc:
            print("ERR", path, params, str(exc)[:120])


if __name__ == "__main__":
    asyncio.run(main())
