"""018: 候选池 source_meta JSONB（竞品商品发现等扩展来源信息）"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "018_candidate_source_meta"
down_revision: Union[str, None] = "017_contact_discovery_phase4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "collection_task_candidates",
        sa.Column("source_meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("collection_task_candidates", "source_meta")
