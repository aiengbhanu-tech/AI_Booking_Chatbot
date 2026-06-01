"""add prospects table

Revision ID: cd2e1907071c
Revises: c8173a0ee82f
Create Date: 2026-06-01 10:51:40.600556

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa



# revision identifiers, used by Alembic.
revision: str = 'cd2e1907071c'
down_revision: Union[str, None] = 'c8173a0ee82f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade():
    op.create_table(
            "prospects",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("clinic_name", sa.String(length=255), nullable=True),
            sa.Column("website", sa.Text(), nullable=False),
            sa.Column("email", sa.String(length=255), nullable=True),
            sa.Column("phone", sa.String(length=50), nullable=True),
            sa.Column("country", sa.String(length=100), nullable=True),
            sa.Column("city", sa.String(length=100), nullable=True),
            sa.Column("has_chatbot", sa.String(length=10), nullable=True),
            sa.Column("has_booking", sa.String(length=10), nullable=True),
            sa.Column("has_contact_form", sa.String(length=10), nullable=True),
            sa.Column("has_faq", sa.String(length=10), nullable=True),
            sa.Column("score", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(length=50), nullable=True),
            sa.Column("audit_summary", sa.Text(), nullable=True),
            sa.Column("pitch", sa.Text(), nullable=True),
            sa.Column("raw_findings", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        )

def downgrade():
    op.drop_table("prospects")