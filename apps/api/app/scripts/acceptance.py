"""端到端 API 验收脚本。需先启动 PostgreSQL、migrate，并启动 API 服务。"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

import httpx

BASE = os.getenv("ACCEPTANCE_API_BASE", "http://localhost:8000")
TIMEOUT = 120.0


class AcceptanceError(Exception):
    pass


def ok(name: str) -> None:
    print(f"  [OK] {name}")


async def request(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    expected: int | tuple[int, ...] = 200,
    **kwargs: Any,
) -> httpx.Response:
    response = await client.request(method, f"{BASE}{path}", timeout=TIMEOUT, **kwargs)
    codes = (expected,) if isinstance(expected, int) else expected
    if response.status_code not in codes:
        detail = response.text[:500]
        raise AcceptanceError(f"{method} {path} -> {response.status_code}, expected {codes}: {detail}")
    return response


async def run() -> None:
    print("Instagram 红人智能采集平台 API 验收\n")

    async with httpx.AsyncClient() as client:
        await request(client, "GET", "/health")
        ok("Health check")

        summary = (await request(client, "GET", "/api/dashboard/summary")).json()
        if "instagram_influencers" not in summary:
            raise AcceptanceError("Dashboard summary 缺少 instagram_influencers")
        ok(f"Dashboard summary（Instagram {summary['instagram_influencers']} 人）")

        influencers = (
            await request(client, "GET", "/api/influencers?platform=instagram&page=1&page_size=5")
        ).json()
        if not influencers.get("items"):
            print("  [WARN] 红人库为空，将用 mock 采集任务写入测试数据")
        else:
            ok(f"红人列表（共 {influencers['total']} 条）")
        influencer_id = influencers["items"][0]["id"] if influencers.get("items") else None

        for param, label in [
            ("platform=instagram&has_email=true", "有邮箱"),
            ("platform=instagram&contactable=true", "可联系"),
            ("platform=instagram&high_match=true", "高匹配"),
        ]:
            filtered = (await request(client, "GET", f"/api/influencers?{param}&page_size=1")).json()
            ok(f"筛选「{label}」（{filtered['total']} 条）")

        # Instagram hashtag 发现（mock 或 apify）
        kw_task = (
            await request(
                client,
                "POST",
                "/api/collection-tasks",
                expected=201,
                json={
                    "name": "验收-Hashtag发现",
                    "collection_mode": "discovery",
                    "platform": "instagram",
                    "keywords": ["travel", "lifestyle"],
                    "discovery_limit": 10,
                },
            )
        ).json()
        kw_run = (
            await request(client, "POST", f"/api/collection-tasks/{kw_task['id']}/run", expected=(200, 201))
        ).json()
        if kw_run.get("new_count", 0) + kw_run.get("updated_count", 0) <= 0:
            raise AcceptanceError(f"Hashtag 采集未产生数据: {kw_run}")
        ok(f"Hashtag 发现任务 #{kw_task['id']}（new={kw_run.get('new_count')}, updated={kw_run.get('updated_count')}）")

        url_task = (
            await request(
                client,
                "POST",
                "/api/collection-tasks",
                expected=201,
                json={
                    "name": "验收-链接采集",
                    "collection_mode": "urls",
                    "platform": "instagram",
                    "input_urls": [
                        "https://www.instagram.com/mock_acceptance_1/",
                        "mock_acceptance_2",
                    ],
                    "discovery_limit": 10,
                },
            )
        ).json()
        url_run = (
            await request(client, "POST", f"/api/collection-tasks/{url_task['id']}/run", expected=(200, 201))
        ).json()
        ok(
            f"链接采集任务 #{url_task['id']}（new={url_run.get('new_count')}, updated={url_run.get('updated_count')}）"
        )

        batch = (
            await request(
                client,
                "POST",
                "/api/link-import/batches",
                expected=201,
                json={
                    "name": "验收-链接导入",
                    "raw_urls": (
                        "https://www.instagram.com/mock_import_1/\n"
                        "https://www.instagram.com/mock_import_2/\n"
                        "https://youtube.com/@invalid"
                    ),
                },
            )
        ).json()
        import_run = (
            await request(
                client,
                "POST",
                f"/api/link-import/batches/{batch['id']}/run",
                expected=(200, 201),
            )
        ).json()
        ok(f"链接导入批次 #{batch['id']}（success={import_run.get('success_count', '?')}）")

        refreshed = (
            await request(client, "GET", "/api/influencers?platform=instagram&page=1&page_size=5")
        ).json()
        if not refreshed.get("items"):
            raise AcceptanceError("采集后红人库仍为空")
        influencer_id = influencer_id or refreshed["items"][0]["id"]
        ok(f"红人库已有数据（{refreshed['total']} 条）")

        detail = (await request(client, "GET", f"/api/influencers/{influencer_id}")).json()
        required_fields = [
            "score",
            "product_fit",
            "travel_fit_score",
            "purchasing_power_score",
            "sales_potential_score",
            "audience_match_score",
        ]
        missing = [field for field in required_fields if detail.get(field) is None]
        if missing:
            raise AcceptanceError(f"红人详情缺少评分字段: {missing}")
        ok(f"红人详情 #{influencer_id} 含完整评分指标")

        ai = (
            await request(
                client,
                "POST",
                f"/api/ai/analyze-influencer/{influencer_id}",
                expected=(200, 201),
            )
        ).json()
        analysis = ai.get("analysis") or {}
        summary_text = analysis.get("ai_summary") or ai.get("summary")
        if not summary_text:
            raise AcceptanceError(f"AI 分析无 ai_summary: {list(ai.keys())}")
        if not analysis.get("score_reason") and not detail.get("score_reason"):
            raise AcceptanceError("AI 分析缺少 score_reason")
        ok(f"AI 分析（source={analysis.get('source', '?')}）")

        export = await request(client, "GET", "/api/influencers/export/excel?platform=instagram")
        if len(export.content) < 100:
            raise AcceptanceError("Excel 导出内容过小")
        ok(f"Excel 导出（{len(export.content)} bytes）")

        ai_status = (await request(client, "GET", "/api/ai/status")).json()
        ok(f"AI 状态（mode={ai_status.get('mode')}）")

        email_resp = (
            await request(
                client,
                "POST",
                "/api/email/test",
                expected=(200, 201, 400, 422),
                json={"to_email": "acceptance@example.com"},
            )
        ).json()
        ok(f"测试邮件（success={email_resp.get('success')}）")

        logs = (await request(client, "GET", "/api/email-logs?page=1&page_size=5")).json()
        ok(f"邮件日志（共 {logs.get('total', 0)} 条）")

        settings = (await request(client, "GET", "/api/settings/status")).json()
        for key in ("smtp", "ai", "apify"):
            if key not in settings:
                raise AcceptanceError(f"Settings 缺少 {key} 状态")
        ok("系统设置状态")

        rejected = await request(
            client,
            "POST",
            "/api/collection-tasks",
            expected=422,
            json={
                "name": "验收-拒绝非IG",
                "collection_mode": "urls",
                "platform": "youtube",
                "input_urls": ["https://www.youtube.com/@test"],
            },
        )
        ok("非 Instagram 平台创建被拒绝")

    print("\n全部验收通过")


def main() -> None:
    try:
        asyncio.run(run())
    except AcceptanceError as exc:
        print(f"\n验收失败: {exc}", file=sys.stderr)
        sys.exit(1)
    except httpx.ConnectError:
        print(f"\n无法连接 {BASE}，请先启动 API 服务。", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
