"""Remove system default brand memberships from non-admin users."""

from typing import Sequence, Union

from alembic import op


revision: str = "050_remove_default_brand_from_sales"
down_revision: Union[str, None] = "049_clear_seeded_sales_product_members"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM product_members pm
        USING users, products
        WHERE pm.user_id = users.id
          AND pm.product_id = products.id
          AND users.is_admin = false
          AND (products.is_default = true OR products.slug = 'default')
        """
    )


def downgrade() -> None:
    pass
