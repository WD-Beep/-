"""019: collection_tasks.platforms JSONB 多平台采集。"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "019_collection_task_platforms"
down_revision: Union[str, None] = "018_candidate_source_meta"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "collection_tasks",
        sa.Column(
            "platforms",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
    )
    op.execute(
        """
        UPDATE collection_tasks
        SET platforms = jsonb_build_array(platform)
        WHERE platforms = '[]'::jsonb OR platforms IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("collection_tasks", "platforms")
