"""补采 YouTube 频道 About 外链并写回 influencers 表。"""
from __future__ import annotations

import argparse
import asyncio
import re

from sqlalchemy import or_, select

from app.db.session import async_session_factory
from app.models.influencer import Influencer
from app.services.api_direct_client import ad_get, reset_request_budget
from app.services.platform_providers.youtube_api_direct import (
    _append_links_to_profile,
    _collect_snippet_links_by_channel,
    fetch_youtube_channel_about_links,
)
from app.services.platform_types import PlatformCandidateProfile
from app.services.platform_utils import profile_to_collected

CHANNEL_ID_RE = re.compile(r"youtube\.com/channel/([^/?#]+)", re.I)


def _channel_id_from_profile_url(profile_url: str | None) -> str | None:
    if not profile_url:
        return None
    match = CHANNEL_ID_RE.search(profile_url)
    return match.group(1) if match else None


def _needs_about_links(row: Influencer) -> bool:
    if row.linktree_url:
        return False
    for link in row.other_social_links or []:
        if not isinstance(link, dict):
            continue
        url = str(link.get("url") or "").lower()
        if "lnktr.ee" in url or "linktr.ee" in url:
            return False
    return True


async def _snippet_links_for_row(row: Influencer, channel_id: str | None) -> list[dict[str, str]]:
    if not channel_id:
        return []
    query = (row.display_name or row.username or "").strip()
    if not query:
        return []
    reset_request_budget()
    try:
        post_data = await ad_get(
            "/v1/youtube/posts",
            params={"query": query, "pages": 1},
            platform="youtube",
        )
    except Exception:
        return []
    by_channel = _collect_snippet_links_by_channel(post_data.get("posts") or [])
    return by_channel.get(channel_id, [])


async def backfill(*, display_name: str | None = None, limit: int = 50, dry_run: bool = False) -> None:
    updated = 0
    skipped = 0
    async with async_session_factory() as session:
        stmt = select(Influencer).where(Influencer.platform == "youtube")
        if display_name:
            stmt = stmt.where(
                or_(
                    Influencer.display_name.ilike(f"%{display_name}%"),
                    Influencer.username.ilike(f"%{display_name}%"),
                )
            )
        stmt = stmt.limit(limit)
        rows = (await session.execute(stmt)).scalars().all()

        for row in rows:
            if not _needs_about_links(row):
                skipped += 1
                continue
            channel_id = _channel_id_from_profile_url(row.profile_url)
            snippet_links = await _snippet_links_for_row(row, channel_id)
            about_links = await fetch_youtube_channel_about_links(channel_id, row.profile_url)
            merged_links = [*about_links, *snippet_links]
            if not merged_links:
                print(f"[skip] {row.display_name or row.username}: 未取到 About/视频描述外链")
                skipped += 1
                continue

            profile = PlatformCandidateProfile(
                platform="youtube",
                username=row.username,
                profile_url=row.profile_url,
                display_name=row.display_name,
                bio=row.bio,
                followers_count=row.followers_count,
                website=row.website,
                email=row.email,
                other_social_links=list(row.other_social_links or []),
                channel_id=channel_id,
                source_meta={
                    "about_links_hydrated": bool(about_links),
                    "about_links_fetch": "empty_or_unreachable" if not about_links else None,
                },
            )
            enriched = _append_links_to_profile(profile, merged_links)
            item = profile_to_collected(enriched)

            print(
                f"[update] {row.display_name or row.username}: "
                f"linktree={item.linktree_url} links={len(item.other_social_links or [])}"
            )
            if dry_run:
                updated += 1
                continue

            row.website = item.website or row.website
            row.linktree_url = item.linktree_url or row.linktree_url
            row.other_social_links = item.other_social_links or row.other_social_links or []
            row.contact_fetch_status = getattr(item, "contact_fetch_status", None) or row.contact_fetch_status
            row.contact_fetch_error = getattr(item, "contact_fetch_error", None) or row.contact_fetch_error
            updated += 1

        if not dry_run and updated:
            await session.commit()

    print(f"done: updated={updated} skipped={skipped} dry_run={dry_run}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill YouTube About links")
    parser.add_argument("--name", dest="display_name", default=None, help="按 display_name/username 过滤")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    asyncio.run(backfill(display_name=args.display_name, limit=args.limit, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
