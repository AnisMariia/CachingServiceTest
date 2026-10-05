"""Create cached_transformations and payloads.

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None


def upgrade() -> None:
    op.create_table(
        "cached_transformations",
        sa.Column("source_hash", sa.String(64), primary_key=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("transformed", sa.Text(), nullable=False),
    )
    op.create_table(
        "payloads",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("output", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("payloads")
    op.drop_table("cached_transformations")
