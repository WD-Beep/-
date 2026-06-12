import asyncio
import json
import re

import httpx


async def main() -> None:
    urls = [
        "https://www.youtube.com/channel/UCjFszKQ1yE9FJhHHqb5HQpg/about",
        "https://www.youtube.com/@TheSommerHome/about",
        "https://www.youtube.com/@TheSommerHomeYT/about",
    ]
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as client:
        for url in urls:
            try:
                response = await client.get(url)
                print("URL", url, "status", response.status_code, "len", len(response.text))
                text = response.text
                for pattern in (
                    r"ytInitialData\s*=\s*(\{.*?\});",
                    r"var ytInitialData = (\{.*?\});",
                ):
                    match = re.search(pattern, text, re.S)
                    if match:
                        print("found ytInitialData", len(match.group(1)))
                for token in ("lnktr.ee", "linktr.ee", "TheSommerHomeYT", "channelExternalLink", "aboutChannelRenderer"):
                    if token.lower() in text.lower():
                        print("token", token, "present")
                links = re.findall(r"https?://(?:www\.)?lnktr\.ee/[A-Za-z0-9_-]+", text, re.I)
                print("regex links", links[:5])
            except Exception as exc:
                print("ERR", url, exc)


if __name__ == "__main__":
    asyncio.run(main())
