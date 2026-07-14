"""Remove non-admin salesperson accounts for admin CRUD verification.

Clears per-user email/reply/task rows, unassigns brands, then deletes users.
Keeps the admin account (id=1) by default.
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import delete, select

from app.db.session import async_session_factory
from app.models.collection_task import CollectionTask
from app.models.email_log import EmailLog
from app.models.email_reply import EmailReply
from app.models.tenant import ProductMember, User, WorkspaceMember


async def cleanup_sales_users(*, dry_run: bool = False) -> None:
    async with async_session_factory() as session:
        users = (
            await session.execute(
                select(User).where(User.is_admin.is_(False)).order_by(User.id.asc())
            )
        ).scalars().all()

        if not users:
            print("No salesperson accounts to remove.")
            return

        print(f"Found {len(users)} salesperson account(s).")
        for user in users:
            print(
                f"  - id={user.id} username={user.username} "
                f"display={user.display_name!r}"
            )

        if dry_run:
            print("Dry run only. Re-run with --execute to apply.")
            return

        removed = 0
        for user in users:
            user_id = user.id
            replies = await session.execute(delete(EmailReply).where(EmailReply.user_id == user_id))
            emails = await session.execute(delete(EmailLog).where(EmailLog.user_id == user_id))
            tasks = await session.execute(delete(CollectionTask).where(CollectionTask.user_id == user_id))
            members = await session.execute(delete(ProductMember).where(ProductMember.user_id == user_id))
            workspaces = await session.execute(
                delete(WorkspaceMember).where(WorkspaceMember.user_id == user_id)
            )
            await session.delete(user)
            removed += 1
            print(
                f"Removed user {user.username} (#{user_id}): "
                f"replies={replies.rowcount or 0}, emails={emails.rowcount or 0}, "
                f"tasks={tasks.rowcount or 0}, product_members={members.rowcount or 0}, "
                f"workspace_members={workspaces.rowcount or 0}"
            )

        await session.commit()
        print(f"Done. Removed {removed} salesperson account(s). Admin account kept.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Remove all non-admin salesperson accounts")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Apply deletions (default is dry-run)",
    )
    args = parser.parse_args()
    asyncio.run(cleanup_sales_users(dry_run=not args.execute))


if __name__ == "__main__":
    main()
