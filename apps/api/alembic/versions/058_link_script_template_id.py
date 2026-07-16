"""Persist the message template used by link script jobs."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "058_link_script_template_id"
down_revision: Union[str, None] = "057_ai_template_rules_selling_points"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "link_script_jobs",
        sa.Column("message_template_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_link_script_jobs_message_template_id",
        "link_script_jobs",
        ["message_template_id"],
    )
    op.create_foreign_key(
        "link_script_jobs_message_template_id_fkey",
        "link_script_jobs",
        "message_templates",
        ["message_template_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "link_script_jobs_message_template_id_fkey",
        "link_script_jobs",
        type_="foreignkey",
    )
    op.drop_index("ix_link_script_jobs_message_template_id", table_name="link_script_jobs")
    op.drop_column("link_script_jobs", "message_template_id")
