import asyncio
import sys

async def main():
    import httpx
    url = "https://www.youtube.com/youtubei/v1/browse?key=AIzaSyAO_FJ2SlWIP9oR0QdBjAtpU1QU_Twe1eQ"
    payload = {
        "context": {"client": {"clientName": "WEB", "clientVersion": "2.20250328.01.00", "hl": "en", "gl": "US"}},
        "browseId": "UCjFszKQ1yE9FJhHHqb5HQpg",
        "params": "EgVhYm91dCI6FAgKBg9",
    }
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
            r = await c.post(url, json=payload, headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"})
            sys.stdout.write(f"status={r.status_code} len={len(r.text)} lnktr={'lnktr' in r.text.lower()}\n")
            sys.stdout.flush()
    except Exception as e:
        sys.stdout.write(f"err={type(e).__name__}: {e}\n")
        sys.stdout.flush()

asyncio.run(main())
