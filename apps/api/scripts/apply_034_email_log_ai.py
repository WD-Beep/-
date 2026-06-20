"""Manually apply migration 034 columns when alembic overlap blocks upgrade."""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from app.db.session import async_session_factory

COLUMNS = {
    "body": "ALTER TABLE email_logs ADD COLUMN IF NOT EXISTS body TEXT",
    "generated_by_ai": (
        "ALTER TABLE email_logs ADD COLUMN IF NOT EXISTS generated_by_ai "
        "BOOLEAN NOT NULL DEFAULT false"
    ),
    "ai_provider": "ALTER TABLE email_logs ADD COLUMN IF NOT EXISTS ai_provider VARCHAR(50)",
    "ai_reason": "ALTER TABLE email_logs ADD COLUMN IF NOT EXISTS ai_reason TEXT",
    "matched_knowledge": (
        "ALTER TABLE email_logs ADD COLUMN IF NOT EXISTS matched_knowledge JSONB"
    ),
    "risk_notes": "ALTER TABLE email_logs ADD COLUMN IF NOT EXISTS risk_notes JSONB",
}


async def main() -> None:
    async with async_session_factory() as db:
        result = await db.execute(
            text(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'email_logs'
                  AND column_name = ANY(:names)
                """
            ),
            {"names": list(COLUMNS.keys())},
        )
        existing = {row[0] for row in result.fetchall()}
        missing = set(COLUMNS.keys()) - existing
        for name in missing:
            await db.execute(text(COLUMNS[name]))
        if missing:
            await db.execute(
                text(
                    """
                    INSERT INTO alembic_version (version_num)
                    SELECT '034_email_log_ai_outreach'
                    WHERE NOT EXISTS (
                        SELECT 1 FROM alembic_version
                        WHERE version_num = '034_email_log_ai_outreach'
                    )
                    """
                )
            )
        await db.commit()
        print(f"existing={sorted(existing)} missing_applied={sorted(missing)}")


if __name__ == "__main__":
    asyncio.run(main())
