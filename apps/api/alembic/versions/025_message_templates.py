"""025: 话术库 message_templates"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "025_message_templates"
down_revision: Union[str, None] = "024_tenant_link_import_global_dedup"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "message_templates" in inspector.get_table_names():
        return

    op.create_table(
        "message_templates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("scenario", sa.String(length=64), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=True),
        sa.Column("language", sa.String(length=16), nullable=True),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_message_templates_product_id", "message_templates", ["product_id"])
    op.create_index("ix_message_templates_user_id", "message_templates", ["user_id"])
    op.create_index("ix_message_templates_scenario", "message_templates", ["scenario"])
    op.create_index("ix_message_templates_platform", "message_templates", ["platform"])
    op.create_index("ix_message_templates_updated_at", "message_templates", ["updated_at"])
    op.create_index("ix_message_templates_last_used_at", "message_templates", ["last_used_at"])


def downgrade() -> None:
    op.drop_index("ix_message_templates_last_used_at", table_name="message_templates")
    op.drop_index("ix_message_templates_updated_at", table_name="message_templates")
    op.drop_index("ix_message_templates_platform", table_name="message_templates")
    op.drop_index("ix_message_templates_scenario", table_name="message_templates")
    op.drop_index("ix_message_templates_user_id", table_name="message_templates")
    op.drop_index("ix_message_templates_product_id", table_name="message_templates")
    op.drop_table("message_templates")
