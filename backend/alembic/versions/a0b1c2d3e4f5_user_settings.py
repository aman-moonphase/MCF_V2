"""User settings: per-user preferences for the calendar and the Add to Calendar dialog

Revision ID: a0b1c2d3e4f5
Revises: f6a7b8c9d0e1
Create Date: 2026-10-11 10:00:00.000000

Adds one table only. No existing row is read or changed; users without a row get the defaults.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a0b1c2d3e4f5'
down_revision: Union[str, None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'user_settings',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('timezone', sa.String(length=64), nullable=True),
        sa.Column('calendar_default_view', sa.String(length=10), nullable=False, server_default='month'),
        sa.Column('default_plan_time', sa.String(length=5), nullable=False, server_default='09:00'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id'),
        sa.CheckConstraint("calendar_default_view IN ('month', 'week', 'day')", name='ck_user_settings_calendar_view'),
        sa.CheckConstraint("default_plan_time ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$'", name='ck_user_settings_plan_time'),
    )


def downgrade() -> None:
    op.drop_table('user_settings')
