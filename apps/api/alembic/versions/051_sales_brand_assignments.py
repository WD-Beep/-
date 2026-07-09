"""Create sales11 and assign one real brand to each sales account."""

from typing import Sequence, Union

from alembic import op


revision: str = "051_sales_brand_assignments"
down_revision: Union[str, None] = "050_remove_default_brand_from_sales"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SALES_VALUES = """
    ('sales1', U&'\\4E1A\\52A1\\54581', 'sales1@local', U&'\\73FA\\4E34', 'EPEDAL24', 'junlin-epedal24'),
    ('sales2', U&'\\4E1A\\52A1\\54582', 'sales2@local', U&'\\54C6\\83B1\\5A01', 'Aquorix', 'duolaiwei-aquorix'),
    ('sales3', U&'\\4E1A\\52A1\\54583', 'sales3@local', U&'\\54C6\\83B1\\745E', 'RecoverJoy', 'duolairui-recoverjoy'),
    ('sales4', U&'\\4E1A\\52A1\\54584', 'sales4@local', U&'\\94B1\\94B0', 'Scandihome', 'qianyu-scandihome'),
    ('sales5', U&'\\4E1A\\52A1\\54585', 'sales5@local', U&'\\591A\\83B1\\8FBE', 'ACESTRIKE', 'duolaida-acestrike'),
    ('sales6', U&'\\4E1A\\52A1\\54586', 'sales6@local', U&'\\6822\\535A', 'P.travel', 'baibo-p-travel'),
    ('sales7', U&'\\4E1A\\52A1\\54587', 'sales7@local', 'OCE', 'OCE GEAR', 'oce-oce-gear'),
    ('sales8', U&'\\4E1A\\52A1\\54588', 'sales8@local', U&'\\73FA\\94B0', 'P.TRAVEL DESIGN', 'junyu-p-travel-design'),
    ('sales9', U&'\\4E1A\\52A1\\54589', 'sales9@local', U&'\\591A\\83B1\\5409', 'HOMEHIVE', 'duolaiji-homehive'),
    ('sales10', U&'\\4E1A\\52A1\\545810', 'sales10@local', U&'\\7396\\94B0', 'BBCREAT', 'jiuyu-bbcreat'),
    ('sales11', U&'\\4E1A\\52A1\\545811', 'sales11@local', U&'\\5F18\\535A\\6717', 'Hongbolang', 'hongbolang')
"""


def upgrade() -> None:
    op.execute(
        f"""
        WITH assignments(username, display_name, email, product_name, brand, slug) AS (
            VALUES {SALES_VALUES}
        )
        INSERT INTO users (username, display_name, email, is_active, is_admin)
        SELECT username, display_name, email, true, false
        FROM assignments
        ON CONFLICT (username) DO UPDATE
        SET is_active = true,
            is_admin = false,
            email = COALESCE(users.email, EXCLUDED.email)
        """
    )
    op.execute(
        """
        INSERT INTO workspace_members (workspace_id, user_id, role)
        SELECT 1, users.id, 'member'
        FROM users
        WHERE users.username ~ '^sales([1-9]|10|11)$'
        ON CONFLICT ON CONSTRAINT uq_workspace_member DO NOTHING
        """
    )
    op.execute(
        f"""
        WITH assignments(username, display_name, email, product_name, brand, slug) AS (
            VALUES {SALES_VALUES}
        )
        INSERT INTO products (
            workspace_id, name, slug, brand, description, is_default,
            is_archived, is_hidden, is_test, created_source
        )
        SELECT
            1,
            product_name,
            slug,
            brand,
            CASE
                WHEN slug = 'hongbolang'
                THEN 'Hongbolang is a temporary slug/English placeholder.'
                ELSE 'Seeded sales brand.'
            END,
            false,
            false,
            false,
            false,
            'seed'
        FROM assignments
        ON CONFLICT ON CONSTRAINT uq_product_workspace_slug DO UPDATE
        SET name = EXCLUDED.name,
            brand = EXCLUDED.brand,
            description = EXCLUDED.description,
            is_default = false,
            is_archived = false,
            is_hidden = false,
            is_test = false
        """
    )
    op.execute(
        """
        DELETE FROM product_members pm
        USING users u, products p
        WHERE pm.user_id = u.id
          AND pm.product_id = p.id
          AND u.is_admin = false
          AND (p.is_default = true OR p.slug = 'default')
        """
    )
    op.execute(
        f"""
        WITH assignments(username, display_name, email, product_name, brand, slug) AS (
            VALUES {SALES_VALUES}
        )
        DELETE FROM product_members pm
        USING users u, products p, assignments a
        WHERE pm.user_id = u.id
          AND pm.product_id = p.id
          AND u.username = a.username
          AND p.slug <> a.slug
        """
    )
    op.execute(
        f"""
        WITH assignments(username, display_name, email, product_name, brand, slug) AS (
            VALUES {SALES_VALUES}
        )
        INSERT INTO product_members (user_id, product_id, role)
        SELECT u.id, p.id, 'owner'
        FROM assignments a
        JOIN users u ON u.username = a.username
        JOIN products p ON p.workspace_id = 1 AND p.slug = a.slug
        ON CONFLICT ON CONSTRAINT uq_product_member_user_product DO UPDATE
        SET role = 'owner'
        """
    )


def downgrade() -> None:
    pass
