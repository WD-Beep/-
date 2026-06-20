from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collection_task import CollectionTask
from app.models.collection_task_candidate import CollectionTaskCandidate
from app.models.enums import CandidateStatus, CollectionMode
from app.models.global_influencer_profile import GlobalInfluencerProfile
from app.models.influencer import Influencer
from app.models.product_influencer import ProductInfluencer
from app.services.influencer_projection import merged_influencer_for_ai


def influencer_has_email(influencer: Influencer) -> bool:
    return bool(
        influencer.final_email
        or influencer.email
        or influencer.public_email
        or influencer.business_email
    )


def influencer_has_contact(influencer: Influencer) -> bool:
    return influencer_has_email(influencer) or bool(
        influencer.whatsapp
        or influencer.telegram
        or influencer.contact_page
        or influencer.linktree_url
    )


class TaskInfluencerService:
    @staticmethod
    async def get_influencers_for_task(db: AsyncSession, task: CollectionTask) -> list[Influencer]:
        if not task.product_id:
            return []

        query = (
            select(ProductInfluencer, GlobalInfluencerProfile)
            .join(GlobalInfluencerProfile, ProductInfluencer.global_influencer_id == GlobalInfluencerProfile.id)
            .join(
                CollectionTaskCandidate,
                CollectionTaskCandidate.product_influencer_id == ProductInfluencer.id,
            )
            .where(
                CollectionTaskCandidate.task_id == task.id,
                CollectionTaskCandidate.status == CandidateStatus.INSERTED.value,
                ProductInfluencer.product_id == task.product_id,
                CollectionTaskCandidate.product_id == task.product_id,
            )
        )

        if task.collection_mode == CollectionMode.LINK_SEED_DISCOVERY.value:
            pass
        elif task.platform:
            platform = task.platform.strip().lower()
            platforms = [
                str(value).strip().lower()
                for value in (task.platforms or [])
                if value and str(value).strip()
            ]
            if platform == "multi":
                if platforms:
                    query = query.where(GlobalInfluencerProfile.platform.in_(platforms))
            elif platforms and len(platforms) > 1:
                query = query.where(GlobalInfluencerProfile.platform.in_(platforms))
            else:
                query = query.where(GlobalInfluencerProfile.platform == platform)
        elif task.platforms:
            platforms = [
                str(value).strip().lower()
                for value in task.platforms
                if value and str(value).strip()
            ]
            if platforms:
                query = query.where(GlobalInfluencerProfile.platform.in_(platforms))
        if task.country:
            query = query.where(GlobalInfluencerProfile.country == task.country)
        if task.category:
            query = query.where(GlobalInfluencerProfile.category == task.category)

        query = query.order_by(ProductInfluencer.score.desc().nullslast(), ProductInfluencer.updated_at.desc())
        result = await db.execute(query)
        seen: set[int] = set()
        influencers: list[Influencer] = []
        for product_row, global_row in result.all():
            if product_row.id in seen:
                continue
            seen.add(product_row.id)
            influencers.append(merged_influencer_for_ai(product_row, global_row))
        return influencers

    @staticmethod
    def compute_contact_stats(influencers: list[Influencer]) -> tuple[int, int, int]:
        total = len(influencers)
        email_count = sum(1 for item in influencers if influencer_has_email(item))
        missing_contact_count = sum(1 for item in influencers if not influencer_has_contact(item))
        return total, email_count, missing_contact_count

    @staticmethod
    async def refresh_task_stats(db: AsyncSession, task: CollectionTask) -> None:
        influencers = await TaskInfluencerService.get_influencers_for_task(db, task)
        total, email_count, missing_contact_count = TaskInfluencerService.compute_contact_stats(
            influencers
        )
        task.result_count = total
        task.email_count = email_count
        task.missing_contact_count = missing_contact_count
