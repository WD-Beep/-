"""036: outreach send queue allow_resend flag"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "036_outreach_queue_allow_resend"
down_revision: Union[str, None] = "035_outreach_send_queue"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "outreach_send_queue",
        sa.Column("allow_resend", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("outreach_send_queue", "allow_resend")
