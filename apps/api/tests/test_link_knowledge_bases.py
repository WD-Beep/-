"""Link knowledge base MVP behavior tests."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import delete, select

from app.collectors.base import CollectedInfluencer
from app.db.session import async_session_factory
from app.models.global_influencer_profile import GlobalInfluencerProfile
from app.models.product_influencer import ProductInfluencer
from app.services.influencer_persistence import (
    create_global_profile_from_collected,
    create_product_influencer_from_collected,
)
from app.services import link_script_generator
from app.services.link_script_generator import _fallback_script
from app.schemas.link_knowledge_base import LinkKnowledgeBaseUpdate, LinkScriptGenerateRequest


def _suffix() -> str:
    return uuid.uuid4().hex[:10]


def test_fallback_link_script_is_complete_enough_to_send():
    snapshot = {
        "link_knowledge": {
            "name": "FoldAway Travel Laundry Bag",
            "extracted_knowledge": {
                "brand_name": "FoldAway",
                "product_name": "compressible travel laundry bag",
                "selling_points": ["saves half the space", "keeps luggage neat"],
                "collaboration_angles": ["packing tips", "travel routines"],
            },
        },
        "influencer": {
            "display_name": "Chellene",
            "username": "chellene",
            "category": "beauty and travel",
        },
    }

    script = _fallback_script(snapshot)

    email = script["email_first_touch"]
    assert len(email.split()) >= 75
    assert "Why I thought of you" in email
    assert "Collaboration idea" in email
    assert "Would you be open" in email
    assert "Best," in email


def test_manual_selling_points_are_prioritized_and_deduplicated():
    merge = getattr(link_script_generator, "merge_selling_points", None)
    assert callable(merge), "link script generator should expose merge_selling_points"

    points = merge(
        ["Manual benefit", "Shared benefit", "manual benefit"],
        ["Shared benefit", "Extracted benefit"],
    )

    assert points == ["Manual benefit", "Shared benefit", "Extracted benefit"]


def test_manual_selling_points_schema_trims_and_deduplicates():
    payload = LinkKnowledgeBaseUpdate(
        manual_selling_points=["  Manual benefit  ", "", "manual benefit", "Second benefit"]
    )

    assert payload.manual_selling_points == ["Manual benefit", "Second benefit"]


def test_fallback_link_script_prefers_manual_selling_points():
    snapshot = {
        "link_knowledge": {
            "name": "Travel product",
            "manual_selling_points": ["manual compact design"],
            "effective_selling_points": ["manual compact design", "automatic durable material"],
            "extracted_knowledge": {
                "brand_name": "TravelPro",
                "product_name": "Packing Cube",
                "selling_points": ["automatic durable material"],
                "collaboration_angles": ["packing routine"],
            },
        },
        "influencer": {"display_name": "Mia", "category": "travel"},
    }

    script = _fallback_script(snapshot)

    assert "manual compact design" in script["email_first_touch"]


def test_link_script_enforces_required_english_affiliate_offer_and_product_link():
    enforce = getattr(link_script_generator, "_enforce_link_script_business_requirements", None)
    assert callable(enforce)
    snapshot = {
        "link_knowledge": {
            "url": "https://example.com/products/packing-cube",
            "name": "旅行收纳包",
            "extracted_knowledge": {
                "brand_name": "TravelPro",
                "product_name": "Packing Cube",
            },
        },
        "influencer": {
            "display_name": "Mia",
            "username": "mia",
            "platform": "instagram",
            "category": "travel",
            "profile_url": "https://instagram.com/mia",
        },
    }
    generated = {
        "match_reason": "适合旅行博主",
        "personalization_points": ["旅行收纳"],
        "email_subjects": ["旅行收纳合作"],
        "email_first_touch": "你好 Mia，我们想合作。",
        "instagram_dm": "你好，想合作吗？",
        "tiktok_dm": "你好，想合作吗？",
        "youtube_pitch": "你好 Mia，我们想合作。",
        "follow_up_1": "你好，跟进一下。",
        "follow_up_2": "你好，再跟进一下。",
        "negotiation_reply": "可以沟通报价。",
        "comment_script": "内容不错。",
        "notes": "internal note",
    }

    script = enforce(generated, snapshot)
    combined = "\n".join(
        str(value)
        for key, value in script.items()
        if key != "notes"
        for value in (value if isinstance(value, list) else [value])
    )

    assert "TravelPro" in combined
    assert "Amazon" in combined
    assert "Affiliate" in combined
    assert "10%-30%" in combined
    assert "https://example.com/products/packing-cube" in combined
    assert not any("\u4e00" <= char <= "\u9fff" for char in combined)


def test_link_script_validation_requires_long_copy_dm_and_supplied_selling_point():
    validate = getattr(link_script_generator, "_link_script_validation_errors", None)
    assert callable(validate)

    errors = validate(
        {
            "email_first_touch": "Short email without the approved benefit.",
            "youtube_pitch": "Short pitch.",
            "instagram_dm": "Too short.",
            "tiktok_dm": "Too short.",
        },
        {
            "language": "en",
            "message_template": {"generation_rules": {"min_length": 40, "max_length": 120}},
            "link_knowledge": {
                "manual_selling_points": ["manual compact design"],
                "effective_selling_points": ["manual compact design", "automatic durable material"],
            },
        },
    )

    assert any("email_first_touch length" in item for item in errors)
    assert any("youtube_pitch length" in item for item in errors)
    assert any("instagram_dm length" in item for item in errors)
    assert any("tiktok_dm length" in item for item in errors)
    assert "missing supplied selling point" in errors


def test_link_script_request_keeps_message_template_id():
    payload = LinkScriptGenerateRequest(influencer_ids=[1], message_template_id=9)

    assert payload.message_template_id == 9


def test_link_generator_passes_template_and_effective_selling_points_to_ai():
    async def _run() -> None:
        db = AsyncMock()
        db.scalars = AsyncMock(return_value=SimpleNamespace(all=lambda: []))
        base = SimpleNamespace(
            id=3,
            name="Travel product",
            url="https://example.com/product",
            domain="example.com",
            summary="Travel organizer",
            extracted_knowledge={
                "brand_name": "TravelPro",
                "product_name": "Packing Cube",
                "selling_points": ["automatic durable material"],
            },
            manual_selling_points=["manual compact design"],
        )
        product_row = SimpleNamespace(
            id=7,
            product_fit="high",
            score=90,
            ai_summary="travel creator",
            ai_collaboration_suggestion="packing routine",
            tags=[],
        )
        global_row = SimpleNamespace(
            platform="instagram",
            username="mia",
            display_name="Mia",
            profile_url="https://instagram.com/mia",
            bio="travel packing creator",
            category="travel",
            niche="packing",
            followers_count=42000,
            engagement_rate=3.2,
            country="US",
            language="en",
            recent_post_titles=[],
            content_topics=[],
        )
        ai_payload = {
            "match_reason": "fit",
            "personalization_points": ["packing"],
            "email_subjects": ["TravelPro x Mia"],
            "email_first_touch": "Hi Mia, manual compact design. Would you be open to details?",
        }
        valid_payload = {
            **ai_payload,
            "email_first_touch": (
                "Hi Mia, your practical packing videos make complex travel routines easy to follow. "
                "TravelPro's manual compact design gives your audience a clear benefit they can understand quickly, "
                "while the durable material supports repeated trips. We could build a lightweight packing-routine story "
                "that fits your normal content style. Would you be open to reviewing the details? Best, Brand Team"
            ),
        }

        with patch("app.services.link_script_generator.settings") as mock_settings:
            mock_settings.is_openai_configured = True
            with patch(
                "app.services.link_script_generator.chat_completion_json",
                new_callable=AsyncMock,
                side_effect=[ai_payload, valid_payload],
            ) as ai_mock:
                await link_script_generator.generate_scripts_for_influencer(
                    db,
                    base,
                    product_row,
                    global_row,
                    {
                        "tone": "natural",
                        "message_template": {
                            "id": 9,
                            "title": "Detailed framework",
                            "content": "Greeting, product value, CTA, signature",
                            "generation_rules": {"min_length": 50, "required_content": ["Would you be open"]},
                        },
                    },
                )

        prompt = ai_mock.await_args.kwargs["user_prompt"]
        assert "manual compact design" in prompt
        assert "Detailed framework" in prompt
        assert "Greeting, product value, CTA, signature" in prompt
        assert ai_mock.await_count == 2

    asyncio.run(_run())


async def _create_product_influencer(db, suffix: str) -> ProductInfluencer:
    run_at = datetime.now(UTC)
    username = f"link_kb_{suffix}"
    item = CollectedInfluencer(
        platform="instagram",
        username=username,
        profile_url=f"https://instagram.com/{username}",
        platform_unique_id=f"ig_link_kb_{suffix}",
        followers_count=25000,
        engagement_rate=3.4,
        bio="clean beauty and morning routine creator",
        category="beauty",
        final_email=f"{username}@example.com",
    )
    global_profile = create_global_profile_from_collected(item, run_at=run_at)
    db.add(global_profile)
    await db.flush()
    record = create_product_influencer_from_collected(
        product_id=1,
        global_profile=global_profile,
        data=item,
        task=None,
        run_at=run_at,
    )
    db.add(record)
    await db.flush()
    return record


def test_create_link_knowledge_base_parses_and_saves_chunks():
    async def _run() -> None:
        from httpx import ASGITransport, AsyncClient

        from app.main import app
        from app.models.link_knowledge_base import LinkKnowledgeBase, LinkKnowledgeChunk

        suffix = _suffix()
        fetch_payload = {
            "url": f"https://example.com/products/serum-{suffix}",
            "domain": "example.com",
            "source_type": "product_page",
            "raw_html": "<html><title>Glow Serum</title></html>",
            "clean_text": "GlowSkin Vitamin C Serum. Vegan brightening serum for sensitive skin.",
            "title": "Glow Serum",
        }
        extracted = {
            "brand_name": "GlowSkin",
            "product_name": "Vitamin C Serum",
            "category": "skincare",
            "price": "$29",
            "target_audience": "skincare beginners",
            "brand_summary": "Clean skincare brand focused on gentle routines.",
            "product_summary": "A daily brightening serum.",
            "selling_points": ["vegan", "sensitive skin"],
            "brand_tone": "clean and friendly",
            "collaboration_angles": ["morning routine"],
            "faq": [{"question": "Is it gentle?", "answer": "The page says it is gentle."}],
            "do_not_claim": ["Do not claim medical treatment effects"],
            "keywords": ["vitamin c", "serum"],
        }

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            with patch(
                "app.api.routes.link_knowledge_bases.fetch_url_content",
                new_callable=AsyncMock,
                return_value=fetch_payload,
            ), patch(
                "app.api.routes.link_knowledge_bases.extract_link_knowledge",
                new_callable=AsyncMock,
                return_value=extracted,
            ):
                response = await client.post(
                    "/api/link-knowledge-bases",
                    headers={"X-User-Id": "1", "X-Product-Id": "1"},
                    json={
                        "name": f"Glow link {suffix}",
                        "url": fetch_payload["url"],
                        "parse_immediately": True,
                    },
                )

        assert response.status_code == 201, response.text
        data = response.json()
        assert data["status"] == "parsed"
        assert data["domain"] == "example.com"
        assert data["extracted_knowledge"]["brand_name"] == "GlowSkin"
        assert len(data["chunks"]) >= 4

        async with async_session_factory() as db:
            row = await db.get(LinkKnowledgeBase, data["id"])
            assert row is not None
            chunks = (
                await db.execute(
                    select(LinkKnowledgeChunk).where(LinkKnowledgeChunk.link_knowledge_base_id == row.id)
                )
            ).scalars().all()
            assert {chunk.chunk_type for chunk in chunks} >= {
                "brand_intro",
                "product_features",
                "selling_points",
                "collaboration_angle",
            }
            await db.execute(delete(LinkKnowledgeChunk).where(LinkKnowledgeChunk.link_knowledge_base_id == row.id))
            await db.execute(delete(LinkKnowledgeBase).where(LinkKnowledgeBase.id == row.id))
            await db.commit()

    asyncio.run(_run())


def test_generate_scripts_creates_job_results_and_regenerate_keeps_edited_content():
    async def _run() -> None:
        from httpx import ASGITransport, AsyncClient

        from app.main import app
        from app.models.link_knowledge_base import LinkKnowledgeBase, LinkScriptJob, LinkScriptResult

        suffix = _suffix()
        async with async_session_factory() as db:
            influencer = await _create_product_influencer(db, suffix)
            kb = LinkKnowledgeBase(
                workspace_id=1,
                user_id=1,
                product_id=1,
                name=f"Glow script {suffix}",
                url=f"https://example.com/glow-{suffix}",
                domain="example.com",
                source_type="product_page",
                status="parsed",
                fetch_status="success",
                parse_status="success",
                clean_text="GlowSkin Vitamin C Serum",
                extracted_knowledge={"brand_name": "GlowSkin", "product_name": "Vitamin C Serum"},
                summary="Clean skincare brand.",
                tags=["skincare"],
            )
            db.add(kb)
            await db.flush()
            await db.commit()
            kb_id = kb.id
            influencer_id = influencer.id
            global_id = influencer.global_influencer_id

        generated = {
            "match_reason": "Beauty creator fits skincare routine content.",
            "personalization_points": ["morning routine"],
            "email_subjects": ["GlowSkin collab idea"],
            "email_first_touch": "Hi, loved your skincare content.",
            "instagram_dm": "Loved your routines, open to a GlowSkin collab?",
            "tiktok_dm": "",
            "youtube_pitch": "",
            "follow_up_1": "Just checking in.",
            "follow_up_2": "Happy to share details.",
            "negotiation_reply": "",
            "comment_script": "",
            "notes": "",
        }
        regenerated = {**generated, "match_reason": "Regenerated match reason."}
        snapshot = {
            "link_knowledge": {"id": kb_id, "name": f"Glow script {suffix}"},
            "influencer": {"id": influencer_id, "username": f"link_kb_{suffix}"},
            "config": {"tone": "friendly"},
        }
        regenerated_snapshot = {
            **snapshot,
            "config": {"tone": "professional"},
        }

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            with patch(
                "app.services.link_script_generator.generate_scripts_for_influencer",
                new_callable=AsyncMock,
                return_value=(generated, snapshot),
            ):
                response = await client.post(
                    f"/api/link-knowledge-bases/{kb_id}/generate-scripts",
                    headers={"X-User-Id": "1", "X-Product-Id": "1"},
                    json={"influencer_ids": [influencer_id], "tone": "friendly"},
                )
            assert response.status_code == 201, response.text
            job = response.json()
            assert job["status"] == "completed"
            assert job["success_count"] == 1

            results = await client.get(
                f"/api/link-script-jobs/{job['id']}/results",
                headers={"X-User-Id": "1", "X-Product-Id": "1"},
            )
            assert results.status_code == 200
            result = results.json()["items"][0]
            assert result["generated_content"]["match_reason"] == generated["match_reason"]
            assert result["input_snapshot"] == snapshot

            edited = {"email_first_touch": "Manual edit"}
            patch_resp = await client.patch(
                f"/api/link-script-results/{result['id']}",
                headers={"X-User-Id": "1", "X-Product-Id": "1"},
                json={"edited_content": edited},
            )
            assert patch_resp.status_code == 200

            with patch(
                "app.services.link_script_generator.generate_scripts_for_influencer",
                new_callable=AsyncMock,
                return_value=(regenerated, regenerated_snapshot),
            ):
                regen_resp = await client.post(
                    f"/api/link-script-results/{result['id']}/regenerate",
                    headers={"X-User-Id": "1", "X-Product-Id": "1"},
                    json={"tone": "professional"},
                )
            assert regen_resp.status_code == 200
            regen = regen_resp.json()
            assert regen["generated_content"]["match_reason"] == "Regenerated match reason."
            assert regen["input_snapshot"] == regenerated_snapshot
            assert regen["edited_content"] == edited

        async with async_session_factory() as db:
            await db.execute(delete(LinkScriptResult).where(LinkScriptResult.link_knowledge_base_id == kb_id))
            await db.execute(delete(LinkScriptJob).where(LinkScriptJob.link_knowledge_base_id == kb_id))
            await db.execute(delete(LinkKnowledgeBase).where(LinkKnowledgeBase.id == kb_id))
            await db.execute(delete(ProductInfluencer).where(ProductInfluencer.id == influencer_id))
            await db.execute(delete(GlobalInfluencerProfile).where(GlobalInfluencerProfile.id == global_id))
            await db.commit()

    asyncio.run(_run())
