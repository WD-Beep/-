"""Probe YouTube InnerTube browse for channel About links."""
from __future__ import annotations

import asyncio
import json
import re

import httpx

CHANNEL_ID = "UCjFszKQ1yE9FJhHHqb5HQpg"
INNERTUBE_KEY = "AIzaSyAO_FJ2SlWIP9oR0QdBjAtpU1QU_Twe1eQ"
CLIENT_VERSION = "2.20250328.01.00"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def find_external_links(obj, found: list) -> None:
    if isinstance(obj, dict):
        if "channelExternalLinkViewModel" in obj:
            model = obj["channelExternalLinkViewModel"]
            title = (
                model.get("title", {}).get("content")
                if isinstance(model.get("title"), dict)
                else model.get("title")
            )
            link = (
                model.get("link", {}).get("content")
                if isinstance(model.get("link"), dict)
                else model.get("link")
            )
            if link:
                found.append({"title": title, "link": link})
        for value in obj.values():
            find_external_links(value, found)
    elif isinstance(obj, list):
        for item in obj:
            find_external_links(item, found)


async def try_innertube(params: str) -> None:
    payload = {
        "context": {
            "client": {
                "clientName": "WEB",
                "clientVersion": CLIENT_VERSION,
                "hl": "en",
                "gl": "US",
            }
        },
        "browseId": CHANNEL_ID,
        "params": params,
    }
    url = f"https://www.youtube.com/youtubei/v1/browse?key={INNERTUBE_KEY}"
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        r = await client.post(url, json=payload, headers={"User-Agent": UA, "Content-Type": "application/json"})
        print("innertube", params, r.status_code, len(r.text))
        if r.status_code != 200:
            print(r.text[:500])
            return
        data = r.json()
        found: list = []
        find_external_links(data, found)
        print("links", found)
        text = json.dumps(data)
        for token in ("lnktr.ee", "TheSommerHomeYT", "channelExternalLink"):
            print(token, token.lower() in text.lower())


async def try_about_html() -> None:
    url = f"https://www.youtube.com/channel/{CHANNEL_ID}/about"
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        r = await client.get(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
        print("html", r.status_code, len(r.text))
        text = r.text
        for token in ("lnktr.ee", "TheSommerHomeYT", "channelExternalLinkViewModel", "ytInitialData"):
            print(token, token in text or token.lower() in text.lower())
        m = re.search(r"var ytInitialData = (\{.*?\});", text, re.S)
        if m:
            data = json.loads(m.group(1))
            found: list = []
            find_external_links(data, found)
            print("ytInitialData links", found)


async def main() -> None:
    for params in (
        "EgVhYm91dCI6FAgKBg9",
        "EgVhYm91dCI%3D",
        "EgVhYm91dA%3D%3D",
        "EgVhYm91dCI6BYI2",
    ):
        try:
            await try_innertube(params)
        except Exception as exc:
            print("ERR innertube", params, exc)
    try:
        await try_about_html()
    except Exception as exc:
        print("ERR html", exc)


if __name__ == "__main__":
    asyncio.run(main())
