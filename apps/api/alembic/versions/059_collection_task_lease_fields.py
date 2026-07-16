from __future__ import annotations

import asyncio
import logging
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "059_collection_task_lease_fields"
down_revision: Union[str, None] = "058_link_script_template_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("collection_tasks", sa.Column("worker_id", sa.String(length=64), nullable=True))
    op.add_column(
        "collection_tasks",
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "collection_tasks",
        sa.Column("run_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_collection_tasks_worker_id",
        "collection_tasks",
        ["worker_id"],
        unique=False,
    )
    op.create_index(
        "ix_collection_tasks_heartbeat_at",
        "collection_tasks",
        ["heartbeat_at"],
        unique=False,
    )
    op.create_index(
        "ix_collection_tasks_status_heartbeat",
        "collection_tasks",
        ["status", "heartbeat_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_collection_tasks_status_heartbeat", table_name="collection_tasks")
    op.drop_index("ix_collection_tasks_heartbeat_at", table_name="collection_tasks")
    op.drop_index("ix_collection_tasks_worker_id", table_name="collection_tasks")
    op.drop_column("collection_tasks", "run_started_at")
    op.drop_column("collection_tasks", "heartbeat_at")
    op.drop_column("collection_tasks", "worker_id")
