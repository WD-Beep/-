"""验证知识库 API 与话术推荐接口。"""

import asyncio

from httpx import ASGITransport, AsyncClient

from app.main import app

HEADERS = {"X-User-Id": "1", "X-Product-Id": "1"}


async def main() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        bases = await client.get("/api/knowledge-bases", headers=HEADERS)
        print("knowledge-bases", bases.status_code, bases.json())

        docs = await client.get("/api/knowledge-documents", headers=HEADERS)
        print("knowledge-documents", docs.status_code, docs.json()["total"], "docs")

        search = await client.get(
            "/api/knowledge-search",
            params={"q": "北欧 视觉 品牌"},
            headers=HEADERS,
        )
        print("knowledge-search", search.status_code, len(search.json()), "hits")

        influencers = await client.get("/api/influencers", params={"page": 1, "page_size": 1}, headers=HEADERS)
        items = influencers.json().get("items", [])
        if not items:
            print("no influencers, skip recommend")
            return
        influencer_id = items[0]["id"]
        recommend = await client.post(
            "/api/scripts/recommend",
            headers=HEADERS,
            json={"influencer_id": influencer_id, "user_intent": "首次联系"},
        )
        body = recommend.json()
        print("scripts/recommend", recommend.status_code, body.get("provider"), body.get("configured"))
        print("final_message preview:", (body.get("final_message") or "")[:120])


if __name__ == "__main__":
    asyncio.run(main())
