"""Add score_reason to influencers."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002_add_score_reason"
down_revision: Union[str, None] = "001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("influencers", sa.Column("score_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("influencers", "score_reason")
