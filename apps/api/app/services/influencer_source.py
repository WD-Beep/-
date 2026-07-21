# 文件说明：后端业务服务，负责采集、筛选、AI、邮件和任务流程；当前文件：influencer source
"""记录红人与来源作品链接的关联，支持同一红人多个来源。"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.base import CollectedInfluencer
from app.models.collection_task import CollectionTask
from app.models.product_influencer import ProductInfluencer
from app.models.product_influencer_source import ProductInfluencerSource
from app.services.link_import_url import normalize_url
from app.services.platform_utils import normalize_profile_url
from app.services.url_parser import detect_platform


def normalize_source_key(url: str | None) -> str:
    text = (url or "").strip()
    if not text:
        return ""
    return normalize_url(text).lower().rstrip("/")


def _is_profile_only_url(url: str | None, profile_url: str | None) -> bool:
    if not url or not profile_url:
        return False
    return normalize_profile_url(url) == normalize_profile_url(profile_url)


def resolve_source_fields(
    *,
    source_post_url: str | None,
    source_input_url: str | None,
    profile_url: str | None,
) -> tuple[str | None, str | None, str | None]:
    """返回 (作品链接, 输入链接, 去重 key)。作品链接不会与主页链接混淆。"""
    post = (source_post_url or "").strip() or None
    inp = (source_input_url or "").strip() or None
    if post and _is_profile_only_url(post, profile_url):
        post = None
    if inp and _is_profile_only_url(inp, profile_url) and not post:
        key = normalize_source_key(inp)
        return None, inp, key or None
    key_source = post or inp
    if not key_source:
        return post, inp, None
    return post, inp, normalize_source_key(key_source) or None


class InfluencerSourceService:
    @staticmethod
    async def record_from_collected(
        db: AsyncSession,
        product_record: ProductInfluencer,
        item: CollectedInfluencer,
        *,
        task: CollectionTask | None = None,
        run_at: datetime | None = None,
        source_post_url: str | None = None,
        source_input_url: str | None = None,
        import_batch_id: int | None = None,
    ) -> ProductInfluencerSource | None:
        collected_at = run_at or datetime.now(UTC)
        post_url, input_url, source_key = resolve_source_fields(
            source_post_url=source_post_url or item.source_post_url,
            source_input_url=source_input_url or getattr(item, "source_input_url", None),
            profile_url=item.profile_url,
        )
        if not source_key:
            return None

        existing = await db.execute(
            select(ProductInfluencerSource).where(
                ProductInfluencerSource.product_influencer_id == product_record.id,
                ProductInfluencerSource.source_key == source_key,
            )
        )
        if existing.scalar_one_or_none():
            return None

        record_platform = (item.platform or "").strip().lower() or None
        if input_url:
            detected = detect_platform(input_url)
            if detected:
                record_platform = detected

        row = ProductInfluencerSource(
            product_influencer_id=product_record.id,
            task_id=task.id if task else None,
            import_batch_id=import_batch_id,
            source_post_url=post_url,
            source_input_url=input_url,
            source_platform=record_platform,
            task_name=task.name if task else None,
            source_key=source_key,
            collected_at=collected_at,
        )
        db.add(row)
        await db.flush()
        return row

    @staticmethod
    async def list_for_product_influencers(
        db: AsyncSession,
        product_influencer_ids: list[int],
    ) -> dict[int, list[ProductInfluencerSource]]:
        if not product_influencer_ids:
            return {}
        rows = await db.execute(
            select(ProductInfluencerSource)
            .where(ProductInfluencerSource.product_influencer_id.in_(product_influencer_ids))
            .order_by(ProductInfluencerSource.collected_at.desc(), ProductInfluencerSource.id.desc())
        )
        grouped: dict[int, list[ProductInfluencerSource]] = {}
        for row in rows.scalars():
            grouped.setdefault(row.product_influencer_id, []).append(row)
        return grouped

    @staticmethod
    def aggregate_for_export(sources: list[ProductInfluencerSource]) -> dict[str, str]:
        if not sources:
            return {
                "source_post_url": "",
                "source_input_url": "",
                "source_task_name": "",
                "source_task_id": "",
                "source_platform": "",
                "collected_at": "",
            }

        def join(field: str) -> str:
            seen: set[str] = set()
            parts: list[str] = []
            for row in sources:
                value = getattr(row, field, None)
                if value is None:
                    continue
                text = str(value).strip()
                if not text or text in seen:
                    continue
                seen.add(text)
                parts.append(text)
            return "\n".join(parts)

        def join_task_id() -> str:
            seen: set[str] = set()
            parts: list[str] = []
            for row in sources:
                if row.task_id is None:
                    continue
                text = str(row.task_id)
                if text in seen:
                    continue
                seen.add(text)
                parts.append(text)
            return "\n".join(parts)

        collected_parts: list[str] = []
        for row in sources:
            if row.collected_at:
                collected_parts.append(row.collected_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S"))
        return {
            "source_post_url": join("source_post_url"),
            "source_input_url": join("source_input_url"),
            "source_task_name": join("task_name"),
            "source_task_id": join_task_id(),
            "source_platform": join("source_platform"),
            "collected_at": "\n".join(collected_parts),
        }
