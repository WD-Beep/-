"""批量 AI 个性化邮件发送测试。"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from sqlalchemy import delete, select

from app.collectors.base import CollectedInfluencer
from app.core.exceptions import SMTP_NOT_CONFIGURED_MSG
from app.db.session import async_session_factory
from app.models.email_log import EmailLog
from app.models.enums import EmailLogStatus
from app.models.global_influencer_profile import GlobalInfluencerProfile
from app.models.product_influencer import ProductInfluencer
from app.schemas.outreach_email import (
    OutreachBatchSendRequest,
    OutreachEmailGenerationResult,
)
from app.services.influencer_persistence import (
    create_global_profile_from_collected,
    create_product_influencer_from_collected,
)
from app.services.outreach_email_service import OutreachEmailService


def _suffix() -> str:
    return uuid.uuid4().hex[:10]


async def _create_influencer(db, *, suffix: str, email: str) -> ProductInfluencer:
    run_at = datetime.now(UTC)
    uname = f"outreach_send_{suffix}"
    item = CollectedInfluencer(
        platform="tiktok",
        username=uname,
        profile_url=f"https://tiktok.com/@{uname}",
        platform_unique_id=f"tt_{suffix}",
        followers_count=88000,
        engagement_rate=4.1,
        bio="product reviews",
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


def _generation_for_username(username: str) -> OutreachEmailGenerationResult:
    return OutreachEmailGenerationResult(
        subject=f"Invite {username}",
        body=f"Personalized outreach body for @{username}.",
        recommended_script_id=None,
        recommended_script_title="",
        reason=f"Good fit for {username}",
        matched_knowledge=[],
        tone="friendly",
        risk_notes=[],
        provider="openai",
        configured=True,
        error_message=None,
    )


async def _fake_generate(db, *, product_id, product_row, global_row, **kwargs):
    return _generation_for_username(global_row.username or "unknown")


def test_send_batch_dry_run_writes_logs_without_smtp():
    async def _run() -> None:
        suffix = _suffix()
        async with async_session_factory() as db:
            a = await _create_influencer(db, suffix=f"{suffix}a", email=f"a_{suffix}@example.com")
            b = await _create_influencer(db, suffix=f"{suffix}b", email=f"b_{suffix}@example.com")
            await db.commit()
            ids = [a.id, b.id]

            with patch.object(OutreachEmailService, "_generate_for_pair", side_effect=_fake_generate):
                with patch(
                    "app.services.outreach_email_service.EmailService._send_message",
                    new_callable=AsyncMock,
                ) as mock_send:
                    result = await OutreachEmailService.send_batch(
                        db,
                        product_id=1,
                        user_id=1,
                        payload=OutreachBatchSendRequest(
                            influencer_ids=ids,
                            user_intent="首次合作邀约",
                            dry_run=True,
                        ),
                    )

            assert result.dry_run is True
            assert result.summary.pending == 2
            assert result.summary.sent == 0
            mock_send.assert_not_awaited()

            logs = (
                await db.execute(
                    select(EmailLog)
                    .where(EmailLog.product_influencer_id.in_(ids))
                    .order_by(EmailLog.id)
                )
            ).scalars().all()
            assert len(logs) == 2
            bodies = {log.body for log in logs}
            assert len(bodies) == 2
            assert all(log.status == EmailLogStatus.PENDING.value for log in logs)
            assert all(log.body and log.subject for log in logs)

            await db.execute(delete(EmailLog).where(EmailLog.product_influencer_id.in_(ids)))
            await db.execute(delete(ProductInfluencer).where(ProductInfluencer.id.in_(ids)))
            gp_ids = [a.global_influencer_id, b.global_influencer_id]
            await db.execute(delete(GlobalInfluencerProfile).where(GlobalInfluencerProfile.id.in_(gp_ids)))
            await db.commit()

    asyncio.run(_run())


def test_send_batch_real_send_per_influencer_and_isolates_smtp_failure():
    async def _run() -> None:
        suffix = _suffix()
        async with async_session_factory() as db:
            ok = await _create_influencer(db, suffix=f"{suffix}ok", email=f"ok_{suffix}@example.com")
            fail = await _create_influencer(db, suffix=f"{suffix}fail", email=f"fail_{suffix}@example.com")
            await db.commit()
            ids = [ok.id, fail.id]

            async def _send_side_effect(message, recipients):
                if fail.id and recipients and "fail_" in recipients[0]:
                    raise RuntimeError("SMTP auth failed")

            with patch.object(OutreachEmailService, "_generate_for_pair", side_effect=_fake_generate):
                with patch(
                    "app.services.outreach_email_service.EmailService.ensure_smtp_configured",
                ):
                    with patch(
                        "app.services.outreach_email_service.EmailService._send_message",
                        new_callable=AsyncMock,
                        side_effect=_send_side_effect,
                    ):
                        result = await OutreachEmailService.send_batch(
                            db,
                            product_id=1,
                            user_id=1,
                            payload=OutreachBatchSendRequest(
                                influencer_ids=ids,
                                user_intent="首次合作邀约",
                                dry_run=False,
                            ),
                        )

            assert result.summary.sent == 1
            assert result.summary.failed == 1
            assert result.summary.generated == 2

            logs = (
                await db.execute(
                    select(EmailLog).where(EmailLog.product_influencer_id.in_(ids))
                )
            ).scalars().all()
            assert len(logs) == 2
            by_status = {log.status: log for log in logs}
            assert EmailLogStatus.SENT.value in by_status
            assert EmailLogStatus.FAILED.value in by_status

            sent_log = by_status[EmailLogStatus.SENT.value]
            failed_log = by_status[EmailLogStatus.FAILED.value]
            assert sent_log.body != failed_log.body
            assert sent_log.body.startswith("Personalized outreach body")
            assert failed_log.body.startswith("Personalized outreach body")

            await db.execute(delete(EmailLog).where(EmailLog.product_influencer_id.in_(ids)))
            await db.execute(delete(ProductInfluencer).where(ProductInfluencer.id.in_(ids)))
            gp_ids = [ok.global_influencer_id, fail.global_influencer_id]
            await db.execute(delete(GlobalInfluencerProfile).where(GlobalInfluencerProfile.id.in_(gp_ids)))
            await db.commit()

    asyncio.run(_run())


def test_send_batch_without_smtp_config_returns_failed():
    async def _run() -> None:
        suffix = _suffix()
        async with async_session_factory() as db:
            record = await _create_influencer(db, suffix=suffix, email=f"smtp_{suffix}@example.com")
            await db.commit()

            with patch(
                "app.services.outreach_email_service.EmailService.ensure_smtp_configured",
                side_effect=__import__(
                    "app.services.email", fromlist=["EmailNotConfiguredError"]
                ).EmailNotConfiguredError(SMTP_NOT_CONFIGURED_MSG),
            ):
                result = await OutreachEmailService.send_batch(
                    db,
                    product_id=1,
                    user_id=1,
                    payload=OutreachBatchSendRequest(
                        influencer_ids=[record.id],
                        dry_run=False,
                    ),
                )

            assert result.summary.failed == 1
            assert result.items[0].error_message == SMTP_NOT_CONFIGURED_MSG

            await db.execute(delete(ProductInfluencer).where(ProductInfluencer.id == record.id))
            await db.execute(
                delete(GlobalInfluencerProfile).where(
                    GlobalInfluencerProfile.id == record.global_influencer_id
                )
            )
            await db.commit()

    asyncio.run(_run())
