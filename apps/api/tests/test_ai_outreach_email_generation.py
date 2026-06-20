"""批量 AI 个性化邮件生成测试。"""

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
from app.models.message_template import MessageTemplate
from app.models.product_influencer import ProductInfluencer
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
        product_id=1,
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
            title="品牌定位",
            content="ScandiHome 专注北欧简约家居，强调自然材质。",
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
            assert any("未配置 AI" in note for note in result.risk_notes)
            assert result.subject
            assert result.body
            assert "未配置 AI，未生成个性化话术" in " ".join(result.risk_notes)

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
                title=f"首次邀约-{suffix}",
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
                        user_intent="首次合作邀约",
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
            assert "邮箱" in (skipped[0].error_message or "")

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
