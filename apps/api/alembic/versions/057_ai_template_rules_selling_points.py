"""Add AI template rules and manual link selling points."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "057_ai_template_rules_selling_points"
down_revision: Union[str, None] = "056_admin_user_safe_delete"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "message_templates",
        sa.Column(
            "generation_rules",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "message_templates",
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "message_templates",
        sa.Column("source_filename", sa.String(length=255), nullable=True),
    )
    op.create_index(
        "uq_message_templates_product_default",
        "message_templates",
        ["product_id"],
        unique=True,
        postgresql_where=sa.text("is_default = true"),
    )
    op.add_column(
        "link_knowledge_bases",
        sa.Column(
            "manual_selling_points",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("link_knowledge_bases", "manual_selling_points")
    op.drop_index("uq_message_templates_product_default", table_name="message_templates")
    op.drop_column("message_templates", "source_filename")
    op.drop_column("message_templates", "is_default")
    op.drop_column("message_templates", "generation_rules")
