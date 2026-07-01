"""044: seed sales users for task owner isolation"""

from typing import Sequence, Union

from alembic import op

revision: str = "044_seed_sales_users"
down_revision: Union[str, None] = "043_email_reply_center_status"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO users (id, username, display_name, email, is_active, is_admin)
        SELECT
            series.id,
            'sales' || (series.id - 1),
            '业务员 ' || (series.id - 1),
            'sales' || (series.id - 1) || '@local',
            true,
            false
        FROM generate_series(2, 11) AS series(id)
        ON CONFLICT (username) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO workspace_members (workspace_id, user_id, role)
        SELECT 1, users.id, 'member'
        FROM users
        WHERE users.username ~ '^sales([1-9]|10)$'
        ON CONFLICT ON CONSTRAINT uq_workspace_member DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM workspace_members
        WHERE workspace_id = 1
          AND user_id IN (SELECT id FROM users WHERE username ~ '^sales([1-9]|10)$')
        """
    )
    op.execute("DELETE FROM users WHERE username ~ '^sales([1-9]|10)$'")
