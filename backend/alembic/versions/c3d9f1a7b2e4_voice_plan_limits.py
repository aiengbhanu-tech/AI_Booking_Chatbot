"""voice plan limits: per-call reserved seconds, widget voice engine

Revision ID: c3d9f1a7b2e4
Revises: b7e4c2a91f03
Create Date: 2026-11-25 12:00:00.000000

Additive only.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3d9f1a7b2e4"
down_revision: Union[str, None] = "b7e4c2a91f03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("voice_settings", sa.Column("web_voice_engine", sa.String(10), nullable=False, server_default="auto"))
    op.add_column("voice_calls", sa.Column("max_seconds", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("voice_calls", "max_seconds")
    op.drop_column("voice_settings", "web_voice_engine")
