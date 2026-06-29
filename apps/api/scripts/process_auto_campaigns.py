"""CLI: process due outreach email campaign auto-send slots."""

from __future__ import annotations

import asyncio
import logging

from app.db.session import async_session_factory
from app.services.outreach_campaign_service import OutreachCampaignService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    async with async_session_factory() as db:
        result = await OutreachCampaignService.process_due_auto_campaigns(db)
    logger.info(
        "Auto campaign run: checked=%s processed=%s items=%s",
        result.checked,
        result.processed,
        len(result.items),
    )
    for item in result.items:
        logger.info(
            "campaign_id=%s processed=%s sent=%s failed=%s skipped=%s error=%s",
            item.campaign_id,
            item.processed,
            item.sent,
            item.failed,
            item.skipped,
            item.error_message,
        )


if __name__ == "__main__":
    asyncio.run(main())
