from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "062_clear_sentry_ingest_emails"
down_revision: Union[str, None] = "061_user_smtp_imap_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SENTRY_INGEST_PATTERN = "%ingest.sentry.io%"


def _clear_sentry_emails(table_name: str) -> None:
    op.execute(
        f"""
        UPDATE {table_name}
        SET
            business_email = CASE
                WHEN business_email ILIKE '{SENTRY_INGEST_PATTERN}' THEN NULL
                ELSE business_email
            END,
            public_email = CASE
                WHEN public_email ILIKE '{SENTRY_INGEST_PATTERN}' THEN NULL
                ELSE public_email
            END,
            email = CASE
                WHEN email ILIKE '{SENTRY_INGEST_PATTERN}' THEN NULL
                ELSE email
            END,
            final_email = CASE
                WHEN final_email ILIKE '{SENTRY_INGEST_PATTERN}' THEN COALESCE(
                    CASE WHEN business_email ILIKE '{SENTRY_INGEST_PATTERN}' THEN NULL ELSE business_email END,
                    CASE WHEN public_email ILIKE '{SENTRY_INGEST_PATTERN}' THEN NULL ELSE public_email END,
                    CASE WHEN email ILIKE '{SENTRY_INGEST_PATTERN}' THEN NULL ELSE email END
                )
                ELSE final_email
            END,
            email_source = CASE
                WHEN (
                    final_email ILIKE '{SENTRY_INGEST_PATTERN}'
                    AND COALESCE(
                        CASE WHEN business_email ILIKE '{SENTRY_INGEST_PATTERN}' THEN NULL ELSE business_email END,
                        CASE WHEN public_email ILIKE '{SENTRY_INGEST_PATTERN}' THEN NULL ELSE public_email END,
                        CASE WHEN email ILIKE '{SENTRY_INGEST_PATTERN}' THEN NULL ELSE email END
                    ) IS NULL
                ) THEN NULL
                ELSE email_source
            END
        WHERE
            COALESCE(final_email, '') ILIKE '{SENTRY_INGEST_PATTERN}'
            OR COALESCE(email, '') ILIKE '{SENTRY_INGEST_PATTERN}'
            OR COALESCE(public_email, '') ILIKE '{SENTRY_INGEST_PATTERN}'
            OR COALESCE(business_email, '') ILIKE '{SENTRY_INGEST_PATTERN}'
        """
    )


def upgrade() -> None:
    _clear_sentry_emails("global_influencer_profiles")
    _clear_sentry_emails("influencers")


def downgrade() -> None:
    pass
