# 文件说明：后端内部脚本入口，用于初始化、验收或数据处理；当前文件：purge data
"""清空业务数据（红人、采集任务、邮件日志、链接导入批次）。"""

import argparse
import asyncio

from sqlalchemy import delete, or_, select

from app.db.session import async_session_factory
from app.models.collection_task import CollectionTask
from app.models.email_log import EmailLog
from app.models.influencer import Influencer
from app.models.link_import_batch import LinkImportBatch


def _mock_influencer_filter():
    return or_(
        Influencer.username.ilike("mock%"),
        Influencer.username.ilike("%mock_%"),
        Influencer.profile_url.ilike("%mock_%"),
        Influencer.profile_url.ilike("%mock_acceptance%"),
        Influencer.profile_url.ilike("%mock_import%"),
        Influencer.ai_summary.ilike("该红人主要在%"),
    )


def _junk_influencer_filter(*, min_followers: int = 1000):
    return or_(
        _mock_influencer_filter(),
        Influencer.followers_count.is_(None),
        Influencer.followers_count < min_followers,
    )


async def purge_acceptance_tasks() -> int:
    async with async_session_factory() as session:
        result = await session.execute(
            select(CollectionTask.id).where(CollectionTask.name.ilike("验收%"))
        )
        ids = [row[0] for row in result.all()]
        if not ids:
            print("No acceptance collection tasks found.")
            return 0
        deleted = await session.execute(delete(CollectionTask).where(CollectionTask.id.in_(ids)))
        await session.commit()
        count = deleted.rowcount or 0
        print(f"Purged {count} acceptance collection tasks.")
        return count


async def purge_mock_influencers() -> int:
    async with async_session_factory() as session:
        result = await session.execute(select(Influencer.id).where(_mock_influencer_filter()))
        ids = [row[0] for row in result.all()]
        if not ids:
            print("No mock influencers found.")
            return 0
        deleted = await session.execute(delete(Influencer).where(Influencer.id.in_(ids)))
        await session.commit()
        count = deleted.rowcount or 0
        print(f"Purged {count} mock influencers.")
        return count


async def purge_junk_influencers(*, min_followers: int = 1000) -> int:
    async with async_session_factory() as session:
        result = await session.execute(
            select(Influencer.id).where(_junk_influencer_filter(min_followers=min_followers))
        )
        ids = [row[0] for row in result.all()]
        if not ids:
            print("No junk influencers found.")
            return 0
        deleted = await session.execute(delete(Influencer).where(Influencer.id.in_(ids)))
        await session.commit()
        count = deleted.rowcount or 0
        print(f"Purged {count} junk influencers (mock AI / followers < {min_followers}).")
        return count


async def purge_all_influencers() -> int:
    async with async_session_factory() as session:
        deleted = await session.execute(delete(Influencer))
        await session.commit()
        count = deleted.rowcount or 0
        print(f"Purged {count} influencers.")
        return count


async def purge() -> None:
    async with async_session_factory() as session:
        email_logs = await session.execute(delete(EmailLog))
        tasks = await session.execute(delete(CollectionTask))
        batches = await session.execute(delete(LinkImportBatch))
        influencers = await session.execute(delete(Influencer))
        await session.commit()

        print(
            "Purged:",
            f"{influencers.rowcount} influencers,",
            f"{tasks.rowcount} collection tasks,",
            f"{email_logs.rowcount} email logs,",
            f"{batches.rowcount} link import batches.",
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Purge influencer-intel data")
    parser.add_argument(
        "--mock-only",
        action="store_true",
        help="Only delete mock/test influencers (username or URL contains mock)",
    )
    parser.add_argument(
        "--acceptance-tasks",
        action="store_true",
        help="Delete collection tasks created by acceptance tests (name starts with 验收)",
    )
    parser.add_argument(
        "--influencers-only",
        action="store_true",
        help="Delete all influencers in the library",
    )
    parser.add_argument(
        "--junk-influencers",
        action="store_true",
        help="Delete mock AI profiles and accounts with followers below 1000",
    )
    parser.add_argument(
        "--min-followers",
        type=int,
        default=1000,
        help="Follower threshold used with --junk-influencers (default: 1000)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Delete all business data",
    )
    args = parser.parse_args()
    if args.mock_only:
        asyncio.run(purge_mock_influencers())
    elif args.junk_influencers:
        asyncio.run(purge_junk_influencers(min_followers=args.min_followers))
    elif args.influencers_only:
        asyncio.run(purge_all_influencers())
    elif args.acceptance_tasks:
        asyncio.run(purge_acceptance_tasks())
    elif args.all:
        asyncio.run(purge())
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
