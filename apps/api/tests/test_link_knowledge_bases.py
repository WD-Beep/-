"""Link knowledge base MVP behavior tests."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
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
from app.services.link_script_generator import _fallback_script


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
