"""031: 候选池 source_input_url 字段"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "031_candidate_source_input_url"
down_revision: Union[str, None] = "030_collection_task_archive"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "collection_task_candidates",
        sa.Column("source_input_url", sa.String(length=512), nullable=True),
    )
    op.execute(
        """
        UPDATE collection_task_candidates
        SET source_input_url = COALESCE(
            NULLIF(source_meta->>'source_input_url', ''),
            NULLIF(source_meta->>'input_url', '')
        )
        WHERE source_input_url IS NULL
          AND source_meta IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_column("collection_task_candidates", "source_input_url")
