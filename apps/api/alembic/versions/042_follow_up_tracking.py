"""042: follow-up tracking for outreach records"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "042_follow_up_tracking"
down_revision: Union[str, None] = "041_outreach_send_queue_scheduler"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("email_logs", sa.Column("has_replied", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("email_logs", sa.Column("replied_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("email_logs", sa.Column("reply_email_log_id", sa.Integer(), nullable=True))
    op.add_column("email_logs", sa.Column("reply_summary", sa.Text(), nullable=True))
    op.add_column("email_logs", sa.Column("last_outbound_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("email_logs", sa.Column("follow_up_status", sa.String(length=32), nullable=True, server_default="none"))
    op.add_column("email_logs", sa.Column("follow_up_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("email_logs", sa.Column("max_followups", sa.Integer(), nullable=False, server_default="2"))
    op.add_column("email_logs", sa.Column("next_follow_up_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("email_logs", sa.Column("stop_follow_up", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("email_logs", sa.Column("stop_reason", sa.String(length=64), nullable=True))
    op.create_foreign_key(
        "fk_email_logs_reply_email_log_id_email_replies",
        "email_logs",
        "email_replies",
        ["reply_email_log_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_email_logs_has_replied", "email_logs", ["has_replied"])
    op.create_index("ix_email_logs_replied_at", "email_logs", ["replied_at"])
    op.create_index("ix_email_logs_reply_email_log_id", "email_logs", ["reply_email_log_id"])
    op.create_index("ix_email_logs_last_outbound_at", "email_logs", ["last_outbound_at"])
    op.create_index("ix_email_logs_follow_up_status", "email_logs", ["follow_up_status"])
    op.create_index("ix_email_logs_next_follow_up_at", "email_logs", ["next_follow_up_at"])
    op.create_index("ix_email_logs_stop_follow_up", "email_logs", ["stop_follow_up"])

    op.add_column(
        "outreach_send_queue",
        sa.Column("queue_type", sa.String(length=32), nullable=False, server_default="first_touch"),
    )
    op.add_column("outreach_send_queue", sa.Column("follow_up_step", sa.Integer(), nullable=True))
    op.add_column("outreach_send_queue", sa.Column("parent_queue_id", sa.Integer(), nullable=True))
    op.add_column("outreach_send_queue", sa.Column("outreach_record_id", sa.Integer(), nullable=True))
    op.add_column(
        "outreach_send_queue",
        sa.Column("should_skip_if_replied", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.create_foreign_key(
        "fk_outreach_send_queue_parent_queue_id",
        "outreach_send_queue",
        "outreach_send_queue",
        ["parent_queue_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_outreach_send_queue_outreach_record_id_email_logs",
        "outreach_send_queue",
        "email_logs",
        ["outreach_record_id"],
        ["id"],
    )
    op.create_index("ix_outreach_send_queue_queue_type", "outreach_send_queue", ["queue_type"])
    op.create_index("ix_outreach_send_queue_outreach_record_id", "outreach_send_queue", ["outreach_record_id"])


def downgrade() -> None:
    op.drop_index("ix_outreach_send_queue_outreach_record_id", table_name="outreach_send_queue")
    op.drop_index("ix_outreach_send_queue_queue_type", table_name="outreach_send_queue")
    op.drop_constraint("fk_outreach_send_queue_outreach_record_id_email_logs", "outreach_send_queue", type_="foreignkey")
    op.drop_constraint("fk_outreach_send_queue_parent_queue_id", "outreach_send_queue", type_="foreignkey")
    op.drop_column("outreach_send_queue", "should_skip_if_replied")
    op.drop_column("outreach_send_queue", "outreach_record_id")
    op.drop_column("outreach_send_queue", "parent_queue_id")
    op.drop_column("outreach_send_queue", "follow_up_step")
    op.drop_column("outreach_send_queue", "queue_type")

    op.drop_index("ix_email_logs_stop_follow_up", table_name="email_logs")
    op.drop_index("ix_email_logs_next_follow_up_at", table_name="email_logs")
    op.drop_index("ix_email_logs_follow_up_status", table_name="email_logs")
    op.drop_index("ix_email_logs_last_outbound_at", table_name="email_logs")
    op.drop_index("ix_email_logs_reply_email_log_id", table_name="email_logs")
    op.drop_index("ix_email_logs_replied_at", table_name="email_logs")
    op.drop_index("ix_email_logs_has_replied", table_name="email_logs")
    op.drop_constraint("fk_email_logs_reply_email_log_id_email_replies", "email_logs", type_="foreignkey")
    op.drop_column("email_logs", "stop_reason")
    op.drop_column("email_logs", "stop_follow_up")
    op.drop_column("email_logs", "next_follow_up_at")
    op.drop_column("email_logs", "max_followups")
    op.drop_column("email_logs", "follow_up_count")
    op.drop_column("email_logs", "follow_up_status")
    op.drop_column("email_logs", "last_outbound_at")
    op.drop_column("email_logs", "reply_summary")
    op.drop_column("email_logs", "reply_email_log_id")
    op.drop_column("email_logs", "replied_at")
    op.drop_column("email_logs", "has_replied")
