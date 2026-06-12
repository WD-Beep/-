"""Quick verification for phase-3 lead followup schema."""

import asyncio

from sqlalchemy import select, text

from app.db.session import async_session_factory
from app.models.influencer import Influencer
from app.schemas.influencer_lead import InfluencerLeadUpdate
from app.services.influencer_lead import InfluencerLeadService


async def main() -> None:
    async with async_session_factory() as db:
        result = await db.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='influencers' "
                "AND column_name IN ('next_follow_up_at','last_contacted_at','invalid_reason')"
            )
        )
        cols = [row[0] for row in result]
        print("influencer cols:", cols)

        table = await db.scalar(text("SELECT to_regclass('public.influencer_followups')"))
        print("followups table:", table)

        influencer = await db.scalar(select(Influencer).limit(1))
        if not influencer:
            print("no influencer to test lead update")
            return

        old_status = influencer.follow_status
        updated = await InfluencerLeadService.update_lead(
            db,
            influencer,
            InfluencerLeadUpdate(
                lead_status="to_contact",
                owner_name="verify-script",
                operator_name="verify-script",
            ),
        )
        print("updated status:", updated.follow_status, "owner:", updated.owner)

        followups = await InfluencerLeadService.list_followups(db, updated.id, limit=5)
        print("followup count:", len(followups), "latest:", followups[0].action_type if followups else None)

        if old_status:
            await InfluencerLeadService.update_lead(
                db,
                updated,
                InfluencerLeadUpdate(lead_status=old_status, operator_name="verify-script"),
            )
            print("restored status:", old_status)


if __name__ == "__main__":
    asyncio.run(main())
