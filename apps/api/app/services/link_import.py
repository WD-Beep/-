import logging
import math

from datetime import UTC, datetime

logger = logging.getLogger(__name__)

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.base import CollectedInfluencer
from app.deps.tenant import TenantContext, require_write_product_id
from app.models.enums import LinkImportBatchStatus
from app.models.global_influencer_profile import GlobalInfluencerProfile
from app.models.link_import_batch import LinkImportBatch
from app.models.product_influencer import ProductInfluencer
from app.schemas.common import PaginatedResponse
from app.schemas.link_import import LinkImportBatchCreate, LinkImportBatchRead
from app.services.apify_instagram import ProfileScrapeResult, _username_from_url
from app.services.collect_errors import summarize_errors
from app.services.ai_service import analyze_influencer
from app.services.contact_discovery import ContactDiscoveryService
from app.services.influencer_persistence import (
    InfluencerPersistenceService,
    apply_global_profile_data,
    apply_product_influencer_data,
    create_global_profile_from_collected,
    create_product_influencer_from_collected,
    global_profile_has_changes,
    identity_key_for_item,
    product_record_has_changes,
    should_refresh_global_profile,
)
from app.services.influencer_projection import apply_ai_to_product_record, merged_influencer_for_ai
from app.services.instagram_provider import scrape_instagram_profiles
from app.services.url_parser import parse_raw_urls


class LinkImportService:
    @staticmethod
    async def list_batches(
        db: AsyncSession,
        page: int,
        page_size: int,
        *,
        product_id: int,
    ) -> PaginatedResponse[LinkImportBatchRead]:
        base = select(LinkImportBatch).where(LinkImportBatch.product_id == product_id)
        total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
        result = await db.execute(
            base.order_by(LinkImportBatch.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = [LinkImportBatchRead.model_validate(row) for row in result.scalars().all()]
        return PaginatedResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            pages=math.ceil(total / page_size) if total else 0,
        )

    @staticmethod
    async def get_batch(
        db: AsyncSession,
        batch_id: int,
        *,
        product_id: int | None = None,
    ) -> LinkImportBatch | None:
        query = select(LinkImportBatch).where(LinkImportBatch.id == batch_id)
        if product_id is not None:
            query = query.where(LinkImportBatch.product_id == product_id)
        result = await db.execute(query)
        return result.scalar_one_or_none()

    @staticmethod
    async def create_batch(
        db: AsyncSession,
        data: LinkImportBatchCreate,
        *,
        ctx: TenantContext,
    ) -> LinkImportBatch:
        valid_urls, invalid_urls = parse_raw_urls(data.raw_urls)
        non_empty_lines = [line.strip() for line in data.raw_urls.splitlines() if line.strip()]
        total_count = len(non_empty_lines)

        batch = LinkImportBatch(
            name=data.name.strip(),
            raw_urls=data.raw_urls,
            valid_urls=valid_urls,
            invalid_urls=invalid_urls,
            status=LinkImportBatchStatus.PENDING.value,
            total_count=total_count,
            failed_count=len(invalid_urls),
            user_id=ctx.user_id,
            workspace_id=ctx.workspace_id,
            product_id=require_write_product_id(ctx),
        )
        db.add(batch)
        await db.commit()
        await db.refresh(batch)
        return batch

    @staticmethod
    async def run_batch(db: AsyncSession, batch: LinkImportBatch) -> LinkImportBatch:
        if batch.status == LinkImportBatchStatus.RUNNING.value:
            raise ValueError("Import batch is already running")
        if not batch.product_id:
            raise ValueError("导入批次未绑定产品，无法执行")

        batch.status = LinkImportBatchStatus.RUNNING.value
        batch.error_message = None
        await db.commit()
        await db.refresh(batch)

        run_at = datetime.now(UTC)
        new_count = 0
        updated_count = 0
        import_failed = 0
        import_errors: list[str] = []
        valid_urls = batch.valid_urls or []
        product_id = batch.product_id

        try:
            instagram_urls: list[str] = []
            instagram_entries: list[tuple[str, str]] = []

            for entry in valid_urls:
                url = entry.get("url", "")
                platform = entry.get("platform", "")
                if not url or not platform:
                    import_failed += 1
                    continue
                if platform == "instagram":
                    instagram_urls.append(url)
                    instagram_entries.append((url, platform))
                else:
                    import_failed += 1
                    import_errors.append(f"仅支持 Instagram 链接，已跳过: {url}")

            apify_by_username: dict[str, CollectedInfluencer] = {}
            if instagram_urls:
                scrape_result: ProfileScrapeResult = await scrape_instagram_profiles(instagram_urls)
                apify_by_username = {item.username.lower(): item for item in scrape_result.profiles}
                for item in scrape_result.profiles:
                    await ContactDiscoveryService.enrich_collected(item)
                import_errors.extend(scrape_result.errors)
                if not scrape_result.profiles:
                    import_errors.append(
                        f"未返回任何主页数据（请求 {len(instagram_urls)} 条 Instagram 链接）"
                    )

            for url, platform in instagram_entries:
                try:
                    if platform == "instagram":
                        username = _username_from_url(url).lower()
                        item = apify_by_username.get(username)
                        if not item:
                            import_failed += 1
                            import_errors.append(f"链接导入失败，未匹配到采集结果: {url}")
                            continue
                    else:
                        import_failed += 1
                        continue

                    outcome = await LinkImportService._upsert_product_influencer(
                        db, item, run_at, product_id=product_id
                    )
                    if outcome == "new":
                        new_count += 1
                    elif outcome == "updated":
                        updated_count += 1
                except Exception as exc:
                    import_failed += 1
                    import_errors.append(f"入库失败 {url}: {exc}")

            success_count = len(valid_urls) - import_failed
            invalid_count = len(batch.invalid_urls or [])
            batch.new_count = new_count
            batch.updated_count = updated_count
            batch.success_count = success_count
            batch.failed_count = invalid_count + import_failed
            batch.status = LinkImportBatchStatus.COMPLETED.value
            batch.completed_at = run_at
            batch.error_message = summarize_errors(
                import_errors,
                prefix="导入已完成，部分链接存在问题：" if import_errors else "",
            )
            await db.commit()
            await db.refresh(batch)
            return batch

        except Exception as exc:
            batch.status = LinkImportBatchStatus.FAILED.value
            batch.error_message = str(exc)[:2000]
            batch.completed_at = run_at
            await db.commit()
            await db.refresh(batch)
            raise

    @staticmethod
    async def _upsert_product_influencer(
        db: AsyncSession,
        item: CollectedInfluencer,
        run_at: datetime,
        *,
        product_id: int,
    ) -> str:
        global_map = await InfluencerPersistenceService.find_global_profiles_batch(db, [item])
        product_map = await InfluencerPersistenceService.find_product_influencers_batch(
            db, product_id, [item], global_map=global_map
        )
        identity_key = identity_key_for_item(item)
        global_profile = global_map.get(identity_key)
        product_record = product_map.get(identity_key)

        if product_record:
            if not product_record_has_changes(product_record, item, None):
                product_record.last_collected_at = run_at
                await db.flush()
                return "unchanged"
            if global_profile and (
                should_refresh_global_profile(global_profile, now=run_at)
                or global_profile_has_changes(global_profile, item)
            ):
                apply_global_profile_data(global_profile, item, run_at=run_at)
            apply_product_influencer_data(product_record, item, None, run_at=run_at)
            await LinkImportService._analyze_product_influencer(db, product_record, global_profile)
            return "updated"

        if not global_profile:
            global_profile = create_global_profile_from_collected(item, run_at=run_at)
            db.add(global_profile)
            await db.flush()
        elif should_refresh_global_profile(global_profile, now=run_at) or global_profile_has_changes(
            global_profile, item
        ):
            apply_global_profile_data(global_profile, item, run_at=run_at)

        product_record = create_product_influencer_from_collected(
            product_id=product_id,
            global_profile=global_profile,
            data=item,
            task=None,
            run_at=run_at,
        )
        db.add(product_record)
        await db.flush()
        await LinkImportService._analyze_product_influencer(db, product_record, global_profile)
        return "new"

    @staticmethod
    async def _analyze_product_influencer(
        db: AsyncSession,
        product_row: ProductInfluencer,
        global_row: GlobalInfluencerProfile | None,
    ) -> None:
        if not global_row:
            return
        try:
            merged = merged_influencer_for_ai(product_row, global_row)
            analysis = await analyze_influencer(merged)
            apply_ai_to_product_record(product_row, analysis, global_row=global_row)
        except Exception as exc:
            logger.warning("Link import AI failed for %s: %s", global_row.username, exc)
