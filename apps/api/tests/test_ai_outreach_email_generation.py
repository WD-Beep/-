"""鎵归噺 AI 涓€у寲閭欢鐢熸垚娴嬭瘯銆?""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from sqlalchemy import delete, select

from app.collectors.base import CollectedInfluencer
from app.db.session import async_session_factory
from app.models.email_log import EmailLog
from app.models.global_influencer_profile import GlobalInfluencerProfile
from app.models.knowledge import KnowledgeBase, KnowledgeChunk, KnowledgeDocument
from app.models.link_knowledge_base import LinkKnowledgeBase
from app.models.message_template import MessageTemplate
from app.models.product_influencer import ProductInfluencer
from app.models.tenant import Product
from app.schemas.outreach_email import OutreachBatchPreviewRequest, OutreachEmailGenerationResult
from app.services.ai.openai_client import OPENAI_NOT_CONFIGURED_MSG
from app.services.influencer_persistence import (
    create_global_profile_from_collected,
    create_product_influencer_from_collected,
)
from app.services.knowledge.knowledge_service import KnowledgeService
from app.services.outreach_email_service import OutreachEmailService
from app.services.speech_recommendation_service import SpeechRecommendationService
from app.deps.tenant import TenantContext


def _suffix() -> str:
    return uuid.uuid4().hex[:10]


async def _create_influencer(
    db,
    *,
    suffix: str,
    email: str | None,
    username: str | None = None,
    product_id: int = 1,
) -> ProductInfluencer:
    run_at = datetime.now(UTC)
    uname = username or f"outreach_gen_{suffix}"
    item = CollectedInfluencer(
        platform="instagram",
        username=uname,
        profile_url=f"https://instagram.com/{uname}",
        platform_unique_id=f"ig_outreach_{suffix}",
        followers_count=42000 + len(suffix),
        engagement_rate=2.8,
        bio="travel lifestyle creator",
        category="travel",
        final_email=email,
    )
    global_profile = create_global_profile_from_collected(item, run_at=run_at)
    db.add(global_profile)
    await db.flush()
    record = create_product_influencer_from_collected(
        product_id=product_id,
        global_profile=global_profile,
        data=item,
        task=None,
        run_at=run_at,
    )
    db.add(record)
    await db.flush()
    return record


async def _seed_knowledge(db) -> None:
    ctx = TenantContext(user_id=1, product_id=1, workspace_id=1, is_admin=True)
    base = await KnowledgeService.get_or_create_default_base(db, ctx=ctx, product_id=1)
    doc = KnowledgeDocument(
        knowledge_base_id=base.id,
        workspace_id=1,
        product_id=1,
        file_name="brand-outreach.pdf",
        file_type="pdf",
        status="ready",
    )
    db.add(doc)
    await db.flush()
    db.add(
        KnowledgeChunk(
            document_id=doc.id,
            knowledge_base_id=base.id,
            workspace_id=1,
            product_id=1,
            chunk_index=0,
            title="鍝佺墝瀹氫綅",
            content="ScandiHome 涓撴敞鍖楁绠€绾﹀灞咃紝寮鸿皟鑷劧鏉愯川銆?,
            chunk_metadata={"page": 1},
        )
    )


def test_generate_outreach_email_openai_not_configured_fallback():
    async def _run() -> None:
        suffix = _suffix()
        async with async_session_factory() as db:
            record = await _create_influencer(
                db,
                suffix=suffix,
                email=f"creator_{suffix}@example.com",
            )
            global_row = await db.get(GlobalInfluencerProfile, record.global_influencer_id)
            assert global_row is not None

            with patch("app.services.speech_recommendation_service.settings") as mock_settings:
                mock_settings.is_openai_configured = False
                mock_settings.active_ai_provider = "none"

                result = await SpeechRecommendationService.generate_outreach_email(
                    db,
                    product_id=1,
                    global_row=global_row,
                    product_row=record,
                )

            assert result.error_message == OPENAI_NOT_CONFIGURED_MSG
            assert any("鏈厤缃?AI" in note for note in result.risk_notes)
            assert result.subject
            assert result.body
            assert "鏈厤缃?AI锛屾湭鐢熸垚涓€у寲璇濇湳" in " ".join(result.risk_notes)

            await db.execute(delete(ProductInfluencer).where(ProductInfluencer.id == record.id))
            await db.execute(delete(GlobalInfluencerProfile).where(GlobalInfluencerProfile.id == global_row.id))
            await db.commit()

    asyncio.run(_run())


def test_generate_outreach_email_uses_knowledge_and_script():
    async def _run() -> None:
        suffix = _suffix()
        async with async_session_factory() as db:
            await _seed_knowledge(db)
            script = MessageTemplate(
                user_id=1,
                workspace_id=1,
                product_id=1,
                title=f"棣栨閭€绾?{suffix}",
                scenario="first_contact",
                content="Hi {name}, love your {platform} content about {category}.",
                platform="instagram",
                language="en",
                tags=["intro"],
            )
            db.add(script)
            record = await _create_influencer(
                db,
                suffix=suffix,
                email=f"knowledge_{suffix}@example.com",
            )
            global_row = await db.get(GlobalInfluencerProfile, record.global_influencer_id)
            assert global_row is not None
            await db.commit()

            ai_payload = {
                "subject": f"Collab with {global_row.username}",
                "body": f"Hi {global_row.display_name or global_row.username}, ScandiHome Nordic home brand.",
                "recommended_script_id": str(script.id),
                "recommended_script_title": script.title,
                "reason": "Travel creator fits home decor audience",
                "matched_knowledge": [
                    {
                        "document": "brand-outreach.pdf",
                        "section": "1",
                        "summary": "Nordic home brand positioning",
                    }
                ],
                "tone": "professional",
                "risk_notes": [],
            }

            with patch(
                "app.services.speech_recommendation_service.chat_completion_json",
                new_callable=AsyncMock,
                return_value=ai_payload,
            ):
                with patch("app.services.speech_recommendation_service.settings") as mock_settings:
                    mock_settings.is_openai_configured = True
                    result = await SpeechRecommendationService.generate_outreach_email(
                        db,
                        product_id=1,
                        global_row=global_row,
                        product_row=record,
                    )

            assert result.recommended_script_id == str(script.id)
            assert result.recommended_script_title == script.title
            assert len(result.matched_knowledge) >= 1
            assert result.matched_knowledge[0].document == "brand-outreach.pdf"
            assert result.provider == "openai"
            assert result.configured is True

            await db.execute(delete(MessageTemplate).where(MessageTemplate.id == script.id))
            await db.execute(delete(ProductInfluencer).where(ProductInfluencer.id == record.id))
            await db.execute(delete(GlobalInfluencerProfile).where(GlobalInfluencerProfile.id == global_row.id))
            await db.commit()

    asyncio.run(_run())


def test_generate_outreach_email_retries_when_template_rules_are_not_met():
    async def _run() -> None:
        suffix = _suffix()
        async with async_session_factory() as db:
            product = Product(
                workspace_id=1,
                name=f"AI rules product {suffix}",
                slug=f"ai-rules-{suffix}",
                is_default=False,
            )
            db.add(product)
            await db.flush()
            script = MessageTemplate(
                user_id=1,
                workspace_id=1,
                product_id=product.id,
                title=f"Long natural outreach-{suffix}",
                scenario="first_contact",
                content="Greeting, creator fit, product value, collaboration idea, CTA and signature.",
                platform="instagram",
                language="en",
                tags=["outreach"],
                generation_rules={
                    "tone": "natural",
                    "language": "en",
                    "min_length": 40,
                    "max_length": 120,
                    "required_content": ["Would you be open"],
                    "forbidden_content": ["guaranteed results"],
                    "cta": "Would you be open to reviewing the details?",
                },
            )
            db.add(script)
            record = await _create_influencer(
                db,
                suffix=suffix,
                email=f"rules_{suffix}@example.com",
                product_id=product.id,
            )
            global_row = await db.get(GlobalInfluencerProfile, record.global_influencer_id)
            assert global_row is not None
            await db.commit()

            short_payload = {
                "subject": "Quick collab",
                "body": "Hi, interested?",
                "recommended_script_id": str(script.id),
                "recommended_script_title": script.title,
                "reason": "fit",
                "matched_knowledge": [],
                "tone": "natural",
                "risk_notes": [],
            }
            valid_body = (
                "Hi creator, your practical travel content feels aligned with our product and audience. "
                "The compact design can support a useful packing-routine story without changing your normal style. "
                "We can share product details and a lightweight collaboration outline for your review. "
                "Would you be open to reviewing the details? Best, Brand Team"
            )
            valid_payload = {**short_payload, "body": valid_body}

            with patch(
                "app.services.speech_recommendation_service.chat_completion_json",
                new_callable=AsyncMock,
                side_effect=[short_payload, valid_payload],
            ) as ai_mock:
                with patch("app.services.speech_recommendation_service.settings") as mock_settings:
                    mock_settings.is_openai_configured = True
                    mock_settings.active_ai_provider = "deepseek"
                    result = await SpeechRecommendationService.generate_outreach_email(
                        db,
                        product_id=product.id,
                        global_row=global_row,
                        product_row=record,
                        selected_script_ids=[script.id],
                    )

            assert ai_mock.await_count == 2
            first_prompt = ai_mock.await_args_list[0].kwargs["user_prompt"]
            second_prompt = ai_mock.await_args_list[1].kwargs["user_prompt"]
            assert "Long natural outreach" in first_prompt
            assert "Would you be open" in first_prompt
            assert "鏍￠獙澶辫触" in second_prompt
            assert result.body == valid_body
            assert result.error_message is None

            await db.execute(delete(MessageTemplate).where(MessageTemplate.id == script.id))
            await db.execute(delete(ProductInfluencer).where(ProductInfluencer.id == record.id))
            await db.execute(delete(GlobalInfluencerProfile).where(GlobalInfluencerProfile.id == global_row.id))
            await db.execute(delete(Product).where(Product.id == product.id))
            await db.commit()

    asyncio.run(_run())


def test_generate_outreach_email_includes_template_note_as_internal_guidance_only():
    async def _run() -> None:
        suffix = _suffix()
        async with async_session_factory() as db:
            product = Product(
                workspace_id=1,
                name=f"AI note product {suffix}",
                slug=f"ai-note-{suffix}",
                is_default=False,
            )
            db.add(product)
            await db.flush()
            internal_note = "INTERNAL_TEMPLATE_NOTE: emphasize sample request, do not copy this note."
            script = MessageTemplate(
                user_id=1,
                workspace_id=1,
                product_id=product.id,
                title=f"Note guided outreach-{suffix}",
                scenario="first_contact",
                content="Hi {name}, follow this paragraph structure for a collaboration email.",
                note=internal_note,
                platform="instagram",
                language="en",
                tags=["outreach"],
                generation_rules={"tone": "natural", "language": "en"},
            )
            db.add(script)
            record = await _create_influencer(
                db,
                suffix=suffix,
                email=f"note_{suffix}@example.com",
                product_id=product.id,
            )
            global_row = await db.get(GlobalInfluencerProfile, record.global_influencer_id)
            assert global_row is not None
            await db.commit()

            ai_payload = {
                "subject": "Collaboration idea",
                "body": "Hi creator, we like your travel posts and would love to share a product sample.",
                "recommended_script_id": str(script.id),
                "recommended_script_title": script.title,
                "reason": "fit",
                "matched_knowledge": [],
                "tone": "natural",
                "risk_notes": [],
            }

            with patch(
                "app.services.speech_recommendation_service.chat_completion_json",
                new_callable=AsyncMock,
                return_value=ai_payload,
            ) as ai_mock:
                with patch("app.services.speech_recommendation_service.settings") as mock_settings:
                    mock_settings.is_openai_configured = True
                    mock_settings.active_ai_provider = "deepseek"
                    result = await SpeechRecommendationService.generate_outreach_email(
                        db,
                        product_id=product.id,
                        global_row=global_row,
                        product_row=record,
                        selected_script_ids=[script.id],
                    )

            prompt = ai_mock.await_args.kwargs["user_prompt"]
            assert internal_note in prompt
            assert "涓嶈鎶婃ā鏉垮娉ㄥ師鏂囧啓鍏ラ偖浠舵爣棰樻垨姝ｆ枃" in prompt
            assert internal_note not in result.body

            await db.execute(delete(MessageTemplate).where(MessageTemplate.id == script.id))
            await db.execute(delete(ProductInfluencer).where(ProductInfluencer.id == record.id))
            await db.execute(delete(GlobalInfluencerProfile).where(GlobalInfluencerProfile.id == global_row.id))
            await db.execute(delete(Product).where(Product.id == product.id))
            await db.commit()

    asyncio.run(_run())


def test_generate_outreach_email_does_not_block_short_but_usable_ai_draft():
    async def _run() -> None:
        suffix = _suffix()
        async with async_session_factory() as db:
            product = Product(
                workspace_id=1,
                name=f"AI short draft product {suffix}",
                slug=f"ai-short-draft-{suffix}",
                is_default=False,
            )
            db.add(product)
            await db.flush()
            script = MessageTemplate(
                user_id=1,
                workspace_id=1,
                product_id=product.id,
                title=f"Long rule outreach-{suffix}",
                scenario="first_contact",
                content="Template fallback content must not replace the AI draft.",
                platform="instagram",
                language="en",
                tags=["outreach"],
                generation_rules={"language": "en", "min_length": 180},
            )
            db.add(script)
            record = await _create_influencer(
                db,
                suffix=suffix,
                email=f"short_{suffix}@example.com",
                product_id=product.id,
            )
            global_row = await db.get(GlobalInfluencerProfile, record.global_influencer_id)
            assert global_row is not None
            await db.commit()

            ai_body = "Hi Marta, we like your style and would love to discuss a travel bag collaboration."
            ai_payload = {
                "subject": "Travel bag collaboration",
                "body": ai_body,
                "recommended_script_id": str(script.id),
                "recommended_script_title": script.title,
                "reason": "fit",
                "matched_knowledge": [],
                "tone": "natural",
                "risk_notes": [],
            }

            with patch(
                "app.services.speech_recommendation_service.chat_completion_json",
                new_callable=AsyncMock,
                return_value=ai_payload,
            ):
                with patch("app.services.speech_recommendation_service.settings") as mock_settings:
                    mock_settings.is_openai_configured = True
                    mock_settings.active_ai_provider = "deepseek"
                    result = await SpeechRecommendationService.generate_outreach_email(
                        db,
                        product_id=product.id,
                        global_row=global_row,
                        product_row=record,
                        selected_script_ids=[script.id],
                    )

            assert result.subject == "Travel bag collaboration"
            assert result.body == ai_body
            assert "Template fallback content" not in result.body
            assert result.error_message is None

            await db.execute(delete(MessageTemplate).where(MessageTemplate.id == script.id))
            await db.execute(delete(ProductInfluencer).where(ProductInfluencer.id == record.id))
            await db.execute(delete(GlobalInfluencerProfile).where(GlobalInfluencerProfile.id == global_row.id))
            await db.execute(delete(Product).where(Product.id == product.id))
            await db.commit()

    asyncio.run(_run())


def test_generate_outreach_email_uses_english_brand_when_product_name_is_chinese():
    async def _run() -> None:
        suffix = _suffix()
        async with async_session_factory() as db:
            product = Product(
                workspace_id=1,
                name="澶氳幈杈?,
                brand=None,
                slug=f"english-brand-{suffix}",
                is_default=False,
            )
            db.add(product)
            await db.flush()
            db.add(
                LinkKnowledgeBase(
                    workspace_id=1,
                    user_id=1,
                    product_id=product.id,
                    name=f"EPEDAL24 source {suffix}",
                    url="https://example.com/product",
                    domain="example.com",
                    source_type="url",
                    status="parsed",
                    extracted_knowledge={"brand_name": "EPEDAL24"},
                    summary="EPEDAL24 sells travel organizers.",
                )
            )
            script = MessageTemplate(
                user_id=1,
                workspace_id=1,
                product_id=product.id,
                title=f"English brand outreach-{suffix}",
                scenario="first_contact",
                content="Write a personalized English collaboration email.",
                platform="instagram",
                language="en",
                tags=["outreach"],
                generation_rules={"language": "en"},
            )
            db.add(script)
            record = await _create_influencer(
                db,
                suffix=suffix,
                email=f"english_brand_{suffix}@example.com",
                product_id=product.id,
            )
            global_row = await db.get(GlobalInfluencerProfile, record.global_influencer_id)
            assert global_row is not None
            await db.commit()

            ai_payload = {
                "subject": "Collaboration with EPEDAL24",
                "body": "Hi creator, I am reaching out on behalf of EPEDAL24 about a travel organizer collaboration.",
                "recommended_script_id": str(script.id),
                "recommended_script_title": script.title,
                "reason": "fit",
                "matched_knowledge": [],
                "tone": "natural",
                "risk_notes": [],
            }

            with patch(
                "app.services.speech_recommendation_service.chat_completion_json",
                new_callable=AsyncMock,
                return_value=ai_payload,
            ) as ai_mock:
                with patch("app.services.speech_recommendation_service.settings") as mock_settings:
                    mock_settings.is_openai_configured = True
                    mock_settings.active_ai_provider = "deepseek"
                    result = await SpeechRecommendationService.generate_outreach_email(
                        db,
                        product_id=product.id,
                        global_row=global_row,
                        product_row=record,
                        selected_script_ids=[script.id],
                    )

            prompt = ai_mock.await_args.kwargs["user_prompt"]
            assert "Brand: EPEDAL24" in prompt
            assert "澶氳幈杈? not in prompt
            assert "Final email must be pure English" in prompt
            assert "make a video and upload/post it to Amazon" in prompt
            assert "Amazon Affiliate Program" in prompt
            assert "10%-30% commission" in prompt
            assert "澶氳幈杈? not in result.subject
            assert "澶氳幈杈? not in result.body

            await db.execute(delete(MessageTemplate).where(MessageTemplate.id == script.id))
            await db.execute(delete(ProductInfluencer).where(ProductInfluencer.id == record.id))
            await db.execute(delete(GlobalInfluencerProfile).where(GlobalInfluencerProfile.id == global_row.id))
            await db.execute(delete(LinkKnowledgeBase).where(LinkKnowledgeBase.product_id == product.id))
            await db.execute(delete(Product).where(Product.id == product.id))
            await db.commit()

    asyncio.run(_run())


def test_outreach_email_body_format_normalizer_breaks_links_and_stuck_sentences():
    raw = (
        "Hi,My name is Dona, and I鈥檓 reaching out."
        "馃憠 Product Link: https://www.amazon.com/dp/B0FJRMSV13?th=1"
        "We鈥檇 also love to explore a long-term partnership.Looking forward to hearing from you."
    )

    formatted = SpeechRecommendationService._normalize_outreach_body_format(raw)

    assert "Hi, My name" in formatted
    assert "\n\n馃憠 Product Link:" in formatted
    assert "partnership.\n\nLooking forward" in formatted


def test_outreach_business_requirements_cleanup_and_append_required_offer():
    class Brand:
        brand_name = "EPEDAL24"
        product_links = ["https://www.amazon.com/dp/example"]

    subject, body = SpeechRecommendationService._enforce_outreach_business_requirements(
        subject="Collaboration with 多莱达 每 A Perfect Fit",
        body="Dear Marta,\n\nI＊m reaching out from our brand about your travel content〞and your creative style.",
        brand_profile=Brand(),
    )

    combined = f"{subject}\n{body}"
    assert "多莱达" not in combined
    assert "每" not in combined
    assert "＊" not in combined
    assert "〞" not in combined
    assert "EPEDAL24" in combined
    assert "video" in body.lower()
    assert "Amazon" in body
    assert "https://www.amazon.com/dp/example" in body
    assert "Amazon Affiliate Program" in body
    assert "10%-30% commission" in body

def test_generate_outreach_email_replaces_brand_placeholder_before_queueing():
    async def _run() -> None:
        suffix = _suffix()
        async with async_session_factory() as db:
            await _seed_knowledge(db)
            record = await _create_influencer(
                db,
                suffix=suffix,
                email=f"brand_{suffix}@example.com",
            )
            global_row = await db.get(GlobalInfluencerProfile, record.global_influencer_id)
            assert global_row is not None
            await db.commit()

            ai_payload = {
                "subject": "Collaboration with {brand}",
                "body": "Hi creator, we would love to explore a collaboration with {brand}.",
                "recommended_script_id": None,
                "recommended_script_title": "",
                "reason": "Creator has relevant audience",
                "matched_knowledge": [],
                "tone": "professional",
                "risk_notes": [],
            }

            with patch(
                "app.services.speech_recommendation_service.chat_completion_json",
                new_callable=AsyncMock,
                return_value=ai_payload,
            ):
                with patch("app.services.speech_recommendation_service.settings") as mock_settings:
                    mock_settings.is_openai_configured = True
                    mock_settings.active_ai_provider = "openai"
                    result = await SpeechRecommendationService.generate_outreach_email(
                        db,
                        product_id=1,
                        global_row=global_row,
                        product_row=record,
                    )

            assert result.error_message is None
            assert "{brand}" not in result.subject
            assert "{brand}" not in result.body
            assert "ScandiHome" in result.subject
            assert "ScandiHome" in result.body

            await db.execute(delete(ProductInfluencer).where(ProductInfluencer.id == record.id))
            await db.execute(delete(GlobalInfluencerProfile).where(GlobalInfluencerProfile.id == global_row.id))
            await db.commit()

    asyncio.run(_run())


def test_preview_batch_generates_distinct_emails_and_skips_missing_email():
    async def _run() -> None:
        suffix = _suffix()

        async def _fake_generate(
            db,
            *,
            product_id,
            product_row,
            global_row,
            user_intent,
            selected_script_ids,
            language,
            tone,
        ) -> OutreachEmailGenerationResult:
            uname = global_row.username or "unknown"
            return OutreachEmailGenerationResult(
                subject=f"Subject for {uname}",
                body=f"Body personalized for {uname} with intent {user_intent}",
                recommended_script_id=None,
                recommended_script_title="",
                reason=f"Reason for {uname}",
                matched_knowledge=[],
                tone="professional",
                risk_notes=[],
                provider="openai",
                configured=True,
                error_message=None,
            )

        async with async_session_factory() as db:
            with_email_a = await _create_influencer(
                db,
                suffix=f"{suffix}a",
                email=f"a_{suffix}@example.com",
            )
            with_email_b = await _create_influencer(
                db,
                suffix=f"{suffix}b",
                email=f"b_{suffix}@example.com",
            )
            no_email = await _create_influencer(db, suffix=f"{suffix}c", email=None)
            await db.commit()

            ids = [with_email_a.id, with_email_b.id, no_email.id]

            with patch.object(OutreachEmailService, "_generate_for_pair", side_effect=_fake_generate):
                preview = await OutreachEmailService.preview_batch(
                    db,
                    product_id=1,
                    payload=OutreachBatchPreviewRequest(
                        influencer_ids=ids,
                        user_intent="棣栨鍚堜綔閭€绾?,
                    ),
                )

            assert preview.summary.total == 3
            assert preview.summary.generated == 2
            assert preview.summary.missing_email == 1
            assert preview.summary.failed == 0

            generated = [item for item in preview.items if item.can_send]
            assert len(generated) == 2
            subjects = {item.subject for item in generated}
            bodies = {item.body for item in generated}
            assert len(subjects) == 2
            assert len(bodies) == 2

            skipped = [item for item in preview.items if not item.can_send]
            assert len(skipped) == 1
            assert skipped[0].influencer_id == no_email.id
            assert "閭" in (skipped[0].error_message or "")

            await db.execute(delete(EmailLog).where(EmailLog.product_influencer_id.in_(ids)))
            await db.execute(delete(ProductInfluencer).where(ProductInfluencer.id.in_(ids)))
            gp_ids = [
                with_email_a.global_influencer_id,
                with_email_b.global_influencer_id,
                no_email.global_influencer_id,
            ]
            await db.execute(delete(GlobalInfluencerProfile).where(GlobalInfluencerProfile.id.in_(gp_ids)))
            await db.commit()

    asyncio.run(_run())

