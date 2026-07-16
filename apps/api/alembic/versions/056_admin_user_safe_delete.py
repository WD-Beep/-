"""Allow safe administrator deletion of salesperson accounts."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "056_admin_user_safe_delete"
down_revision: Union[str, None] = "055_expand_whatsapp_urls"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "outreach_email_campaigns_user_id_fkey",
        "outreach_email_campaigns",
        type_="foreignkey",
    )
    op.alter_column(
        "outreach_email_campaigns",
        "user_id",
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.create_foreign_key(
        "outreach_email_campaigns_user_id_fkey",
        "outreach_email_campaigns",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.drop_constraint(
        "outreach_send_queue_user_id_fkey",
        "outreach_send_queue",
        type_="foreignkey",
    )
    op.alter_column(
        "outreach_send_queue",
        "user_id",
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.create_foreign_key(
        "outreach_send_queue_user_id_fkey",
        "outreach_send_queue",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "admin_audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("actor_username", sa.String(length=100), nullable=False),
        sa.Column("target_user_id", sa.Integer(), nullable=False),
        sa.Column("target_username", sa.String(length=100), nullable=False),
        sa.Column("target_display_name", sa.String(length=255), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_admin_audit_logs_action", "admin_audit_logs", ["action"])
    op.create_index("ix_admin_audit_logs_actor_user_id", "admin_audit_logs", ["actor_user_id"])
    op.create_index("ix_admin_audit_logs_target_user_id", "admin_audit_logs", ["target_user_id"])
    op.create_index("ix_admin_audit_logs_created_at", "admin_audit_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_admin_audit_logs_created_at", table_name="admin_audit_logs")
    op.drop_index("ix_admin_audit_logs_target_user_id", table_name="admin_audit_logs")
    op.drop_index("ix_admin_audit_logs_actor_user_id", table_name="admin_audit_logs")
    op.drop_index("ix_admin_audit_logs_action", table_name="admin_audit_logs")
    op.drop_table("admin_audit_logs")

    op.execute(
        """
        UPDATE outreach_email_campaigns
        SET user_id = (SELECT id FROM users ORDER BY is_admin DESC, id ASC LIMIT 1)
        WHERE user_id IS NULL
        """
    )
    op.drop_constraint(
        "outreach_email_campaigns_user_id_fkey",
        "outreach_email_campaigns",
        type_="foreignkey",
    )
    op.alter_column(
        "outreach_email_campaigns",
        "user_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.create_foreign_key(
        "outreach_email_campaigns_user_id_fkey",
        "outreach_email_campaigns",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.execute(
        """
        UPDATE outreach_send_queue
        SET user_id = (SELECT id FROM users ORDER BY is_admin DESC, id ASC LIMIT 1)
        WHERE user_id IS NULL
        """
    )
    op.drop_constraint(
        "outreach_send_queue_user_id_fkey",
        "outreach_send_queue",
        type_="foreignkey",
    )
    op.alter_column(
        "outreach_send_queue",
        "user_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.create_foreign_key(
        "outreach_send_queue_user_id_fkey",
        "outreach_send_queue",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
