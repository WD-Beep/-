from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import FollowupActionType, LeadStatus
from app.models.influencer import Influencer
from app.models.influencer_followup import InfluencerFollowup
from app.models.product_influencer import ProductInfluencer
from app.schemas.influencer_lead import FollowupCreate, InfluencerLeadUpdate

VALID_LEAD_STATUSES = frozenset(item.value for item in LeadStatus)
VALID_PRIORITIES = frozenset({"P0", "P1", "P2", "P3"})
VALID_ACTION_TYPES = frozenset(item.value for item in FollowupActionType)

CONTACTED_STATUSES = frozenset(
    {
        LeadStatus.CONTACTED.value,
        LeadStatus.REPLIED.value,
        LeadStatus.INTERESTED.value,
        LeadStatus.QUOTED.value,
        LeadStatus.COOPERATING.value,
        LeadStatus.COOPERATED.value,
        "negotiating",
        "collaborated",
    }
)

EXCLUDED_FROM_TODAY = frozenset(
    {
        LeadStatus.INVALID.value,
        LeadStatus.BLACKLISTED.value,
        "rejected",
    }
)

TODAY_RECOMMENDED_STATUSES = frozenset(
    {
        LeadStatus.NEW.value,
        LeadStatus.TO_CONTACT.value,
    }
)


class InfluencerLeadService:
    @staticmethod
    def _validate_lead_status(status: str | None) -> None:
        if status is not None and status not in VALID_LEAD_STATUSES:
            legacy = {"negotiating", "collaborated", "rejected"}
            if status not in legacy:
                raise ValueError(f"Invalid lead_status: {status}")

    @staticmethod
    def _validate_priority(priority: str | None) -> None:
        if priority is not None and priority not in VALID_PRIORITIES:
            raise ValueError(f"Invalid lead_priority: {priority}")

    @staticmethod
    async def create_followup(
        db: AsyncSession,
        influencer: Influencer,
        *,
        action_type: str,
        content: str | None = None,
        operator_name: str | None = None,
        contact_channel: str | None = None,
        old_status: str | None = None,
        new_status: str | None = None,
    ) -> InfluencerFollowup:
        if action_type not in VALID_ACTION_TYPES:
            raise ValueError(f"Invalid action_type: {action_type}")

        followup = InfluencerFollowup(
            influencer_id=influencer.id,
            action_type=action_type,
            old_status=old_status,
            new_status=new_status,
            content=content,
            operator_name=operator_name,
            contact_channel=contact_channel,
        )
        db.add(followup)
        return followup

    @staticmethod
    def _apply_status_side_effects(
        influencer: Influencer,
        old_status: str | None,
        new_status: str | None,
    ) -> None:
        if not new_status or new_status == old_status:
            return

        now = datetime.now(UTC)
        if new_status == LeadStatus.CONTACTED.value and old_status != LeadStatus.CONTACTED.value:
            influencer.last_contacted_at = now
        if new_status == LeadStatus.REPLIED.value and old_status != LeadStatus.REPLIED.value:
            influencer.last_reply_at = now

    @staticmethod
    async def update_lead(
        db: AsyncSession,
        influencer: Influencer,
        data: InfluencerLeadUpdate,
    ) -> Influencer:
        update = data.model_dump(exclude_unset=True)
        operator_name = update.pop("operator_name", None)
        old_status = influencer.follow_status

        for field in ("next_follow_up_at", "invalid_reason", "blacklist_reason"):
            if field in update:
                setattr(influencer, field, update.pop(field))

        if "lead_priority" in update:
            priority = update.pop("lead_priority")
            InfluencerLeadService._validate_priority(priority)
            influencer.final_priority = priority

        if "owner_name" in update:
            influencer.owner = update.pop("owner_name")

        if "lead_status" in update:
            new_status = update.pop("lead_status")
            InfluencerLeadService._validate_lead_status(new_status)
            if new_status != old_status:
                influencer.follow_status = new_status
                InfluencerLeadService._apply_status_side_effects(influencer, old_status, new_status)
                await InfluencerLeadService.create_followup(
                    db,
                    influencer,
                    action_type=FollowupActionType.STATUS_CHANGED.value,
                    old_status=old_status,
                    new_status=new_status,
                    operator_name=operator_name,
                )
                if new_status == LeadStatus.INVALID.value:
                    await InfluencerLeadService.create_followup(
                        db,
                        influencer,
                        action_type=FollowupActionType.INVALID_MARKED.value,
                        content=influencer.invalid_reason,
                        operator_name=operator_name,
                    )
                elif new_status == LeadStatus.BLACKLISTED.value:
                    await InfluencerLeadService.create_followup(
                        db,
                        influencer,
                        action_type=FollowupActionType.BLACKLISTED.value,
                        content=influencer.blacklist_reason,
                        operator_name=operator_name,
                    )

        if "lead_note" in update:
            note = update.pop("lead_note")
            influencer.note = note
            if note:
                await InfluencerLeadService.create_followup(
                    db,
                    influencer,
                    action_type=FollowupActionType.NOTE.value,
                    content=note,
                    operator_name=operator_name,
                )

        if update:
            raise ValueError(f"Unknown fields: {', '.join(update)}")

        await db.commit()
        await db.refresh(influencer)
        return influencer

    @staticmethod
    async def mark_product_email_sent(
        db: AsyncSession,
        product_row: ProductInfluencer,
        *,
        subject: str | None = None,
        operator_name: str | None = None,
    ) -> ProductInfluencer:
        old_status = product_row.follow_status
        new_status = LeadStatus.CONTACTED.value
        now = datetime.now(UTC)

        product_row.follow_status = new_status
        product_row.last_contacted_at = now

        await InfluencerLeadService.create_product_followup(
            db,
            product_row,
            action_type=FollowupActionType.EMAIL_SENT.value,
            content=subject,
            operator_name=operator_name,
            contact_channel="email",
            old_status=old_status,
            new_status=new_status,
        )
        await db.commit()
        await db.refresh(product_row)
        return product_row

    @staticmethod
    async def mark_email_sent(
        db: AsyncSession,
        influencer: Influencer,
        *,
        subject: str | None = None,
        operator_name: str | None = None,
    ) -> Influencer:
        old_status = influencer.follow_status
        new_status = LeadStatus.CONTACTED.value
        now = datetime.now(UTC)

        influencer.follow_status = new_status
        influencer.last_contacted_at = now

        await InfluencerLeadService.create_followup(
            db,
            influencer,
            action_type=FollowupActionType.EMAIL_SENT.value,
            content=subject,
            operator_name=operator_name,
            contact_channel="email",
            old_status=old_status,
            new_status=new_status,
        )
        await db.commit()
        await db.refresh(influencer)
        return influencer

    @staticmethod
    async def add_followup(
        db: AsyncSession,
        influencer: Influencer,
        data: FollowupCreate,
    ) -> InfluencerFollowup:
        followup = await InfluencerLeadService.create_followup(
            db,
            influencer,
            action_type=data.action_type,
            content=data.content,
            operator_name=data.operator_name,
            contact_channel=data.contact_channel,
        )
        await db.commit()
        await db.refresh(followup)
        return followup

    @staticmethod
    async def list_followups(
        db: AsyncSession,
        influencer_id: int,
        *,
        limit: int = 100,
    ) -> list[InfluencerFollowup]:
        query = (
            select(InfluencerFollowup)
            .where(InfluencerFollowup.influencer_id == influencer_id)
            .order_by(InfluencerFollowup.created_at.desc())
            .limit(limit)
        )
        result = await db.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def create_product_followup(
        db: AsyncSession,
        product_row: ProductInfluencer,
        *,
        action_type: str,
        content: str | None = None,
        operator_name: str | None = None,
        contact_channel: str | None = None,
        old_status: str | None = None,
        new_status: str | None = None,
    ) -> InfluencerFollowup:
        if action_type not in VALID_ACTION_TYPES:
            raise ValueError(f"Invalid action_type: {action_type}")
        followup = InfluencerFollowup(
            product_influencer_id=product_row.id,
            influencer_id=product_row.legacy_influencer_id,
            action_type=action_type,
            old_status=old_status,
            new_status=new_status,
            content=content,
            operator_name=operator_name,
            contact_channel=contact_channel,
        )
        db.add(followup)
        return followup

    @staticmethod
    def _apply_product_status_side_effects(
        product_row: ProductInfluencer,
        old_status: str | None,
        new_status: str | None,
    ) -> None:
        if not new_status or new_status == old_status:
            return
        now = datetime.now(UTC)
        if new_status == LeadStatus.CONTACTED.value and old_status != LeadStatus.CONTACTED.value:
            product_row.last_contacted_at = now
        if new_status == LeadStatus.REPLIED.value and old_status != LeadStatus.REPLIED.value:
            product_row.last_reply_at = now

    @staticmethod
    async def update_product_lead(
        db: AsyncSession,
        product_row: ProductInfluencer,
        data: InfluencerLeadUpdate,
    ) -> ProductInfluencer:
        update = data.model_dump(exclude_unset=True)
        operator_name = update.pop("operator_name", None)
        old_status = product_row.follow_status

        for field in ("next_follow_up_at", "invalid_reason", "blacklist_reason"):
            if field in update:
                setattr(product_row, field, update.pop(field))

        if "lead_priority" in update:
            priority = update.pop("lead_priority")
            InfluencerLeadService._validate_priority(priority)
            product_row.final_priority = priority

        if "owner_name" in update:
            product_row.owner = update.pop("owner_name")

        if "lead_status" in update:
            new_status = update.pop("lead_status")
            InfluencerLeadService._validate_lead_status(new_status)
            if new_status != old_status:
                product_row.follow_status = new_status
                InfluencerLeadService._apply_product_status_side_effects(product_row, old_status, new_status)
                await InfluencerLeadService.create_product_followup(
                    db,
                    product_row,
                    action_type=FollowupActionType.STATUS_CHANGED.value,
                    old_status=old_status,
                    new_status=new_status,
                    operator_name=operator_name,
                )
                if new_status == LeadStatus.INVALID.value:
                    await InfluencerLeadService.create_product_followup(
                        db,
                        product_row,
                        action_type=FollowupActionType.INVALID_MARKED.value,
                        content=product_row.invalid_reason,
                        operator_name=operator_name,
                    )
                elif new_status == LeadStatus.BLACKLISTED.value:
                    await InfluencerLeadService.create_product_followup(
                        db,
                        product_row,
                        action_type=FollowupActionType.BLACKLISTED.value,
                        content=product_row.blacklist_reason,
                        operator_name=operator_name,
                    )

        if "lead_note" in update:
            note = update.pop("lead_note")
            product_row.note = note
            if note:
                await InfluencerLeadService.create_product_followup(
                    db,
                    product_row,
                    action_type=FollowupActionType.NOTE.value,
                    content=note,
                    operator_name=operator_name,
                )

        if update:
            raise ValueError(f"Unknown fields: {', '.join(update)}")

        await db.commit()
        await db.refresh(product_row)
        return product_row

    @staticmethod
    async def add_product_followup(
        db: AsyncSession,
        product_row: ProductInfluencer,
        data: FollowupCreate,
    ) -> InfluencerFollowup:
        followup = await InfluencerLeadService.create_product_followup(
            db,
            product_row,
            action_type=data.action_type,
            content=data.content,
            operator_name=data.operator_name,
            contact_channel=data.contact_channel,
        )
        await db.commit()
        await db.refresh(followup)
        return followup

    @staticmethod
    async def list_product_followups(
        db: AsyncSession,
        product_influencer_id: int,
        *,
        limit: int = 100,
    ) -> list[InfluencerFollowup]:
        query = (
            select(InfluencerFollowup)
            .where(InfluencerFollowup.product_influencer_id == product_influencer_id)
            .order_by(InfluencerFollowup.created_at.desc())
            .limit(limit)
        )
        result = await db.execute(query)
        return list(result.scalars().all())
