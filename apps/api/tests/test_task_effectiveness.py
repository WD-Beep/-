"""任务效果分类回归测试。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from app.db.session import async_session_factory
from app.main import app
from app.models.collection_task import CollectionTask
from app.models.collection_task_candidate import CollectionTaskCandidate
from app.models.enums import CandidateStatus, CollectionMode, CollectionTaskStatus
from app.models.global_influencer_profile import GlobalInfluencerProfile
from app.models.product_influencer import ProductInfluencer
from app.models.product_influencer_source import ProductInfluencerSource
from app.schemas.collection_task import CollectionTaskFilter
from app.services.collection_task import CollectionTaskService
from app.services.task_effectiveness import (
    batch_task_has_valuable_insert,
    classify_task_effectiveness,
    is_collection_task_ineffective,
)


def _task(**kwargs) -> CollectionTask:
    defaults = {
        "name": "test",
        "product_id": 1,
        "collection_mode": CollectionMode.LINK_IMPORT.value,
        "platform": "ltk",
        "platforms": ["ltk"],
        "keywords": [],
        "input_urls": ["https://www.shopltk.com/explore/creator"],
        "status": CollectionTaskStatus.COMPLETED_WITH_RESULTS.value,
        "last_run_at": datetime.now(UTC),
        "inserted_count": 1,
        "result_count": 1,
        "success_count": 1,
        "discovered_count": 1,
        "profile_fetched_count": 1,
    }
    defaults.update(kwargs)
    return CollectionTask(**defaults)


def test_zero_insert_is_no_result():
    task = _task(inserted_count=0, result_count=0, success_count=0, status=CollectionTaskStatus.COMPLETED_NO_RESULTS.value)
    assert classify_task_effectiveness(task, has_valuable_insert=False) == "no_result"
    assert is_collection_task_ineffective(task, has_valuable_insert=False) is True


def test_zero_insert_low_value_seed_marker_is_low_value_result():
    task = _task(
        inserted_count=0,
        result_count=0,
        success_count=0,
        status=CollectionTaskStatus.COMPLETED_NO_RESULTS.value,
        run_checkpoint={"link_seed_enrichment": {"low_value_seed_count": 1}},
    )
    assert classify_task_effectiveness(task, has_valuable_insert=False) == "low_value_result"


def test_empty_ltk_insert_is_low_value_result():
    task = _task(platform="ltk", platforms=["ltk"])
    assert classify_task_effectiveness(task, has_valuable_insert=False) == "low_value_result"
    assert is_collection_task_ineffective(task, has_valuable_insert=False) is True


def test_insert_with_contact_is_effective():
    task = _task(platform="shopmy", platforms=["shopmy"])
    assert classify_task_effectiveness(task, has_valuable_insert=True) == "effective"
    assert is_collection_task_ineffective(task, has_valuable_insert=True) is False


def test_insert_with_followers_is_effective():
    task = _task(platform="pinterest", platforms=["pinterest"])
    assert classify_task_effectiveness(task, has_valuable_insert=True) == "effective"


def test_running_task_is_not_cleanable():
    task = _task(status=CollectionTaskStatus.RUNNING.value)
    assert is_collection_task_ineffective(task, has_valuable_insert=False) is False


@pytest.mark.anyio
async def test_list_tasks_effectiveness_filters_low_value_vs_effective():
    low_value_id: int
    effective_id: int
    no_result_id: int

    async with async_session_factory() as db:
        low_value = _task(name="ltk-low-value", platform="ltk", platforms=["ltk"])
        effective = _task(name="shopmy-effective", platform="shopmy", platforms=["shopmy"])
        no_result = _task(
            name="no-result",
            inserted_count=0,
            result_count=0,
            success_count=0,
            status=CollectionTaskStatus.COMPLETED_NO_RESULTS.value,
        )
        db.add_all([low_value, effective, no_result])
        await db.flush()
        low_value_id = low_value.id
        effective_id = effective.id
        no_result_id = no_result.id
        db.add(
            CollectionTaskCandidate(
                task_id=low_value.id,
                product_id=1,
                username="ltk_creator",
                profile_url="https://www.shopltk.com/explore/ltk_creator",
                platform="ltk",
                status=CandidateStatus.INSERTED.value,
                is_high_value=False,
                has_email=False,
                has_contact=False,
            )
        )
        db.add(
            CollectionTaskCandidate(
                task_id=effective.id,
                product_id=1,
                username="shop_creator",
                profile_url="https://shopmy.us/shop_creator",
                platform="shopmy",
                status=CandidateStatus.INSERTED.value,
                is_high_value=True,
                has_email=True,
                has_contact=True,
                followers_count=5000,
            )
        )
        await db.commit()

    async with async_session_factory() as db:
        effective_page = await CollectionTaskService.list_tasks(
            db, CollectionTaskFilter(product_id=1, effectiveness="effective"), 1, 100
        )
        low_value_page = await CollectionTaskService.list_tasks(
            db, CollectionTaskFilter(product_id=1, effectiveness="low_value_result"), 1, 100
        )
        no_result_page = await CollectionTaskService.list_tasks(
            db, CollectionTaskFilter(product_id=1, effectiveness="no_result"), 1, 100
        )

    effective_ids = {item.id for item in effective_page.items}
    low_value_ids = {item.id for item in low_value_page.items}
    no_result_ids = {item.id for item in no_result_page.items}

    assert effective_id in effective_ids
    assert low_value_id not in effective_ids
    assert low_value_id in low_value_ids
    assert no_result_id in no_result_ids
    assert effective_id not in low_value_ids

    async with async_session_factory() as db:
        for task_id in (low_value_id, effective_id, no_result_id):
            row = await db.get(CollectionTask, task_id)
            if row:
                await db.delete(row)
        await db.commit()


@pytest.mark.anyio
async def test_collection_tasks_api_effectiveness_filters():
    effective_id: int
    low_value_id: int

    async with async_session_factory() as db:
        effective = _task(name="api-effective", platform="tiktok", platforms=["tiktok"])
        low_value = _task(name="api-low-value", platform="ltk", platforms=["ltk"])
        db.add_all([effective, low_value])
        await db.flush()
        effective_id = effective.id
        low_value_id = low_value.id
        db.add(
            CollectionTaskCandidate(
                task_id=effective.id,
                product_id=1,
                username="creator",
                profile_url="https://www.tiktok.com/@creator",
                platform="tiktok",
                status=CandidateStatus.INSERTED.value,
                followers_count=1000,
                is_high_value=True,
            )
        )
        db.add(
            CollectionTaskCandidate(
                task_id=low_value.id,
                product_id=1,
                username="ltk_creator",
                profile_url="https://www.shopltk.com/explore/ltk_creator",
                platform="ltk",
                status=CandidateStatus.INSERTED.value,
                is_high_value=False,
            )
        )
        await db.commit()

    transport = ASGITransport(app=app)
    headers = {"X-User-Id": "1", "X-Product-Id": "1"}
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            effective_resp = await client.get(
                "/api/collection-tasks",
                headers=headers,
                params={"effectiveness": "effective", "page_size": 100},
            )
            low_value_resp = await client.get(
                "/api/collection-tasks",
                headers=headers,
                params={"effectiveness": "low_value_result", "page_size": 100},
            )
            assert effective_resp.status_code == 200, effective_resp.text
            assert low_value_resp.status_code == 200, low_value_resp.text

            effective_ids = {item["id"] for item in effective_resp.json()["items"]}
            low_value_ids = {item["id"] for item in low_value_resp.json()["items"]}

            assert effective_id in effective_ids
            assert low_value_id not in effective_ids
            assert low_value_id in low_value_ids
            assert effective_id not in low_value_ids
    finally:
        async with async_session_factory() as db:
            for task_id in (effective_id, low_value_id):
                row = await db.get(CollectionTask, task_id)
                if row:
                    await db.delete(row)
            await db.commit()


URL_ONLY_SHELL_CASES = [
    (
        "ltk",
        "ltk_creator",
        "https://www.shopltk.com/explore/ltk_creator",
        "https://www.shopltk.com/explore/ltk_creator",
    ),
    (
        "shopmy",
        "shop_creator",
        "https://shopmy.us/shop_creator",
        "https://shopmy.us/shop_creator",
    ),
    (
        "pinterest",
        "pin_creator",
        "https://www.pinterest.com/pin_creator/",
        "https://www.pinterest.com/pin_creator/",
    ),
]


async def _create_shell_profile_task(
    db,
    *,
    platform: str,
    username: str,
    profile_url: str,
    input_url: str,
    name: str,
    **profile_fields,
) -> tuple[int, int]:
    task = _task(
        name=name,
        platform=platform,
        platforms=[platform],
        input_urls=[input_url],
    )
    db.add(task)
    await db.flush()
    global_row = GlobalInfluencerProfile(
        platform=platform,
        username=username,
        normalized_username=username.lower(),
        profile_url=profile_url,
        normalized_profile_url=profile_url.lower(),
        display_name=username.replace("_", " "),
        **profile_fields,
    )
    db.add(global_row)
    await db.flush()
    product_row = ProductInfluencer(product_id=1, global_influencer_id=global_row.id)
    db.add(product_row)
    await db.flush()
    db.add(
        ProductInfluencerSource(
            product_influencer_id=product_row.id,
            task_id=task.id,
            source_input_url=input_url,
            source_platform=platform,
            task_name=task.name,
            source_key=input_url.lower(),
            collected_at=datetime.now(UTC),
        )
    )
    await db.flush()
    return task.id, global_row.id


@pytest.mark.parametrize("platform,username,profile_url,input_url", URL_ONLY_SHELL_CASES)
@pytest.mark.anyio
async def test_url_only_shell_profile_via_source_is_low_value(platform, username, profile_url, input_url):
    task_id: int

    async with async_session_factory() as db:
        task_id, _ = await _create_shell_profile_task(
            db,
            platform=platform,
            username=username,
            profile_url=profile_url,
            input_url=input_url,
            name=f"{platform}-shell",
        )
        valuable = await batch_task_has_valuable_insert(db, [task_id])
        task = await db.get(CollectionTask, task_id)
        assert valuable[task_id] is False
        assert classify_task_effectiveness(task, has_valuable_insert=False) == "low_value_result"
        await db.rollback()


@pytest.mark.parametrize("platform,username,profile_url,input_url", URL_ONLY_SHELL_CASES)
@pytest.mark.anyio
async def test_url_only_shell_profile_api_filters(platform, username, profile_url, input_url):
    task_id: int

    async with async_session_factory() as db:
        task_id, _ = await _create_shell_profile_task(
            db,
            platform=platform,
            username=username,
            profile_url=profile_url,
            input_url=input_url,
            name=f"{platform}-shell-api",
        )
        await db.commit()

    transport = ASGITransport(app=app)
    headers = {"X-User-Id": "1", "X-Product-Id": "1"}
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            effective_resp = await client.get(
                "/api/collection-tasks",
                headers=headers,
                params={"effectiveness": "effective", "page_size": 200},
            )
            low_value_resp = await client.get(
                "/api/collection-tasks",
                headers=headers,
                params={"effectiveness": "low_value_result", "page_size": 200},
            )
            ineffective_resp = await client.get(
                "/api/collection-tasks",
                headers=headers,
                params={"effectiveness": "ineffective", "page_size": 200},
            )
            assert effective_resp.status_code == 200
            assert low_value_resp.status_code == 200
            assert ineffective_resp.status_code == 200

            effective_ids = {item["id"] for item in effective_resp.json()["items"]}
            low_value_ids = {item["id"] for item in low_value_resp.json()["items"]}
            ineffective_ids = {item["id"] for item in ineffective_resp.json()["items"]}

            assert task_id not in effective_ids
            assert task_id in low_value_ids
            assert task_id in ineffective_ids
    finally:
        async with async_session_factory() as db:
            row = await db.get(CollectionTask, task_id)
            if row:
                await db.delete(row)
            await db.commit()


@pytest.mark.anyio
async def test_url_only_profile_with_bio_via_source_is_effective():
    task_id: int

    async with async_session_factory() as db:
        task_id, _ = await _create_shell_profile_task(
            db,
            platform="ltk",
            username="bio_creator",
            profile_url="https://www.shopltk.com/explore/bio_creator",
            input_url="https://www.shopltk.com/explore/bio_creator",
            name="ltk-bio-effective",
            bio="Fashion and travel creator",
        )
        valuable = await batch_task_has_valuable_insert(db, [task_id])
        task = await db.get(CollectionTask, task_id)
        assert valuable[task_id] is True
        assert classify_task_effectiveness(task, has_valuable_insert=True) == "effective"
        await db.rollback()


@pytest.mark.anyio
async def test_profile_with_content_topics_via_source_is_effective():
    task_id: int

    async with async_session_factory() as db:
        task_id, _ = await _create_shell_profile_task(
            db,
            platform="shopmy",
            username="topic_creator",
            profile_url="https://shopmy.us/topic_creator",
            input_url="https://shopmy.us/topic_creator",
            name="shopmy-topics-effective",
            content_topics=["fashion", "travel"],
        )
        valuable = await batch_task_has_valuable_insert(db, [task_id])
        task = await db.get(CollectionTask, task_id)
        assert valuable[task_id] is True
        assert classify_task_effectiveness(task, has_valuable_insert=True) == "effective"
        await db.rollback()


@pytest.mark.anyio
async def test_self_profile_website_via_source_is_low_value():
    profile_url = "https://www.pinterest.com/self_web/"
    task_id: int

    async with async_session_factory() as db:
        task_id, _ = await _create_shell_profile_task(
            db,
            platform="pinterest",
            username="self_web",
            profile_url=profile_url,
            input_url=profile_url,
            name="pinterest-self-website",
            website=profile_url,
        )
        valuable = await batch_task_has_valuable_insert(db, [task_id])
        task = await db.get(CollectionTask, task_id)
        assert valuable[task_id] is False
        assert classify_task_effectiveness(task, has_valuable_insert=False) == "low_value_result"
        await db.rollback()


@pytest.mark.anyio
async def test_storefront_self_website_via_source_is_low_value():
    profile_url = "https://shopmy.us/storefront_self"
    task_id: int

    async with async_session_factory() as db:
        task_id, _ = await _create_shell_profile_task(
            db,
            platform="shopmy",
            username="storefront_self",
            profile_url=profile_url,
            input_url=profile_url,
            name="shopmy-storefront-self",
            website=profile_url,
        )
        valuable = await batch_task_has_valuable_insert(db, [task_id])
        task = await db.get(CollectionTask, task_id)
        assert valuable[task_id] is False
        assert classify_task_effectiveness(task, has_valuable_insert=False) == "low_value_result"
        await db.rollback()


@pytest.mark.anyio
async def test_python_and_api_effectiveness_filters_agree_for_profile_source_tasks():
    cases = [
        {
            "name": "topics-effective",
            "platform": "ltk",
            "username": "topics_api",
            "profile_url": "https://www.shopltk.com/explore/topics_api",
            "input_url": "https://www.shopltk.com/explore/topics_api",
            "profile_fields": {"content_topics": ["beauty"]},
            "expect_valuable": True,
        },
        {
            "name": "self-website-low",
            "platform": "pinterest",
            "username": "self_api",
            "profile_url": "https://www.pinterest.com/self_api/",
            "input_url": "https://www.pinterest.com/self_api/",
            "profile_fields": {"website": "https://www.pinterest.com/self_api/"},
            "expect_valuable": False,
        },
        {
            "name": "shell-storefront-low",
            "platform": "shopmy",
            "username": "shell_api",
            "profile_url": "https://shopmy.us/shell_api",
            "input_url": "https://shopmy.us/shell_api",
            "profile_fields": {
                "other_social_links": [
                    {"type": "shopmy", "label": "ShopMy", "url": "https://shopmy.us/shell_api"}
                ]
            },
            "expect_valuable": False,
        },
    ]

    task_ids: dict[str, int] = {}

    async with async_session_factory() as db:
        for case in cases:
            task_id, _ = await _create_shell_profile_task(
                db,
                platform=case["platform"],
                username=case["username"],
                profile_url=case["profile_url"],
                input_url=case["input_url"],
                name=case["name"],
                **case["profile_fields"],
            )
            task_ids[case["name"]] = task_id
        await db.commit()

    async with async_session_factory() as db:
        valuable = await batch_task_has_valuable_insert(db, list(task_ids.values()))
        effective_page = await CollectionTaskService.list_tasks(
            db, CollectionTaskFilter(product_id=1, effectiveness="effective"), 1, 200
        )
        low_value_page = await CollectionTaskService.list_tasks(
            db, CollectionTaskFilter(product_id=1, effectiveness="low_value_result"), 1, 200
        )
        effective_ids = {item.id for item in effective_page.items}
        low_value_ids = {item.id for item in low_value_page.items}

        for case in cases:
            task_id = task_ids[case["name"]]
            expect = case["expect_valuable"]
            assert valuable[task_id] is expect
            assert (task_id in effective_ids) is expect
            assert (task_id in low_value_ids) is (not expect)

    async with async_session_factory() as db:
        for task_id in task_ids.values():
            row = await db.get(CollectionTask, task_id)
            if row:
                await db.delete(row)
        await db.commit()
