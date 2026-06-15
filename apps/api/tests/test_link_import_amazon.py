"""链接导入 Amazon 商品链接支持测试。"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from app.models.collection_task import CollectionTask
from app.models.enums import CollectionMode
from app.models.tenant import Product
from app.schemas.collection_task import CollectionTaskCreate
from app.services.amazon_url import normalize_amazon_product_url, parse_amazon_product_url
from app.services.collection_task import CollectionTaskService
from app.services.link_import import LinkImportService
from app.services.url_parser import parse_raw_urls, supported_platform_hint
from app.db.session import async_session_factory


CORE_DISCOVERY_PLATFORMS = ["instagram", "youtube", "tiktok", "facebook"]

AMAZON_DP = (
    "https://www.amazon.com/Nylon-Laundry-Bag-Drawstring-Washable/dp/B00VOEZYHI/"
    "ref=sr_1_1?dchild=1&keywords=laundry"
)
AMAZON_GP = "https://www.amazon.co.uk/gp/product/B00VOEZYHI/ref=abc?psc=1"
AMAZON_PRODUCT = "https://www.amazon.de/product/B00VOEZYHI/?utm_source=test&utm_campaign=x"
AMAZON_TRACKED = (
    "https://www.amazon.com/dp/B00VOEZYHI/?ref_=cm_sw_r_cp_ud&tag=affiliate-20&psc=1"
)
AMAZON_FULLWIDTH_PATH = (
    "https://www.amazon.com/Laundry-Washable-Organizer-Drawstring%EF%BC%8CLarge-Essentials/"
    "dp/B0CPF3W9B2/ref=zg_bs_g_3744371_d_sccl_2/138-2111992-2516563?psc=1"
)


def test_normalize_amazon_dp_url():
    assert normalize_amazon_product_url(AMAZON_DP) == "https://www.amazon.com/dp/B00VOEZYHI"


def test_normalize_amazon_gp_product_url():
    assert normalize_amazon_product_url(AMAZON_GP) == "https://www.amazon.co.uk/dp/B00VOEZYHI"


def test_normalize_amazon_product_path_url():
    assert normalize_amazon_product_url(AMAZON_PRODUCT) == "https://www.amazon.de/dp/B00VOEZYHI"


def test_normalize_amazon_strips_ref_tag_psc_utm():
    assert normalize_amazon_product_url(AMAZON_TRACKED) == "https://www.amazon.com/dp/B00VOEZYHI"


def test_parse_amazon_product_url_metadata():
    seed = parse_amazon_product_url(AMAZON_DP)
    assert seed is not None
    assert seed["platform"] == "amazon"
    assert seed["asin"] == "B00VOEZYHI"
    assert seed["marketplace"] == "amazon.com"
    assert seed["normalized_url"] == "https://www.amazon.com/dp/B00VOEZYHI"
    assert seed["source_type"] == "amazon_product"


def test_parse_amazon_product_url_with_fullwidth_path_segment():
    seed = parse_amazon_product_url(AMAZON_FULLWIDTH_PATH)
    assert seed is not None
    assert seed["asin"] == "B0CPF3W9B2"
    assert seed["normalized_url"] == "https://www.amazon.com/dp/B0CPF3W9B2"
    keywords = seed.get("product_keywords") or []
    assert "laundry" in keywords
    assert "organizer" in keywords
    assert "drawstring" in keywords
    strong = seed.get("strong_keywords") or []
    assert "laundry bag" in strong
    assert "travel laundry bag" in strong


def test_parse_amazon_product_url_extracts_keywords_from_slug():
    seed = parse_amazon_product_url(AMAZON_DP)
    assert seed is not None
    keywords = seed.get("product_keywords") or []
    assert "laundry" in keywords
    assert "drawstring" in keywords


def test_parse_competitor_product_inputs_extracts_amazon_path_keywords():
    from app.services.competitor_product_discovery import parse_competitor_product_inputs

    task = CollectionTask(
        name="amazon-fullwidth",
        platform="instagram",
        collection_mode="competitor_product",
        keywords=[],
        input_urls=[AMAZON_FULLWIDTH_PATH],
    )
    info = parse_competitor_product_inputs(task)
    assert info.asin == "B0CPF3W9B2"
    assert "laundry bag" in info.strong_keywords
    assert "travel laundry bag" in info.search_keywords
    assert info.brand == "Aegero"


def test_parse_raw_urls_accepts_amazon_and_rejects_unknown():
    valid, invalid = parse_raw_urls(f"{AMAZON_DP}\nhttps://example.com/unknown")
    assert len(valid) == 1
    assert valid[0]["platform"] == "amazon"
    assert valid[0]["asin"] == "B00VOEZYHI"
    assert len(invalid) == 1
    assert invalid[0].startswith("第 2 行")
    assert "无法识别平台" in invalid[0]


def test_supported_platform_hint_includes_amazon():
    hint = supported_platform_hint()
    assert "Amazon" in hint
    assert "Instagram" in hint


def test_link_import_amazon_converts_to_competitor_product():
    task = CollectionTaskCreate(
        name="Amazon seed",
        collection_mode=CollectionMode.LINK_IMPORT,
        platform="instagram",
        input_urls=[AMAZON_DP],
    )
    assert task.collection_mode == CollectionMode.COMPETITOR_PRODUCT
    assert task.platform == "multi"
    assert task.platforms == CORE_DISCOVERY_PLATFORMS
    assert task.input_urls == ["https://www.amazon.com/dp/B00VOEZYHI"]
    assert "B00VOEZYHI" in task.keywords
    assert "laundry bag" in task.keywords or "laundry" in task.keywords
    seeds = task.run_checkpoint.get("amazon_product_seeds") or []
    assert len(seeds) == 1
    assert seeds[0]["asin"] == "B00VOEZYHI"
    assert seeds[0]["url"] == AMAZON_DP
    assert seeds[0]["normalized_url"] == "https://www.amazon.com/dp/B00VOEZYHI"
    assert seeds[0]["marketplace"] == "amazon.com"
    assert seeds[0]["source_type"] == "amazon_product"
    assert task.run_checkpoint.get("link_import_source") is True


@pytest.mark.parametrize(
    "url",
    [AMAZON_DP, AMAZON_GP, AMAZON_PRODUCT],
)
def test_link_import_amazon_url_shapes_create_task(url: str):
    task = CollectionTaskCreate(
        name="Amazon shape",
        collection_mode=CollectionMode.LINK_IMPORT,
        platform="instagram",
        input_urls=[url],
    )
    assert task.collection_mode == CollectionMode.COMPETITOR_PRODUCT
    seeds = task.run_checkpoint.get("amazon_product_seeds") or []
    assert len(seeds) == 1
    assert seeds[0]["url"] == url
    assert seeds[0]["normalized_url"].endswith("/dp/B00VOEZYHI")


def test_link_import_amazon_seed_preserves_raw_url_with_tracking_params():
    task = CollectionTaskCreate(
        name="Amazon tracked",
        collection_mode=CollectionMode.LINK_IMPORT,
        platform="instagram",
        input_urls=[AMAZON_TRACKED],
    )
    seeds = task.run_checkpoint.get("amazon_product_seeds") or []
    assert seeds[0]["url"] == AMAZON_TRACKED
    assert "ref_" in seeds[0]["url"]
    assert "tag=" in seeds[0]["url"]
    assert seeds[0]["normalized_url"] == "https://www.amazon.com/dp/B00VOEZYHI"


def test_link_import_profile_platforms_still_supported():
    cases = [
        ("https://www.instagram.com/example_user/", "instagram"),
        ("https://www.pinterest.com/example_user/", "pinterest"),
        ("https://www.shopltk.com/explore/example_user", "ltk"),
        ("https://shopmy.us/example_user", "shopmy"),
    ]
    for url, platform in cases:
        task = CollectionTaskCreate(
            name=f"import-{platform}",
            collection_mode=CollectionMode.LINK_IMPORT,
            platform="instagram",
            input_urls=[url],
        )
        assert task.collection_mode == CollectionMode.LINK_IMPORT
        assert task.platform == platform
        assert task.platforms == [platform]
        assert task.input_urls
        assert task.run_checkpoint.get("link_import_platforms") == [platform]

    with pytest.raises(ValueError, match="分任务提交"):
        CollectionTaskCreate(
            name="mixed",
            collection_mode=CollectionMode.LINK_IMPORT,
            platform="instagram",
            input_urls=[
                AMAZON_DP,
                "https://www.instagram.com/example_user/",
            ],
        )


def test_api_create_link_import_amazon_task():
    async def _run() -> None:
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        suffix = uuid.uuid4().hex[:8]
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/collection-tasks",
                headers={"X-User-Id": "1", "X-Product-Id": "1"},
                json={
                    "name": f"amazon-link-import-{suffix}",
                    "collection_mode": "link_import",
                    "platform": "instagram",
                    "input_urls": [AMAZON_DP],
                },
            )
            assert response.status_code == 201, response.text
            data = response.json()
            assert data["collection_mode"] == "competitor_product"
            assert data["platforms"] == CORE_DISCOVERY_PLATFORMS
            assert data["input_urls"] == ["https://www.amazon.com/dp/B00VOEZYHI"]
            assert "B00VOEZYHI" in (data.get("keywords") or [])
            seeds = (data.get("run_checkpoint") or {}).get("amazon_product_seeds") or []
            assert len(seeds) == 1
            assert seeds[0]["asin"] == "B00VOEZYHI"
            assert seeds[0]["url"] == AMAZON_DP
            assert seeds[0]["normalized_url"] == "https://www.amazon.com/dp/B00VOEZYHI"
            assert data["product_id"] == 1
            task_id = data["id"]

            denied_all = await client.get(
                f"/api/collection-tasks/{task_id}",
                headers={"X-User-Id": "1", "X-Product-Id": "0"},
            )
            assert denied_all.status_code == 403
            denied_update = await client.patch(
                f"/api/collection-tasks/{task_id}",
                headers={"X-User-Id": "1", "X-Product-Id": "0"},
                json={"name": "should-not-update"},
            )
            assert denied_update.status_code == 403
            denied_run = await client.post(
                f"/api/collection-tasks/{task_id}/run",
                headers={"X-User-Id": "1", "X-Product-Id": "0"},
            )
            assert denied_run.status_code == 403
            denied_export = await client.get(
                f"/api/collection-tasks/{task_id}/candidates/export",
                headers={"X-User-Id": "1", "X-Product-Id": "0"},
            )
            assert denied_export.status_code == 403
            denied_delete = await client.delete(
                f"/api/collection-tasks/{task_id}",
                headers={"X-User-Id": "1", "X-Product-Id": "0"},
            )
            assert denied_delete.status_code == 403

            await client.delete(
                f"/api/collection-tasks/{task_id}",
                headers={"X-User-Id": "1", "X-Product-Id": "1"},
            )

    asyncio.run(_run())


def test_api_create_amazon_link_import_rejects_all_products_context():
    async def _run() -> None:
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/collection-tasks",
                headers={"X-User-Id": "1", "X-Product-Id": "0"},
                json={
                    "name": "amazon-all-products",
                    "collection_mode": "link_import",
                    "platform": "instagram",
                    "input_urls": [AMAZON_DP],
                },
            )
            assert response.status_code == 400

    asyncio.run(_run())


def test_api_amazon_task_cross_product_access_denied():
    async def _run() -> None:
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        suffix = uuid.uuid4().hex[:8]
        product_b_id: int
        async with async_session_factory() as db_session:
            product_b = Product(
                workspace_id=1,
                name=f"Amazon跨产品B-{suffix}",
                slug=f"amazon-cross-b-{suffix}",
                is_default=False,
            )
            db_session.add(product_b)
            await db_session.flush()
            product_b_id = product_b.id
            await db_session.commit()

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            create = await client.post(
                "/api/collection-tasks",
                headers={"X-User-Id": "1", "X-Product-Id": "1"},
                json={
                    "name": f"amazon-cross-{suffix}",
                    "collection_mode": "link_import",
                    "platform": "instagram",
                    "input_urls": [AMAZON_DP],
                },
            )
            assert create.status_code == 201, create.text
            task_id = create.json()["id"]

            denied = await client.get(
                f"/api/collection-tasks/{task_id}",
                headers={"X-User-Id": "1", "X-Product-Id": str(product_b_id)},
            )
            assert denied.status_code == 403

            await client.delete(
                f"/api/collection-tasks/{task_id}",
                headers={"X-User-Id": "1", "X-Product-Id": "1"},
            )

    asyncio.run(_run())


def test_api_create_link_import_amazon_requires_tenant_headers():
    async def _run() -> None:
        from httpx import ASGITransport, AsyncClient

        from app.main import app

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/collection-tasks",
                json={
                    "name": "amazon-no-tenant",
                    "collection_mode": "link_import",
                    "platform": "instagram",
                    "input_urls": [AMAZON_DP],
                },
            )
            assert response.status_code == 422

    asyncio.run(_run())


def test_amazon_collection_task_isolated_by_product():
    async def _run() -> None:
        suffix = uuid.uuid4().hex[:8]
        async with async_session_factory() as db_session:
            product_b = Product(
                workspace_id=1,
                name=f"Amazon隔离B-{suffix}",
                slug=f"amazon-isolation-b-{suffix}",
                is_default=False,
            )
            db_session.add(product_b)
            await db_session.flush()

            task_a = CollectionTask(
                name=f"amazon-a-{suffix}",
                platform="instagram",
                platforms=["instagram"],
                collection_mode=CollectionMode.COMPETITOR_PRODUCT.value,
                keywords=["B00VOEZYHI"],
                input_urls=["https://www.amazon.com/dp/B00VOEZYHI"],
                product_id=1,
                user_id=1,
                workspace_id=1,
                run_checkpoint={
                    "amazon_product_seeds": [
                        {
                            "asin": "B00VOEZYHI",
                            "platform": "amazon",
                            "normalized_url": "https://www.amazon.com/dp/B00VOEZYHI",
                        }
                    ]
                },
            )
            task_b = CollectionTask(
                name=f"amazon-b-{suffix}",
                platform="instagram",
                platforms=["instagram"],
                collection_mode=CollectionMode.COMPETITOR_PRODUCT.value,
                keywords=["B00VOEZYHI"],
                input_urls=["https://www.amazon.com/dp/B00VOEZYHI"],
                product_id=product_b.id,
                user_id=1,
                workspace_id=1,
                run_checkpoint={
                    "amazon_product_seeds": [
                        {
                            "asin": "B00VOEZYHI",
                            "platform": "amazon",
                            "normalized_url": "https://www.amazon.com/dp/B00VOEZYHI",
                        }
                    ]
                },
            )
            db_session.add_all([task_a, task_b])
            await db_session.flush()

            from app.schemas.collection_task import CollectionTaskFilter

            page = await CollectionTaskService.list_tasks(
                db_session, CollectionTaskFilter(product_id=1), page=1, page_size=200
            )
            names = {item.name for item in page.items}
            assert f"amazon-a-{suffix}" in names
            assert f"amazon-b-{suffix}" not in names
            await db_session.rollback()

    asyncio.run(_run())


def test_link_import_rejects_valid_and_invalid_mixed():
    with pytest.raises(ValueError, match="第 2 行"):
        CollectionTaskCreate(
            name="invalid mixed",
            collection_mode=CollectionMode.LINK_IMPORT,
            input_urls=[
                "https://www.pinterest.com/example_user/",
                "https://unknown.example/x",
            ],
        )


def test_link_import_multi_platform_inferred():
    task = CollectionTaskCreate(
        name="multi",
        collection_mode=CollectionMode.LINK_IMPORT,
        input_urls=[
            "https://www.instagram.com/example_a/",
            "https://www.pinterest.com/example_user/",
            "https://shopmy.us/example_user",
        ],
    )
    assert task.platform == "multi"
    assert task.platforms == ["instagram", "pinterest", "shopmy"]
    assert task.run_checkpoint["link_import_platforms"] == ["instagram", "pinterest", "shopmy"]


def test_link_import_update_schema_rejects_valid_and_invalid_mixed():
    from pydantic import ValidationError

    from app.schemas.collection_task import CollectionTaskUpdate

    with pytest.raises(ValidationError, match=r"第 2 行"):
        CollectionTaskUpdate(
            collection_mode=CollectionMode.LINK_IMPORT,
            input_urls=[
                "https://www.pinterest.com/example_user/",
                "https://unknown.example/x",
            ],
        )


def test_link_import_update_service_rejects_valid_and_invalid_mixed():
    async def _run() -> None:
        from app.schemas.collection_task import CollectionTaskUpdate

        async with async_session_factory() as db_session:
            task = CollectionTask(
                name="link-update-invalid",
                platform="pinterest",
                platforms=["pinterest"],
                collection_mode=CollectionMode.LINK_IMPORT.value,
                input_urls=["https://www.pinterest.com/example_user/"],
                keywords=[],
                product_id=1,
                user_id=1,
                workspace_id=1,
            )
            db_session.add(task)
            await db_session.flush()

            with pytest.raises(ValueError, match=r"第 2 行"):
                await CollectionTaskService.update_task(
                    db_session,
                    task,
                    CollectionTaskUpdate(
                        input_urls=[
                            "https://www.pinterest.com/example_user/",
                            "https://unknown.example/x",
                        ],
                    ),
                )
            await db_session.rollback()

    asyncio.run(_run())


def test_link_import_run_rejects_invalid_urls_before_partial_import(monkeypatch):
    async def fail_execute(*args, **kwargs):
        raise AssertionError("run_collection_task must reject invalid URLs before import execution")

    monkeypatch.setattr(LinkImportService, "_execute_url_import", fail_execute)
    task = CollectionTask(
        name="link-run-invalid",
        platform="pinterest",
        platforms=["pinterest"],
        collection_mode=CollectionMode.LINK_IMPORT.value,
        input_urls=[
            "https://www.pinterest.com/example_user/",
            "https://unknown.example/x",
        ],
        keywords=[],
        product_id=1,
        user_id=1,
        workspace_id=1,
    )

    async def _run() -> None:
        with pytest.raises(ValueError, match=r"第 2 行"):
            await LinkImportService.run_collection_task(None, task)  # type: ignore[arg-type]

    asyncio.run(_run())
