"""027: 写入真实品牌/产品 seed 数据"""

from typing import Sequence, Union

from alembic import op

from app.data.brand_products import BRAND_PRODUCT_SEEDS, DEFAULT_WORKSPACE_ID

revision: str = "027_seed_brand_products"
down_revision: Union[str, None] = "026_collection_quality_filters"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _sql_literal(value: str) -> str:
    return value.replace("'", "''")


def upgrade() -> None:
    for item in BRAND_PRODUCT_SEEDS:
        name = _sql_literal(item["name"])
        brand = _sql_literal(item["brand"])
        slug = _sql_literal(item["slug"])
        op.execute(
            f"""
            INSERT INTO products (workspace_id, name, slug, brand, is_default)
            VALUES ({DEFAULT_WORKSPACE_ID}, '{name}', '{slug}', '{brand}', false)
            ON CONFLICT ON CONSTRAINT uq_product_workspace_slug DO NOTHING
            """
        )


def downgrade() -> None:
    slugs = ", ".join(f"'{_sql_literal(item['slug'])}'" for item in BRAND_PRODUCT_SEEDS)
    op.execute(
        f"""
        DELETE FROM products
        WHERE workspace_id = {DEFAULT_WORKSPACE_ID}
          AND slug IN ({slugs})
        """
    )
