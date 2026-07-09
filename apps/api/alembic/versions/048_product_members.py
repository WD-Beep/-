"""Add product member assignments."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "048_product_members"
down_revision: Union[str, None] = "047_manual_outreach_email"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "product_members",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False, server_default="member"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "product_id", name="uq_product_member_user_product"),
    )
    op.create_index("ix_product_members_user_id", "product_members", ["user_id"])
    op.create_index("ix_product_members_product_id", "product_members", ["product_id"])


def downgrade() -> None:
    op.drop_index("ix_product_members_product_id", table_name="product_members")
    op.drop_index("ix_product_members_user_id", table_name="product_members")
    op.drop_table("product_members")
