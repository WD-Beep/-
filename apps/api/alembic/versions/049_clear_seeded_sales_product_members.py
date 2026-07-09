"""Clear seeded sales product member assignments."""

from typing import Sequence, Union

from alembic import op


revision: str = "049_clear_seeded_sales_product_members"
down_revision: Union[str, None] = "048_product_members"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM product_members pm
        USING users, products
        WHERE pm.user_id = users.id
          AND pm.product_id = products.id
          AND users.username ~ '^sales([1-9]|10)$'
          AND products.id = substring(users.username from '^sales([0-9]+)$')::int
          AND pm.role = 'member'
          AND products.created_source IN ('system', 'seed')
        """
    )


def downgrade() -> None:
    op.execute(
        """
        INSERT INTO product_members (user_id, product_id, role)
        SELECT users.id, products.id, 'member'
        FROM users
        JOIN products
          ON products.id = substring(users.username from '^sales([0-9]+)$')::int
        WHERE users.username ~ '^sales([1-9]|10)$'
          AND products.created_source IN ('system', 'seed')
        ON CONFLICT ON CONSTRAINT uq_product_member_user_product DO NOTHING
        """
    )
