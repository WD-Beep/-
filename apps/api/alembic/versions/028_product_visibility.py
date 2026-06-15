"""028: 产品可见性字段 + 历史测试数据标记"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "028_product_visibility"
down_revision: Union[str, None] = "027_seed_brand_products"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SEED_SLUGS = (
    "junlin-epedal24",
    "duolaiwei-aquorix",
    "duolairui-recoverjoy",
    "qianyu-scandihome",
    "duolaida-acestrike",
    "duolairui-jourcraf",
    "baibo-p-travel",
    "oce-oce-gear",
    "junyu-p-travel-design",
    "duolaiji-homehive",
    "jiuyu-bbcreat",
)


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "products",
        sa.Column("is_hidden", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "products",
        sa.Column("is_test", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column("products", sa.Column("created_source", sa.String(length=32), nullable=True))
    op.add_column("products", sa.Column("display_order", sa.Integer(), nullable=True))

    op.execute(
        """
        UPDATE products
        SET created_source = 'system', display_order = 0
        WHERE slug = 'default'
        """
    )

    for index, slug in enumerate(SEED_SLUGS, start=1):
        op.execute(
            f"""
            UPDATE products
            SET created_source = 'seed', display_order = {index}
            WHERE slug = '{slug}'
            """
        )

    op.execute(
        """
        UPDATE products
        SET is_test = true,
            is_hidden = true,
            created_source = COALESCE(created_source, 'auto_test')
        WHERE slug <> 'default'
          AND slug NOT IN (
            'junlin-epedal24', 'duolaiwei-aquorix', 'duolairui-recoverjoy',
            'qianyu-scandihome', 'duolaida-acestrike', 'duolairui-jourcraf',
            'baibo-p-travel', 'oce-oce-gear', 'junyu-p-travel-design',
            'duolaiji-homehive', 'jiuyu-bbcreat'
          )
          AND (
            name ILIKE '%测试产品%'
            OR name ILIKE '%新品测试%'
            OR name ILIKE '%话术测试%'
            OR name ILIKE '%Amazon跨产品%'
            OR name ILIKE '%test%'
            OR name ILIKE '%demo%'
            OR name ILIKE '%mock%'
            OR name ILIKE '%temp%'
            OR name ILIKE '%临时%'
            OR name ILIKE '%示例%'
            OR slug ILIKE 'test-product%'
            OR slug ILIKE 'dup-slug-%'
            OR name ~* '-[0-9a-f]{8}$'
            OR slug ~* '-[0-9a-f]{8}$'
          )
        """
    )


def downgrade() -> None:
    op.drop_column("products", "display_order")
    op.drop_column("products", "created_source")
    op.drop_column("products", "is_test")
    op.drop_column("products", "is_hidden")
    op.drop_column("products", "is_archived")
